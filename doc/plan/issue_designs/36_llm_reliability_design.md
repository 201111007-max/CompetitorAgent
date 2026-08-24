# 设计文档 36 — LLM 层可靠性（重试 / 多模型路由 / 超时）

> 对应 `implementation_plan.md` §16.1 LLM 层行（"单次调用、正则估 token、无重试"）。
> 触发：2026-08-14 深度复查——`LLMClient.complete`（`llm/client.py:61-87`）对 SDK 调用**无重试/退避/超时/多模型 fallback**，
> 一次 429/5xx/网络抖动即整体降级规则（base.py:44），真实 LLM 评测与长任务稳定性受限。
> 依赖：`llm/client.py`、`config/loader.py`（`LLMConfig` 现有 model/base_url 段）。

## 1. 问题现状

- `complete`（`llm/client.py:61`）单次 `chat.completions.create`，无超时参数、无重试；网络抖动/限流（429）直接抛异常 → 分析降级规则，**不是链路容错而是能力跳档**。
- 单模型固定（默认 `deepseek-chat`），无 fallback 模型；Key 只读一组别名环境变量（:32），无多 Key 轮换。
- token 估算（:28）用 `len//4` 粗估，成本展示量级可用但不可信。
- 影响：真实 LLM 评测（设计文档 37）与生产长任务对单点失败零容错；"工程可靠性"缺证据。

## 2. 目标设计

1. **重试与退避**：SDK 调用遇可重试错误（429/5xx/超时/连接错误）指数退避重试（≤3 次，`backoff=1s`，抖动），不可重试（401/400）直接抛。
2. **超时**：每次调用设 `timeout`（连接 + 读，默认 30s/120s），可配置。
3. **多模型 fallback 链**：`LLMConfig` 增 `fallback_models: list[str]`——主模型失败（重试耗尽）自动切下一个；全灭抛 `LLMUnavailableError` 降级规则。
4. **调用统计**：`_log_call` 增重试次数/最终模型/超时标记，供可观测与成本统计（设计文档 37 复用）。

## 3. 模块/接口设计

### 3.1 `llm/client.py` 扩展

```python
class LLMClient:
    def __init__(self, call_func=None, model="deepseek-chat", api_key=None,
                 base_url=None, fallback_models: list[str] | None = None,
                 timeout: float | None = None, max_retries: int = 3) -> None: ...
    def complete(self, messages) -> str:
        # 逐模型：重试退避 ≤max_retries → 下一个 fallback → 全灭抛 LLMUnavailableError
        # 可重试判定：429/5xx/连接错误/超时；401/400/404 直接失败（不浪费重试）
    def complete_json(self, messages, schema: dict | None = None, retries: int = 2) -> dict:
        # 复用设计文档 34：schema 校验 + 修复重试；底层走带重试的 complete
```

- `_should_retry(exc)` / `_next_model()` / `_sleep_backoff(attempt)` 内部助手。
- 兼容性：`call_func` 注入路径（测试 mock）不受影响；默认参数保持现状。

### 3.2 `config/loader.py` 扩展

- `LLMConfig` 增 `fallback_models`（默认空）、`timeout`（默认 None）、`max_retries`（默认 3）；`review_config.yaml` `llm` section 增对应键；`load_config` 解析与默认值叠加（沿用设计文档 05 的注入语义）。

### 3.3 调用日志

- `_log_call` 增 `attempts`/`final_model`/`retried`/`timed_out` 字段（脱敏，不落 prompt/密钥）。

## 4. 接入方式

```
LLMClient(...) 构造读 LLMConfig（fallback_models/timeout/max_retries）
  → 所有分析器/规划器/发现器共用此实例（已有依赖注入）
  → 重试与 fallback 透明生效，业务代码零改动
评测：--llm real 时稳定性提升（见设计文档 37）；benchmark 不新增用例
```

- 主流程零改动：仅 `LLMClient` 内部调用策略增强；降级规则（base.py:44）语义不变（仅在全灭后触发，触发频率更低）。

## 5. 验证方式

- **单测（重试退避）**：mock `call_func` 前 2 次抛 429、第 3 次成功 → 返回成功、日志 attempts=3；连续失败 3 次 → 抛 `LLMUnavailableError`；401 不重试立即抛。
- **单测（fallback）**：主模型失败 → 依次尝试 fallback_models → 成功返回、日志 final_model=回退模型；全灭抛错。
- **单测（超时）**：mock 慢调用超时 → 计入重试/失败，不悬挂。
- **单测（config）**：LLMConfig 解析 fallback_models/timeout/max_retries，默认值叠加。
- **集成（真实 LLM 冒烟）**：有 Key 时用 `--llm real` 跑 1-2 条用例稳定通过（自动 skipif 无 Key，不卡 CI）。
- **回归**：`llm/client.py` 既有测试（mock call_func 路径）全绿；分析器降级测试（base.py）行为不变。

## 6. 实现优先级与工作量

- 优先级：**中**（工程可靠性 + 真实评测的前置）。
- 工作量：约 0.5-1 天。
  - 重试/退避/超时：0.3 天；
  - fallback 链 + config：0.25 天；
  - 日志字段 + 测试：0.2-0.4 天。
- 前置：设计文档 05（config 注入语义）、34（`complete_json` schema 复用，可同批）。与 37（真实评测）配合：**先 36 后 37**，真实评测才有稳定性底座。
