# 设计文档 13 — 单测隔离缺陷：CLI handler 硬编码真实 LLM

> 对应 `implementation_plan.md` 第 11 节问题 15（P0）

## 1. 问题现状

- `competitor_agent/cli.py:41-59` 的 `_run_analyze` 在内部写死：

  ```python
  parsed = parse_task(args, llm=LLMClient(), use_llm=True)
  ```

  其中 `LLMClient()` 直接从环境变量读取 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `LLM_API_KEY`，并真正发起 HTTP 调用。
- 该 handler 完全绕过测试注入的 `StubAPI` / mock LLM。测试即便传入 `api=StubAPI(...)`，parse 阶段仍会触碰真实模型。
- 后果分两类环境：
  - **本机（带 key）**：单测触发真实外部 HTTP 调用，既慢又不稳定，且可能消耗额度。
  - **CI（无 key）**：`LLMClient()` 无 key 时 `parse_task` 内部（或后续 `api.analyze`）会尝试联网并最终**挂起**（实测 unit suite 卡在 `test_analyze_single_prints_report`，约 58% 处）。CI "通过" 纯属侥幸——无 key 导致早期抛错 → 部分路径被跳过，而非真正验证。
- 根因：`parse_task` 的 LLM 不是依赖注入项，而是在 CLI handler 内 new 出来的，测试无法替换。

## 2. 目标设计

1. **依赖注入到底**：`parse_task` 使用的 LLM 必须由调用方（handler / 测试）显式传入，handler 不得自行 `LLMClient()`。
2. **测试环境确定性**：无论本机还是 CI，`tests/unit/facade/test_cli.py` 都必须快速、离线、可复现地通过，且不触发任何真实网络。
3. **无 key 安全降级**：缺失 key 时 CLI 走规则解析（`use_llm=False`），不再隐式联网。

## 3. 模块/接口设计

### 3.1 重构 `_run_analyze` 的 LLM 来源

`cli.py` 的 `_run_analyze` 改为接收 `llm` 与 `use_llm` 参数（与 `CompetitorAnalysisAPI` 一致），由 CLI 入口统一构造并允许测试覆盖：

```python
def _run_analyze(
    api: CompetitorAnalysisAPI,
    args: str,
    out_dir: str | None = None,
    mode: str = "team",
    llm: LLMClient | None = None,
    use_llm: bool | None = None,
) -> None:
    args = sanitize_task(args.strip())
    if not args:
        print("用法: analyze <竞品或任务>")
        return
    parsed = parse_task(args, llm=llm, use_llm=use_llm)
    ...
```

- `llm` / `use_llm` 来源顺序：**显式参数 > 环境变量开关（如 `COMPETITOR_AGENT_USE_LLM`）> 默认关闭（`use_llm=False`）**。默认关闭保证无 key 不联网。
- `parse_task` 签名保持不变（`llm: LLMClient | None = None, use_llm: bool = False`），仅要求调用方负责注入。

### 3.2 CLI 入口统一构造 LLM

在 CLI 顶层（`main` / 子命令注册处）集中创建 `LLMClient` 与 `use_llm` 决策，向下传递；测试直接构造 `parse_task(args, llm=MockLLM(), use_llm=True)` 或 `use_llm=False`。

### 3.3 conftest 强制隔离（兜底）

`tests/conftest.py` 增加 fixture / autouse，确保单测进程内：
- 通过 `monkeypatch` 清除 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `LLM_API_KEY`；
- 或 `monkeypatch` `LLMClient` 返回 mock，使任何遗漏的真实调用立即失败而非挂起。

## 4. 接入方式

```
CLI main
  └─ llm, use_llm = resolve_llm_config()   # 显式/环境变量/默认(False)
      └─ _run_analyze(api, args, mode, llm=llm, use_llm=use_llm)
            └─ parse_task(args, llm=llm, use_llm=use_llm)

tests:
  parse_task(args, llm=MockLLM(), use_llm=True)   # 验证解析，不联网
  _run_analyze(StubAPI(), args, llm=None, use_llm=False)
```

## 5. 验证方式

- **单元测试（核心）**：
  - `test_cli.py` 中 `_run_analyze` 使用 `StubAPI` + `use_llm=False`，断言打印报告 / 保存 markdown 行为。
  - 新增 `parse_task(use_llm=True, llm=MockLLM())` 用例，断言使用注入的 mock 而非真实客户端（可用 `monkeypatch` 让真实 `LLMClient` 抛错来验证未被调用）。
- **环境一致性**：在**带 key 的本机**与**无 key 的 CI** 各跑一次 `pytest tests/unit/facade/test_cli.py`，二者都应快速通过、时长稳定、零真实网络请求（可用 `pytest --cov` + 网络代理断连断言）。
- **回归**：`tests/unit` 全量不卡死，CI 不再"侥幸通过"。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，测试可信度地基）。
- 工作量：约 0.5-1 天（改 CLI 注入点 + conftest 隔离 + 补测试）。
- 建议与问题 16/17（同为 `facade/api.py` + `cli.py` 入口一致性）一并处理，统一依赖注入风格。
