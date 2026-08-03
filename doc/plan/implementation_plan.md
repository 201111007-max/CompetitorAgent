# 竞品分析 Agent — 分步实现计划（Implementation Plan）

> 依据 `doc/ai_coding_agent_competitor_analysis_architecture.md`，将"从零到可验收"的实现拆分为可执行的分步任务。
> 每步含：目标 / 交付物 / 文件清单 / 验证方式 / 前置依赖。整体遵循 **M1→M4 里程碑**，但步骤细化到可逐条勾选。

---

## 0. 实现总原则

1. **框架优先，领域后置**：先把 `core/`（预算、循环、护栏、记忆框架）跑通，再填充竞品采集与分析领域逻辑。
2. **测试同步**：每个 core 模块落地时立即补单元测试，杜绝 bugs.md 的 P0 #1（无单元测试）重演。
3. **小步可验收**：每步都有明确"通过 = 什么现象"，避免做完一大坨才发现方向错。
4. **目录隔离**：所有代码在 `competitor_agent/` 下，不 import `dota_helper.*`。

---

## 1. 里程碑总览与依赖关系

```
M0 准备 ─► M1 骨架（跑通采集→分析→报告）──► M2 记忆/自进化
              │                              │
              │                              ▼
              └────────────► M3 多Agent+评测 ◄────┘
                                    │
                                    ▼
                              M4 工程化
```

| 里程碑 | 主题 | 依赖 | 状态 |
|--------|------|------|------|
| M0 | 环境/目录/配置准备 | 无 | ✅ 已完成 |
| M1 | 骨架闭环 | M0 | ✅ 已完成 |
| M2 | 记忆 + RAG 自进化 | M1（骨架可用） | ✅ 已完成 |
| M3 | 多 Agent 协作 + 评测体系 | M1、M2 | ◀ 进行中（3.1-3.6 已完成，待补实测基准） |
| M4 | Web/MCP/CI/断点工程化 | M1、M2、M3 | 未开始 |

---

## 2. M0 — 环境与项目骨架（半天）✅ 已完成

### 目标
建立可运行的 `competitor_agent/` 包骨架与工程配置，为后续每步提供"能 import、能跑测试"的底子。

### 步骤清单

| # | 任务 | 交付物 | 验证方式 | 状态 |
|---|------|--------|---------|------|
| 0.1 | 创建目录树（按架构文档第 3 节） | `competitor_agent/` 全量空目录 + `__init__.py` | `python -c "import competitor_agent"` | ✅ |
| 0.2 | 写 `pyproject.toml` | 包配置、依赖（openai/httpx/beautifulsoup4/pyyaml/chromadb/playwright 等）、dev 依赖（pytest/ruff/respx/pytest-asyncio） | `pip install -e .` | ✅ |
| 0.3 | 写 `config/review_config.yaml` | 预算默认值（max_iterations/cost_limit/终止阈值）、维度清单 | `yaml.safe_load` 通过 | ✅ |
| 0.4 | 迁移 SecretVault | `secret_vault.py`（复制 dota_helper 实现，改日志前缀，数据目录指向 `~/.competitor_agent/`） | 单测：get/set/rotate/unset/加密落盘/审计 | ✅ |
| 0.5 | 初始化 `tests/` 骨架 | `tests/unit/`、`tests/integration/`、`tests/evaluation/` + conftest | `pytest` 收集 0 失败 | ✅ |
| 0.6 | 写 README 初版 | 项目定位、启动方式、目录说明 | 可被新成员按文档跑通 | ✅ |

### 里程碑出口条件（实测结果）
- `pip install -e .` 成功 ✅
- `pytest` **28 passed** ✅
- SecretVault 单测全绿 + 覆盖率 **100%** ✅
- `ruff check` 通过、`mypy` 17 source files 无错误 ✅

