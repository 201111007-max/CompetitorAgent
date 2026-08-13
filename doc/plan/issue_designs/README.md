# 已知问题设计文档目录

> 本目录为 `implementation_plan.md` 第 11 节「已知问题与待改进项」以及第 13-15 节 P0 待办中每项对应的**设计文档**。
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
| `07_file_reference_design.md` | 问题 7：`@file:` 任意文件读取 | P2 | ✅ 已修复 |
| `08_auth_cors_design.md` | 问题 8：CORS 全开 + 无认证 | P2 | ✅ 已修复 |
| `09_checkpoint_atomicity_design.md` | 问题 9：checkpoint 写无原子性/锁 | P2 | ✅ 已修复 |
| `10_parallel_runner_design.md` | 问题 10：ParallelRunner 未接入主流程 | P2 | ✅ 已修复 |
| `11_integration_test_design.md` | 问题 11：测试缺集成/端到端 | P2 | ✅ 已修复 |
| `12_code_quality_design.md` | 问题 12-14：重复代码 / 死代码 / 过度设计 | P3 | ✅ 已修复 |
| `13_test_isolation_design.md` | 问题 15：单测隔离缺陷，CLI handler 硬编码真实 LLM | P0 | ✅ 已修复 |
| `14_resume_semantics_design.md` | 问题 16：`resume()` 不续跑，只回读快照即删 | P0 | ✅ 已修复 |
| `15_stream_config_design.md` | 问题 17：`analyze_stream` 静默丢弃 config | P1 | ✅ 已修复 |
| `16_history_interface_design.md` | 问题 18：`get_history` 直捅 `_memory._sessions`，raw 结构不一致 | P1 | ✅ 已修复 |
| `17_observability_design.md` | 问题 19：可观测性配置（tracing/metrics/langfuse）无实现 | P1 | ✅ 已修复 |
| `18_dual_pipeline_design.md` | 问题 20：single/team 两套平行流水线语义分裂 | P2 | ✅ 已修复 |
| `19_engineering_hygiene_design.md` | 问题 21-23：requires-python 声明不一致 / 锁表泄漏 / coverage 无门槛 | P3 | ✅ 已修复 |
| `20_multi_competitor_discovery_design.md` | §13：自主发现竞品 + 多竞品并排对比 | P0 | ✅ 已修复 |
| `21_log_observability_design.md` | §14：日志完善功能（可观测性补齐） | P0 | ✅ 已修复 |
| `22_web_report_display_design.md` | §15：Web 端显示 / 导出报告 | P0 | ✅ 已修复 |
| `23_multi_source_routing_design.md` | §12.1 #1：数据源只认官网（SourceSelector 多源路由） | P0 | ✅ 已实现 |
| `24_ecosystem_sentiment_analyzers_design.md` | §12.1 #2：ecosystem / sentiment 无专属分析器 | P0 | ✅ 已实现 |
| `25_direct_benchmark_sources_design.md` | §12.2 #4：性能数字靠 LLM 读网页（直连榜单） | P1 | ✅ 已实现 |
| `26_freshness_timeline_design.md` | §12.2 #5 + §12.3 #7：无新鲜度/时间线（定时重爬） | P1 | ✅ 已实现 |
| `27_pricing_modeling_design.md` | §12.3 #6：定价分层/用量建模弱 | P2 | ⏳ 待办 |
| `28_structured_export_design.md` | §12.3 #8：输出仅 Markdown（结构化导出+定时+告警） | P2 | ⏳ 待办 |
| `29_evaluation_coverage_design.md` | §12.3 #9：评测盲区（生态/口碑/时间线覆盖） | P2 | ⏳ 待办 |
| `30_ablation_comparison_design.md` | §12.3 #10：无对比/消融实验（有无 RAG/rerank/memory） | P2 | ⏳ 待办 |
| `31_failure_stats_design.md` | §12.3 #11：无失败类型统计（五类分类+聚合分布） | P2 | ⏳ 待办 |

> **问题 1 修复说明**：多 Agent 已接入主流程。`CompetitorAnalysisAPI.analyze()` 新增 `mode` 参数（`single` / `team`，**默认 `team`**），`mode="team"` 时走事件驱动 + 状态决策的多 Agent 流水线（Collector→Analyzer→Validator→Reporter，支持 SUCCESS/RETRY/DEGRADED/FAILED 决策）。CLI 新增 `--mode` 选项。全量 312 个测试通过。

