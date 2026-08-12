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
| `07_file_reference_design.md` | 问题 7：`@file:` 任意文件读取 | P2 | ✅ 已修复 |
| `08_auth_cors_design.md` | 问题 8：CORS 全开 + 无认证 | P2 | ✅ 已修复 |
| `09_checkpoint_atomicity_design.md` | 问题 9：checkpoint 写无原子性/锁 | P2 | ✅ 已修复 |
| `10_parallel_runner_design.md` | 问题 10：ParallelRunner 未接入主流程 | P2 | ✅ 已修复 |
| `11_integration_test_design.md` | 问题 11：测试缺集成/端到端 | P2 | ✅ 已修复 |
| `12_code_quality_design.md` | 问题 12-14：重复代码 / 死代码 / 过度设计 | P3 | ✅ 已修复 |

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

## 设计文档统一模板

每个设计文档包含以下章节：

1. **问题现状** — 现状描述、位置、影响
2. **目标设计** — 期望达到的能力
3. **模块/接口设计** — 新增/修改的类、函数、接口签名
4. **接入方式** — 如何接入主流程
5. **验证方式** — 单测/集成/端到端验证
6. **实现优先级与工作量** — 建议顺序与估算
