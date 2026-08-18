# 设计文档 49 — 多 Agent LLM 主导编排（deer-flow 式）：Lead Agent 动态委派 + 独立 LLM 子 Agent + 领域逻辑 skill/工具化

> 触发：2026-08-18 用户决策——吸收 bytedance/deer-flow（`/home/d00841237/code/deer-flow`）的多 Agent 模型：
> **Lead Agent 用工具动态委派 + 子 Agent 后台线程池执行 + 结果以 ToolMessage 回填 Lead 会话**，编排由 LLM 主导，
> 子 Agent 内部也是 LLM 主导编排与工具调用；competitor_agent 独有的流程/校验脚本保留为 **skill（知识注入）或工具（可调用函数）**。
> 上一版 49（固定 `TeamOrchestrator` 流水线 + 5 项领域编排，Collector→Analyzer→Validator→Reviewer→Reporter）是过渡版，
> 本轮重构为 **LLM 主导的多 Agent 编排**（废弃删除 team/ 固定流水线）。
>
> 前置：47（主路径单轨 LLM）、48（skill 化 `SkillLoader` + 9 skills）、40/41（MCP↔ReAct 统一工具面 + `build_react_dispatcher` + URL 守卫）、
> 43（`ReactLoop` 共享会话上下文：cancel/budget/memory/RAG/events）、44（链式分析语义）、45（L4 `retrieve_patterns_with_outcome` 读侧）、
> 26（新鲜度/时间线）。参考实现：deer-flow `tools/builtins/task_tool.py`（`task_tool`/`_task_result_command` 以 ToolMessage 回填主 Agent）
> + `subagents/executor.py`（`SubagentExecutor` 后台线程池 + 独立上下文 + `execute_async`/`get_background_task_result`/`cleanup_background_task`）
> + `config/subagents_config.py`（`CustomSubagentConfig` 预注册）。

## 1. 问题现状

- **现状**：编排决策在代码。`analyze()` 走 `TeamOrchestrator` 固定阶段序列（`team/orchestrator.py` `run`/`run_async`：
  Collector→Analyzer→Validator(arbitrate + 跨维度冲突)→Reviewer(≤1 轮回灌)→Reporter），LLM 只出现在
  `StrategicPlanner.plan`（PLAN_SCHEMA）与 analyzer 抽取（`analyzers/base._analyze_with_llm`）；Collector/Validator/Reviewer/Reporter 无 LLM。
- **deer-flow 模型**（源码结论）：
  1. Lead Agent = 一个 LLM ReAct agent（`make_lead_agent`），编排决策在它的循环里发生；
  2. `task()` 工具（`task_tool.py:210`）`(description, prompt, subagent_type)`——Lead LLM 自主决定何时委派、委派给谁；
  3. 子 Agent = **独立完整 agent**（`executor.py _create_agent` → `create_agent(model, tools, middleware, state_schema)`），
     自己的 model、工具子集（`_filter_tools` 按 `config.tools`/`disallowed_tools`）、自己的 system prompt + 加载的 skills、
     自己的中间件链；子 Agent 内部同样 LLM 自主调工具、自主收尾；
  4. 执行与回填：`execute_async` 提交后台线程池（`_scheduler_pool.submit`），注册表 `_background_tasks[execution_id]`；
     `task_tool` 轮询 `get_background_task_result`（每 5s），terminal 后 `_task_result_command` 构造
     `Command(update messages += ToolMessage(content, tool_call_id, name="task"))`——**子 Agent 结果作为一条工具 Observation
     进入 Lead 会话，Lead 下一次 LLM 调用读到它继续决策**；
  5. 子 Agent 配置：`CustomSubagentConfig`（name/model/tools/disallowed_tools/system_prompt/skills/timeout/max_concurrent）。
- **本项目差距**：没有「Lead 委派子 Agent」的 `task()`/`delegate` 工具；不存在「独立 LLM 子 Agent」概念（现有 Collector/Analyzer/
  Validator/Reviewer/Reporter 是代码角色）；编排决策在代码。
