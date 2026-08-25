# 设计文档 62 — 全链路编排收敛：统一 run() + 通用委派 + LLM 聚合

> 第十二轮新增项。触发：上一轮把「是否并发」交给主编排 LLM，并在对照 Claude Code（`query.ts` 回合循环）实现后，收窄本设计的原则——**编排骨架用代码，内容/调度意图用 LLM**：不发明"专用编排工具 + 强 schema"，而是复用既有**通用 `delegate` 委派工具**与 `web_tool`，让唯一的 Lead Agent 自然编排 DISCOVERY/COMPARE。聚合结论（市场格局核心判断）由 LLM 产出，压缩/记忆/预算/入口按 Claude 模式交给代码。

## 0. 迭代关系

- 本版本吸收了一次对照评审，**撤销**了上一版"新增 `discover_candidates` / `analyze_competitor` 专属工具 + PLAN/SCHEDULE/AGGREGATE 强 schema"的开法，理由：
  1. 现 `delegate`（doc 49 §3.3，`DelegateRunner` 后台并发 + 合并回填）**已经是通用委派**，候选分析只需扩展"能委派候选竞品"而非再造工具；
  2. Claude/业内主流（LangGraph、Claude `queryLoop`）是"代码守骨架、LLM 回合内自调通用工具"，不把并发度/分批强行 schema 化——故 `SCHEDULE_SCHEMA` 降为 `delegate` 的**可选参数** `{parallel, reason}`，并发细节交给 `DelegateRunner` 默认；
  3. 上下文压缩（`ReactAgent._compress_history`）与四层记忆（`IFourLayerMemory`）项目内**已实现**，本设计只做注入装配，不重写。
- 保留的三个价值点：`aggregate_report`（品类市场格局核心结论，LLM）、统一 `run()` 入口（消灭三入口代码 if-else 分派）、`resolution` 从"分派终点"改为"编排起点/上下文标注"。
- 本轮补充（实现口径收敛，修订本文档）：① **候选子 Agent Final Answer 输出标准多维度 `dimensions[]` 数组**（对齐 REPORT_SCHEMA 维度条目结构），不再复用单维度 `SUBAGENT_RESULT_SCHEMA`——矩阵按"维度 × 竞品"渲染，按维度条目产出才能直接支撑每候选多维度 CompetitorReport，无需组装器二次猜测维度归属；② **`run()` 全 resolution 同走一条单 Lead loop**，组装统一按 `plan.resolution` 分型（registry→CompetitorReport / compare、discovery→ComparisonReport），消灭 run() 内部按 resolution 的分派 if-else。

## 1. 问题现状

### 1.1 全链路编排现状盘点（哪些仍由代码固定）

| 环节 | 现状 | 归属 |
|---|---|---|
| 输入语义解析 `parse_task` | 仅 LLM（`task_parser.py:89`） | ✅ LLM |
| 入口分派（web `web_app.py:135`、CLI `cli.py:86`、MCP） | **三处各写一段重复 if-else**：`resolution==DISCOVERY→discover()` / `is_compare→compare()` / else `analyze()` | ❌ 代码 |
| 单竞品 `analyze()` | Lead ReactLoop：make_plan 首步 + delegate/web_extract/复核 + Final Answer（doc 49） | ✅ LLM |
| COMPARE 竞品级调度 `compare()`/`_compare_parallel` | 串并行由 `execution.mode` 代码写死（api.py:1366） | ❌ 代码 |
| DISCOVERY 候选/并行/聚合 `discover()`/`_analyze_discovered_parallel` | 候选裁剪 `[:max_discover_candidates]`、并行 `max_parallel_subagents`、逐竞品启动、聚合全代码固定（api.py:1417-1459） | ❌ 代码 |
| 多竞品聚合 `build_comparison` | 纯代码渲染"维度 × 竞品"矩阵（report_builder.py:79） | ❌ 代码 |
| 单竞品报告组装 `react_report.assemble` | 解析 Lead Final Answer JSON | ✅ 内容 LLM / 组装代码 |
| 执行层（transcript/SSE/渲染/归档/导出） | — | 代码（执行≠决策） |
| 安全兜底（url_guard/注入防护/预算/取消/checkpoint） | — | 必须代码（doc 49 不变量） |

### 1.2 根本问题（一句话）

doc 49 只做到了"单个竞品内部"的 Lead 编排；DISCOVERY/COMPARE 独有的**候选级调度与聚合**仍由代码批量接管（选举、并发度、聚合叙事不可由 Lead 依据任务上下文决定），且三入口重复维护同一段分派 if-else。

