# 设计文档 49 — 多 Agent 领域差异化编排：证据链回填 / 新鲜度驱动委派 / 对抗式评审 / 跨竞品去重 / 经验路由

> 触发：2026-08-18 调研——对比 bytedance/deer-flow（`/home/d00841237/code/deer-flow`）的多 Agent 机制后，
> 确认 competitor_agent 的 team（`team/orchestrator.py`）已是"事件驱动 + 状态决策"的固定流水线（Collector→Analyzer→
> Validator→Reporter），与 deer-flow"Lead Agent 用 `task()` 工具动态委派 + 子 Agent 后台线程池 + 轮询回填"相比，
> **缺的不是"动态委派"骨架，而是竞品分析领域的差异化智能**——deer-flow 的通用骨架可单调复用，但领域收益来自
> 把本项目已有的资产（证据链、新鲜度、链式校验、L3/L4 记忆、同源哈希）提升到编排层。
> 决策：**不引入 LangGraph/不引入独立子会话轮询**，在现有 `TeamOrchestrator` 骨架上做 5 项领域差异化编排
> （证据链回填+跨维度冲突检测 / 新鲜度驱动委派 / 对抗式评审 ReviewerAgent / 跨竞品同源去重 / 经验路由委派）。
>
> 前置：47（主路径单轨 LLM）、48（skill 化）、33（team 真协作 `MessageBus.publish_async`/`FactValidator.arbitrate`）、
> 44（链式分析 `_analyze_with_llm`/`_verify_via_tools`/`_needs_verification`）、26（新鲜度 TTL/`refresh_stale`/`TimelineMemory`）、
> 45（L3 `SkillStore` 成功率 + L4 `retrieve_patterns_with_outcome` → `_apply_pattern_boost`/`set_failure_penalties`）。
> 参考实现：deer-flow `agents/lead_agent/agent.py`（`make_lead_agent`）+ `tools/builtins/task_tool.py`（`task_tool`/`_task_result_command`
> 以 ToolMessage 回填主 Agent）+ `subagents/executor.py`（`SubagentExecutor` 后台线程池 + 独立上下文）。

## 1. 问题现状

- deer-flow 的多 Agent 是**通用骨架**（Lead Agent 委派 → 子 Agent 后台执行 → 轮询回填主 Agent 下次模型调用），
  competitor_agent 的 team 是**领域固定流水线**（状态决策、无动态委派），两者对比：

| 能力 | deer-flow | competitor_agent team | 差异点 |
|---|---|---|---|
| 委派模型 | Lead Agent 用 `task()` 工具动态委派任意子 Agent | 固定 4 角色（Collector/Analyzer/Validator/Reporter）顺序流水线 | 领域任务维度固定（6 维分析），**动态委派收益低**，固定流水线更可控 |
| 结果回填 | 后台线程池执行，轮询 `get_background_task_result` 以 ToolMessage 回灌 | `MessageBus.publish_async(await_result=True)` 直接等产出 | 已等价（33），无需轮询 |
| 证据/事实 | 无领域证据链概念 | `Observation.evidence`（`SourceEvidence`：url/trust_level/content_hash） | **本项目独有资产，未用于编排** |
| 冲突处理 | 无 | `FactValidator.arbitrate` 同维度多来源取优（33） | 仅**同维度**仲裁，**跨维度同一事实冲突**未检测 |
| 新鲜度 | 无 | 报告层 `ReportFreshness` + `refresh_stale`（26） | TTL 只在报告/重爬用，**未驱动编排层委派** |
| 评审/证伪 | 无 | 链式分析内 `_needs_verification`/`_verify_via_tools`（44） | 工具补证只在**分析器内部**，无**独立对抗式评审角色** |
| 去重 | 无 | `content_hash` 仅存证据，无跨竞品同源缓存 | 多竞品对比（`compare`）时同 URL 重复抓取 |
| 经验路由 | 无 | L3/L4 只注入 selector 成功率/失败惩罚（45） | 经验**未喂给规划/委派决策** |