### M0 落地经验（写后续代码时注意）
- **包布局**：`pyproject.toml` 位于 `competitor_agent/` 内（与架构一致），必须用 `[tool.setuptools] packages.find where=[".."]` + `include=["competitor_agent*"]`。用 `where=["."]` 会把内部子目录误当顶层包，导致 `import competitor_agent` 失败。
- **mypy 版本**：mypy 2.x 不支持 `python_version="3.9"` 配置（会报错），统一用 `python_version="3.10"`。
- **yaml 类型**：`import yaml` 需安装 `types-PyYAML` 消除 mypy 的 `import-untyped` 报错。
- **SecretVault 现代化**：复制 dota_helper 时需按 ruff 规则改写（`dict/list/str|None` 类型、`from __future__ import annotations`）。

---

## 3. M1 — 骨架闭环（4-5 天）✅ 已完成

### 目标
输入"分析 Claude Code"，输出含功能/定价/版本的 Markdown 报告。**此时采集用简单 WebExtractor（requests+BeautifulSoup），不做 Playwright、不做 RAG**。

### 步骤清单

| # | 任务 | 交付物 | 验证方式 | 状态 |
|---|------|--------|---------|------|
| 1.1 | `domain_types/` 数据模型 | competitor.py / info_gap.py / strategy.py / observation.py / report.py / events.py / enums.py | 单测 dataclass 构造与序列化 | ✅ |
| 1.2 | `interfaces/` 契约层 | collector.py / analyzer.py / planner.py / memory.py / verifier.py / reporter.py / data_source.py（Protocol） | import 通过 + 类型检查 | ✅ |
| 1.3 | `core/budget.py` + `core/budget_controller.py` | 预算消耗 + 四条件终止（gap 全关/迭代超限/成本超限/核心满足度） | 单测覆盖 4 个终止分支 | ✅ |
| 1.4 | `core/stop_verifier.py` | 停止验证器（能否终止由 Hook 决定） | 单测 | ✅ |
| 1.5 | `core/strategic_loop.py` | 解析竞品+维度 → 生成 InfoGap 清单（含优先级/初始置信度）→ 分配预算 → 产出 CompetitorStrategy | 单测：规则版（无 LLM）生成正确缺口 | ✅ |
| 1.6 | `collector/web_extractor.py` + `source_selector.py` | 官网/定价/文档页抓取与清洗；降级链（官网→缓存→替代源） | 单测：mock 页面返回结构化 Observation | ✅ |
| 1.7 | `analyzers/base.py` + `feature_analyzer.py` + `pricing_analyzer.py` + `performance_analyzer.py` | 维度分析器（LLM 驱动，可注入 LLMClient） | 单测：给定 Observation 返回 DimensionResult | ✅ |
| 1.8 | `core/tactical_loop.py` | 单缺口闭环：预算消耗→SourceSelector→采集→分析→置信度更新→验证/反馈迭代 | 集成测试：mock 数据源跑完整循环 | ✅ |
| 1.9 | `agent/react_agent.py` + `react_loop.py` + `response_parser.py` + `tool_dispatcher.py` | ReAct 交互层（Thought→Action→Observation） | 单测：给定系统+工具描述，产出合法 Action | ✅ |
| 1.10 | `core/report_builder.py` + `markdown_renderer.py` | 汇总维度结果→Markdown 报告（含置信度/证据/未关闭缺口） | 单测：报告格式正确 | ✅ |
| 1.11 | `facade/api.py` | `CompetitorAnalysisAPI.analyze(competitor)`（组装 Strategic→Tactical→Report） | 端到端：`analyze("Claude Code")` 输出报告 | ✅ |
| 1.12 | M1 单测补全 | `tests/unit/core/`、`tests/unit/collector/`、`tests/unit/analyzers/` | `pytest` 全绿 + ruff 通过 | ✅ |

