# Changelog

> 竞品分析 Agent 变更记录。格式：`## [日期] 版本号`，重大变更入 [Unreleased]。

## [Unreleased]

### Added
- 项目骨架与文档：架构设计（doc/）、实现计划（doc/plan/）、接口契约、领域模型、Prompt 规范、数据源目录、配置说明、评测规范、测试策略、使用手册、API 参考、迁移对照表、验收模板、风险登记表。
- M2 记忆系统：`memory/`（json_store / session_archive L1 / persistent_notes L2 / skill_store L3 / evolution_memory L4 / four_layer_memory 组合）。
- M2 知识库 RAG：`knowledge_base/`（competitor_store 词袋检索 / ingester 分块摄入 / retriever 混合检索）。
- M2 记忆接入：`agent/prompts/react_system.py`（enrich_prompt 注入技能/笔记/知识库片段）、`facade/api.py`（注入 memory + 成功后自动沉淀技能/成功率）、`collector/source_selector.py`（成功率驱动源优选）。
- M2 Playwright SPA：`collector/spa_extractor.py`（惰性导入 + 注入钩子）、`tactical_loop.py` extractors 分发注册表。
- M3 多 Agent 协作：`team/`（message_bus / collector_agent / analyzer_agent / validator_agent / reporter_agent / orchestrator）。
- M3 评测体系：`evaluation/`（accuracy_eval / strategy_eval / benchmark）+ `tests/evaluation/fixtures/` 标注用例。
- M3 并行执行：`core/subagent.py` + `core/parallel_runner.py`（ThreadPoolExecutor + 共享预算 + 稳定合并）。
- M7 结构化导出 + 定时调度轮 + 异动告警（设计文档 28）：`core/report_exporter.py`（竞品 JSON schema v1.0.0 / 对比矩阵 JSON）、`facade/api.py`（`run_scheduled` 按 TTL 定时重爬）、`core/alerting.py`（`ConsoleAlertSink` / `FileAlertSink`，时间线 diff → 异动告警）、CLI `schedule` 子命令。
- M8 评测盲区覆盖（设计文档 29）：`evaluation/benchmark.py` `DIMENSION_KINDS` 扩展 ecosystem/sentiment/roadmap 三维度（`extract_prediction` 新分支 `ecosystem_signal` / `sentiment_signal` / `timeline_event`，`BenchmarkMockLLM` 生态/口碑确定性解析），`BenchmarkReport` 新增按维度字段准确率/幻觉率与逐 case 明细，新增 10 条 accuracy（含生态/口碑空数据护栏）+ 2 条 strategy 用例，harness 版本 0.3.0 → 0.4.0。
- M9 消融/对比实验（设计文档 30）：`facade/api.py` `CompetitorAnalysisAPI` 新增 `enable_rag`/`enable_memory` 组件开关（默认开启行为不变，`enable_memory=False` 门控全部记忆副作用、`enable_rag=False` 门控 store/ingester/retriever）；`evaluation/ablation.py` `AblationRunner` 对真实执行用例逐变体跑 5 组对比（full / no-rag / no-memory / no-rag+no-memory / no-llm-rule 纯规则降级），按变体隔离并累积共享记忆与知识库（RAG/记忆差分可测），`render_ablation_table` 对比表（每行标粗最优 + 幻觉率差分门禁）+ `write_ablation_report` 落盘 `reports/ablation/`；CLI `benchmark --ablate`；12 条消融测试（开关门控 / Runner / 渲染 / RAG 差分集成）。
- M10 失败类型统计（设计文档 31）：`evaluation/failure.py` `FailureType` 五类（source_unavailable / hallucination / no_data / parse_failure / budget_exhausted）+ `FailureRecord` + `classify_case`（优先级：幻觉 > 预算 > 源不可用 > 无数据 > 解析错误，全命中返回空，判定口径复用 `accuracy_eval` 归一化）；`evaluation/benchmark.py` `Benchmark.run()` 逐 case 保留真实报告 → `_classify_failures` 聚合（accuracy 未命中 + strategy miss 归类、按 (case_id, type) 去重）→ `BenchmarkReport.failure_stats`/`failure_records`（`to_dict` 同步携带）；`_write_markdown` 增「失败类型分布」表（类型/计数/占比 + 逐 case 样本含证据 URL）、`_write_csv` 增 `failure.{type}`/`failure.total` 行；`build_benchmark_api` 注入每 case 独立空 `TimelineMemory`（时间线隔离加固，防外部共享状态污染首轮无事件边界）；harness 0.4.0 → 0.5.0；`test_failure_stats.py` 19 条（classify 5 类场景 / 聚合去重 / 自定义 fixtures 集成 / 分布表与 CSV 渲染）。
- M11 多 Agent LLM 主导编排（设计文档 49 重写，deer-flow 式）：`agent/react_schemas.py`（PLAN_SCHEMA/REPORT_SCHEMA/SUBAGENT_RESULT_SCHEMA + DIMENSIONS）、`agent/subagent_registry.py`（预注册 6 维度独立 LLM 子 Agent：ReactAgent + 维度 skill + fact_verification/confidence_disclosure + 工具子集，排除 `analyze_competitor` 防递归）、`agent/make_plan.py`/`agent/delegate_tool.py`（Lead 规划工具 + 批量后台并发委派、结果合并回填 Observation）、`agent/review_tools.py`（`select_source`/`validate_facts`/`detect_conflict`/`check_freshness` 复核工具化）、`agent/react_loop.py`（plan-first 强制 + transcript 捕获）、`facade/react_report.py`（REPORT_SCHEMA JSON → 多维度 CompetitorReport，复用 ReportBuilder 渲染/freshness/证据链）；`facade/api.py` `analyze()` 收拢为 Lead ReAct 编排（无代码阶段序列），`analyze_team`/`analyze_stream` 薄包装，`_record_memory_success` 单点记忆写侧，resume 从 checkpoint 合成 ReAct 任务续跑；`BenchmarkMockLLM` 改 ReAct-scripted 编排（make_plan → delegate → 子 Agent 确定性抽取 → REPORT_SCHEMA），HARNESS_VERSION 0.6 → 0.7.0 重定门禁；消融 `no-llm-rule` 变体改 `no-tools`；定价消费侧（markdown_renderer/report_exporter/timeline/archive）统一走 `profile_from_details`（doc-49 `details["plans"]` 命名空间）；全量 730 passed / 6 skipped。

### Removed
- M11 删除规则管线与固定流水线（设计文档 49 重写）：`team/`（TeamOrchestrator/MessageBus/Collector/Analyzer/Validator/Reporter/Reviewer）、`analyzers/`（base + 5 子类 + fallback + registry）、`core/strategic_loop.py`/`gap_executor.py`/`tactical_loop.py`/`orchestrator.py`/`subagent.py`/`parallel_runner.py`/`stop_verifier.py`、`collector/source_selector.py`/`spa_extractor.py`/`providers/`、`interfaces/planner.py`/`verifier.py`/`analyzer.py`/`collector.py` 及全部规则兜底（`_parse_task_rule`/`_rule_extract`/`candidates()`）；config 死字段（StopVerifier/Termination/default_budget/analysis_order）。无 LLM 显式抛 `LLMUnavailableError`，无静默规则降级。
