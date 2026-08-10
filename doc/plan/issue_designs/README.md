# 已知问题设计文档目录

> 本目录为 `implementation_plan.md` 第 11 节「已知问题与待改进项」中每个问题对应的**设计文档**。
> 每个文档描述问题的现状、目标设计、模块/接口、接入方式、验证方式与实现优先级。

## 文档索引

| 文档 | 对应问题 | 优先级 | 状态 |
|------|---------|--------|------|
| `01_multi_agent_design.md` | 问题 1：多 Agent 名不副实，主流程不走它 | P0 | ✅ 已修复 |
| `02_rag_integration_design.md` | 问题 2：RAG 完全未接线 | P0 | ✅ 已修复 |
| `03_benchmark_design.md` | 问题 3：benchmark 静态 fixture 自证 | P0 | 待修复 |
| `04_web_cancel_design.md` | 问题 4：Web 取消功能 session_id 断链 | P1 | 待修复 |
| `05_config_loading_design.md` | 问题 5：配置 YAML 从未被加载 | P1 | 待修复 |
| `06_prompt_injection_design.md` | 问题 6：提示注入防护缺失 | P2 | 待修复 |
| `07_file_reference_design.md` | 问题 7：`@file:` 任意文件读取 | P2 | 待修复 |
| `08_auth_cors_design.md` | 问题 8：CORS 全开 + 无认证 | P2 | 待修复 |
| `09_checkpoint_atomicity_design.md` | 问题 9：checkpoint 写无原子性/锁 | P2 | 待修复 |
| `10_parallel_runner_design.md` | 问题 10：ParallelRunner 未接入主流程 | P2 | 待修复 |
| `11_integration_test_design.md` | 问题 11：测试缺集成/端到端 | P2 | 待修复 |
| `12_code_quality_design.md` | 问题 12-14：重复代码 / 死代码 / 过度设计 | P3 | 待修复 |

> **问题 1 修复说明**：多 Agent 已接入主流程。`CompetitorAnalysisAPI.analyze()` 新增 `mode` 参数（`single` / `team`，**默认 `team`**），`mode="team"` 时走事件驱动 + 状态决策的多 Agent 流水线（Collector→Analyzer→Validator→Reporter，支持 SUCCESS/RETRY/DEGRADED/FAILED 决策）。CLI 新增 `--mode` 选项。全量 312 个测试通过。

> **问题 2 修复说明**：RAG 已接入主流程。`CompetitorAnalysisAPI.__init__` 组装 `CompetitorStore` + `Ingester` + `Retriever`；`TacticalLoop`（single 路径）与 `CollectorAgent`（team 路径）采集到有效文本后自动摄入知识库；`TacticalLoop._analyze` 与 `AnalyzerAgent.analyze` 分析前用 `Retriever` 检索相关片段，经 `AnalysisContext.rag_context` 注入分析器 LLM prompt（`BaseCompetitorAnalyzer._inject_rag_context`），作为外部事实依据降低幻觉。全量 316 个测试通过（含 4 个新增 RAG 集成测试）。

## 设计文档统一模板

每个设计文档包含以下章节：

1. **问题现状** — 现状描述、位置、影响
2. **目标设计** — 期望达到的能力
3. **模块/接口设计** — 新增/修改的类、函数、接口签名
4. **接入方式** — 如何接入主流程
5. **验证方式** — 单测/集成/端到端验证
6. **实现优先级与工作量** — 建议顺序与估算