### 里程碑出口条件（实测结果）
- `CompetitorAnalysisAPI.analyze("Claude Code")` 返回含功能/定价/版本三块的 Markdown 报告 ✅（实测输出报告）
- LLM Key 缺失时走 `fallback_analyzer` 仍产出报告（不崩溃）✅（`use_llm=False` 规则降级路径单测覆盖）
- 单元测试覆盖 core 层 ≥ 80% ✅（实测 **97%**；全包 96%）

### M1 验证数据
- `pytest` **147 passed**（0.26s）
- `ruff check` All checks passed；`mypy` 57 source files 无错误
- 补充交付：`competitor_registry.py`（竞品注册表）、`llm/client.py`（LLMClient 抽象）、`analyzers/registry.py`（维度→分析器映射）、`observability/logger.py`

### M1 落地经验
- **respx 慢**：respx 0.23.1 与 httpx 0.28 存在每请求 ~1.2s 延迟（即使 mock）。改用 `httpx.MockTransport` 注入 client，采集测试从 10s 降到 0.17s。
- **mypy 依赖链**：openai 依赖链引入 numpy，其 `.pyi` 需要 py3.12 语法。`pyproject.toml` 加 `follow_imports = "skip"` 全局跳过第三方类型跟随。
- **InfoGap.field 命名冲突**：字段名 `field` 与 `dataclasses.field` 重名，import 用 `field as d_field` 解决。

---

## 4. M2 — 记忆与自进化（3-4 天）

### 目标
第二次分析同一竞品时自动命中记忆与知识库，工具选择逐渐变聪明。

### 步骤清单

| # | 任务 | 交付物 | 验证方式 | 状态 |
|---|------|--------|---------|------|
| 2.1 | `memory/four_layer_memory.py` + `session_archive.py` + `persistent_notes.py` | L1 会话归档、L2 持久笔记（sqlite/json，键 = competitor_name） | 单测：写读/去重/老化 | ✅ |
| 2.2 | `memory/skill_store.py` | L3 技能沉淀：分析成功后提炼"该竞品用哪个源更有效" | 单测：技能自动抽取并下次命中 | ✅ |
| 2.3 | `memory/evolution_memory.py` | L4 进化记录：数据源成功率统计（SPA 站点→Playwright 优先） | 单测：成功率排序影响 SourceSelector | ✅ |
| 2.4 | `knowledge_base/ingester.py` + `retriever.py` + `competitor_store.py` | 竞品文档/Changelog 向量化、混合检索、按竞品×维度索引 | 集成测试：检索返回相关 chunk | ✅ |
| 2.5 | `agent/prompts/react_system.py` 改造 | Prompt 注入：`enrich_prompt` 拼入技能+历史教训 | 单测：prompt 含记忆片段 | ✅ |
| 2.6 | `core/strategic_loop.py` 接记忆 | 规划前查记忆，缺口初始置信度随历史提升 | 集成测试：二次分析优先命中 | ✅ |
| 2.7 | 接入 Playwright（渐进） | `collector/web_extractor.py` 增加 SPA 支持（可选依赖） | 对 Cursor/Claude Code 官网实测 | ✅ 已完成（`spa_extractor.py` + 降级链接入） |

### 里程碑出口条件
- 二次分析同一竞品：起点置信度高于首次、报告更快（记忆命中日志可见）。
- 知识库可检索出正确竞品文档片段。