- **问题**：① 证据链停留在"单个结论←单个来源"的逐条记录，没有在**编排层跨维度**核对同一事实的矛盾（例：pricing 说
  "$20/mo" 而 performance 证据里同源页面写 "$25/mo"）；② 新鲜度 TTL 已算好但采集阶段仍**无差别全量抓**，过期维度不优先、
  新鲜维度不跳过；③ 分析器自检（`_needs_verification`）是"自己核对自己"，缺一个**独立 Reviewer 角色主动证伪**，防止
  单一 LLM 自洽性陷阱；④ `compare(*competitors)` 对共享官网/榜单源重复抓取；⑤ L3/L4 记忆只提升选源排序，**没有提升
  "委派哪个维度、先做哪个缺口"的决策**。
- **不变量**：本次**不触碰**已走 LLM 的调用结构/次数/schema（47/48 承诺）；**不引入** LangGraph、独立子会话后台线程池、
  轮询回填（33 的 `publish_async` 已等价）；保证型逻辑（注入防护/选源路由/降级链/真值校验兜底/仲裁阈值/聚合/渲染/checkpoint）保持代码兜底。

## 2. 目标设计

在 `TeamOrchestrator` 现有骨架上做 5 项**领域差异化编排**（skill/机制分离延续 48）：

1. **证据链回填 + 跨维度冲突检测（编排层）**：分析结果携带结构化证据链（`dimension → {claim, evidence_hashes}`），
   Validator 阶段在 `arbitrate`（同维度）之外**新增跨维度冲突检测**——同 `content_hash` 来源在同一事实键上输出不同值
   → 记 `ConflictRecord` 并回灌需要复核的维度（触发重分析或报告标注），复用 `SourceEvidence.content_hash` 作为同源判据。
2. **新鲜度驱动委派**：TTL 从"报告标注/定时重爬"提升到**编排层委派**——Collector 按维度新鲜度（`ReportFreshness` +
   归档/时间线）决定委派哪些缺口：过期维度优先委派采集、新鲜维度跳过采集只走分析、时间线变更事件（26）命中维度提权。
3. **对抗式评审 ReviewerAgent（第 5 角色）**：Reporter 之前插入独立 `ReviewerAgent`——对草稿维度结论**主动证伪**
   （复用 44 的 `_verify_via_tools` 语义做"反方核对"：找反例来源、复查关键数值、跨维度矛盾），产出
   `needs_revision`（带问题清单）回灌 → 对应分析器**有限重试修订**（≤1 轮），仍不通过则报告标注 `[REVIEWED/PARTIAL]`。
4. **跨竞品同源去重**：采集层维护 URL 级 `content_hash` 缓存（跨竞品共享），同源 URL 二次抓取直接复用缓存观测
   （`compare` 多竞品共享官网/榜单时省抓取 + 保证跨竞品引用同一版本数据）。
5. **经验路由委派**：把 L3 `SkillStore` 成功源/L4 失败反例提升到**委派决策**——规划后按维度经验排序缺口执行顺序、
   对失败反例命中维度降级委派（跳过高风险源/换路由），与现有 `_apply_pattern_boost`/`set_failure_penalties` 叠加。

**编排协议整合**：`run_async` 阶段序列扩为
`Collector（新鲜度驱动委派）→ Analyzer（并行，证据链回填）→ Validator（arbitrate + 跨维度冲突检测）→ ReviewerAgent（证伪 → needs_revision 回灌重分析 ≤1 轮）→ Reporter`；
同步 `run()` 保持同语义（回归安全网）。评审回灌为**有界循环**（`_MAX_REVISION_ROUNDS=1`），不破坏 47 的调用次数不变量
（重试仅在评审提出 `needs_revision` 且命中维度时发生，mock 门禁下 Reviewer 无缺陷 → 零回灌）。

## 3. 模块/接口设计

### 3.1 证据链回填 + 跨维度冲突检测