- **已具备复用件**：`ReactAgent`（`agent/react_agent.py`，单 Agent LLM 工具循环，`build_system_prompt` 已支持注入 `skills`）+
  `ReactLoop`（`agent/react_loop.py`，budget/cancel/memory/RAG/events/obs 截断/历史压缩）可直接作为 Lead 与子 Agent 的引擎
  （**不需要引入 LangGraph**）；`build_react_dispatcher` + 8 工具（web_extract/web_search/analyze_pricing/github_stars/
  github_releases/github_commits/run_benchmark/analyze_competitor）；`SkillLoader` + 9 skills（planning / 6×`<dim>_analysis` /
  fact_verification / confidence_disclosure）。
- **不变量**：安全与机制类逻辑**强制代码兜底，不进 LLM**——注入防护（`trust_boundary`）、URL 守卫（`url_guard`）、
  预算/取消/checkpoint、聚合/渲染/归档/导出、评测 harness。deer-flow 通用骨架可借鉴其「委派 + 回填」模型，但不照搬其框架。

## 2. 目标设计

主路径改为 **LLM Lead Agent 编排的多 Agent 流程**：

```
CompetitorAnalysisAPI.analyze(task, session_id=…)
  → 构建 Lead ReactLoop（共享 cancel/budget/memory/RAG/events，max_steps≈12）
  → Lead LLM 自主编排：
       首步必须 make_plan（PLAN_SCHEMA：competitor/dimensions/budget/custom_sources）——否则回灌"必须先 make_plan"
       之后自由调用 delegate / web_extract / web_search / github_* / run_benchmark / 复核工具
       低置信/冲突关键数值 → validate_facts / 重新抓取核验（承接 44 的 _verify_via_tools 语义）
       需要时对维度子 Agent 委派（delegate 批量后台并发 + 结果回填）
       Final Answer 输出 REPORT_SCHEMA JSON（competitor + dimensions[{dimension,summary,details,confidence,evidence_urls}]）
  → react_report.assemble → CompetitorReport（多维度，复用 ReportBuilder 渲染/freshness/证据链）
  → _record_memory_success(report, transcript)（唯一记忆写侧）
  → 时间线 / 归档 / 导出 / checkpoint → return report
```

**关键点**：

1. **Lead = ReactAgent + delegate 工具**：Lead 复用现有 `ReactAgent`/`ReactLoop`，新增 `make_plan` 与 `delegate` 两个工具。
   Lead 的"编排"= LLM 自主决定委派哪些维度子 Agent、分几批、是否补证、何时收尾——编排不再有代码阶段序列。
2. **delegate 工具 = 批量后台并发委派 + 回填**（用户确认：后台并发+回填，仿 deer-flow）：`delegate(task, dimensions=[...])`
   一次性 spawn 指定维度子 Agent（后台线程池并发），阻塞轮询全部 terminal 后把各子 Agent 结果（截断）合并回填为一条
   Observation（`wrap_untrusted`）。Lead 仍自主决定分批（如先委派 core 维度，读结果后再委派次要维度）。
   *与 deer-flow 差异*：deer-flow 是 Lead 多轮多次 `task()` + 独立轮询（fire-and-poll）；本项目同步 ReAct 循环一次解析一个
   Action，故合并为「批量 spawn + 一次轮询 + 合并回填」，保留「后台并发」实质，不引入 fire-and-poll 状态机。
3. **子 Agent = 独立 LLM Agent**（用户确认：预注册 6 维度）：`SubagentRegistry` 预注册
   pricing/feature/performance/ecosystem/sentiment/roadmap，每个 = `ReactAgent` + 对应 `<dim>_analysis` skill +
   fact_verification + confidence_disclosure + 工具子集（web_extract/web_search + 维度专属工具：pricing 含 analyze_pricing、
   ecosystem/roadmap 含 github_*）；**排除 analyze_competitor**（防递归调用 analyze()）。子 Agent 内部 LLM 自主调工具、
   自主收尾（Final Answer = 维度结果 JSON）。