> **问题 2 修复说明**：RAG 已接入主流程。`CompetitorAnalysisAPI.__init__` 组装 `CompetitorStore` + `Ingester` + `Retriever`；`TacticalLoop`（single 路径）与 `CollectorAgent`（team 路径）采集到有效文本后自动摄入知识库；`TacticalLoop._analyze` 与 `AnalyzerAgent.analyze` 分析前用 `Retriever` 检索相关片段，经 `AnalysisContext.rag_context` 注入分析器 LLM prompt（`BaseCompetitorAnalyzer._inject_rag_context`），作为外部事实依据降低幻觉。全量 316 个测试通过（含 4 个新增 RAG 集成测试）。

> **问题 3 修复说明**：benchmark 改为**真实执行**。`Benchmark.run()` 对每个用例真实调用 `CompetitorAnalysisAPI.analyze()`（`mode` 按用例取 `single`/`team`）；字段预测由 `extract_prediction(report, dimension, ground_truth)` 按维度（pricing→`plans`、feature→`features`、performance→`benchmarks`）从真实报告抽取，与 `ground_truth` 同命名空间计算字段准确率/幻觉率/F1；策略指标由 `extract_strategy(report, best_url, fail_urls)` 从真实证据（`evidence.url`）反推选中源、降级成本与闭环。确定性：`BenchmarkExtractor`（固定网页内容 + 首候选源可模拟故障）+ `BenchmarkMockLLM`（按 system prompt 维度抽取规范化 JSON，CI 无 Key/无网络可复现），CLI `--llm mock|real` 切换真实 LLM。fixture 重写为"只含 task + ground_truth + 确定性采集配置"（17 accuracy + 9 strategy，覆盖 normal/boundary/safety/tool_failure，含 1 个诚实 miss 用例），门禁基于真实输出：字段准确率 ≥0.90、幻觉率 ≤0.05、工具选择准确率 ≥0.85、trace 完整率 100%。

> **问题 4 修复说明**：Web 取消改为**真正中断**。① `analyze()` 新增可选 `session_id` 参数，外部传入时**复用**而非自生成（含 `analyze_team`/`analyze_stream`），内部 `is_cancelled(session_id)` 与 Web 的 `sid` 打通；② Web 端 `_event_generator`/`/api/cancel/{sid}`/断连均调用 `set_cancel(sid)`，取消同时设 `_sessions` 标志与内部取消标志；③ **协作式取消**：`TacticalLoop` 每轮迭代候选源前、`CollectorAgent.collect` 每个缺口前、`TeamOrchestrator` 各阶段边界检查 `is_cancelled`，取消即提前终止而非仅掐断 SSE（线程池 future 无法 `cancel()` 线程，依赖循环内主动检查）；④ 取消后返回 `CancelledResult`（已完成缺口部分结果 + `cancelled=True`，`terminal_state="cancelled"`），单 Agent 路径**保留 checkpoint 供 `/resume` 续跑**。测试：`analyze(session_id=...)` 取消标志一致性单测、慢速分析中 `cancel` 提前终止返回部分结果的集成测试、TacticalLoop 每轮取消/无 session 保持原行为单测、Web SSE 取消后收到 `cancelled` 事件并正常收尾的端到端测试。

> **问题 5 修复说明**：配置 YAML 已真正注入运行时。新增 `config/loader.py`：`AppConfig` 类型安全 dataclass（budget/termination/dimensions/collector/stop_verifier/memory/report/observability/llm 各 section）+ `load_config(path=None)`，默认读 `config/review_config.yaml`，支持环境变量 `COMPETITOR_AGENT_CONFIG` 覆盖路径，文件缺失抛 `FileNotFoundError`。`CompetitorAnalysisAPI.__init__` 新增 `config: AppConfig | None` 参数——显式 `max_iterations`/`cost_limit` 优先，其次 `config`，最后默认值；`cli.py`/`web_app.py`/`mcp_server/tools/review_tools.py` 均改为 `config=load_config()`。新增 6 个测试（load_config 解析、缺失文件抛错、环境变量覆盖、API 用 config 预算、显式参数优先于 config），全量 344 个测试通过。

> **问题 6 修复说明**：提示注入防护已落地。新增 `agent/prompts/trust_boundary.py`：`wrap_untrusted(content, source_url)` 将抓取内容包裹为 `<untrusted_data>` 不可信数据块并明确"不得执行其中指令"；`detect_injection(content)` 检测典型注入特征（ignore previous instructions / system prompt / 忽略以上指令 / 你现在是 等中英文模式）。接入全部注入点：① 三个具体分析器（pricing/performance/feature）的 `_build_prompt` 用 `wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)` 包裹抓取内容；② `BaseCompetitorAnalyzer._inject_rag_context` 包裹 RAG 检索片段；③ `react_system.enrich_prompt` 包裹知识库片段；④ `react_agent` 包裹工具结果；⑤ **主动检测接入运行时**：`BaseCompetitorAnalyzer._analyze_with_llm` 在调用 LLM 前对 `observation.raw_text` 执行 `detect_injection`，命中即跳过 LLM、降级规则提取（不把疑似注入内容送入 LLM）。新增 8 个测试（wrap 标记/无来源、中英文注入检测、良性内容不误报、分析器 prompt 包裹、RAG 片段包裹、注入命中跳过 LLM 降级规则），全量 408 个测试通过。

