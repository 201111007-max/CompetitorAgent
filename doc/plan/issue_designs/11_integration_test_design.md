# 设计文档 11 — 测试缺集成/端到端

> 对应 `implementation_plan.md` 第 11 节问题 11（P2）

## 1. 问题现状

- `tests/integration/` 目录**只有空的 `__init__.py`**，没有任何集成测试。
- 没有一条测试真正走"真实 HTTP 抓取 + 真实 LLM"的端到端链路，所有网络/LLM 都被 fake 替换。

## 2. 目标设计

1. 建立**集成测试层**：验证组件间真实协作（采集→分析→报告）。
2. 建立**端到端测试**：走完整 `CompetitorAnalysisAPI.analyze()` 链路。
3. 用可控的 mock 采集 + 真实/模拟 LLM 保证确定性。

## 3. 模块/接口设计

### 3.1 集成测试（`tests/integration/`）

覆盖组件间协作：

| 测试 | 内容 |
|------|------|
| `test_analyze_flow.py` | `analyze()` 完整链路产出报告 |
| `test_memory_loop.py` | 分析后记忆沉淀 → 二次分析命中 |
| `test_budget_termination.py` | 预算耗尽/满足度终止 |
| `test_checkpoint_resume.py` | 中断 → resume 恢复 |
| `test_team_flow.py` | `analyze_team()` 多 Agent 链路 |

### 3.2 端到端测试（`tests/e2e/`）

- 用 `FakeExtractor`（固定网页内容）+ 真实 LLM（或 mock LLM）跑完整链路。
- 断言：报告结构完整、证据带 source_url、维度结果正确。

### 3.3 测试基础设施

- `conftest.py` 提供 `FakeExtractor`、`FakeLLM`、临时数据目录 fixture。
- 采集层可注入（`CompetitorAnalysisAPI` 接受自定义 extractor），保证不依赖真实网络。

### 3.4 与 benchmark 联动

- 集成测试复用设计文档 03 的 `extract_prediction`，验证真实报告可评测。

## 4. 接入方式

```
pytest tests/integration/  → 组件协作测试
pytest tests/e2e/          → 完整链路测试（mock 采集 + mock/real LLM）
```

## 5. 验证方式

- **集成测试**：`analyze()` 产出完整报告，记忆闭环生效。
- **端到端**：`analyze("Cursor")` 输出含功能/定价/版本的 Markdown 报告。
- **CI**：集成/端到端测试纳入 pytest 全量。

## 6. 实现优先级与工作量

- 优先级：**中**（P2，可信度）。
- 工作量：约 1-2 天。
- 建议先补 `test_analyze_flow.py`（核心链路），再补记忆/预算/checkpoint。