4. **保留逻辑 → skill / 工具 / 代码兜底**（用户确认：安全兜底 + 复核工具化）：

   | 现状资产 | 去向 |
   |---|---|
   | `planning` / 6×`<dim>_analysis` / `fact_verification` / `confidence_disclosure` skills（已有，48） | 注入 Lead / 对应子 Agent system prompt |
   | `SourceSelector` 选源路由（`collector/source_selector.py`） | `select_source` 工具（子 Agent/Lead 可调，确定性候选由代码生成） |
   | `FactValidator` / `_count_numeric_conflicts`（44） | `validate_facts` 工具（Lead 收尾代码强制复核兜底 + 可调） |
   | `ConflictRegistry` / `detect_cross_dimension_conflicts`（49 旧版） | `detect_conflict` 工具（Lead 收尾调用）+ 报告渲染兜底 |
   | `FreshnessGate`（49 旧版） | `check_freshness` 工具（Lead 决定是否重采） |
   | `SourceDedup`（49 旧版） | `web_extract`/`select_source` 内部透明（不进 LLM 决策） |
   | `PricingAnalyzer` 结构归一化/成本估算（27） | `analyze_pricing` / `estimate_costs` 工具 |
   | L3/L4 记忆经验（45） | 注入 Lead 规划提示（`_react_memory_context` 扩 L4 patterns），LLM 自主运用 |
   | `url_guard` / 注入防护 / 预算 / 取消 / checkpoint / 聚合渲染 / 归档导出 / 评测 | **代码强制兜底，不进 LLM** |

5. **报告组装**：新 `facade/react_report.py`——解析 Lead Final Answer 的 REPORT_SCHEMA JSON → 多维度 `DimensionResult` →
   `CompetitorReport`（复用 `ReportBuilder`/freshness/证据链）；非 JSON/非法 → 单 react 维度 PARTIAL（解析健壮性，非规则决策）。
6. **评测确定性**：`BenchmarkMockLLM` 改 **ReAct-scripted 编排**（用户确认废弃旧流水线后的必然路径）——mock Lead 按脚本：
   首步 make_plan → delegate（按 case dimension 委派）→ mock 子 Agent 按维度确定性抽取（复用现有抽取器命名空间）→
   Final Answer 组 REPORT_SCHEMA JSON；HARNESS_VERSION 0.6→0.7 重定门禁（house 规则：改动大允许重定并有记录）。

## 3. 模块/接口设计

### 3.1 新 `agent/react_schemas.py`

- `DIMENSIONS` 枚举（6 维，对齐现有 `Dimension`）。
- `PLAN_SCHEMA`（从 `core/strategic_loop.py` `_strategy_from_llm` 迁入，doc 44 定义不变：competitor 必填 + dimensions 枚举 + priorities/budget/custom_sources 可选）。
- `REPORT_SCHEMA`：`{competitor: str, dimensions: [{dimension, summary, details, confidence}]}`；details 键名沿用现有命名空间
  （plans/features/benchmarks/…）使 evaluation 抽取与渲染不变。
- `SUBAGENT_RESULT_SCHEMA`：`{dimension, summary, details, confidence, evidence_urls: [url]}`（子 Agent Final Answer，含证据 URL 供记忆写侧/报告组装）。

### 3.2 新 `agent/subagent_registry.py`

- `SubagentConfig(name, tools: list[str], skills: list[str], system_prompt: str)`——工具子集白名单 + skill 名清单 + 专属提示。
- `SubagentRegistry`：预注册 6 维度（pricing: tools=[web_extract,web_search,analyze_pricing], skills=[pricing_analysis,fact_verification,confidence_disclosure]; …）。
- `build_subagent(name, llm, dispatcher, shared) -> ReactLoop`：构造子 ReactAgent（注入 skills）+ 子 ReactLoop
  （独立 `IterationBudget`、共享 `session_id` 取消、共享 memory/RAG、obs 截断）——子 Agent 即独立会话上下文。