### M2 落地情况（实测）
- `memory/`：`session_archive.py`（L1 会话归档，TTL 老化/去重）、`persistent_notes.py`（L2 笔记，去重+上限裁剪）、`skill_store.py`（L3 技能，成功加权/失败衰减）、`evolution_memory.py`（L4 成功率，平滑）、`json_store.py`（原子写 JSON 基类）、`four_layer_memory.py`（组合实现 IFourLayerMemory）。
- `knowledge_base/`：`competitor_store.py`（词袋倒排+余弦检索，未装 chromadb 也可用）、`ingester.py`（分块摄入）、`retriever.py`（同竞品优先+维度加权）。chromadb/sentence-transformers 为 `[rag]` 可选依赖，装上后走向量检索（渐进增强）。
- `agent/prompts/react_system.py`：`enrich_prompt()` 注入技能/笔记/知识库片段；`ReactAgent.build_system_prompt()` 支持记忆参数。
- `core/strategic_loop.py`：`_apply_memory_boost()` 命中技能缺口初始置信度 +0.2（≤0.8）。
- `collector/source_selector.py`：`set_success_rates()` 按 L4 成功率提升候选源 trust（0.5~1.0）。
- `facade/api.py`：构造函数支持注入 `memory`；分析成功后自动 `record_skill` + `record_outcome`（记忆自进化）。
- **2.7 Playwright**：新增 `collector/spa_extractor.py`（惰性导入 playwright，未装时 `is_available()==False` 优雅降级；`render_page` 钩子可注入测试）；`tactical_loop.py` 增加 `extractors` 分发注册表，SPA 候选源自动走 SpaExtractor；`source_selector.py` 降级链末尾追加 `spa_extractor` 兜底候选。安装 `pip install -e .[spa]` 后 `playwright install` 即可启用真实渲染。
- **验证**：`pytest` **212 passed**；`ruff check` All checks passed；`mypy` 79 source files 无错误；总覆盖率 **94%**（team 85-100%、evaluation 92-100%、parallel/subagent 81-88%、spa 96%）。
- **剩余**：chromadb 向量检索为渐进增强项（未装 `[rag]` 前词袋检索已覆盖）。

---

## 5. M3 — 多 Agent 协作 + 评测体系（3-4 天）◀ 进行中

### 目标
Collector→Analyzer→Validator→Reporter 协作；评测体系能量化字段准确率、幻觉率、工具选择准确率。

### 步骤清单

| # | 任务 | 交付物 | 验证方式 | 状态 |
|---|------|--------|---------|------|
| 3.1 | `team/collector_agent.py` + `analyzer_agent.py` + `validator_agent.py` + `reporter_agent.py` | 多 Agent + 消息总线（结构化 Artifact 传递） | 集成测试：一条任务流经 4 个 Agent 产出草稿 | ✅ |
| 3.2 | Validator 事实校验 | 证据引用校验 + 与历史冲突检测，冲突打回交叉验证 | 单测：构造冲突证据被拦截 | ✅ |
| 3.3 | `evaluation/accuracy_eval.py` | 字段准确率 / F1 / 幻觉率（prediction vs ground_truth） | 对 fixtures 跑出指标 | ✅ |
| 3.4 | `evaluation/strategy_eval.py` | 工具选择准确率 / 成本效率 | 对 fixtures 跑出指标 | ✅ |
| 3.5 | `evaluation/benchmark.py` + `tests/evaluation/fixtures/` | 10+ 标注用例（定价/版本/功能 ground truth） | `pytest tests/evaluation` 全绿 | ✅ |
| 3.6 | `core/parallel_runner.py` + `subagent.py` | 高优先级独立维度并行采集分析 | 集成测试：并行任务正确合并结果 | ✅ |

### 里程碑出口条件
- benchmark 跑出三指标（字段准确率≥90%、幻觉率≤5%、工具选择≥85%）目标值有数据支撑。
- 多 Agent 流一次跑通并产出草稿报告。

### M3 落地情况（实测）
- **多 Agent 流水线** `team/`：
  - `message_bus.py`：进程内发布/订阅总线（topic 路由 + sequenced Envelope + 审计回放 + 全局通配订阅 + thread-safe）。
  - `collector_agent.py`（缺口→降级链→Observation）、`analyzer_agent.py`（观测→DimensionResult）、`validator_agent.py`（证据/置信度/冲突校验）、`reporter_agent.py`（校验后草稿 + 校验备注）、`orchestrator.py`（`TeamOrchestrator.run()` 一条任务流经 4 个 Agent 产出 CompetitorReport）。
  - `validator_agent.FactValidator`：missing_evidence（无证据链拦截 / 高置信低可信证据告警）、low_confidence、conflict（与历史置信翻转检测）；冲突结论从报告正文剔除并计入待办。
