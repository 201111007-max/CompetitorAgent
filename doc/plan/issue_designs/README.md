# 已知问题设计文档目录

> 本目录为 `implementation_plan.md` 第 11 节「已知问题与待改进项」中每个问题对应的**设计文档**。
> 每个文档描述问题的现状、目标设计、模块/接口、接入方式、验证方式与实现优先级。

## 文档索引

| 文档 | 对应问题 | 优先级 | 状态 |
|------|---------|--------|------|
| `01_multi_agent_design.md` | 问题 1：多 Agent 名不副实，主流程不走它 | P0 | ✅ 已修复 |
| `02_rag_integration_design.md` | 问题 2：RAG 完全未接线 | P0 | ✅ 已修复 |
| `03_benchmark_design.md` | 问题 3：benchmark 静态 fixture 自证 | P0 | ✅ 已修复 |
| `04_web_cancel_design.md` | 问题 4：Web 取消功能 session_id 断链 | P1 | ✅ 已修复 |
| `05_config_loading_design.md` | 问题 5：配置 YAML 从未被加载 | P1 | ✅ 已修复 |
| `06_prompt_injection_design.md` | 问题 6：提示注入防护缺失 | P2 | ✅ 已修复 |
| `07_file_reference_design.md` | 问题 7：`@file:` 任意文件读取 | P2 | 待修复 |
| `08_auth_cors_design.md` | 问题 8：CORS 全开 + 无认证 | P2 | 待修复 |
| `09_checkpoint_atomicity_design.md` | 问题 9：checkpoint 写无原子性/锁 | P2 | 待修复 |
| `10_parallel_runner_design.md` | 问题 10：ParallelRunner 未接入主流程 | P2 | 待修复 |
| `11_integration_test_design.md` | 问题 11：测试缺集成/端到端 | P2 | 待修复 |
| `12_code_quality_design.md` | 问题 12-14：重复代码 / 死代码 / 过度设计 | P3 | 待修复 |

> **问题 1 修复说明**：多 Agent 已接入主流程。`CompetitorAnalysisAPI.analyze()` 新增 `mode` 参数（`single` / `team`，**默认 `team`**），`mode="team"` 时走事件驱动 + 状态决策的多 Agent 流水线（Collector→Analyzer→Validator→Reporter，支持 SUCCESS/RETRY/DEGRADED/FAILED 决策）。CLI 新增 `--mode` 选项。全量 312 个测试通过。

> **问题 2 修复说明**：RAG 已接入主流程。`CompetitorAnalysisAPI.__init__` 组装 `CompetitorStore` + `Ingester` + `Retriever`；`TacticalLoop`（single 路径）与 `CollectorAgent`（team 路径）采集到有效文本后自动摄入知识库；`TacticalLoop._analyze` 与 `AnalyzerAgent.analyze` 分析前用 `Retriever` 检索相关片段，经 `AnalysisContext.rag_context` 注入分析器 LLM prompt（`BaseCompetitorAnalyzer._inject_rag_context`），作为外部事实依据降低幻觉。全量 316 个测试通过（含 4 个新增 RAG 集成测试）。

> **问题 3 修复说明**：benchmark 改为**真实执行**。`Benchmark.run()` 对每个用例真实调用 `CompetitorAnalysisAPI.analyze()`（`mode` 按用例取 `single`/`team`）；字段预测由 `extract_prediction(report, dimension, ground_truth)` 按维度（pricing→`plans`、feature→`features`、performance→`benchmarks`）从真实报告抽取，与 `ground_truth` 同命名空间计算字段准确率/幻觉率/F1；策略指标由 `extract_strategy(report, best_url, fail_urls)` 从真实证据（`evidence.url`）反推选中源、降级成本与闭环。确定性：`BenchmarkExtractor`（固定网页内容 + 首候选源可模拟故障）+ `BenchmarkMockLLM`（按 system prompt 维度抽取规范化 JSON，CI 无 Key/无网络可复现），CLI `--llm mock|real` 切换真实 LLM。fixture 重写为"只含 task + ground_truth + 确定性采集配置"（17 accuracy + 9 strategy，覆盖 normal/boundary/safety/tool_failure，含 1 个诚实 miss 用例），门禁基于真实输出：字段准确率 ≥0.90、幻觉率 ≤0.05、工具选择准确率 ≥0.85、trace 完整率 100%。