### 3.3 新 `agent/delegate_tool.py`（仿 deer-flow `task_tool.py` + `subagents/executor.py`）

- `DelegateRunner`：后台线程池 `_scheduler_pool` + 注册表 `_background_tasks[execution_id]`（含 status/result/started_at/cancel_event）；
  `spawn(subagent, task, budget)` → `execute_async` 语义；`await_terminal(execution_id, max_polls)`（每 ~1-2s 轮询）；
  `cleanup`（terminal 后删除防泄漏）；超时 → `TIMED_OUT`。
- `delegate(task, dimensions, tool_call_id) -> str`：**工具函数**，一次 spawn 全部指定维度子 Agent（后台并发），
  轮询全部 terminal 后把各结果（状态 + 截断正文）合并为一条回填文本；子 Agent 取消/超时逐维度标注，不影响其余。
- 回填格式复用现有 Observation 约定：`Observation（工具结果，不可信外部数据）: <wrap_untrusted(截断)>`。

### 3.4 新 `facade/react_report.py`

- `assemble(lead_answer, competitor, loop_plan, transcript) -> CompetitorReport`：
  解析 REPORT_SCHEMA JSON → `DimensionResult` 列表（dimension/summary/details/confidence + `evidence_hashes` 从
  `evidence_urls` 回填）；数值真值核对兜底（复用 `_count_numeric_conflicts` 语义，冲突 → 标注）；非 JSON → 单 react 维度 PARTIAL。
- 复用 `ReportBuilder` 渲染（freshness/证据链/时间线段落），`gaps_pending` 按 plan 中未产出维度列明。

### 3.5 修改 `agent/react_loop.py`

- **plan-first 强制**：首步必须是 `Action: make_plan`（注入 dispatcher，非 MCP 工具）；否则回灌 Observation
  "必须先调用 make_plan"；`make_plan` 结果存入 `loop.plan`（供报告组装与记忆写侧）；plan 无效/未产出 → 报告 terminal `partial`。
- **transcript 捕获**：每步记录 `(tool, args, result_brief, url)`（工具结果中的首个 URL），供 `_record_memory_success`。
- 子 Agent 支持：`run_subagent`（独立预算/会话，复用 `run_with_result` 语义）。

### 3.6 修改 `agent/tool_registry.py`

- `build_react_dispatcher(*, exclude=(), extra_tools=None)`——`exclude=("analyze_competitor",)`（防递归）、
  `extra_tools` 注入 `make_plan`/`delegate`/`validate_facts`/`detect_conflict`/`check_freshness`/`select_source`/`estimate_costs`。
- `build_subagent_dispatcher(name)`——按 `SubagentConfig.tools` 白名单构造子 Agent 工具面（web_extract 覆盖真实采集链路）。

### 3.7 修改 `agent/prompts/react_system.py`

- `build_lead_system_prompt`：plan-first（首步 make_plan）/委派策略（delegate 用于维度子任务）/复核工具用法
  （低置信/冲突关键数值重抓核验，承接 44）/Final Answer=REPORT_SCHEMA JSON；注入 planning + fact_verification skills。
- `build_subagent_system_prompt(name)`：维度任务说明 + `<dim>_analysis` skill + fact_verification + confidence_disclosure；
  Final Answer=SUBAGENT_RESULT_SCHEMA JSON。

### 3.8 修改 `facade/api.py`

- `analyze()` 收拢为 Lead ReAct；`mode` 参数废弃（兼容接受 + 告警）；`analyze_team`/`analyze_team_async` 保留为薄包装委托 `analyze()`；
  `analyze_stream` 不变（包装 `analyze()`）。