## 2. 目标设计

唯一 Lead Agent 从解析后到产出全程自主编排，原则不变：**决策归 LLM、时机/边界/执行归代码**；编排工具不新造，复用通用 `delegate` 与 `web_tool`。

```
统一入口 run(task)                    # 取代三入口各自的分派 if-else
  → parse_task(task)                  # LLM 出 resolution/competitors/dimensions
  → 构建单个 Lead ReactLoop（resolution 仅作 querySource 式上下文标注，不分派）
  → Lead 首步 make_plan               # 计划含 competitor 集 / 维度 / scheduling 意图
  → Lead 自主（回合内自然调通用工具，Observation 回填驱动下一轮）：
        web_tool / discover(scope)    # 候选枚举，需要时才联网（doc 61）
        delegate(targets, ...)        # 通用委派：候选竞品子 Agent 后台并发分析
        aggregate_report(parts, ...)  # 聚合口径与市场格局核心结论（LLM）
  → Final Answer = 编排收尾结论
  → assemble：矩阵渲染 + 结论段（代码，仅渲染不决策）
```

**关键点**：

1. **单个 Lead 贯穿到底**：不做 `discover()/compare()` 两个代码薄调度方法，统一为 `run()` 内一条 LLM 编排。`resolution` 只是 Lead 的起始上下文，**不产生 Lead 之外的硬件分派路径**（对齐 Claude `querySource` 只作标注、不驱动分支）；单竞品（registry）/对比（compare）/普查（discovery）**同走一条 Lead loop**，仅 `plan.resolution` 不同，组装据此统一分型（CompetitorReport / ComparisonReport）。
2. **候选分析 = 复用通用 `delegate`**：不新增 `discover_candidates` / `analyze_competitor` 专属工具。候选子 Agent 注册进 `SubagentRegistry`，Lead 通过既有 `delegate(targets, ...)` 批量后台委派。是否并行由 Lead 在 `delegate` 的可选参数表达；**并发细节（max_workers/分批）不暴露给 LLM**，交 `DelegateRunner` 默认接管。
3. **调度参数 = "LLM 意图 + 代码守边界"**：`delegate` 仅增可选 `{parallel: bool=true, reason: str}`；代码做硬上限收敛（并发不超 `budget.max_parallel_subagents`，候选不超 `max_discover_candidates`），不再读取 `execution.mode` 自决。
4. **聚合保留 `aggregate_report`**：Lead 决定聚合口径并产出"市场格局核心结论"（最佳/最差、趋势、替代关系），矩阵仍由 `ReportBuilder` 渲染（执行层）。
5. **入口统一**：web/CLI/MCP 只调 `run()`，分派 if-else 消灭；`resolution` 作为 querySource 标注透传。入口只剩壳（认证/日志/SSE/打印）。

## 3. 模块/接口设计

### 3.1 `agent/schemas.py`（仅保留规划与聚合两个 schema）

```python
DIMENSIONS  # 复用 react_schemas.DIMENSIONS

PLAN_SCHEMA  # make_plan 的计划：
# {competitor: str|None, competitors: [str]|None, dimensions: [...]|None,
#  resolution: "registry"|"discovery"|"compare", custom_sources: {...},
#  scheduling: {parallel: bool, reason: str} | None}   # 可选，Lead 意图提示

AGGREGATE_SCHEMA  # aggregate_report 的产出：
# {competitors: [str], kind: "compare"|"position", dimensions: [str]|null,
#  conclusion: str, best_per_dimension: {dim: name}, gaps: [str]}
```

> 说明：**不再定义独立的 `SCHEDULE_SCHEMA`**。并发/分批的"意图"只是 `delegate` 的可选参数 `{parallel, reason}`（见 3.2），且只作 Lead 提示、不作强 schema 校验；真实并发上限由代码硬收敛。

### 3.2 `agent/delegate_tool.py` 扩展（候选委派，无新工具）

不做新工具文件，修改既有 `make_delegate_tool`：

```python
def delegate(targets: list[str], task: str = "",
             parallel: bool = True, reason: str = "") -> str:
    """通用委派（doc 49）。targets 可为「维度」或「候选竞品名」（新增）。
    parallel/reason 是 Lead 的调度意图提示（可观测）；当 parallel 时批量 spawn
    DelegateRunner 后台并发，否则串行 await。并发度不暴露，由 runner._max_concurrent
    默认接管；代码对 workers 做硬收敛 min(..., budget.max_parallel_subagents)。
    结果合并回填（延续 _render_record：状态 + 截断正文，单失败不影响整体）。"""
```