> **问题 7 修复说明**：`@file:` 引用已收紧为**仅允许数据文件**。`core/input_sanitizer.py` 白名单从"目录"细化为"数据目录 + 扩展名 + 大小"三重校验：`_ALLOWED_REF_DIRS = ("evaluation/cases", "reports/templates")`（仅数据目录，移除 `competitor_agent`/`docs`/`tests` 等可读源码的根）、`_ALLOWED_REF_EXTENSIONS = {.md, .txt, .json, .yaml}`（禁止 `.py`/`.toml`/`.env` 等源码/配置/凭据）、`_MAX_REFERENCE_BYTES = 64KB`。读取内容改用 `wrap_untrusted(content, source_url)` 包裹为不可信数据块（承接问题 6 防护）。不合规/过大/不存在引用**静默跳过**（不读取、不报错，避免信息泄露）。新增 3 个测试（内容包裹为不可信块、源码/凭据文件被拒、超大文件被拒），全量 354 个测试通过。

> **问题 8 修复说明**：CORS 已收紧 + Web 端点已加 API Token 认证。① `config/loader.py` 新增 `SecurityConfig`（`cors_origins` 默认 `["http://localhost:8000"]`、`auth_token` 默认空），`auth_token` 优先从环境变量 `COMPETITOR_AUTH_TOKEN` 读取（不明文落码），`review_config.yaml` 新增 `security` section；② `web_app.py` CORS 中间件 `allow_origins` 由 `["*"]` 改为 `cfg.security.cors_origins`；③ 新增 `require_auth` 依赖，`/api/*` 全部端点（analyze/cancel/history/status）接入——未配置 token 时放行（本地开发），配置后校验 `Authorization: Bearer <token>` 或 `?token=`（EventSource 无法设 Header，故支持 query 参数），错误/缺失返回 401。新增 8 个测试（无 token 放行、缺失/错误 Bearer 401、正确 Bearer/query 通过、CORS 收紧非 `*`、env token 读取、默认值），全量 362 个测试通过。

> **问题 9 修复说明**：checkpoint 写改为**原子写入 + 并发安全**。① `checkpoint.py` 新增 `_atomic_write`：唯一命名临时文件（`.{stem}.{pid}.{hex}.tmp`）→ 落盘（`flush`+`os.fsync`）→ `os.replace` 原子替换，进程崩溃不损坏主文件，陈旧的 `.tmp` 写入后自动清理；② **进程内锁**：按 session 的 `threading.Lock` 串行化同进程并发写；③ **跨进程文件锁** `CheckpointLock`：Unix `fcntl.flock` / Windows `msvcrt.locking` 对 `.lock` 文件阻塞式加锁；④ **备份回退**：写入前将旧版本原子备份为 `.bak`，`load_checkpoint`/`list_checkpoints` 主文件损坏或缺失时自动回退 `.bak`；⑤ `delete_checkpoint` 同时清理主文件/`.bak`/`.lock`/临时文件并释放进程内锁。新增 11 个测试（原子写往返/无陈旧 tmp、模拟中断不损坏原文件、更新生成 `.bak`、save/load 往返、主文件损坏回退 `.bak`、主文件缺失回退、删除清理全部产物、8 线程并发写最终文件完整且可解析、跨进程锁抢占阻塞串行、顺序加解锁无死锁），全量 373 个测试通过。

> **问题 10 修复说明**：并行缺口执行已接入主流程。① `config/loader.py` 新增 `ExecutionConfig`（`execution.mode`: `single` 默认兼容 / `parallel`；`execution.max_parallel_subagents`: 默认 4），`review_config.yaml` 新增 `execution` section。② `analyze()`（单 Agent 路径）抽出 `_run_gap`（预算/取消检查→TacticalLoop→记忆沉淀→`record_iteration`→checkpoint），`execution.mode == parallel` 时用 `ThreadPoolExecutor`（`max_workers = min(max_parallel_subagents, gaps)`）并行执行独立缺口，结果按缺口原始顺序稳定合并（与串行路径一致），单缺口异常不影响整体。③ 预算并行安全：`IterationBudget` 的 `used_iterations`/`used_cost`/`remaining_iterations` 读写加锁；`BudgetController.record_iteration`/`should_stop` 计数组件加锁并快照读取，并行共享预算原子扣减、不超发。④ 取消贯通：并行任务每轮仍执行 `is_cancelled(session_id)` 协作式检查，取消即返 `CancelledResult`。⑤ `CompetitorStore` 加 `RLock`，并行缺口并发摄入/检索知识库安全。新增 7 个测试（execution section 解析、`IterationBudget` 并行不超发、`BudgetController` 并发计数不丢失、并行结果按缺口顺序合并、并行共享预算不超缺口总数、parallel 与 single 输出一致、并行中途取消返部分结果），全量 380 个测试通过。