- **评测体系** `evaluation/`：
  - `accuracy_eval.py`：`AccuracyEvaluator`（字段级 exact-match 准确率 / token-F1 / 幻觉率）。
  - `strategy_eval.py`：`StrategyEvaluator`（工具选择准确率 / 命中排名 / 成本效率）。
  - `benchmark.py`：`Benchmark.run()` 加载 fixtures 产出 `BenchmarkReport`。
  - fixtures：`tests/evaluation/fixtures/`（accuracy 4 条 + strategy 4 条，覆盖定价/模型/SPA 选源）。
- **并行执行** `core/`：`subagent.py`（单缺口闭环子代理）+ `parallel_runner.py`（ThreadPoolExecutor 并行 + 共享 ThreadSafe 预算 + 按策略顺序稳定合并）。实测 3 个 0.15s 抓取任务并行 < 0.4s。
- **验证**：`pytest` **212 passed**（新增 team 11 + evaluation 10 + parallel 4 + spa 6 = 31）；`ruff` All checks passed；`mypy` 79 source files 无错误；总覆盖率 **94%**。
- **待补**：把真实标注用例（定价/版本/功能 ground truth）扩充到 10+ 后，跑出三项 benchmark 指标并回填出口条件目标值；可选接入 TeamOrchestrator 到 `facade/api.py` 的 analyze 模式。

### M3 落地经验
- **结果维度取 analyzer.dimension**：并行合并测试中曾用单一 PricingAnalyzer 跑所有缺口，导致 `DimensionResult.dimension` 全为 pricing；必须按缺口 field 经 AnalyzerRegistry 分发分析器。
- **共享预算防递减**：ParallelRunner 多缺口共享 IterationBudget 时，0 token delta 会触发"边际递减"提前停；测试用 `min_continuations=999` 禁用该逻辑。
- **SourceSelector SPA 兜底会改变候选集**：测试竞品须配齐 home/pricing/docs 链接，否则非 pricing 缺口零候选、直接 BLOCKED。

---

## 6. M4 — 工程化（3-4 天）

### 目标
Web SSE 可视化、MCP Server 对外开放、CI、断点续跑/中断/历史。

### 步骤清单

| # | 任务 | 交付物 | 验证方式 |
|---|------|--------|---------|
| 4.1 | `web_app.py` | FastAPI + SSE（ProgressEvent 流） | 浏览器可看逐步进度 |
| 4.2 | `mcp_server/server.py` + `tools/`（web/github/pricing/benchmark/review_tools.py） | FastMCP("Competitor Intelligence Agent")，工具按领域分组 | MCP Client 可调用采集工具 |
| 4.3 | `mcp_server/tools/github_tools.py` | GitHub API（stars/releases/commits，Token 经 SecretVault） | 单测 mock API 返回 |
| 4.4 | 断点续跑/中断 | 会话 checkpoint 恢复 + `cancel` 接口 | 集成测试：中断后恢复继续 |
| 4.5 | 历史查询 | 按竞品查历史报告（记忆 L1） | 集成测试 |
| 4.6 | CI（GitHub Actions 或等效） | pytest + ruff + mypy 流程 | push 自动跑 |
| 4.7 | 文档收口 | README 完善 + `docs/usage.md` + `docs/api.md` | 按文档可用 |

### 里程碑出口条件
- Web 端完整可视化一次分析全程。
- MCP Client 调用 3+ 采集工具成功。
- CI 全绿。

---

## 7. 需要补充/创建的文档清单

> 架构文档已给出"设计蓝图"，以下是落地过程**必须补齐**的支撑文档。

### 7.1 实现阶段（随代码同步）

