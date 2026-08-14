# 设计文档 33 — 多 Agent 真协作（深度补充）

> 对应 `implementation_plan.md` §16.1 多 Agent 行（"顺序流水线非真协作"）。
> 触发：2026-08-14 深度复查——`TeamOrchestrator.run()` 是逐步同步调用（orchestrator.py:100-132），
> MessageBus 仅作事后记录（analyzer_agent.py:72），"事件驱动/多 Agent"名不副实；简历/面试深挖易崩。
> 依赖：`team/message_bus.py`、`team/orchestrator.py`、`core/parallel_runner.py`、`facade/api.py`。

## 1. 问题现状

- `TeamOrchestrator.run`（`team/orchestrator.py:82-132`）顺序执行 Collector→Analyzer→Validator→Reporter，每步 `agent.run(ctx)` 直连，阶段间无并行、无协商。
- `MessageBus`（`team/message_bus.py:75` 行）是 dict 键值对 pub/sub，仅内存 `_log`（:43-44）；`publish`（analyzer_agent.py:72）是**事后审计记录**，编排并不靠订阅驱动——总线形同日志器（设计文档 12.3 曾简化过它，但未改变"非驱动编排"的事实）。
- 影响：宣称"多 Agent 协作"实为"流水线 + 重试状态机"，面试被问"Agent 之间如何协商/仲裁/并行"时无支撑。

## 2. 目标设计

两条路择一（设计文档给出倾向，实现时可与面试叙事对齐）：

1. **真异步协作（推荐）**：各 Agent 独立决策循环 + 异步消息传递，Analyzer 与 Collector 可并行；Validator 对冲突结论做仲裁（多数/证据/置信度投票）；跨 Agent 超时与降级。
2. **明确叙事降级（保底）**：若不投入真协作，则在文档/README 把"多 Agent"改述为"**多角色流水线 + 状态机编排**"，消除名不副实——成本最低，但失去"多 Agent 协作"卖点。

本设计按路线 1 展开；若最终选路线 2，仅需文档/README 措辞与代码注释，无接口改动。

## 3. 模块/接口设计

### 3.1 `MessageBus` 增强（`team/message_bus.py`）

- 异步分发：`subscribe_async(topic, coro)` + `publish` 支持 `await`；保留同步 `publish`（向后兼容现有阶段埋点）。
- 消息确认与结果回调：`publish(..., await_result=True) → asyncio.Future`，供编排器等待某 Agent 产出并收集结果。
- 超时：`publish(..., timeout=...)` 超时未确认 → 记录 `DEGRADED`（不阻塞流水线）。

### 3.2 `TeamOrchestrator` 并行编排（`team/orchestrator.py`）

- `run_async(task, strategy)`：基于 `asyncio`（`core/parallel_runner.py` 已有 ThreadPoolExecutor 基建，可包装为 async 任务池）：
  - Collector 与 Analyzer 依赖链：Collector 产出观测 → 按缺口分发 Analyzer 并行分析（沿用 `execution.max_parallel_subagents`）；
  - Validator 汇总各维度结论做**仲裁**（见 3.3）；
  - Reporter 收口。整体维持原预算/取消/checkpoint 语义。
- `run()`（同步）保留为 `run_async` 的薄封装，`analyze(mode="team")`（facade/api.py）默认仍走同步，新增 `async` 入口可选。

### 3.3 Validator 仲裁（`team/validator_agent.py`）

- 新增 `arbitrate(results: list[DimensionResult]) -> dict[str, DimensionResult]`：同维度多来源冲突时按 `置信度 > 证据源 trust > 时间新鲜度` 取优，冲突保留 `conflict_evidence` 供报告标注（不静默丢弃）。
- `FactValidator` 现有规则校验复用为单条结论的准入闸。

### 3.4 协作叙事收口

- `README`/`implementation_plan.md §16.2 #3` 在实现后标注"真异步协作"落地；若未投入，则改述为"多角色流水线"（路线 2）。

## 4. 接入方式

```
analyze(mode="team") → TeamOrchestrator.run_async (async)
  ├─ Collector.collect (async) → bus.publish(collected, await_result=True)
  ├─ Analyzer 按缺口并行 → bus.publish(analyzed) → 逐维度结果
  ├─ Validator.arbitrate(冲突仲裁) → bus.publish(validated)
  └─ Reporter.draft → CompetitorReport（复用现有 builder/memory/timeline）
同步 run() 保持现状 → 回归安全网；execution.mode=parallel 语义对齐
```

- 默认入口行为不变（`run()` 同步封装），仅能力增强；取消/预算/checkpoint 贯穿 async 各 await 边界（复用 `is_cancelled` 协作式检查）。

## 5. 验证方式

- **单测（MessageBus async）**：异步订阅收到消息；`await_result` 拿到 Agent 产出；超时标记 DEGRADED 不阻塞。
- **单测（arbitrate）**：同维度多来源冲突 → 置信度/trust 取优；证据保留。
- **集成（并行编排）**：mock LLM + 固定页面，`run_async` 产出报告与 `run()` 串行**字段准确率/证据 URL 一致**（并行不改变结果语义）；Collector 与 Analyzer 并行耗时 < 串行（用 `test_parallel_speedup` 同款真实计时断言）。
- **回归**：既有 `test_team.py` / `test_dual_pipeline_consistency.py` / 集成 17 条全绿；取消/预算贯穿用例重跑。

## 6. 实现优先级与工作量

- 优先级：**中高**（卖点真实性 + 面试深挖风险；纯功能交付影响小，但叙事影响大）。
- 工作量：约 1.5-2 天。
  - MessageBus async + 结果回调/超时：0.5 天；
  - `run_async` 并行编排 + 取消/预算贯穿：0.75 天；
  - Validator 仲裁 + 测试 + 叙事收口：0.25-0.5 天。
- 前置：设计文档 18（single/team 语义已统一）、10（parallel_runner 基建可包装）；与设计文档 32 无冲突。