> **问题 11 修复说明**：补齐集成/端到端测试层。① **共享测试基础设施**：`tests/conftest.py` 提供 `FakeExtractor`（固定网页内容，无网络可复现）、`mock_llm`（复用 benchmark 的 `BenchmarkMockLLM`，无 Key 可复现）与 `memory`（tmp_path 隔离的四层记忆）fixture；`pyproject.toml` 注册 `integration`/`e2e` marker（`--strict-markers` 强制）。② **集成层 `tests/integration/`（17 个）**：`test_analyze_flow`（single/team 完整链路产出报告、证据带 source_url、事件阶段贯通、真实报告可被 `extract_prediction` 评测——复用设计文档 03）、`test_memory_loop`（分析后沉淀技能+L4 成功率、落盘重载、二次规划置信度 +0.2 命中）、`test_budget_termination`（迭代耗尽→partial、成本 0.01 触顶即停、mock LLM 核心缺口关闭后提前 success 终止=满足度终止）、`test_checkpoint_resume`（慢速分析中取消→`CancelledResult`，其 `resume(sid)` 恢复部分结果，checkpoint 消费后二次 resume 抛 `ValueError`）、`test_team_flow`（`analyze_team()` 事件驱动流水线报告完整、证据 https、记忆沉淀）。③ **端到端层 `tests/e2e/`（4 个）**：mock LLM + 固定页面真实跑 `analyze("Cursor")`，断言 Markdown 含 `### [OK] pricing/feature` 与 `证据:`；报告可评测；team 全链路；real LLM smoke 有 Key（`OPENAI_API_KEY`/`DEEPSEEK_API_KEY`/`LLM_API_KEY`）时真实调用、无 Key 自动跳过（`skipif`），CI 不卡网络。全量 401 个测试通过（+21：17 集成 + 4 端到端）。

> **问题 12 修复说明**：按设计文档 12 完成代码质量整改。① **消除重复（12.1）**：新增 `core/gap_executor.py`——`GapExecutor` 收敛"计划/取消检查→选源→采集（按 source_name 分发、失败降级记录 sources_tried）→RAG 摄入/检索注入→分析→缺口置信度与状态更新"的完整单缺口闭环；`TacticalLoop.execute` 与 `SubAgent.run` 均改为委托 `GapExecutor`（并行子代理与单 Agent 主路径闭环行为完全一致，并行预算共享语义不变）；采集环节另抽出 `fetch_candidate` 共享助手，`CollectorAgent.collect` 复用（多 Agent 采集 Agent 只采集不分析，故合理复用选源-采集段而非整环）。② **清理死代码（12.2）**：删除 `web_app.py` 中创建后立即丢弃的 `CompetitorAnalysisAPI` 实例；`analyze_react` 的 `web_extract` 工具由硬编码占位改为**接入真实采集链路**（`self._extractor.fetch`，失败返回可读信息而非抛异常）。③ **简化过度设计（12.3）**：`team/message_bus.py` 删除无任何调用方的 `subscribe_and_forward` 与未用的 `T_STRATEGY` topic，保留最小 pub/sub + 顺序审计（`history`/`Envelope`，多 Agent 流水线各阶段发布 artifact 供回溯）。④ 新增 `tests/unit/core/test_gap_executor.py`（6 个：成功闭环、跨源降级、预算耗尽 BLOCKED、会话取消不抓取即 BLOCKED、RAG 上下文注入 + 观察摄入、`fetch_candidate` 按源分发与默认回退）。全量 **407 个测试通过**（401 + 6），`GapExecutor`/`fetch_candidate` 从 `core` 包导出。

> **问题 15 修复说明**：CLI handler 不再硬编码 `LLMClient()`。`_run_analyze` 新增 `llm` / `use_llm` 参数，由 `main` 统一构造并传递；默认 `use_llm=False`（无 key 不联网）。`tests/conftest.py` 新增 `autouse` fixture 清除 API Key 环境变量，确保单测进程内零真实网络。`TestMain._patch_api` 同时 monkeypatch `LLMClient`。全量 407 个测试通过。