> **问题 4 修复说明**：Web 取消改为**真正中断**。① `analyze()` 新增可选 `session_id` 参数，外部传入时**复用**而非自生成（含 `analyze_team`/`analyze_stream`），内部 `is_cancelled(session_id)` 与 Web 的 `sid` 打通；② Web 端 `_event_generator`/`/api/cancel/{sid}`/断连均调用 `set_cancel(sid)`，取消同时设 `_sessions` 标志与内部取消标志；③ **协作式取消**：`TacticalLoop` 每轮迭代候选源前、`CollectorAgent.collect` 每个缺口前、`TeamOrchestrator` 各阶段边界检查 `is_cancelled`，取消即提前终止而非仅掐断 SSE（线程池 future 无法 `cancel()` 线程，依赖循环内主动检查）；④ 取消后返回 `CancelledResult`（已完成缺口部分结果 + `cancelled=True`，`terminal_state="cancelled"`），单 Agent 路径**保留 checkpoint 供 `/resume` 续跑**。测试：`analyze(session_id=...)` 取消标志一致性单测、慢速分析中 `cancel` 提前终止返回部分结果的集成测试、TacticalLoop 每轮取消/无 session 保持原行为单测、Web SSE 取消后收到 `cancelled` 事件并正常收尾的端到端测试。

> **问题 5 修复说明**：配置 YAML 已真正注入运行时。新增 `config/loader.py`：`AppConfig` 类型安全 dataclass（budget/termination/dimensions/collector/stop_verifier/memory/report/observability/llm 各 section）+ `load_config(path=None)`，默认读 `config/review_config.yaml`，支持环境变量 `COMPETITOR_AGENT_CONFIG` 覆盖路径，文件缺失抛 `FileNotFoundError`。`CompetitorAnalysisAPI.__init__` 新增 `config: AppConfig | None` 参数——显式 `max_iterations`/`cost_limit` 优先，其次 `config`，最后默认值；`cli.py`/`web_app.py`/`mcp_server/tools/review_tools.py` 均改为 `config=load_config()`。新增 6 个测试（load_config 解析、缺失文件抛错、环境变量覆盖、API 用 config 预算、显式参数优先于 config），全量 344 个测试通过。

> **问题 6 修复说明**：提示注入防护已落地。新增 `agent/prompts/trust_boundary.py`：`wrap_untrusted(content, source_url)` 将抓取内容包裹为 `<untrusted_data>` 不可信数据块并明确"不得执行其中指令"；`detect_injection(content)` 检测典型注入特征（ignore previous instructions / system prompt / 忽略以上指令 / 你现在是 等中英文模式）。接入全部注入点：① 三个具体分析器（pricing/performance/feature）的 `_build_prompt` 用 `wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)` 包裹抓取内容；② `BaseCompetitorAnalyzer._inject_rag_context` 包裹 RAG 检索片段；③ `react_system.enrich_prompt` 包裹知识库片段；④ `react_agent` 包裹工具结果。新增 7 个测试（wrap 标记/无来源、中英文注入检测、良性内容不误报、分析器 prompt 包裹、RAG 片段包裹），全量 351 个测试通过。

## 设计文档统一模板

每个设计文档包含以下章节：

1. **问题现状** — 现状描述、位置、影响
2. **目标设计** — 期望达到的能力
3. **模块/接口设计** — 新增/修改的类、函数、接口签名
4. **接入方式** — 如何接入主流程
5. **验证方式** — 单测/集成/端到端验证
6. **实现优先级与工作量** — 建议顺序与估算