- **领域模型**（`domain_types/observation.py`）：`SourceEvidence`（:13，含 url/trust_level/content_hash:19）已有同源判据；
  新增 `domain_types/conflict.py`：
  - `CrossDimensionConflict(claim_key, dimension_a, dimension_b, value_a, value_b, evidence_hashes, severity)`
  - `ConflictRegistry`：按 `claim_key × evidence_hash` 索引跨维度结论，产出冲突清单（`content_hash` 同源且键同名但值不同）。
- **Analyzer 侧**（`analyzers/base.py`）：`DimensionResult` 新字段 `evidence_hashes: list[str]`（从结论引用的
  `observation.evidence.content_hash` 收集，缺省空——向后兼容）；`_analyze_with_llm` 填写（非破坏）。
- **Validator 侧**（`team/validator_agent.py`）：`FactValidator` 新增 `detect_cross_dimension_conflicts(results) -> list[CrossDimensionConflict]`
  ——在 `arbitrate`（:115，同维度）之后执行，冲突命中维度由 `TeamOrchestrator` 决定回灌（§3.3）或报告标注
  （`ReporterAgent` 渲染「## 跨维度冲突备注」）。

### 3.2 新鲜度驱动委派

- **编排层**（`team/orchestrator.py::_collect_async`/`CollectorAgent.collect`）：Collector 委派前注入
  `FreshnessGate`（新 `core/freshness_gate.py`）：
  - `decide(competitor, planned_gaps, archive_freshness, timeline_events) -> dict[gap, fresh|stale|skip]`
    ——按维度 `dimension_ttl_days`（`FreshnessConfig`，26）判定：过期 → 委派采集（优先）；新鲜 → 跳过采集直接进入分析
    （复用归档观测）；时间线变更事件（26 `TimelineMemory`）命中维度 → 提权强制重采。
  - `facade/api.py` 装配时把 `archive`/`timeline` 传给 orchestrator（`TeamOrchestrator` 新增可选 `freshness_gate` 参数，缺省 None → 原行为）。
- 与 `refresh_stale` 区分：那是"事后过期重爬"，这是**委派期预防性跳过**，二者叠加不冲突。

### 3.3 对抗式评审 ReviewerAgent（第 5 角色）

- **新 `team/reviewer_agent.py`**：`ReviewerAgent(BaseAgent)`（挂 `AgentContext`/`AgentResult` 生命周期）：
  - `review(ctx, draft_results) -> ReviewVerdict`：对每个 `DimensionResult` 主动证伪——
    a) 关键数值复查：复用 44 `_count_numeric_conflicts`/`_verify_via_tools` 语义做**反方核对**（用 `tool_dispatcher` 独立重查同源/别源）；
    b) 跨维度矛盾：消费 §3.1 的 `CrossDimensionConflict`；
    c) 置信度/证据不足：低于阈值（复用 `FactValidator.min_confidence` 语义）标 `needs_revision`。
  - 产出 `ReviewVerdict(ok: bool, issues: list[ReviewIssue])`，`needs_revision` 携带 issue（dimension/claim/期望动作）。
- **回灌**（`team/orchestrator.py::run_async`）：Reviewer 出 `needs_revision` → 对命中维度**重入 Analyzer 修订**
  （`_MAX_REVISION_ROUNDS=1` 有界），修订后**强制复查**该维度（不再无限回灌）；超限未过 → 报告标注
  `[REVIEWED]` + issue 摘要，不降级为失败。
- **确定性**：`BenchmarkMockLLM` 下 Reviewer 基于 mock 无缺陷 → `ok=True` 零回灌，LLM 调用次数不变（§4.3）。

### 3.4 跨竞品同源去重

- **新 `core/source_dedup.py`**：`SourceDedup`（进程内 URL→content_hash 缓存 + 可选落盘归档复用）：
  - `get_or_fetch(url, fetch_fn) -> Observation`：hash 命中直接复用缓存观测（跨竞品共享，`compare` 多竞品同源省抓取）。
  - 缓存键 = 规范化 URL（复用 `url_guard` 的归一化），内容相同但 URL 不同 → 仅当 `content_hash` 命中时复用。