> **问题 16 修复说明**：`resume()` 从"读快照即删"改为真正**断点续跑**。新增 `_reconstruct_gaps_from_checkpoint` 从 checkpoint 重建 `InfoGap` 对象（保留 status/confidence/evidence），重建剩余预算（`_used_iterations` / `_used_cost` 预置已消耗部分），仅重跑 `not g.is_closed` 的缺口（复用 `_run_gaps` / `_run_gap`），合并已关闭维度 + 新完成维度，一次性消费 checkpoint。续跑中再次取消返回 `CancelledResult`。全量 407 个测试通过。

> **问题 17 修复说明**：`analyze_stream` 不再内部 new `CompetitorAnalysisAPI` 子实例。改为直接复用 `self`（`self.analyze`），配置与组件完全透传，流式路径与直调路径行为一致。归档 `raw` schema 统一（含 `markdown_report`）。全量 407 个测试通过。

> **问题 18 修复说明**：`get_history` 不再直捅 `self._memory._sessions` 私有字段。新增 `IFourLayerMemory.list_sessions(competitor)` 协议方法，`FourLayerMemory` 实现按竞品过滤 / 最近全部查询；`get_history` / `web_app.py` 均改为调用协议方法。归档 `raw` schema 统一为含 `markdown_report` + `terminal_state` + `dimension_count` + `competitor_name` + `created_at`。全量 407 个测试通过。

> **问题 19 修复说明**：从 `ObservabilityConfig` 与 `review_config.yaml` 中移除无任何消费方的 `tracing` / `metrics` / `langfuse_*` 字段，仅保留 `log_level`。消除"假亮点"配置。全量 407 个测试通过。

> **问题 20 修复说明**：single/team 两套流水线语义已收敛统一。① **统一入口**：`analyze()` 默认 `mode="team"`，`mode="team"` 直接委托 `analyze_team`（`facade/api.py:147-149`），`mode="single"` 委托 `SingleOrchestrator`（`core/orchestrator.py`，新增 `AnalysisOrchestrator` 协议，缺口级闭环复用 `GapExecutor`，`execution.mode=parallel` 时 ThreadPoolExecutor 并行缺口）。② **统一规划语义**：`analyze_team` 与 single 用同一 `StrategicPlanner.plan`、同一 `competitor.resolved`/`gaps.planned` 埋点。③ **统一预算约束**：`analyze_team` 复用同一 `BudgetController`，规划后先 `should_stop` 预检（耗尽即提前终止返回 0 维度报告），成功后 `record_iteration(cost=0.01)`，与 single 路径预算语义一致。④ **统一 checkpoint 语义**：`analyze_team` 成功/取消均 `save_checkpoint`（含 competitor_name/gaps/迭代/成本/sources_tried），取消返回 `CancelledResult` 且保留 checkpoint 供 `/resume` 续跑，成功 `delete_checkpoint`——与 single 完全对齐；`resume()` 用 `resolve_competitor(cp.competitor_name)` 重建竞品（带 official_links），修复"续跑 0 候选"隐性 bug。⑤ **统一记忆沉淀**：`_record_team_memory_success` 按报告维度结果记录技能 + 数据源成功率，与 single 路径对齐。新增 `tests/integration/test_dual_pipeline_consistency.py` 等验证两路径对取消/记忆/checkpoint 行为一致。全量 471 个测试通过。

> **问题 21-23 修复说明**：① `pyproject.toml` `requires-python` / poetry.python / ruff / mypy / black 统一对齐到 `>=3.10`；② `checkpoint.py` `_session_locks` 由 `dict` 改为 `weakref.WeakValueDictionary`，会话结束后锁条目自动回收，防内存泄漏；③ `pyproject.toml` 新增 `[tool.coverage.report] fail_under = 80` + `addopts` 含 `--cov-report=xml --cov-report=html`，覆盖率下降有门禁。全量 407 个测试通过。