- **候选子 Agent 注册**（`SubagentRegistry`）：新增一类 `competitor` 子 Agent 配置（工具面 = `web_extract/web_search/github_*/analyze_pricing`，排除 `delegate` 防递归）；每个候选竞品 = 一个 `competitor` 运行时，复用 `DelegateRunner` 后台并发。
- `_render_record` 截断正文上限保留（`[:4000]`），保证候选结果合并不撑爆 Lead 上下文。
- **候选枚举不改造**：联网候选清单仍由 `web_tool` / doc 61 `web_search_candidates` 提供（Lead 需要时自调）；`max_discover_candidates` 作为候选数**硬上限**在工具实现内收敛。

### 3.3 `agent/aggregate_tool.py`（聚合工具，保留）

```python
def aggregate_report(parts: str, dimensions: list[str] | None = None,
                     kind: str = "position") -> str:
    """Lead 调：把已完成的候选结论（delegate 回填的 transcript）按 Lead 决策的
    口径聚合——生成「市场格局核心结论」段落（LLM 分析，非代码拼矩阵）；
    矩阵仍由 ReportBuilder.build_comparison 渲染（执行层，不经 LLM）。
    返回聚合结果回填，供 Lead 最终收尾。"""
```

> `kind="compare"`（明确对比）vs `"position"`（普查格局）由 Lead 定；代码只做结构校验。

### 3.4 修改 `agent/prompts/react_system.py`

- `build_lead_system_prompt` 增编排说明：
  - `resolution` 是起点非终点；DISCOVERY/COMPARE 需自主 `web_tool/discover → delegate → aggregate_report`；
  - 何时并行（候选多/任务聚焦或预算有限 → 串行/小批）由 Lead 依据上下文决策，调用 `delegate` 时给出 `parallel` 与 `reason`；
  - 聚合时输出市场格局核心结论（最佳/最差/趋势/替代），不只交矩阵；
  - 复用 planning / fact_verification skills。
- 候选子 Agent system prompt：延续 `build_subagent_system_prompt`，但 **Final Answer 输出标准多维度 `dimensions[]` 数组**（对齐 REPORT_SCHEMA 的维度条目结构：`{competitor, dimensions: [{dimension, summary, details, confidence, evidence_urls}]}`，逐维度填全），并额外携带 `official_links` 供聚合阶段引用。理由：矩阵按"维度 × 竞品"渲染，候选子 Agent 按维度条目产出可直接支撑每候选多维度 CompetitorReport，组装器无需二次猜测维度归属。

### 3.5 修改 `facade/api.py`（统一入口 + 装配）

```python
class CompetitorAnalysisAPI:
    def run(self, task: str, *, session_id: str | None = None) -> CompetitorReport | ComparisonReport:
        """统一入口：取代 web/CLI/MCP 各自分派。
        parse_task（LLM）→ 构建单个 Lead ReactLoop（resolution 作 querySource 标注）
        → 运行 → assemble。
        全部 resolution（registry/compare/discovery）都走同一条单 Lead loop，
        run() 内**无 resolution 分派 if-else**——DISCOVERY/COMPARE 的候选枚举、
        并行、聚合由 Lead 回合内自调 web_tool/delegate/aggregate_report 完成。
        组装按 `plan.resolution` 统一分型：registry→CompetitorReport、
        compare/discovery→ComparisonReport（矩阵 + 市场格局核心结论段）。
        Lead 工具面装配：make_plan / web_tool(discover) / delegate(+parallel/reason) /
        aggregate_report / web_extract / 复核。
        """
        ...

    # 兼容保留（薄包装，只做语义转发，不再自行决定并行）：
    def discover(self, task: str):   # = run(task) 的 DISCOVERY 语义路径（deprecated 告警）
    def compare(self, *names):       # = run(task) 的 COMPARE 语义路径（deprecated 告警）
```

