# 设计文档 04 — Web 取消功能 session_id 断链

> 对应 `implementation_plan.md` 第 11 节问题 4（P1）

## 1. 问题现状

- `api.analyze()` 内部**自己生成 session_id**（`facade/api.py:116` `session_id = f"sess_{uuid.uuid4().hex[:8]}"`），与 web 的 `sid` 永远不同。
- 因此 `api.py:121` 的 `is_cancelled(session_id)` 永远返回 False，**checkpoint 取消机制在 web 场景下根本触发不了**。
- `analysis_task.cancel()`（`web_app.py:110-118`）取消的是 `run_in_executor` 的 future，**不会停止已在线程池里运行的 `api.analyze`**——线程继续跑完，只是 SSE 流被掐断。"假取消"。

## 2. 目标设计

让 Web 取消**真正停止**正在运行的分析：

1. **session_id 贯通**：外部传入的 session_id 与内部取消标志一致。
2. **真正中断**：取消能停止线程池中运行的分析循环（而非仅掐断 SSE）。

## 3. 模块/接口设计

### 3.1 session_id 贯通（`facade/api.py`）

`analyze()` 增加可选 `session_id` 参数，外部传入时**复用**而非重新生成：

```python
def analyze(self, task, conversation_history=None, session_id: str | None = None):
    sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
    # 后续 is_cancelled(sid) 与外部一致
```

### 3.2 取消标志贯通（`web_app.py`）

- `_event_generator(sid, task)` 调用 `api.analyze(task, session_id=sid)`，使内部取消标志与 web 的 `sid` 一致。
- `cancel(sid)` 设置 `set_cancel(sid)` 后，内部 `is_cancelled(sid)` 能感知。

### 3.3 真正中断（`facade/api.py` + `core/tactical_loop.py`）

- 在 `TacticalLoop` 每轮迭代检查 `is_cancelled(session_id)`，为 True 时**提前终止循环**并返回部分结果。
- 线程池 future 的 `cancel()` 无法停止线程，因此依赖**协作式取消**：循环内主动检查取消标志。

### 3.4 取消状态返回

- 取消后返回 `CancelledResult`（含已完成的缺口结果 + 取消状态），而非静默丢弃。

## 4. 接入方式

```
Web: POST /api/analyze?task=...&sid=xxx
  → _event_generator(sid, task)
  → api.analyze(task, session_id=sid)   # 复用 sid
  → TacticalLoop 每轮检查 is_cancelled(sid)
POST /api/cancel/{sid}
  → set_cancel(sid) → 循环感知 → 提前终止 → 返回部分结果
```

## 5. 验证方式

- **单元测试**：`analyze(session_id="x")` 内部 `is_cancelled("x")` 一致。
- **集成测试**：慢速分析中调用 `cancel(sid)`，确认循环提前终止、返回部分结果。
- **端到端**：Web 取消后 SSE 正常结束且返回取消状态。

## 6. 实现优先级与工作量

- 优先级：**中高**（P1，真实 bug，可当面试亮点）。
- 工作量：约 0.5-1 天。
- 建议先做 session_id 贯通（改动最小、收益最大），再做协作式取消。