> **§13 修复说明**：多竞品发现与对比已落地。① **LLM 决策**：`parse_task` 输出 `resolution`（`REGISTRY` / `DISCOVERY` / `COMPARE`），`TaskParseResult.is_discovery` 派生；畸形/缺失回退规则弱推断（无 Key 降级，`_DISCOVERY_MARKERS` 识别"所有/有哪些/市场"等）；② **发现器** `core/competitor_discoverer.py`：`CompetitorDiscoverer.discover(task)` 注册表命中优先 → 注入 `web_tool` 联网枚举 → 无候选走内置兜底清单（8 个常见 AI coding agent，均带 official_links），`use_llm=True` 时 LLM 归纳去重补全链接；③ **N 向对比**：`api.compare(*competitors)` 支持 ≥2（旧 `compare(a, b=None)` 签名兼容），逐个 `analyze` 后聚合；④ **品类格局矩阵**：`report_builder.build_comparison` + `markdown_renderer.render_comparison` 产出"维度 × 竞品"矩阵 + 每维度最佳（状态 [OK]>[PARTIAL]>[N/A] + 置信度）+ 汇总排名/覆盖缺口；⑤ **任务带源注入** `_task_with_sources`：把发现竞品的 official_links 转成 custom_sources，根治"未知竞品 0 候选 → 0 维度"；⑥ CLI/Web 路由：普查任务走 `discover()` 而非把整句拼成假竞品。注册表新增 windsurf/aider/gemini-cli/opencode。新增 4+8+5+5 共 22 个测试（LLM 决策 schema 鲁棒性、发现器去重/兜底、N 向对比、矩阵渲染、发现集成 e2e）。全量 441 个测试通过。**增强已落地（本轮）**：① `api.compare` 聚合支持按 `execution.mode=parallel` 并行分析多个竞品——`_compare_parallel` 用 `ThreadPoolExecutor`（`max_workers = min(max_parallel_subagents, 竞品数)`），按输入顺序经 `by_name` 稳定返回，语义与串行一致（矩阵/竞品顺序相同，`test_compare_parallel.py` 用剥离生成时间的 markdown 断言并行==串行）；② **Web 矩阵可视化**：`renderMatrix()` 把报告「品类格局矩阵」Markdown 表格渲染为 HTML（`textContent` 防 XSS），`clearReport()` 同步清空矩阵；③ **discovery SSE 候选实时推送**：`CompetitorDiscoverer.discover` 新增 `on_candidate` 回调，`api.discover` 逐候选发 `discovery.candidate` 事件（先于聚合的 `discovery`），Web SSE 前端 `addCandidate()` 实时展示候选清单。全量 **471 个测试通过**（含 `test_compare_parallel.py` 3 个 + `test_discovery.py`/`test_competitor_discoverer.py` 新增回调测试）。

> **§14 修复说明**：日志完善已落地。① **结构化 JSON 日志**：`observability/logger.py` 新增 `SessionRouterHandler`——`session_id` 记录路由到 `logs/<sid>.log`（`set_current_session` 线程本地注入，`_emit_with_extra` 手动合并 extra 规避 LoggerAdapter.process 覆盖 caller 的问题），控制台 + 文件双出口 + 强制 flush（detached 不再丢日志）。② **会话级落盘**：`cli.py::main` 调 `setup_logging(level, log_dir)`，每次分析建独立 `<sid>.log`。③ **关键路径埋点**：`gap_executor.py` 埋 `source.selected` / `collect.fail` / `collect.done` / `analyze.done`（含 elapsed_ms/bytes/confidence），覆盖"竞品识别 / 选源 / 采集状态 / 分析置信度 / 终止原因"全链路；`facade/api.py` 埋 `session_started` / `competitor.resolved` / `gaps.planned` / `analysis.terminated` / `report.built`。④ **LLM 调用日志（脱敏）**：`llm/client.py` 新增 `_log_call`——记录 model/base_url/input/output token/elapsed_ms/cost_usd，**不落 prompt 全文、不落 api_key**。⑤ **Web 端点**：`/api/logs/{session_id}`（查看）+ `/api/logs/stream/{sid}`（实时流）。新增 `tests/unit/observability/test_logger.py`、`tests/unit/web/test_web_logs.py`、`tests/integration/test_observability.py`。详见 `21_log_observability_design.md`。

> **§15 修复说明**：Web 显示/导出已落地。① **SSE 携带报告正文**：`report` 事件 payload 增加 `markdown_report` + `session_id`，前端收到后渲染为可读报告（不再仅状态行）。② **自动落盘**：新增 `core/report_archiver.py`——`save_report_markdown()` 原子写 `reports/competitor/<竞品>.md`（复用 `config.report.output_dir`，`_safe_filename` 清洗文件名，`resolve_output_dir` 对齐命名）。③ **Web 导出端点**：`/api/reports/{competitor}`（查看）+ `/download`（`Content-Disposition: attachment` 下载）。④ **前端导出入口**：报告区「复制 Markdown」（`navigator.clipboard`，失败降级）+「下载 .md」按钮；`clearReport()` 清空报告区。新增 `tests/unit/core/test_report_archiver.py`、`tests/integration/test_report_export.py`。详见 `22_web_report_display_design.md`。