- `_react_loop` 注入 `make_plan` + `delegate` + 复核工具 + `exclude=("analyze_competitor",)` + `max_steps≈12`。
- `_record_memory_success(report, transcript)` **单点**（删除 `_record_team_memory_success`）：每维度取 transcript 首个 URL → record_skill/record_outcome/note_pattern。
- `resume()` 重构：pending 缺口合成 Lead ReAct 任务，合并 checkpoint 已完成维度。
- `compare`/`discover`/`_disambiguate_with_history` 改 LLM-only（47 已单轨，保持）。
- 删除 `_begin_team`/`_finish_team`/`_orchestrator_for(mode)`/`_freshness_gate_for`/`_archive_freshness_for`/`_archive_results_for`/`_set_selector_penalties`。

### 3.9 修改 `mcp_server/tools/pricing_tools.py`

- `analyze_pricing` 去 `SourceSelector` 依赖：改 `competitor_registry` 查 official_links + `WebExtractor` 直抓（签名不变，doc 47 计划项）。

### 3.10 修改 `config/loader.py` + `review_config.yaml`

- 删除旧 5 开关（`orchestration.reviewer`/`freshness_delegation`/`cross_dimension_conflict`/`source_dedup`/`experience_routing`——被工具化/内部化取代）。
- 新增 `subagents` section：`enabled`（默认 true，主路径）/ `max_concurrent`（默认 3，对齐 `budget.max_parallel_subagents`）/ `timeout_seconds`（默认子 Agent 超时）。
- 复核工具开关：`tools.validate_facts`/`tools.detect_conflict`/`tools.check_freshness`/`tools.select_source`（默认 true，注册即用）。

### 3.11 修改 `cli.py` / `web_app.py`

- `--mode` 废弃告警；无 LLM Key → `LLMUnavailableError` 友好报错 + 非零退出（47 语义不变）；Web 路由走 `analyze()`。

### 3.12 修改评测

- `evaluation/benchmark.py`：`BenchmarkMockLLM` 改 ReAct-scripted（首步 make_plan → delegate 按 case dimension → mock 子 Agent
  确定性抽取 → Final Answer 组 REPORT_SCHEMA JSON，details 复用现有抽取器）；`HARNESS_VERSION 0.6→0.7` + 门禁重定（字段 ≥0.90 / 幻觉 ≤0.05 / 工具选择 ≥0.85 / trace 100%）。
- `evaluation/ablation.py`：删 no-llm-rule（已有），改 `no-tools` 变体（单发 plan + Final Answer 无工具循环）保 5 列。
- `evaluation/behavior_eval.py`：`RecoveryEvaluator` 脚本加 make_plan 首步。
- `tests/conftest.py`：新增 `react_mock_llm`（ReAct-scripted Lead + 子 Agent 双角色）+ `react_fake_extractor` fixtures。

## 4. 接入方式

### 4.1 配置（`review_config.yaml`）

```yaml
# ===== 多 Agent LLM 主导编排（设计文档 49）=====
subagents:
  enabled: true            # analyze() 主路径 = Lead ReAct 编排
  max_concurrent: 3        # delegate 一次最大并发子 Agent 数（对齐 budget.max_parallel_subagents）
  timeout_seconds: 60      # 子 Agent 单次执行超时
tools:
  validate_facts: true     # 复核工具（事实/数值冲突核验）注册
  detect_conflict: true    # 跨维度冲突检测工具注册
  check_freshness: true    # 新鲜度查询工具注册
  select_source: true      # 选源工具注册（确定性候选由代码生成）
```

默认：主路径即 LLM 编排；安全兜底（url_guard/注入防护/预算/取消/checkpoint/聚合渲染）保持代码，不进 LLM。

### 4.2 阶段序列（语义）

```
Lead ReAct 循环（LLM 主导，无代码阶段序列）
  make_plan（强制首步）→ delegate 维度子 Agent（后台并发）→ 复核（validate_facts/detect_conflict/check_freshness）
  → 补证（web_extract/web_search）→ Final Answer REPORT_SCHEMA JSON
  → react_report.assemble → CompetitorReport → 记忆/时间线/归档/导出
```

### 4.3 评测/确定性保持