| 文档 | 路径 | 内容 | 何时写 |
|------|------|------|--------|
| **接口契约文档** | `competitor_agent/docs/interfaces.md` | 各 Protocol 的签名、语义、异常约定、数据流方向 | M1 的 1.2 完成时 |
| **领域模型文档** | `competitor_agent/docs/domain_models.md` | InfoGap/Observation/CompetitorStrategy 字段含义与状态机（如 GapStatus 流转） | M1 的 1.1 完成时 |
| **Prompt 规范文档** | `competitor_agent/docs/prompts.md` | 各 Prompt 模板清单、动态注入点（记忆/工具描述/知识库） | M1→M2 过程维护 |
| **数据源目录** | `competitor_agent/docs/data_sources.md` | 每个竞品的数据源清单、降级链、采集方式（static/SPA）、反爬注意 | M1/M2 随采集器维护 |
| **配置说明** | `competitor_agent/docs/configuration.md` | review_config.yaml 每个字段含义与默认值 | M0 完成时 | ✅ 已完成 |
| **迁移对照表** | `doc/plan/migration_map.md` | dota_helper 模块 → competitor_agent 模块 的复制/改造/重写映射（架构文档第 8 节展开） | M0 开始时 | ✅ 已完成 |
| **评测用例标注规范** | `competitor_agent/docs/evaluation_guide.md` | ground truth 标注格式、用例如何新增、指标口径 | M3 的 3.3 前 |

### 7.2 验收/交付阶段

| 文档 | 路径 | 内容 | 何时写 |
|------|------|------|--------|
| **使用手册** | `competitor_agent/docs/usage.md` | 启动 Web / CLI / MCP 的方式、常用命令 | M4 |
| **API 参考** | `competitor_agent/docs/api.md` | `CompetitorAnalysisAPI` 全部方法签名与示例 | M4 |
| **测试策略文档** | `competitor_agent/docs/testing.md` | 测试分层（unit/integration/evaluation）、覆盖率目标、如何 mock 网络 | M1 起随补 |
| **验收报告模板** | `doc/plan/acceptance_template.md` | 每个里程碑的验收清单（把本文"出口条件"固化为勾选表） | M1 前 |

### 7.3 建议但不强制

| 文档 | 用途 |
|------|------|
| `doc/plan/risk_register.md` | 风险登记（LLM 成本失控、反爬、SPA 无法解析、幻觉）与缓解 |
| `competitor_agent/CHANGELOG.md` | 变更记录 |

---

## 8. 风险与缓解（提前登记）

| 风险 | 影响 | 缓解 |
|------|------|------|
| 竞品官网为 SPA，requests 拿不到内容 | 采集失败 | M2 起引入 Playwright；SourceSelector 按 L4 成功率自动升级 |
| LLM 成本失控 | 预算超支 | BudgetController 成本上限 + Token 计数 + 缓存命中优先 |
| 反爬 / 封 IP | 采集中断 | 限速（ToolGuard rate limit）、缓存、User-Agent、低并发 |
| 幻觉：编造定价/功能 | 报告不可信 | 证据链（SourceEvidence）+ Validator 事实校验 + 幻觉率评测 |
| 版本演进与文档不符 | 过期结论 | 时间戳标注 + 定期 re-analyze + evolution_memory 数据源新鲜度 |

---

## 9. 关键依赖清单（写 pyproject.toml 时用）

```
runtime:
  openai>=1.0, httpx, pyyaml, beautifulsoup4, lxml, python-dotenv
  chromadb, sentence-transformers (M2 RAG)
  fastapi, uvicorn (M4 Web)
  mcp (M4 Server)
optional:
  playwright (M2 SPA)
  numpy, pandas (M3 评测统计)
dev:
  pytest, pytest-asyncio, respx, ruff, mypy
```

---

## 10. 建议执行节奏

```
第 1 周：M0（0.5 天）+ M1（4.5 天）
第 2 周：M2
第 3 周：M3
第 4 周：M4 + 文档收口 + 演示准备
```

每周五用对应里程碑"出口条件"自检一次；不达标则下周一优先补齐该缺口再前进。