> **设计文档 23 修复说明**：多源路由已落地。`ExternalSourceProvider` 协议（kind/supports/candidates/fetch）+ `Competitor.external_refs`（github_repo/marketplace 等）；`SourceSelector` 按缺口路由到外部源（ecosystem→github+marketplace、sentiment→social、performance→benchmark、roadmap→github），trust 排序 + L4 成功率提升 + 剔除已尝试源 + SPA 兜底；`GithubSourceProvider`/`MarketplaceSourceProvider`/`CommunitySourceProvider` + `build_providers` 按配置构造；`fetch_candidate` 按 kind 分发到 provider，`GapExecutor`/`TacticalLoop`/`CollectorAgent` 统一复用。外部源主开关 `enable_external_sources` 默认关，保证 CI/benchmark 零真实网络。新增 17 个路由/Provider 单测，全量 **487 个测试通过**。

> **设计文档 24 修复说明**：ecosystem/sentiment 专属分析器已落地。`EcosystemAnalyzer`（MCP server/插件/IDE/集成/仓库活跃度结构化盘点）+ `SentimentAnalyzer`（正负信号 + polarity_ratio + 信号不足 → `[PARTIAL]` 低置信不编造）注册进 `AnalyzerRegistry`（roadmap 保留 Fallback）；`base._analyze_with_rules` 支持显式 confidence → 低置信自动 PARTIAL。新增 14 个分析器/注册/注入防护/多源集成单测，全量 **501 个测试通过**。

> **设计文档 25 修复说明**：性能榜单直连已落地。`BenchmarkScore`（board/score/unit/retrieved_at/source_url）+ `BenchmarkSourceProvider`（SWE-bench/Aider/Terminal-Bench/LMArena 按竞品名匹配，TTL 缓存）；`PerformanceAnalyzer` 榜单优先合并（同指标以榜单为准、仅页面降档、均无 `[PARTIAL]` 不编造；无榜单时完全保留原页面/LLM 结果，不破坏评测抽取契约）；`GapExecutor` 对 performance 缺口注入 `context.benchmark_scores`。新增 10 个 Provider/合并/注入闭环单测 + 2 个路由单测，全量 **514 个测试通过**。

> **设计文档 26 修复说明**：数据新鲜度 + 竞品时间线已落地。① **新鲜度元数据**：`domain_types/freshness.py` 新增 `ReportFreshness`（`dimension_ages` / `source_retrieved_at` / `stale_dimensions`，仅按证据 `access_time` 算龄，无证据不给维度）+ `stale_under_ttl`；`config/loader.py` 新增 `FreshnessConfig`（`dimension_ttl_days` 默认值 YAML 叠加覆盖），`review_config.yaml` 新增 `freshness` section。② **报告注记**：`ReportBuilder` 计算并注入 `report.freshness`，`MarkdownRenderer` 渲染 `> 数据新鲜度: 分析于 …` + 过期维度 `⚠️ **数据可能过期**` 与 `re-analyze` 提示。③ **时间线记忆**：`memory/timeline_memory.py` 新增 `TimelineMemory`——`update(report)` 对比上次快照 `_diff_snapshots` 产出 `TimelineEvent`（`price_change`/`feature_added`/`score_change`/`version_release`，带 `occurred_at` + `evidence_urls` + `diff_from` 基线），首轮无基线不产生事件防噪声；`api.analyze`/`analyze_team`/`resume` 均 `_record_timeline` 并把 `## 竞品时间线` 段落追加进 Markdown。④ **过期重爬**：`api.refresh_stale(ttl_override=…, recompute_all=…)` 按归档 freshness（含在 `_archive_report` 的 raw schema）判定过期维度并逐竞品重爬；CLI 新增 `refresh`（`--stale`/`--all`）与 `timeline <competitor>` 子命令，Web 新增 `/api/timeline/{competitor}`。新增 14（freshness）+10（timeline）+7（refresh_stale）单测与 3 个集成测试，全量 **561 个测试通过**（含 1 个环境性失败：本机已装 playwright 使 `is_available` 为真）。

## 设计文档统一模板

每个设计文档包含以下章节：

1. **问题现状** — 现状描述、位置、影响
2. **目标设计** — 期望达到的能力
3. **模块/接口设计** — 新增/修改的类、函数、接口签名
4. **接入方式** — 如何接入主流程
5. **验证方式** — 单测/集成/端到端验证
6. **实现优先级与工作量** — 建议顺序与估算

> 待办项（§13-15）对应文档沿用同一模板；实现完成后在表中将状态更新为 ✅ 并追加"修复说明"。

---

## 当前进展与下一步计划（2026-08-13）

