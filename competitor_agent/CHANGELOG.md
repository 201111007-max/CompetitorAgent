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

### Fixed
- （暂无）

### Changed
- （暂无）