- `BenchmarkMockLLM` ReAct-scripted：mock Lead 固定脚本（make_plan → delegate → Final Answer），mock 子 Agent 按维度分支
  确定性返回 SUBAGENT_RESULT_SCHEMA JSON（details 复用现有抽取器命名空间）→ 门禁可复现（HARNESS_VERSION 0.7.0 重定并有记录）。
- 新增 `tests/evaluation/test_orchestration_eval.py`：mock 全量门禁在 `subagents.enabled=true` 下通过、delegate 次数按 case dimension
  确定、子 Agent 结果回填含证据 URL。

### 4.4 测试处理

| 类别 | 处理 |
|---|---|
| 新增单测 | `tests/unit/agent/test_subagent_registry.py`（6 维度注册/工具子集/skill 注入/排除 analyze_competitor）、`tests/unit/agent/test_delegate_tool.py`（后台并发/轮询 terminal/超时 TIMED_OUT/取消/清理/部分失败不影响其余）、`tests/unit/agent/test_make_plan.py`（首步强制/非首步回灌/plan 存储/无效 plan→partial）、`tests/unit/facade/test_react_report.py`（REPORT_SCHEMA 多维度组装/evidence_urls→hashes/数值冲突标注/非 JSON→单维度 PARTIAL）、`tests/unit/tools/test_validate_facts.py`（数值冲突/无冲突/低置信）、`tests/unit/llm/test_react_schemas.py`（PLAN/REPORT/SUBAGENT schema 校验） |
| 新增集成 | `tests/integration/test_react_multi_agent.py`：mock 下 `analyze("Cursor")` 全链路——Lead make_plan → delegate → 子 Agent 结果回填 → 多维度报告；并行委派计数；记忆写侧（每维度 transcript 首 URL → record_skill/outcome）；`compare` 多竞品走 Lead 编排 |
| 回归改写 | `tests/integration/` 大部分（team 流水线相关改 Lead 编排断言）、`tests/unit/facade/test_api*.py`、`test_react_context*.py`（脚本加 make_plan）、`tests/evaluation/` 全套（benchmark/ablation/behavior_eval/real_evaluation/skill_injection）、`test_cli`/`test_web`（mode 废弃告警、无 Key 报错） |
| 删除 | `tests/unit/team/`、`test_strategic_loop*`、`test_gap_executor`、`test_tactical_loop`、`test_stop_verifier`、`test_parallel_runner`、`test_source_selector`、`test_freshness_gate`、`test_cross_dimension_conflict`、`test_source_dedup`、`test_reviewer_agent`、`test_experience_routing`、`test_domain_orchestration`（team 语义删除）、analyzers 单测（complete_json schema 部分迁 `tests/unit/llm/`）、`test_dual_pipeline_consistency` team 半、`test_task_parser` 规则用例 |
| 保留 | `test_react`/`test_tool_registry`/`test_trust_boundary`/`test_url_guard`/`test_web_*`/`tests/unit/llm/`/memory 基础/budget/checkpoint/alerting/report_*/input_sanitizer/observability/agent 等 |

### 4.5 文档收口

- `competitor_agent/README.md` 改写「多 Agent」段为 LLM 主导编排；`docs/usage.md`/`docs/configuration.md`/`docs/evaluation_guide.md` 同步；
- `implementation_plan.md` 登记 §21（第七轮）；`issue_designs/README.md` 索引行更新（49 重构为 deer-flow 式 LLM 主导编排）。

## 5. 验证方式

