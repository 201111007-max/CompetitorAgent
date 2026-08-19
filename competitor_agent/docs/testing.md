# 测试策略文档（testing.md）

> 竞品分析 Agent 的分层测试策略：单元 / 集成 / 评测三层划分、Mock 网络方式、覆盖率目标。
> 吸取 bugs.md P0 #1「无单元测试」教训：**模块落地即带测试**。

---

## 1. 测试分层

```
tests/
├── unit/            # 纯逻辑，无网络/无 LLM，毫秒级
│   ├── core/        # budget / checkpoint / report / url_guard
│   ├── agent/       # react_loop / parser / dispatcher / make_plan / delegate / subagent_registry
│   ├── collector/   # 各数据源（respx mock HTTP）
│   ├── facade/      # 入口编排与 react_report 组装（注入假 LLM）
│   ├── skills/      # skill 加载与注入
│   ├── memory/      # 四层记忆
│   ├── interfaces/  # Protocol 冒烟
│   └── config/      # 配置校验
├── integration/     # 组装式，仍 mock 网络与 LLM 响应
└── evaluation/      # ground truth 用例（真实或快照）
```

| 层 | 目标 | 依赖 | 运行时间 | 用例数(估算) |
|----|------|------|---------|-------------|
| unit | 逻辑正确性 | 无网络/无 LLM | 秒级 | 80+ |
| integration | 模块协作 | mock | 分钟级 | 20+ |
| evaluation | 质量指标 | fixtures | 分钟级 | 15+ |

---

## 2. Mock 网络与 LLM 约定

### 2.1 HTTP（respx 或自定义 FakeTransport）

```python
import respx

@respx.mock
def test_pricing_collector():
    respx.get("https://cursor.com/pricing").mock(
        return_value=httpx.Response(200, html=PRICING_HTML_FIXTURE)
    )
    obs = pricing_source.fetch(gap, ctx)
    assert obs.status == "ok"
```

- 所有测试请求走 mock，禁真实网络（CI 可离线跑）。
- 失败路径测试：404 / 429 / SPA 空 HTML 各一条。

### 2.2 LLM（FakeLLMClient）

```python
class FakeLLMClient:
    def __init__(self, script: Dict[str, str]):
        self.script = script  # input_prefix -> canned response
    async def chat(self, messages, **kw):
        key = next(k for k in self.script if messages[-1]["content"].startswith(k))
        return self.script[key]
```

- 每次 LLM 调用用确定性响应，保证可复现。
- 超时/熔断测试用抛异常的 Fake。

### 2.3 时间与随机

- 冻结时间：`freezegun` 或注入时钟。
- 禁用随机 seed（涉及采样处注入随机源）。

---

## 3. 覆盖率目标

| 模块 | 行覆盖率目标 |
|------|-------------|
| core/（budget/controller/checkpoint/report/guard） | ≥ 90% |
| agent/（parser/dispatch/react_loop/delegate） | ≥ 85% |
| memory/ | ≥ 80% |
| collector/ | ≥ 75% |
| facade/（api/react_report） | ≥ 80% |
| **整体** | **≥ 80%** |

CI 用 `--cov --cov-fail-under=80` 门禁。

---

## 4. 关键测试场景清单

### 4.1 BudgetController（四条件终止）

| 用例 | 断言 |
|------|------|
| 全部缺口 CLOSED | stop=True, reason=all_gaps_closed |
| 迭代超限 | stop=True, reason=iteration_budget_exhausted |
| 成本超限 | stop=True, reason=cost_limit_reached |
| 核心满足度达标 | stop=True, reason=core_satisfaction_reached |
| 都不满足 | stop=False |

### 4.2 InfoGap 状态机

| 用例 | 断言 |
|------|------|
| OPEN→PARTIAL | 采集到 Observation 后状态迁移 |
| PARTIAL→CONFIRMED | 双源一致 |
| CONFIRMED→CLOSED | 终态 |
| 失败重试回 OPEN | conflict 打回 |
| 全部失败→BLOCKED | 不编造，进报告 pending |

### 4.3 ToolGuard 护栏

| 用例 | 断言 |
|------|------|
| 参数越界 | ToolArgumentError |
| 敏感操作 | ConfirmationRequiredError |
| 速率超限 | RateLimitExceededError |

### 4.4 InjectionGuard

| 用例 | 断言 |
|------|------|
| 网页含 "ignore previous instructions" | 被净化/不泄漏系统指令 |
| 输出校验 | 恶意输出被拦截 |

### 4.5 降级路径

| 用例 | 断言 |
|------|------|
| LLM 不可用（无 API Key） | 显式抛 `LLMUnavailableError`，无静默规则降级（设计文档 47/49） |
| 数据源全失败 | 缺口 BLOCKED，报告如实标注 |

---

## 5. 测试命令（pyproject 配置）

```bash
pytest                                  # 全量
pytest tests/unit -q                    # 单元
pytest tests/integration -q             # 集成
pytest tests/evaluation -q              # 评测
pytest --cov=competitor_agent --cov-report=term-missing
ruff check competitor_agent tests
mypy competitor_agent
```

---

## 6. 新增功能必须带的测试

任何新功能合并前检查：
- [ ] 正常路径 unit 测试
- [ ] 异常/失败路径测试
- [ ] 降级路径测试（若涉及 LLM/网络）
- [ ] 覆盖率达标
- [ ] 相关 fixtures/快照已提交