- 删除 `_analyze_discovered_parallel`（代码写死并行）、`_compare_parallel` 的 `execution.mode` 自决逻辑，以及 `run()` 内按 resolution 的三分支代码分派（并行由 `delegate` 的 `parallel` 表达，调度/聚合由 Lead 自编排，代码只硬收敛上限）。
- 新增 **comparison 组装器**：从单 Lead loop 的产物（`loop.plan.resolution` + delegate 回填的候选子 Agent `dimensions[]` 结果 + Lead Final Answer 结论段）→ ComparisonReport——每候选子 Agent 的 `dimensions[]` 组装为最小 CompetitorReport → `build_comparison` 渲染矩阵；Lead Final Answer 的【市场格局核心结论】拼入结论段。
- `DelegateRunner` 实例化传入 `max_concurrent=budget.max_parallel_subagents` 作为默认并发上限。
- `_task_with_sources` 逻辑并入候选子 Agent 运行时注入（把 `official_links` 带进子 Agent 提示）。
- `build_comparison` 保留为**执行层渲染**，位于 `aggregate_report` 结论段之上（Lead 已产出结论段，矩阵补充可视化）。

### 3.6 修改 `agent/react_loop.py`（编排 + 压缩/记忆装配）

- `max_steps`：Lead 从单竞品约 12 上调到调度场景可容纳（默认 24，配置项 `lead.max_orchestration_steps`）；子 Agent 维持自身 `max_steps`。
- 保留取消/预算/事件/记忆/RAG；`delegate` 与 `aggregate_report` 结果作为普通工具 Observation 回填，供 Lead 下一轮决策（沿用 doc 49 委派-回填模型，无新增状态机）。
- **压缩/记忆装配**：Lead 与候选子 Agent 各自复用 `ReactAgent._compress_history`（`max_history_steps` + `pinned_facts`）与 `react_loop.memory_context_fn`（四层记忆召回），见 3.9。

### 3.7 修改入口（web / CLI / MCP）

- `web_app.py` `/api/analyze` 的 `_run_analysis`：三支 `if` 分派改为统一 `run()`；`parsed.resolution` 透传为上下文标注（`querySource` 语义），不在 HTTP 层选方法；SSE 事件由 Lead 侧 `event_sink` 照常发出。
- `cli.py` `_run_analyze`：收敛到 `run()`；`--mode`/`! parallel` 相关旧分支删除或告警。
- MCP：工具面暴露 `run` 不变量；既有 `analyze/data_source` 工具保持兼容，内部走 `run()`。

### 3.8 修改 `config/loader.py` + `review_config.yaml`

- 语义从"决策开关"调整为"硬上限"：
  - `execution.mode`（single/parallel）**删除**——并行与否交由 Lead（`delegate.parallel`）；`execution.max_parallel_subagents` 保留为**硬上限**（即 `DelegateRunner.max_concurrent` 默认值）；
  - `max_discover_candidates` 保留为候选数硬上限；
  - 新增 `lead.max_orchestration_steps: int = 24`（Lead 编排步数硬上限）与 `lead.max_history_steps: int = 12`（Lead 上下文压缩保留步数，透传 `ReactAgent._compress_history`）。

### 3.9 上下文压缩与记忆注入（复用现有实现，新增装配）

原则：**不重写，只接线**。现有能力（单竞品内部已跑通）按"单竞品"粒度实现，本设计把同套机制复用到 "候选子 Agent / Lead 编排" 两个粒度：

- **压缩（代码控制，确定性无 LLM）**：`ReactAgent._compress_history(messages, max_history_steps, summary_lines, pinned_facts)` 按工具步（turn）折叠 + 累计摘要行 + pinned 段（已核验事实，`_PINNED_MAX_LINES`/`_PINNED_LINE_CHARS` 双封顶），**不发 LLM、结果可测**。
  - **候选子 Agent**：每个 `competitor` 运行时沿用 `react_agent` 默认 `max_history_steps`，无需改。
  - **Lead 编排会话**：`run()` 装配时把 `lead.max_history_steps` 透传给 Lead 的 `ReactAgent`；`delegate` 回填正文已由 `_render_record[:4000]` 截断，候选 JSON/结果不会单点撑爆上下文；仍超限时靠 Lead 压缩器折叠旧工具步。
- **记忆（代码召回注入）**：`react_loop.memory_context_fn(task)` → `IFourLayerMemory.recent_context(competitor, top_k, query)`（L1 会话/摘要召回，注入分析器 prompt；doc 35）。
  - **候选子 Agent**：按 `competitor_name` 召回（单竞品现有行为，自动生效）。
  - **Lead 聚合前**：候选级/品类级召回——`recent_context(competitor="", query=task)`（无具体竞品时按任务语义召回最近会话/摘要），注入 Lead 聚合工具上下文，让"市场格局结论"参考既有经验。
  - **记忆写入**：沿用 `BackgroundReviewer`（会话归档/质量评估/模式提取/DreamRecap），62 不新增状态；LLM Key 不可用时自动降级为仅建实例（memory 既有 fallback 不变量）。