- **单测（新增）**：子 Agent 注册表 / delegate 工具（并发/超时/取消/清理）/ make_plan 强制 / REPORT_SCHEMA 组装 / 复核工具；
- **集成**：`react_mock_llm` 下 `analyze("Cursor")` 全链路多维度报告 + 并行委派计数 + 记忆写侧 + compare 走 Lead 编排；
- **回归**：全量 `pytest` 保持绿（删减后规模收缩）；benchmark mock 门禁（HARNESS_VERSION 0.7 重定并有记录）；mypy 不新增错误；
- **实测**：有 Key 环境 `analyze("Claude Code")` 出报告，LLM 调用可见 make_plan→delegate→Final Answer 链路；无 Key 显式报错。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 预计 |
|---|--------|------|------|
| 0 | 设计文档 49 重写 + README 索引 + implementation_plan §21 + 提交 | 本文件 + 索引 | 0.5d |
| 1 | 核心 agent | `react_schemas.py` / `subagent_registry.py` / `delegate_tool.py` / Lead+子 Agent prompt / `react_loop` plan-first+transcript / `tool_registry` exclude+extra / ReAct-scripted `BenchmarkMockLLM` / conftest fixtures | 1-1.5d |
| 2 | facade 换核 | `react_report.py` assemble / `api.py` 收拢 ReAct + 薄包装 + `_record_memory_success` 单点 / resume 重构 / analyze_pricing 去 SourceSelector / cli/web_app 最小 | 1.5d |
| 3 | 删除 | DELETE 清单（team/ / strategic_loop / gap_executor / tactical_loop / single orchestrator / subagent / parallel_runner / stop_verifier / analyzers / source_selector / conflict / freshness_gate 代码路径）+ config 死字段 + interfaces 精简 | 0.5-1d |
| 4 | 评测 | benchmark 0.7 门禁 / ablation no-tools / behavior_eval make_plan / test_orchestration_eval | 1d |
| 5 | 测试迁移 | 删 ~15 文件 + 改写 ~30 文件，按目录分批跑到绿（最大阶段） | 1.5-2.5d |
| 6 | 文档 | README/CHANGELOG/docs/*.md 无流水线叙事 + 提交 | 0.5d |

每个里程碑独立提交（`feat(agent)` / `refactor(...)` / `test(...)` / `docs(design)`）。

## 7. 风险与缓解

1. **测试迁移规模（最大）**：~958 测试，~30 文件触 API 构造器/team 语义。缓解：conftest 集中 ReAct mock + fake extractor，
   按目录分批（facade→integration→evaluation→e2e）每批跑绿；删被删模块的测试（无保留价值）。
2. **评测门禁**：LLM 主导编排改变 mock 的调用结构。缓解：REPORT_SCHEMA details 命名空间保留 → 抽取不变；mock Lead 脚本化
   （make_plan→delegate→Final Answer）确定性；必要时 HARNESS_VERSION 0.7.0 重定门禁（house 规则，有记录）。
3. **子 Agent 结果质量**：LLM 主导后子 Agent 可能产出弱结果。缓解：子 Agent 受 dimension skill 约束 + `validate_facts`/`detect_conflict`
   收尾复核兜底 + 报告证据 URL 透明（防幻觉透明化，不改"低置信标注"约定）。
4. **记忆写侧**：record_skill/note_pattern 现散在 api 两处（都将删除）。缓解：`analyze()` 末尾单点 `_record_memory_success(report, transcript)`，
   同时补 L4 读侧（45 已完成）。
5. **delegate 后台并发**：线程安全（共享 BudgetController/知识库）。缓解：复用 10 号问题已加锁的 `IterationBudget`/`CompetitorStore` RLock；
   子 Agent 独立 budget 原子扣减。
6. **resume()/checkpoint 语义**：pending 缺口合成 Lead ReAct 任务，合并 checkpoint 已完成维度（保 doc 14 承诺）。
7. **无 LLM 显式失败**：`analyze_react()`（裸文本交互）可保留返回错误串，报告路径抛 `LLMUnavailableError`；CLI 友好报错 + 非零退出。

- 依赖：47/48（单轨 LLM + skill 不变量）、40/41/43（ReAct 统一工具面 + 共享会话上下文 + URL 守卫）、44（链式/真值校验语义）、45（L4 读侧）、26（新鲜度/时间线）。
- 范围外（不修改）：注入防护 / url_guard / 预算 / 取消 / checkpoint / 聚合渲染 / 归档导出的代码兜底；deer-flow 框架本身（仅借鉴委派-回填模型，不引入 LangGraph）。
