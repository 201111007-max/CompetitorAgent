# 设计文档 59 — 原生协议并行 tool_calls 并发执行

> 触发：2026-08-24 复核 native 协议循环——`_run_native`（react_agent.py:215-310）对单回合
> `reply.tool_calls` 串行逐个分发（:288 `for call in reply.tool_calls: self._dispatch_call(call)`），
> 模型一次请求多个工具（如同时 `web_extract` 两个 URL）时墙钟 = 各工具耗时之和，无并发收益。
> 用户拍板：**补并行 tool_calls 并发**（doc 53 §2.5「一期不做并行」转做）。
> 前置：53（native 协议循环 `_run_native`）、54（tool.call span 埋点）、56（native 压缩折叠）。

## 1. 问题现状

- `_run_native`（react_agent.py:288）：`for call in reply.tool_calls: result = self._dispatch_call(call)`
  ——一个 LLM 回合返回的多个 tool_calls 串行执行。
- 工具多为网络 IO（`web_extract`/`web_search`，单次秒级），串行下多工具回合延迟线性累加，
  长链路分析（Lead + 多子 Agent）的墙钟被工具串行放大。
- 影响：并发是成熟的低风险优化（工具无相互依赖、结果按原序回灌即可保语义与确定性），缺它纯属浪费。

## 2. 目标设计

1. **并发分发 + 原序回灌**：`ThreadPoolExecutor` 并发 submit 全部 tool_calls，结果**按 tool_calls 原序**收集——
   transcript、tool 消息回灌、plan-first sink 的遍历顺序与现状逐字节一致，模型侧看到的消息序列不变。
2. **并发上限配置化**：`max_parallel_tool_calls`（默认 4），防 delegate 类重工具叠加；配置 1 = 完全串行（回归现状）。
3. **确定性不受影响**：并行只缩短墙钟，不改变结果序列（工具独立、顺序固定）——mock 确定性、benchmark 门禁零突变。
4. **错误隔离**：`_dispatch_call` 已把参数错误/工具缺失/执行异常转可回灌文本、不冒泡；并行后每 future 独立，
   单失败不影响其他工具，回灌语义不变。

## 3. 模块/接口设计

### 3.1 `agent/react_agent.py`（~20 行增量）

```python
# __init__ 新增：self._max_parallel_tool_calls = max_parallel_tool_calls（默认 4）

def _run_native(self, ...):
    ...
    # 替换 :288 串行 for 循环：
    calls = reply.tool_calls
    if len(calls) <= 1 or self._max_parallel_tool_calls <= 1:
        results = [(call, self._dispatch_call(call)) for call in calls]      # 串行（现状路径）
    else:
        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(
            max_workers=min(len(calls), self._max_parallel_tool_calls))
        futures = [(call, executor.submit(self._dispatch_call, call)) for call in calls]
        results = [(call, fut.result()) for call, fut in futures]            # 按原序收集
        executor.shutdown(wait=True)
    # 后续 first_tool_sink / on_step / tool 回灌 / _compress_history_native 全部遍历 results，逐字节不变
    for call, result in results:
        if call.name == mandatory_first_tool and not first_tool_done: ...    # 原逻辑
        if on_step is not None: ...
        messages.append({"role": "tool", "tool_call_id": call.id,
                         "content": wrap_untrusted(self._truncate(str(result), obs_max_chars))})
```

- **plan-first 安全**：`make_plan` 只在首轮经 `tool_choice` 强制、首轮通常单 tool_call，不构成并行；
  后续轮才可能批量并行（首轮 `first_tool_done` 已在首个 `make_plan` 回灌后置位，逻辑不变）。
- **`_dispatch_call` 线程安全**：无共享可变状态（读 `self._dispatcher`/`self._llm`），并发安全；
  底层工具线程安全契约见 §3.3。

### 3.2 参数透传（`ReactAgent`/`ReactLoop`/`facade`/`subagent_registry`）

- `ReactAgent.__init__(..., max_parallel_tool_calls: int = 4)`；
- `ReactLoop`/`build_subagent`/facade `_react_loop` 透传（与 `max_history_steps` doc 56 同模式）；
- 不配置 = 默认 4；配置 1 = 串行。无 yaml 新字段（构造参数，同 doc 51/53 哲学）。

### 3.3 线程安全契约（文档标注）

- `ToolDispatcher.dispatch` 内 `CompetitorStore` 已 RLock（competitor_store.py:85）→ `kb_recall`/RAG 检索安全；
- `web_extract` 每次独立抓取上下文；`web_search`/`make_plan` 无共享状态；
- 契约：**注册到 dispatcher 的工具需线程安全**；若有状态工具，用 `max_parallel_tool_calls=1` 或改独立实现。
- **trace span**（doc 54）：`dispatch` 已包 `tool.*` span；并行 = 同一 trace/step 下多个 span 时间重叠，
  父子关系不变，`trace show` 瀑布图正常。

## 4. 接入方式

```
LLM 回合返回 N 个 tool_calls
  ├─ N≤1 或 max_parallel≤1 → 串行（现状路径）
  └─ 否则 → ThreadPoolExecutor(≤min(N, max_parallel)) 并发分发 → 按原序收集 → 原序回灌/transcript/压缩
```

- 调用方零改动（仅构造参数）；默认路径行为变化 = 多工具回合并发（墙钟缩短），单工具回合逐字节不变。
- 回退：删并行分支（或设 `max_parallel_tool_calls=1`）即完全串行。
- 文本协议（`protocol="react"`，doc 53 保留的 fallback）不动——它本无批量 tool_calls。

## 5. 验证方式

- **单测（并发确实发生，确定性）**：注入带 `threading.Barrier(2)` 的 fake 工具，构造一个回合 2 个 tool_calls——
  Barrier 同步确保两工具真正并发进入（不靠 sleep 猜测）；断言回灌/transcript 顺序与原序一致。
- **单测（边界）**：`max_parallel_tool_calls=1` → 行为与现状逐字节一致（回归网）；单 tool_call 不建线程池；
  `_dispatch_call` 单失败不影响其他（一个返回"工具不可用:..."其余正常）。
- **集成**：mock 下 analyze 全链路通过；benchmark 门禁（mock 脚本不产批量 tool_calls）零突变；
  `--protocol both` 对照（若 60 前保留）react 侧不受影响。
- 全量 `pytest -q` + ruff/mypy。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README 登记 | 0.2d ✅ 2026-08-24 |
| 1 | 并发分发 | `_run_native` 并行分支 + 参数透传 + 单测 | 0.4d |
| 2 | 边界与回归 | 串行回归、错误隔离、线程安全契约文档 | 0.2d |

- 前置：53（native 循环本体）；与 57/58 并行；**若 60（删文本 ReAct）同期落地，本文档只改 `_run_native`，
  与 60 删除路径正交**。
- 依赖：零新依赖（`concurrent.futures` 标准库）。

## 7. 风险与缓解

1. **工具线程不安全**：文档标注契约 + 默认并发 4 保守 + `max_parallel=1` 逃生舱；
   已核实 `kb_recall`（RLock）与 `web_extract`（独立上下文）安全。
2. **delegate 重工具叠加**（子 Agent 后台并发嵌套）：默认并发上限抑制；若实测叠加卡顿可对 delegate 工具
   降并发或独立串行（后续按需）。
3. **mock/时序不确定性**：用 `threading.Barrier` 确定性断言并发，不依赖 sleep——CI 可复现。
4. **并发下成本/预算语义**：`step_guard`/预算按"步"（模型回合）计，与工具并发无关，语义不变。