## 4. 接入方式

### 4.1 数据流（DISCOVERY 示例）

```
run("帮我分析市面上常用的 coding agent")
  → parse_task → resolution=discovery
  → Lead ReactLoop（resolution 标注）
       首步 make_plan → plan={..., scheduling:{parallel:true, reason:"候选多需并行"}}
       → web_tool(scope="市面上常用的 coding agent") → 候选 JSON 回填（doc 61）
       → delegate(targets=[候选竞品名], parallel=true, reason="候选多") → 后台并发委派候选子 Agent
            → 各子 Agent Final Answer(dimensions[] 多维度条目 + official_links) 合并回填
       → aggregate_report(parts, kind="position") → 市场格局核心结论（LLM）
       → Final Answer 收尾
  → assemble：矩阵渲染（ReportBuilder）+ 结论段 → ComparisonReport
```

> 同一 Lead loop 亦承载 registry（单竞品：无需 web_tool 枚举，delegate 维度 → Final Answer REPORT_SCHEMA → CompetitorReport）与 compare（无 web_tool，delegate(targets=[已知竞品], parallel) → aggregate_report(kind="compare") → ComparisonReport）；区别仅在 `plan.resolution` 标注与是否需候选枚举。

### 4.2 配置（`review_config.yaml`）

```yaml
execution:
  max_parallel_subagents: 4   # 保留为硬上限 = DelegateRunner.max_concurrent 默认；删 execution.mode
  max_discover_candidates: 10 # 候选数硬上限
lead:
  max_orchestration_steps: 24 # Lead 编排步数硬上限
  max_history_steps: 12       # Lead 上下文压缩保留步数（透传 ReactAgent._compress_history）
```

### 4.3 评测/确定性

- `BenchmarkMockLLM` 增 DISCOVERY/COMPARE 的 **ReAct-scripted** 分支：收到 `web_tool` → 返回固定候选；收到 `delegate` → 候选子 Agent 确定性返回标准 `dimensions[]`（逐候选多维度条目 + official_links）、维度子 Agent 确定性返回单维度条目；收到 `aggregate_report` → 返回固定结论；Lead 按 resolution 确定性收尾（registry→REPORT_SCHEMA，compare/discovery→comparison JSON）。评测无需真实网络/LLM，门禁可复现。
- `HARNESS_VERSION` 递增并登记（house 规则）。

## 5. 验证方式

- **单测（delegate 扩展）**：`test_delegate_candidate.py` —— `targets` 候选/维度兼用；`parallel` 触发批量 spawn、`parallel=false` 串行；并发度硬收敛不超上限；超时 `TIMED_OUT`；单候选失败不影响整体；`reason` 记入事件/日志可观测性。
- **单测（aggregate）**：`test_aggregate_tool.py` —— `kind` 校验、结论段含竞品名、缺失竞品标注、`aggregate_report` 缺失时 `build_comparison` 矩阵兜底不报错。
- **单测（装配）**：`run()` 统一单 Lead——内部无 resolution 分派 if-else；registry/compare/discovery 同走一条 Lead loop，组装按 `plan.resolution` 分型（CompetitorReport/ComparisonReport）；`compare/discover` 兼容薄包装告警；配置语义（`execution.mode` 移除、`lead.max_orchestration_steps`/`max_history_steps` 解析）。
- **集成**：mock Lead 下 `run("市面上所有 coding agent")` 全链路——Lead make_plan(competitors+scheduling)→web_tool→delegate(并发)→aggregate_report→多竞品报告；候选并行计数；单候选失败聚合其余；候选子 Agent 结果含标准 `dimensions[]` 且组装为每候选 CompetitorReport 出矩阵；`run("分析 Cursor")` 同走一条 Lead loop 且组装为 CompetitorReport（按 `plan.resolution` 分型）；**压缩**：超 `lead.max_history_steps` 后确认 Lead 消息被 `_compress_history` 折叠且 pinned 保留；**记忆**：确认 Lead 聚合前收到品类级 `recent_context` 召回。
- **回归**：既有 `test_discovery.py`/`test_compare*`/`test_search_provider.py` 迁移到新装配断言；全量 `pytest` 保持绿；mypy 改动文件不新增错误。
- **实测**：有 Key 环境 `run("帮我分析市面上常用的 coding agent")`，日志应见 Lead 依次调用 `web_tool → delegate(并行) → aggregate_report`，报告含矩阵 + 市场格局核心结论段；不再出现"预算耗尽/代码固定并行"提示。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 |
|---|---|---|
| 0 | 本设计文档 + README 索引登记 | 收敛原则（对齐 Claude/业内：代码骨架 + LLM 内容） |
| 1 | `delegate` 扩展 + 候选子 Agent 注册 | 候选/维度兼用、`parallel/reason`、并发硬收敛 |
| 2 | `aggregate_tool.py` + Lead prompt 扩展 | `aggregate_report` + 编排提示（候选子 Agent 标准 `dimensions[]` 产出指引） |
| 3 | `run()` 单 Lead 统一 + comparison 组装 | 全 resolution 走同一 Lead loop、无分派 if-else；组装按 `plan.resolution` 分型；候选子 Agent `dimensions[]` → 每候选 CompetitorReport → 矩阵 + 结论段 |
| 4 | 压缩/记忆装配 + mock 分支 + 测试迁移 | Lead 品类级召回、`lead.max_history_steps`；DISCOVERY/COMPARE ReAct-scripted 分支 + HARNESS_VERSION；既有测试迁移 |
| 5 | 文档收口 + 提交 | README/CHANGELOG/docs 同步 |

