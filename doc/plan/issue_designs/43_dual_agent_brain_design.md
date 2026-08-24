# 设计文档 43 — 双 Agent 大脑未统一（ReAct 旁路 vs 主流水线）

> 触发：2026-08-15 第三轮评审——项目实际存在**两条平行的"智能"**：① 主流水线（`analyze`/`analyze_team`：
> 规则规划 → 缺口 → 采集 → 单轮结构化补全）与 ② ReAct 工具循环（`agent/react_agent.py` + `react_loop.py`，
> 入口 `facade/api.py::analyze_react`）。二者互不共享状态，ReAct 产物进不了 `CompetitorReport`，且 `analyze_react`
> **全仓库仅测试调用**（tests/unit/facade/test_api.py:69-93），是旁路；team 的"多 Agent"实为带总线的顺序流水线
> （Collector/Validator/Reporter 均为确定性阶段，仅 Analyzer 内含一发 LLM 补全）。
> 依赖：设计文档 38（工具契约/回灌）、40（`TOOLS`+`TOOL_SPECS` 唯一工具源 + `build_react_dispatcher` 多工具）、
> 41（URL 守卫，ReAct 的 web_extract 已接入）；可选 39（真实成本，供共享预算）。

## 1. 问题现状

- **ReAct 是旁路**：`analyze_react`（facade/api.py:470）返回裸字符串，不进 `CompetitorReport`；无取消（不查
  `is_cancelled(session_id)`）、无预算（不 consume/record_iteration）、无记忆/RAG 注入、事件仅
  `phase_start`/`phase_complete`。主入口 `analyze`（api.py:166）与 `analyze_team`（api.py:504）走的是
  "StrategicPlanner → 缺口 → Collector/GapExecutor → Analyzer.complete_json" 流水线，**从不经过 ReAct**。
- **多 Agent 名不副实**：`team/base_agent.py:57` 仅抽象 `run(ctx)`；CollectorAgent（降级链）、ValidatorAgent
  （规则仲裁）、ReporterAgent（模板汇总）全是确定性阶段，只有 AnalyzerAgent 内的一发 `complete_json`
  （analyzers/base.py:157）用了 LLM。`TeamOrchestrator.run`（team/orchestrator.py:100-153）是硬编码顺序调用，
  `MessageBus` 的订阅只服务 async 分支（`_handle_async`），无 agent 间 LLM 协商/规划/反思。
- 影响：项目自称 "agent 项目"，但"会推理的循环（ReAct）"与"能产报告的流水线"两条智能各走各的；
  "agent 主循环在哪 / 多 Agent 如何协作 / 工具调用和主流程什么关系"答不圆，且两条路径的行为（记忆注入、预算、
  取消）已在漂移（见设计文档 45）。

## 2. 目标设计

1. **明确主智能路径**：把主流水线的"分析阶段"升级为 LLM 可工具调用（ReAct 循环）的闭环，规则路径保留为降级；
   或明确宣布 ReAct 为独立交互模式、与主流水线共享统一会话上下文。
2. **共享会话上下文**：预算（cost/iteration）、记忆（RAG + memory_context）、取消（session_id）、事件（event_sink）、
   产物类型（结构化 `DimensionResult`）在两条路径间一致，消除旁路。
3. **ReAct 产物结构化**：`analyze_react` 产出从裸字符串改为可入 `CompetitorReport` 的结构化结论
   （summary/details/confidence，复用设计文档 34 的 schema），或经 `ResponseParser` 归一化。

## 3. 模块/接口设计

### 3.1 统一会话上下文（`facade/api.py` / `agent/react_loop.py`）

```python
class ReactLoop:
    def __init__(self, agent, *, max_steps=6, event_sink=None,
                 session_id: str | None = None,          # 取消协作
                 budget: IterationBudget | None = None,   # 预算共享
                 memory_context_fn=None, rag_fn=None):    # 记忆/RAG 注入
        ...
    # run() 内：每步前 is_cancelled(session_id) 检查；每步后 budget.consume(真实增量)
```

- `analyze_react` 透传 `self._session_id` 与现有 `self._budget`/`self._retriever`/`self._memory`，与 `analyze` 同源。
- `ReactAgent.build_system_prompt` 已支持注入 skills/notes/knowledge（react_agent.py:32-45），补接线即可。

### 3.2 分析阶段可工具调用（`analyzers/base.py`）

- `BaseCompetitorAnalyzer._analyze_with_llm` 在 `use_llm and llm` 时，可选走"先抽取（complete_json）→ 真值校验
  （`_verify_details` 已有）→ 发现缺口时经 `ToolDispatcher` 调 `web_extract`/`web_search` 补证 → 二次补全"的多步闭环；
  规则降级路径（`_analyze_with_rules`）不变。
- 与设计文档 44 的"LLM 深度"互补：43 解决"路径归属"，44 解决"单轮变多步"。

### 3.3 team 路径的 LLM 决策（可选收敛）

- 明确叙事：`team/` 保留为"流水线 + 状态机"（文档级一致性），不再宣称 LLM 多智能体；或在 Collector/Validator
  阶段接入 LLM 决策（成本高，列为远期）。

## 4. 接入方式

```
analyze（主路径）──► 缺口闭环：采集 → [ReAct 工具循环（LLM 可用时）] → 结构化 DimensionResult
                              ▲                │
                         共享 budget /        rules 降级（无 LLM/失败）
                         cancel / memory / event
analyze_react（独立交互）──► 复用同一 ReactLoop，产物结构化入 CompetitorReport
```

- 主路径调用方零改动（`_orchestrator_for`/`TeamOrchestrator` 内部接线）；`use_llm=False` 时全链规则降级，行为不变。

## 5. 验证方式

- **单测（路径统一）**：mock LLM 下 `analyze` 走 ReAct 循环并产出 `DimensionResult`（summary/details/confidence
  可解析）；`analyze_react` 结果可入 `CompetitorReport`（不再是裸字符串）。
- **单测（上下文共享）**：同会话 ReAct 步数计入 `IterationBudget`/`BudgetController`；`cancel(sid)` 能中断 ReAct 循环；
  系统提示含记忆/RAG 注入块。
- **回归**：`use_llm=False` 规则路径与现状逐字节一致；`test_react.py`（38）、`test_tool_registry.py`（40）、
  `test_url_guard.py`（41）全绿。

## 6. 实现优先级与工作量

- 优先级：**高**（"agent 主循环在哪"是项目叙事的根基，双大脑不统一是最显眼的架构问题）。
- 工作量：约 1.5-2 天。
  - ReactLoop 上下文（cancel/budget/记忆/RAG）：0.5 天；
  - 分析阶段 ReAct 闭环 + 结构化：0.8 天；
  - 测试 + 回归：0.4 天。
- 前置：38/40/41（工具层已就绪，`build_react_dispatcher` 已多工具）；可选 39（真实成本共享）。独立于 44/45/46。