- **接入**（`collector/` 采集入口）：`GapExecutor.fetch_candidate`/`CollectorAgent` 采集前查 `SourceDedup`，命中跳过网络请求。

### 3.5 经验路由委派

- **规划期委派排序**（`core/strategic_loop.py`）：`StrategicPlanner.plan` 产出 `gaps` 后，新增 `_order_gaps_by_experience`
  ——按 L4 `retrieve_patterns_with_outcome`（45）排序缺口执行顺序（成功模式维度提前、失败反例命中维度后置并降权），
  与 `_apply_pattern_boost`（置信度）叠加；纯排序不改变缺口集合，mock 门禁下无经验 → 顺序不变。
- **委派降级**（`team/orchestrator.py` 装配）：`_set_selector_penalties`（45）已有 selector 失败惩罚；
  新增把失败反例同时传给 `FreshnessGate`/委派（高风险维度走保守委派：少并行、优先重查）。

### 3.6 不宜改（保证型，保持代码，明确清单）

| 项 | 位置 | 理由 |
|---|---|---|
| 注入防护 | `agent/prompts/trust_boundary.py` + 命中短路 | 安全，不能交给 LLM |
| 选源路由 | `source_selector.py`（:17 `_GAP_TO_KINDS`/`candidates`）、SPA 兜底 | 确定性：benchmark 门禁 tool_sel 依赖固定路由 mock oracle |
| 降级链/预算/取消/checkpoint | `gap_executor.py`/`budget.py`/`checkpoint.py`/`orchestrator.py` | 编排机制，非知识 |
| 真值校验动作 | `base.py:80 _count_numeric_conflicts`/`_verify_details` | 强制兜底（LLM 不保证自觉遵守） |
| 链式停止 | `base.py:47 _UNHELPFUL_TOOL_MARKERS`/`_MAX_CHAIN_STEPS` | 防 stub 当证据/防无限循环 |
| 同维度仲裁/阈值 | `validator_agent.py:46` `FactValidator`/`arbitrate:115` | 正确性保证（跨维度冲突检测是**新增**，不改仲裁语义） |
| 聚合/渲染 | `report_builder.py`/`markdown_renderer` | 确定性输出 |
| 已走 LLM 调用结构 | `parse_task`/`plan`/`analyze` 调用次数与 schema | 47/48 不变量 |
| 定价结构抽取 | `pricing_analyzer.py` `_parse_plan`/`_detect_tier`/`_estimate_costs` | schema 归一化，非编排 |

## 4. 接入方式

### 4.1 配置开关

- `config/review_config.yaml` 新增 `orchestration` section：
  - `reviewer.enabled`（默认 false，行为不变；启用后 `run_async` 插入 ReviewerAgent）
  - `freshness_delegation.enabled`（默认 false；开启后 Collector 走 `FreshnessGate` 委派）
  - `cross_dimension_conflict.enabled`（默认 true，仅检测+标注，不改结论）
  - `source_dedup.enabled`（默认 true，`compare` 多竞品共享源省抓取；无副作用）
  - `experience_routing.enabled`（默认 true，纯排序不改缺口集合）
- 默认全部保守：评审/新鲜度委派默认关（零行为变化），冲突检测/去重/经验排序默认开（无副作用）。

### 4.2 阶段序列（`run_async`）

```
Collector(FreshnessGate 委派, SourceDedup 去重)
  → Analyzer(并行, DimensionResult.evidence_hashes 回填)
  → Validator(arbitrate 同维度 + detect_cross_dimension_conflicts 跨维度)
  → ReviewerAgent(证伪 → needs_revision → Analyzer 修订 ≤1 轮 → 复查)
  → Reporter(draft, 渲染冲突/评审标注)
```
同步 `run()` 保持同语义（回归安全网）；`analyze()`/`analyze_team` 入口不变（`TeamOrchestrator` 构造参数可选）。

### 4.3 评测/确定性保持