每里程碑独立提交（`feat(agent)` / `refactor(...)` / `test(...)` / `docs(design)`）。

## 7. 风险与缓解

1. **改动面大（覆盖 web/CLI/MCP/评测）**：分派收敛触及多处。缓解：`run()` 内保持兼容薄包装（`discover/compare` 告警转发），既有测试逐一迁移，分目录分批跑绿。
2. **Lead 不按编排走 / `aggregate_report` 缺失**：缓解：make_plan 首步强制 + 回灌提示；`aggregate_report` 缺失时仍用既有 `build_comparison` 矩阵兜底（结论段为空不报错）；候选子 Agent 失败回灌可自恢复。
3. **评测确定性**：真实 LLM 调度不可复现。缓解：mock ReAct-scripted 分支 + `HARNESS_VERSION` 递增登记。
4. **`delegate` 泛化后的维度/候选混用**：`targets` 既可能是维度也可能是候选竞品。缓解：以 `SubagentRegistry` 为唯一键源（注册即合法），`competitor` 子 Agent 配置独立命名空间，避免 `delegate(dimensions=[@competitor...])` 歧义；工具实现按名称查注册表收敛。
5. **并发线程安全**：候选子 Agent 后台并发共享 RAG/记忆。缓解：沿用 doc 49 `DelegateRunner` 既有锁与独立预算模式，会话收尾统一 `shutdown`。
6. **兼容语义**：`execution.mode` 删除影响既有配置。缓解：加载时对未知键告警而非静默；文档说明"并行已归 Lead 决策、配置仅硬上限"。

## 核心技术点总结

- **编排原则收敛（对照 Claude 一次评审）**：从"发明专用编排工具 + 强 schema"回到"**代码守骨架 + LLM 回合内自调通用工具**"。候选分析为复用既有通用 `delegate`（扩展可委派候选竞品，不新造 `discover_candidates/analyze_competitor`）；`SCHEDULE_SCHEMA` 降为 `delegate` 可选参数 `{parallel, reason}`，并发细节交 `DelegateRunner` 默认。
- **统一 `run()` 入口**：web/CLI/MCP 分派 if-else 消除；`resolution` 从"分派终点"改为"编排起点/querySource 标注"（对齐 Claude：`querySource` 只作标注、不驱动分支）。
- **聚合归 LLM，保留 `aggregate_report`**：Lead 决定聚合口径并产出"市场格局核心结论"；矩阵仍由 `ReportBuilder.build_comparison` 渲染（执行层），职责边界不变。
- **压缩/记忆注入（复用现有）**：候选子 Agent 与 Lead 编排会话各用 `ReactAgent._compress_history`（确定性无 LLM）+ 四层记忆召回；Lead 聚合前新增品类级 `recent_context(competitor="", query=task)` 召回；写入沿用 `BackgroundReviewer`，62 不重写、只装配。
- **安全兜底不变**：url_guard / 注入防护 / 预算 / 取消 / checkpoint 仍由代码硬守（doc 49 不变量）。

---

> 触发关联：上一轮 "将是否并发交给主编排 LLM"。本文档经对照 Claude Code（`query.ts` 回合循环、`querySource` 标注、`extract_memories`/autocompact 代码 gate）后收敛：编排骨架归代码、内容与调度意图归 LLM；单竞品内部编排（doc 49）与联网候选枚举（doc 61）保持不变。