### 已完成
- 问题 1-23 全部按设计文档修复并通过全量测试。
- **§13 多竞品发现与对比（P0）**：已实现（见上方 §13 修复说明）——`resolution` LLM 决策 + 规则降级、`CompetitorDiscoverer`（web_tool 注入 + 内置兜底清单）、`compare(*competitors)` N 向对比、品类格局矩阵渲染、CLI/Web 路由。
- **§13 增强（本轮）**：`compare` 按 `execution.mode=parallel` 并行分析多竞品（顺序稳定）、Web 品类矩阵可视化（XSS 安全）、`discovery.candidate` SSE 候选实时推送。
- **§14 日志完善（P0）**：已实现（见上方 §14 修复说明）——结构化 JSON 日志 + `SessionRouterHandler` 会话级落盘 `logs/<sid>.log` + 关键路径埋点 + LLM 脱敏调用日志 + Web `/api/logs/{sid}` 与 `/api/logs/stream/{sid}`。
- **§15 Web 报告显示/导出（P0）**：已实现（见上方 §15 修复说明）——`report` 事件 payload 携带 `markdown_report` + `save_report_markdown` 原子落盘 + `/api/reports/{competitor}` 与 `/download` 端点 + 前端渲染面板/复制/下载。
- **问题 20 双流水线语义分裂（P2）**：已修复（见上方问题 20 修复说明）——统一入口（`analyze` 默认 team）/统一规划/统一预算/统一 checkpoint/统一记忆沉淀；新增 `core/orchestrator.py` 收敛缺口执行闭环。
- **设计文档 23 §12.1 #1 SourceSelector 多源路由**：已实现（见上方修复说明）——`ExternalSourceProvider` 协议 + `Competitor.external_refs` + 缺口→github/marketplace/benchmark/social 路由 + `GapExecutor.fetch_candidate` 按 kind 分发 + `build_providers` 配置开关。
- **设计文档 24 §12.1 #2 Ecosystem/Sentiment 分析器**：已实现（见上方修复说明）——`EcosystemAnalyzer`（MCP server/插件/IDE/tool-use/仓库活跃度）+ `SentimentAnalyzer`（社区正负信号，低置信护栏不编造）注册进 `AnalyzerRegistry`。
- **设计文档 25 §12.2 #4 直连榜单源**：已实现（见上方修复说明）——`BenchmarkSourceProvider` 直连 SWE-bench/Aider/Terminal-Bench/LM Arena（TTL 缓存 + 失败降级），`PerformanceAnalyzer` 榜单优先合并 + 页面兜底。
- **设计文档 26 §12.2 #5 + §12.3 #7 新鲜度/时间线**：已实现（见上方修复说明）——`ReportFreshness` 陈旧度标注 + `refresh_stale` 过期重爬 + `TimelineMemory` 跨分析 diff 事件 + CLI `refresh`/`timeline` 与 Web `/api/timeline/{competitor}`，报告含新鲜度注记与「竞品时间线」段落。
- 全量 **561 个测试通过**（1 个环境性失败：本机已装 playwright，`test_unavailable_without_playwright_and_hook` 假设未安装）。

### 待办（下一步按序实施，均已有设计文档）
1. **§12.3 #6 定价分层/用量建模**（`27_pricing_modeling_design.md`，P2，约 1.5 天）——`PricingProfile`（plans/usage/cost_scenarios）+ 询价标注。
2. **§12.3 #8 结构化导出 + 定时 + 告警**（`28_structured_export_design.md`，P2，约 2-3 天）——`report_exporter` JSON/矩阵导出 + `run_scheduled` + `AlertSink` 异动告警。
3. **§12.3 #9 评测盲区覆盖**（`29_evaluation_coverage_design.md`，P2，约 1.5-2 天）——`DIMENSION_KINDS` 增 ecosystem/sentiment/roadmap + fixture 用例 + 评测指南同步。
4. **§12.3 #10 消融/对比实验**（`30_ablation_comparison_design.md`，P2，约 1-1.5 天）——`enable_rag`/`enable_memory` 开关 + `AblationRunner` 对 26 条真实执行用例跑 full/no-rag/no-memory/no-llm-rule 对比表（简历/面试数据支撑）。
5. **§12.3 #11 失败类型统计**（`31_failure_stats_design.md`，P2，约 0.5-1 天）——`FailureType` 五类分类 + `BenchmarkReport.failure_stats` 聚合 + 分布报告（归因与简历证据）。

> 依赖顺序建议：23（多源路由，底层）→ 24（分析器）→ 25（榜单，复用 23 的 provider）→ 26（时间线，复用 23 的 Releases）→ 27（定价，独立）→ 28（导出，复用 26/27）→ 29（评测，依赖 24/25/26 的结构化产出）。23-26 是产品差异化主线，27-29 是可信度与交付增强；**30/31 为简历/面试达标补充**，仅依赖已就绪的 `evaluation/benchmark.py`（真实执行版），可随时穿插实现。