- `BenchmarkMockLLM` 各维分支不变；Reviewer 在 mock 下无缺陷 → `ok=True` 零回灌 → **LLM 调用次数不变**；
- `FreshnessGate` 默认关（mock 环境无归档新鲜度）→ 委派行为不变；
- 新增 `tests/evaluation/test_orchestration_eval.py`：mock 全量门禁（字段 1.0/幻觉 0/工具选择 ≥0.85/trace 100%）在开启
  `reviewer`/`freshness_delegation` 后仍过，且无缺陷时回灌次数 0。

### 4.4 测试处理

| 类别 | 处理 |
|---|---|
| 新增 | `tests/unit/domain_types/test_cross_dimension_conflict.py`（同源同键异值检测/无冲突/severity）、`tests/unit/core/test_freshness_gate.py`（过期优先/新鲜跳过/时间线提权/关默认）、`tests/unit/team/test_reviewer_agent.py`（无缺陷 ok/数值反证 needs_revision/超限标注/回灌 ≤1 轮）、`tests/unit/core/test_source_dedup.py`（同 URL 复用/跨竞品共享/不同内容不误用）、`tests/unit/strategic_loop` 经验排序（有经验提前/无经验不变） |
| 新增 | 集成：`tests/integration/test_domain_orchestration.py`——mock LLM 下开全部开关跑通 `analyze_team_async`，报告含冲突/评审标注、采集去重计数 |
| 回归 | 全量 `pytest`（916）保持绿；`_base_messages`/`_plan_messages` 不动（48 注入不变量） |
| benchmark | mock 全量门禁回归不变（§4.3） |

### 4.5 文档收口

- `competitor_agent/README.md` 补「多 Agent 领域差异化编排（设计文档 49）」简述段 + 设计文档索引行；
- `docs/usage.md`/`docs/evaluation_guide.md` 补 `orchestration` 配置与评测口径；
- `implementation_plan.md` 登记 §20（第六轮）；`issue_designs/README.md` 索引登记（📄 设计已出）。

## 5. 验证方式

- **单测（新增）**：冲突检测 / FreshnessGate / ReviewerAgent（含回灌 ≤1 轮）/ SourceDedup / 经验排序；
- **集成**：`mock_llm` fixture 下开全开关跑 `analyze_team_async` 全链路——报告含跨维度冲突/评审标注，`compare` 多竞品同源去重计数下降；
- **回归**：全量 `pytest`（916）通过；benchmark mock 门禁不变；mypy 不新增错误；
- **实测**：有 Key 环境 `analyze("Claude Code")` 出报告；对比开/关 `reviewer` 时一次分析的 LLM 调用次数**不变**（无缺陷零回灌）。

## 6. 实现优先级与工作量

| 阶段 | 内容 | 预计 |
|---|---|---|
| P0 | 对抗式评审 ReviewerAgent（新 `team/reviewer_agent.py` + `ReviewVerdict` + orchestrator 回灌 ≤1 轮 + 报告标注） | 1 天 |
| P1 | 新鲜度驱动委派（`core/freshness_gate.py` + Collector 委派 + api 装配） | 0.5-1 天 |
| P2 | 证据链回填 + 跨维度冲突检测（`DimensionResult.evidence_hashes` + `detect_cross_dimension_conflicts` + 渲染标注） | 0.5-1 天 |
| P3 | 跨竞品同源去重（`core/source_dedup.py`）+ 经验路由委派（`_order_gaps_by_experience`） | 0.5-1 天 |

- 依赖：47/48（单轨 LLM + skill 不变量）、33（team 真协作/arbitrate）、44（`_verify_via_tools` 复用）、26（新鲜度/时间线）、45（L3/L4 经验）。
- 风险：评审回灌可能引入额外 LLM 调用（突破 47 调用次数不变量）。缓解：`_MAX_REVISION_ROUNDS=1` 有界 + mock 无缺陷零回灌 +
  `reviewer.enabled` 默认关（显式开启才生效），回归测试断言"开启后无缺陷回灌次数 0"。
- 范围外（不修改）：deer-flow 通用骨架（不引入 LangGraph/独立子会话轮询）、已走 LLM 的调用结构、保证型逻辑清单（§3.6）。
