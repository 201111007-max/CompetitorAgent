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
| M3 | 多 Agent 协作 + 评测体系 | M1、M2 | ✅ 已完成 |
| M4 | Web/MCP/CI/断点工程化 | M1、M2、M3 | ✅ 已完成 |
| M5 | 用户输入解析与交互层 | M1（解析入口可用） | ✅ 已完成 |

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
- **Benchmark 指标达标**：字段准确率 **90.91%**（目标 ≥ 90%）、幻觉率 **0%**（目标 ≤ 5%）、工具选择准确率 **100%**（目标 ≥ 85%）；标注用例扩充至 **14 条**（accuracy 8 + strategy 6）。
- **TeamOrchestrator 接入 facade/api.py**：新增 `CompetitorAnalysisAPI.analyze_team()` 方法，暴露多 Agent 流水线模式（Collector→Analyzer→Validator→Reporter）。
- **accuracy_eval 归一化增强**：`_normalize()` 增加货币符号去除、单位标准化（/month→per month、/月→per month 等）、标点去除，使 exact-match 更语义友好。

### M3 落地经验
- **结果维度取 analyzer.dimension**：并行合并测试中曾用单一 PricingAnalyzer 跑所有缺口，导致 `DimensionResult.dimension` 全为 pricing；必须按缺口 field 经 AnalyzerRegistry 分发分析器。
- **共享预算防递减**：ParallelRunner 多缺口共享 IterationBudget 时，0 token delta 会触发"边际递减"提前停；测试用 `min_continuations=999` 禁用该逻辑。
- **SourceSelector SPA 兜底会改变候选集**：测试竞品须配齐 home/pricing/docs 链接，否则非 pricing 缺口零候选、直接 BLOCKED。

### 3.7 Benchmark 组合参考（业界通用评测基准）

> 业界没有"唯一通用" benchmark。SWE-bench（含 Verified/Pro）曾是事实标准，但 OpenAI 2025 年审计后公开质疑其信号质量（测试缺陷 ~27.6%、训练污染），不再作为唯一依据。共识是**按能力域组合评测**，并注意 harness 差异可造成 10-20 个百分点分差，"分数必须配版本号（benchmark + subset + harness）"。

| 能力域 | Benchmark | 说明 | 本项目的对应 |
|--------|-----------|------|--------------|
| 通用 Agent 能力 | AgentBench（清华，8 环境，ICLR 2024） | 综合评测基准 | Strategic/Tactical 双循环规划 |
| 代码 / 仓库修复 | SWE-bench Pro / Verified | 真实 GitHub issue → patch 通过测试；Pro 更长上下文/跨文件 | —（非代码 Agent，参考） |
| CLI / 终端操作 | Terminal-Bench 2.0（Stanford + Laude） | 文件系统/进程/基础设施自动化，独立治理 | — |
| Web 操作 | WebArena / BrowserGym | 真实 Web 环境任务 | 官网/文档采集（SPA 渲染） |
| 工具编排 / MCP | MCP-Atlas（Scale Labs, 2026） | 1000 任务 / 36 真实 MCP server / 220 工具，claim 级打分 | `mcp_server/` 对外暴露的采集/分析工具 |
| 通用助手 | GAIA | 多工具、规划、错误恢复 | — |

**评测分层**（对应本项目已有的三层）：
1. **Component Eval**：单模块正确性 → `tests/unit/`（分析器/采集器/预算）
2. **Trajectory Eval**：执行路径合理性 → `evaluation/strategy_eval.py`（工具选择准确率）
3. **End-to-End Eval**：最终任务完成度 → `evaluation/accuracy_eval.py`（字段准确率/幻觉率）

**最小 eval 集建议**：20 条起（10 正常 + 5 边界 + 3 工具失败 + 2 安全/拒绝），写进简历前扩到 50+ 并加回归；每次运行必须保存 trace（工具调用/参数/成本/耗时），否则无法归因失败。

---

## 6. M4 — 工程化（3-4 天）✅ 已完成

### 目标
Web SSE 可视化、MCP Server 对外开放、CI、断点续跑/中断/历史。

### 步骤清单

| # | 任务 | 交付物 | 验证方式 | 状态 |
|---|------|--------|---------|------|
| 4.1 | `web_app.py` | FastAPI + SSE（ProgressEvent 流），含简易前端页面 | 浏览器可看逐步进度 | ✅ |
| 4.2 | `mcp_server/server.py` + `tools/`（web/github/pricing/benchmark/review_tools.py） | FastMCP("Competitor Intelligence Agent")，工具按领域分组 | MCP Client 可调用采集工具 | ✅ |
| 4.3 | `mcp_server/tools/github_tools.py` | GitHub API（stars/releases/commits，Token 经 SecretVault） | 单测 mock API 返回 | ✅ |
| 4.4 | 断点续跑/中断 | `core/checkpoint.py` 会话 checkpoint 恢复 + `cancel`/`resume` 接口 | 集成测试：中断后恢复继续 | ✅ |
| 4.5 | 历史查询 | `get_history()` 按竞品查历史报告（记忆 L1） | 集成测试 | ✅ |
| 4.6 | CI（GitHub Actions） | `.github/workflows/ci.yml` pytest + ruff + mypy 流程 | push 自动跑 | ✅ |
| 4.7 | 文档收口 | README 完善 + `docs/usage.md` + `docs/api.md` | 按文档可用 | ✅ |

### 里程碑出口条件
- Web 端完整可视化一次分析全程。✅（`/api/analyze?task=...` SSE 流 + 前端实时展示）
- MCP Client 调用 3+ 采集工具成功。✅（web_extract / github_stars / analyze_pricing 等 8 个工具）
- CI 全绿。✅（`.github/workflows/ci.yml` 三版本 Python 矩阵）

### M4 落地情况（实测）

#### 4.1 Web 应用（`web_app.py`）
- **FastAPI + SSE**：`GET /api/analyze?task=分析%20Cursor` 返回 `text/event-stream`，逐条推送 `ProgressEvent`。
- **简易前端**：`GET /` 返回含输入框、开始/取消按钮、实时日志的 HTML 页面。
- **API 端点**：`/api/analyze`（SSE）、`/api/cancel/{session_id}`（取消）、`/api/history`（历史）、`/api/history/{competitor}`（按竞品）、`/api/status/{session_id}`（状态）。
- **会话管理**：全局 `_sessions` 字典跟踪运行中会话，支持取消标志检查。
- **记忆归档**：分析完成后自动 `archive_session()` 到 L1 记忆。

#### 4.2 MCP Server（`mcp_server/`）
- **server.py**：`FastMCP("Competitor Intelligence Agent")`，支持 stdio 和 SSE 两种传输模式。
- **工具分组**：
  - `web_tools.py`：`web_extract(url, selector)` — 基于 httpx+BeautifulSoup 的网页采集
  - `pricing_tools.py`：`analyze_pricing(competitor, url)` — 定价分析
  - `github_tools.py`：`github_stars(repo)` / `github_releases(repo, limit)` / `github_commits(repo, days)` — GitHub API，Token 经 SecretVault
  - `benchmark_tools.py`：`run_benchmark()` — 运行评测基准
  - `review_tools.py`：`analyze_competitor(task)` — 综合分析全流程
- **启动方式**：`python -m competitor_agent.mcp_server.server --transport stdio|sse`

#### 4.3 GitHub 工具（`mcp_server/tools/github_tools.py`）
- 通过 GitHub REST API 查询仓库信息。
- Token 经 `SecretVault.get("GITHUB_TOKEN")` 获取，无 Token 时走未认证请求（限流 60 req/h）。
- 错误处理覆盖 404（仓库不存在）、403（限流）、网络异常。

#### 4.4 断点续跑/中断（`core/checkpoint.py`）
- **Checkpoint 数据模型**：`Checkpoint` dataclass 保存 session_id / task / competitor / gaps / dimension_results / 预算状态 / 已尝试源。
- **序列化**：JSON 文件存储于 `~/.competitor_agent/checkpoints/`。
- **保存时机**：`facade/api.py` 的 `analyze()` 每完成一个缺口自动 `save_checkpoint()`。
- **清理**：分析完成后 `delete_checkpoint()` 自动清理。
- **取消机制**：全局 `_cancel_flags` 字典 + `set_cancel()` / `is_cancelled()`，分析循环中每缺口前检查。
- **恢复**：`resume(session_id)` 加载 checkpoint → `checkpoint_to_report()` 重建 `CompetitorReport`。

#### 4.5 历史查询
- `CompetitorAnalysisAPI.get_history(competitor=None)` 通过记忆 L1 查询历史会话。
- Web 端点 `/api/history` 和 `/api/history/{competitor}` 暴露历史数据。

#### 4.6 CI（`.github/workflows/ci.yml`）
- **触发**：push/PR 到 main 分支，仅 `competitor_agent/` 和 CI 配置变更时运行。
- **矩阵**：Python 3.10 / 3.11 / 3.12。
- **步骤**：checkout → setup-python → pip install `.[dev]` → ruff check → mypy → pytest --cov。
- **制品**：3.12 构建上传 coverage 报告。

#### 4.7 文档收口
- **README.md**：更新里程碑状态为全部完成，新增 Web/MCP/编程调用示例。
- **docs/usage.md**：完善安装、启动方式（CLI/Web/MCP/编程）、常用操作、输出说明、FAQ。
- **docs/api.md**：完整 API 参考，含 CompetitorAnalysisAPI 构造参数、全部方法签名、事件契约、数据模型、错误处理。

### 验证结果
- `pytest` **212 passed**（无回归）
- `ruff check` All checks passed
- `mypy` 79 source files 无错误
- 总覆盖率 **94%**

---

## 6.5 M5 — 用户输入解析与交互层（2-3 天）✅ 已完成

> 参考 hermes-agent 的输入处理逻辑（命令注册表 / 浅清洗 / 会话历史），补齐 competitor_agent 输入管线。
> 详细设计见 `doc/plan/input_parsing_design.md`。

### 目标
补齐 CLI 入口（usage.md 已承诺但 `cli.py` 不存在），引入斜杠命令注册表、入站浅清洗、
增强任务语义解析（对比/维度限定/自定义源），并支持交互式多轮会话。

### 步骤清单

| # | 任务 | 交付物 | 验证方式 | 状态 |
|---|------|--------|---------|------|
| 5.1 | CLI 入口补齐 | `competitor_agent/cli.py`（argparse `analyze/history/benchmark` 子命令 + `-z/--oneshot` + `-c/--continue` + 交互 REPL） | `python -m competitor_agent.cli analyze "Claude Code"` 输出报告 | ☑ |
| 5.2 | 命令注册表 | `core/command_registry.py`（CommandDef + `_looks_like_slash_command` + `resolve_command` + `command_dispatch`） | 单测：前缀判定 / 别名解析 / 文件路径排除 | ☑ |
| 5.3 | 入站浅清洗 | `core/input_sanitizer.py`（strip_paste_wrappers / strip_terminal_leaks / expand_references / sanitize_surrogates） | 单测：粘贴包装剥离、`@file:` 展开、代理字符清理各一例 | ☑ |
| 5.4 | 任务语义解析增强 | `core/task_parser.py` + 增强 `competitor_registry.resolve_competitor` / `strategic_loop._build_gaps`（对比拆分、维度白名单、自定义源） | 单测：`parse_task("对比 Cursor 和 Windsurf")` → 2 竞品；`parse_task("只分析 Cursor 定价")` → dimensions=["pricing"] | ☑ |
| 5.5 | 会话历史与恢复 | `facade/api.py` 增 `conversation_history` 参数 + `compare()` + `continue_analysis()` | 集成测试：带历史二次分析命中记忆；`compare(A,B)` 产出对比报告 | ☑ |
| 5.6 | 测试补全 | `tests/unit/core/test_command_registry.py` + `test_input_sanitizer.py` + `test_task_parser.py` + `tests/unit/facade/test_api_history.py` | `pytest` 全绿 + ruff + mypy 通过 | ☑ |
| 5.7 | 文档收口 | usage.md CLI 章节与实现对齐、api.md 补 `compare/continue_analysis` | 按文档可用 | ☑ |

### 里程碑出口条件
- `python -m competitor_agent.cli analyze "Claude Code"` 可运行（当前 usage.md 承诺但 CLI 缺失）。
- 交互模式支持 `/history`、`/compare` 斜杠命令；非交互支持 `-z` oneshot。
- `parse_task` 规则版在无 LLM 时正确处理对比/维度限定/自定义源。
- 带 `conversation_history` 的二次分析能引用上一轮上下文。

### M5 验证结果（实测）
- `pytest` **308 passed**（含 M5 新增 87 项：command_registry 16 / input_sanitizer 17 / task_parser 18 / api_history 7 / cli 29）
- 覆盖率：`command_registry` **100%**、`task_parser` **99%**、`input_sanitizer` **87%**、`cli` **94%**、`facade/api` **80%**
- `ruff check` All checks passed；`mypy` M5 新增 5 个源文件无错误
- CLI 实测：`analyze "Cursor" --out reports/`（写出 cursor.md，exit 0）、`-z "只分析 Cursor 定价"`（仅 pricing 缺口）、`analyze "对比 Cursor 和 Windsurf"`（对比报告）、`benchmark`（27 cases）、`history --competitor cursor`
- 注：mypy 全量在本地 Python 3.13 下报 2 处 `unused-ignore`（`facade/api.py:304/306`，M4 遗留 `get_history`），CI 目标 3.10-3.12 不受影响

---

## 7. 文档清单（全部完成 ✅）

> 架构文档已给出"设计蓝图"，以下文档已在落地过程中同步补齐。

### 7.1 实现阶段（随代码同步）

| 文档 | 路径 | 内容 | 状态 |
|------|------|------|------|
| **接口契约文档** | `competitor_agent/docs/interfaces.md` | 各 Protocol 的签名、语义、异常约定、数据流方向 | ✅ |
| **领域模型文档** | `competitor_agent/docs/domain_models.md` | InfoGap/Observation/CompetitorStrategy 字段含义与状态机 | ✅ |
| **Prompt 规范文档** | `competitor_agent/docs/prompts.md` | 各 Prompt 模板清单、动态注入点（记忆/工具描述/知识库） | ✅ |
| **数据源目录** | `competitor_agent/docs/data_sources.md` | 每个竞品的数据源清单、降级链、采集方式（static/SPA） | ✅ |
| **配置说明** | `competitor_agent/docs/configuration.md` | review_config.yaml 每个字段含义与默认值 | ✅ |
| **迁移对照表** | `doc/plan/migration_map.md` | dota_helper → competitor_agent 模块映射 | ✅ |
| **评测用例标注规范** | `competitor_agent/docs/evaluation_guide.md` | ground truth 标注格式、用例新增、指标口径 | ✅ |
| **输入解析设计文档** | `doc/plan/input_parsing_design.md` | 对照 hermes-agent 的输入管线设计（CLI/命令注册表/浅清洗/任务解析/会话） | ✅ |

### 7.2 验收/交付阶段

| 文档 | 路径 | 内容 | 状态 |
|------|------|------|------|
| **使用手册** | `competitor_agent/docs/usage.md` | 启动 Web / CLI / MCP 的方式、常用命令 | ✅ |
| **API 参考** | `competitor_agent/docs/api.md` | `CompetitorAnalysisAPI` 全部方法签名与示例 | ✅ |
| **测试策略文档** | `competitor_agent/docs/testing.md` | 测试分层（unit/integration/evaluation）策略与运行方式 | ✅ |
| **验收报告模板** | `doc/plan/acceptance_template.md` | 每个里程碑的验收清单 | ✅ |
| **风险登记** | `doc/plan/risk_register.md` | LLM 成本失控、反爬、SPA 解析、幻觉等风险与缓解 | ✅ |

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
第 5 周：M5 输入解析与交互层（CLI/命令/清洗/会话）+ 验收
```

每周五用对应里程碑"出口条件"自检一次；不达标则下周一优先补齐该缺口再前进。

---

## 11. 已知问题与待改进项（代码审查结论）

> 以下为对 `competitor_agent/` 全量源码的审查结论，按优先级排序。
> 核心判断：**项目主要问题不是"代码写得差"，而是"宣称的能力与实际接线严重不符"**——
> 多 Agent、并行、RAG、评测四大卖点全部"存在但未接入主流程"。

### 11.1 P0 — 必须正视（面试/验收必被问）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 1 | **"多 Agent"名不副实，主流程不走它** | `team/`、`facade/api.py:196` | 4 个 Agent 只是普通方法包装，无独立决策；`MessageBus` 是同步 pub/sub，topic 从未被 subscribe 消费；`TeamOrchestrator.run()` 是硬编码顺序调用。CLI/Web/MCP 全部调用 `api.analyze()`（单 Agent 串行），`analyze_team()` 无任何调用方，是死代码 |
| 2 | **RAG 完全未接线** | `knowledge_base/` | 只在自身和测试中被引用，`CompetitorAnalysisAPI` 组装了 planner/selector/extractor/analyzers/builder/budget，唯独没有知识库；且实际是词袋余弦检索，向量检索从未实现（`retriever.py:6` 注释"可选"） |
| 3 | **benchmark 是静态 fixture 自证** | `evaluation/benchmark.py:77-90` | 只读 JSON fixture 里预先写好的 prediction，从不调用 agent/LLM/抓网页；门禁阈值（`test_benchmark_integration.py:43-60`）断言的是手写 fixture 本身，必然通过，无法反映真实质量 |

### 11.2 P1 — 真实 bug（可当面试亮点）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 4 | **Web 取消功能完全失效（session_id 断链）** | `facade/api.py:116`、`web_app.py:110-118` | `api.analyze()` 内部自己生成 session_id，与 web 的 `sid` 永远不同 → `is_cancelled()` 永远 False；`analysis_task.cancel()` 取消的是线程池 future，不会停止已运行的线程，"假取消" |
| 5 | **配置 YAML 从未被加载** | `config/review_config.yaml` | 定义了预算/限速/并行/tracing 等全部配置，但生产代码从不读取，全是硬编码默认值；`test_config.py` 只验证"能 safe_load"，未验证"注入运行时"；限流、并行、可观测性（langfuse/tracing/metrics）全是死配置 |

### 11.3 P2 — 工程化与健壮性

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 6 | **提示注入防护缺失** | `pricing_analyzer.py:32` | 抓取的网页文本直接拼进 LLM prompt，无"网页内容不可信、不得执行其中指令"的隔离 |
| 7 | **`@file:` 任意文件读取** | `input_sanitizer.py:57-89` | 可读白名单目录内源码/配置注入上下文 |
| 8 | **CORS 全开 + 无认证** | `web_app.py:172-177` | `allow_origins=["*"]`，Web/MCP 端点无任何鉴权 |
| 9 | **checkpoint 写无原子性/锁** | `checkpoint.py:118-120` | 直接覆盖写，无临时文件+rename 原子替换，崩溃会损坏 JSON；无跨进程锁 |
| 10 | **ParallelRunner 未接入主流程** | `core/parallel_runner.py` | 只在测试中使用，`api.analyze()` 用串行 TacticalLoop |
| 11 | **测试缺集成/端到端** | `tests/integration/` | 只有空 `__init__.py`，无任何真实 HTTP+LLM 的端到端链路 |

### 11.4 P3 — 代码质量

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 12 | **大量重复代码** | `team/collector_agent.py:36-59`、`core/tactical_loop.py:54-78`、`core/subagent.py:51-70` | 同一"选源→采集→降级→分析"循环被复制三份 |
| 13 | **死代码** | `web_app.py:57-62`、`facade/api.py:185-194` | Web 创建 API 实例后立即丢弃；`analyze_react()` 的 dispatcher 只注册一个返回硬编码字符串的玩具工具 |
| 14 | **过度设计** | `team/message_bus.py` | topic/Envelope/history 回放为"多 Agent"叙事搭建完整基础设施，实际只当日志记录器用 |

### 11.5 能站得住的正面点（面试主动讲）

- **LLM→规则降级链**：`analyzers/base.py:40-48` 捕获异常降级，无 Key 也能出报告。
- **入站清洗**：`input_sanitizer.py` 处理 surrogate/ANSI 泄漏/路径穿越。
- **预算控制**：四条件终止 + `IStopVerifier` Hook。
- **单元测试用真实断言**（非纯 mock），如并行加速用真实计时验证。

### 11.6 后续改进方向（建议优先级）

1. 把 `analyze_team` / `ParallelRunner` / RAG 真正接入生产主路径，消除死代码。
2. 修复 Web 取消的 session_id 断链 bug。
3. 让配置 YAML 真正注入运行时（限流/并行/tracing）。
4. 补端到端集成测试，让 benchmark 跑真实 LLM。
  5. 补提示注入防护与认证鉴权。

---

## 12. 面向 AI coding 工具的竞品分析能力缺口（产品级）

> 以下为把项目视作「**面向 AI coding 工具的竞品分析 Agent**」（对标 Claude Code / Cursor / Windsurf / Copilot / Cline / Aider）时，
> 在产品/能力层面的不足。与第 11 节（代码接线/工程审查）互补：第 11 节是"宣称能力没接进主流程"，
> 本节是"即使接好，能力本身也不足以覆盖 AI coding 工具竞品分析"。
> 优先级判定基于"对竞品报告可信度与差异化的影响"。

### 12.1 P0 — 数据入口太窄 + 关键维度裸奔

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 1 | **数据源只认官网** | `collector/source_selector.py:15-96` | `candidates()` 仅用 `competitor.official_links`（pricing/home/docs/changelog）+ 同一 URL 的 SPA 兜底。对所有维度最终只抓官网页面。但 AI coding 工具最有价值的信号在官网之外：GitHub Releases、VS Code/JetBrains 插件市场评分与下载、SWE-bench/Aider polyglot/Terminal-Bench 榜单、社区（HN/Reddit/X/YouTube）、底层模型定价。MCP 已有 `github`/`benchmark`/`review` 工具，但 `SourceSelector` 从不会把缺口路由过去 |
| 2 | **ecosystem / sentiment 无专属分析器** | `analyzers/`（仅 `feature`/`performance`/`pricing`/`fallback`） | `DIMENSION_PRIORITY` 有 6 维度（`core/strategic_loop.py:28`），但 `ecosystem`（MCP server/扩展/IDE 支持/agentic tool-use/集成）与 `sentiment`（社区口碑）无专属分析器 → 落到 `FallbackAnalyzer` 做通用 LLM 总结。对 AI coding 工具，这两点恰是关键差异化，却被最弱的处理 |

### 12.2 P1 — 对比/性能/时效三类硬伤

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 3 | **对比仅支持两两** | `facade/api.py:637` `compare(self, a, b=None)` | 无 N 向品类矩阵（多工具同维度并排）、无"每维度最佳/品类格局"汇总视图 |
| 4 | **性能数字靠 LLM 读网页** | `analyzers/performance_analyzer.py` | 测试可解析 "SWE-bench: 62%"（`tests/.../test_analyzers.py:75`），但**无直连榜单源**，完全依赖网页恰好提到该数字 → 对快速变动工具，数字易缺失/过时 |
| 5 | **无新鲜度/陈旧度管理** | `core/checkpoint.py`、`memory/*` | `roadmap → ["docs","changelog","home"]`（`source_selector.py:21`）只是抓官方 changelog URL，无真正发布/版本追踪；无"结论已 N 天"检测、无自动重爬、无竞品时间线（四层记忆存 source 成功率而非时序） |

### 12.3 P2 — 建模与交付偏弱

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 6 | **定价分层/用量建模弱** | `analyzers/pricing_analyzer.py` | AI coding 工具普遍 免费档/Pro/Business/Enterprise + 按量（请求/模型档位）混合；测试覆盖轻，易只抓标价、漏真实成本结构 |
| 7 | **无趋势/时序** | `core/report_builder.py`、`markdown_renderer.py` | 报告为时间点快照，无竞品变化追踪（"Cursor 于 X 日加 background agents"） |
| 8 | **输出仅 Markdown** | `core/report_builder.py` → `markdown_renderer.py` | 无结构化 JSON/矩阵导出、无定时跑、无"竞品异动"告警 |
| 9 | **评测有盲区** | `evaluation/benchmark.py`、`tests/evaluation/fixtures/` | 真实执行 + 幻觉率指标是亮点，但 ground-truth fixture 偏通用；对"是否正确刻画 agentic 能力/生态/口碑"覆盖不足——而这恰是当前最弱的分析器（见 12.1 #2） |
| 10 | **无对比/消融实验** | `facade/api.py:114-121`、`evaluation/benchmark.py` | RAG/记忆无条件组装、无开关，从未回答"有无 RAG / 有无 rerank / 有无 memory"的差分效果（简历/面试硬缺口）。已具备 26 条真实执行用例可作对照基线，只差变体运行器 |
| 11 | **无失败类型统计** | `evaluation/accuracy_eval.py:31`、`evaluation/benchmark.py:490` | 只有幻觉率 + 逐实例清单与工具选择混淆矩阵，无"失败根因（源不可用/幻觉/无数据/解析错/预算耗尽）→ 计数 → 占比"聚合口径；底层信号（BLOCKED/`collect.fail`/`[PARTIAL]`/`real_trace`）已存在但未聚合 |

### 12.4 建议落地顺序（与第 11 节协同）

1. **扩 SourceSelector 路由**（最高杠杆）：把 `github`/`benchmark`/`review` MCP 工具 + 新增 `changelog`/`marketplace`/`social` 源接进缺口→源映射；可复用第 11.6 #1 已指出但"未接线"的 RAG/team 基础设施承接多源结果。
2. **补 `EcosystemAnalyzer` 与 `SentimentAnalyzer`**：别再走 fallback（对应 12.1 #2）。
3. **N 向对比矩阵 + 品类格局视图**（对应 12.2 #3）。
4. **新鲜度/陈旧度 + 定时重爬 + 竞品时间线**（对应 12.2 #5、12.3 #7）。
5. **直连榜单源**拉性能数字，而非靠 LLM 读网页（对应 12.2 #4）。
6. **结构化输出 + 定时/告警**（对应 12.3 #8）；并扩充评测 fixture 覆盖生态/口碑维度（对应 12.3 #9）。
7. **消融/对比实验**（对应 12.3 #10）：加 `enable_rag`/`enable_memory` 开关 + `AblationRunner`，对 26 条真实执行用例跑 full / no-rag / no-memory / no-llm-rule 对比表（简历与面试叙事最直接的数据支撑）。
8. **失败类型统计**（对应 12.3 #11）：`FailureType` 五类分类 + `BenchmarkReport.failure_stats` 聚合 + 分布报告，补齐归因能力与简历证据。

> 注：第 11 节的"RAG 未接线 / analyze_team 死代码 / ParallelRunner 未接入"若先修复，
> 本节的"多源采集""N 向对比""生态分析"可直接建于其上，避免重复造轮子。

---

## 13. P0 — 自主发现竞品 + 多竞品并排对比（产品能力，用户已确认）

> 触发：用户实测输入「帮我寻找现在市场上所有的ai coding agent并进行分析」→ 报告 0 维度。
> 根因：`resolve_competitor`（`core/competitor_registry.py:84`）要求用户输入**具体竞品名**才能分析；
> 匹配不到注册表时退化为 ASCII 提取，把整句话拼成假竞品 `ai-coding-agent`（无 `official_links`）
> → `SourceSelector` 0 候选 → 6 缺口全 BLOCKED → 0 维度。且 `compare()`（`facade/api.py:637`，`compare(self, a, b=None)`）
> 仅支持**两两**对比。用户明确诉求：Agent 应具备**自主搜索发现竞品**的能力，且支持**多个同时对比**（N 向）。

### 目标
1. **自主搜索发现竞品**：任务未含可识别竞品名（"所有 AI coding agent""市场上有谁""对比主流工具"）时，
   Agent 能自主联网检索（Web 搜索 / MCP 搜索类工具）枚举候选竞品清单（名称 + 官网），再逐个分析，
   而非把整句拼成假竞品导致 0 维度。
2. **N 向并排对比**：一次传入多个竞品（≥2，不限 2 个），产出"品类格局矩阵"
   （维度 × 竞品表 + 每维度最佳/最差/汇总视图），而非仅 A vs B。

### 步骤清单（P0）

| # | 任务 | 交付物 | 验证方式 |
|---|------|--------|----------|
| 13.1 | 竞品自主发现器 `core/competitor_discoverer.py` | 输入自由任务 → 联网检索候选竞品列表（名称+官网），返回 `list[Competitor]`；注册表命中优先，未知则搜索补全 | 单测：mock 搜索返回 N 个；"所有 AI coding agent" 不再产出 `ai-coding-agent` |
| 13.2 | `resolve_competitor` / `resolve_competitors` 改造 | 无匹配且判定为"市场普查/发现"意图时改走发现器；保留单竞品精确解析 | 集成：模糊/普查任务产出真实候选而非假竞品 |
| 13.3 | N 向对比 `facade/api.py: compare(self, *competitors)` 或 `compare(list)` | 支持 ≥2 竞品；`report_builder` / `markdown_renderer` 产出品类矩阵（维度 × 竞品表 + 每维度最佳） | 集成：`compare("Cursor","Claude Code","Copilot","Codex")` 出多维并排报告 |
| 13.4 | Web 前端支持多竞品输入 | 输入框支持逗号/换行分隔多个竞品；「开始分析」走 N 向对比或逐个；普查类任务提示"将自动发现竞品" | 浏览器：输入多个竞品出对比视图；普查任务不再 0 维度 |
| 13.5 | 发现场景数据源 | 发现器用搜索 / MCP（`web` / `github` / `review` 工具）而非仅 `official_links`；与第 12.1 #1 协同复用 `SourceSelector` 路由 | 发现链路可枚举候选并采集 |

### 出口条件
- "分析所有 AI coding agent"类任务不再 0 维度，能枚举并分析多个竞品。
- 单次可对比 ≥3 竞品，报告含品类格局矩阵（每维度最佳/汇总）。

### 依赖
- 第 12.1 #1（扩 `SourceSelector` 路由）、第 11 节 RAG / team 若先修复更佳；
  发现器依赖可用的搜索/MCP 源（LLM Key 配置后可由 LLM 辅助归纳候选，见第 2 项 DeepSeek 配置）。

---

## 14. P0 — 日志完善功能（可观测性补齐）

> 触发：本次"0 维度"排查中，detached 服务器 stdout 被缓冲、分析过程日志不落地，定位极难；
> 且全链路缺少结构化追踪（竞品识别 / 选源 / 采集状态 / 分析置信度 / 终止原因 / LLM 成本）。

### 目标
补齐端到端可观测性，使任意一次分析的全过程可回溯、"0 维度"类问题一眼可定位：
1. **结构化日志**：统一格式（建议 JSON 或 `request_id` 行日志），覆盖一次分析的完整链路。
2. **每分析独立日志文件**：按 `session_id` 落盘到 `~/.competitor_agent/logs/`，便于事后复盘。
3. **关键节点埋点**：任务解析结果、竞品识别、每个缺口的选源 / 采集（url + HTTP 状态 + 字节数）/ 分析（模型 + token + 耗时 + 置信度）、终止原因、报告维度计数。
4. **LLM 调用日志（脱敏）**：模型、`base_url`、输入/output token、耗时、成本（对接 `BudgetController`）；**不落 prompt 全文、不落密钥**。
5. **实时刷新 / 不缓冲**：确保 detached / 重定向场景下日志即时 flush（修复本次"日志看不到"问题）。
6. **Web 端点暴露**：`/api/logs/{session_id}` 或前端可查看当前 / 历史分析日志流。

### 步骤清单（P0）

| # | 任务 | 交付物 | 验证方式 |
|---|------|--------|----------|
| 14.1 | 统一 logger + handler（`observability/logger.py` 增强） | 结构化格式、`request_id` 注入、文件 + 控制台双出口、强制 flush | 单测：输出含字段；重定向下即时落盘 |
| 14.2 | 会话级日志文件 | 每次 `analyze` 建 `logs/<session_id>.log`，分析结束归档 | 集成：跑一次后文件存在且含全链路 |
| 14.3 | 埋点接入 | 在 `task_parser` / `strategic_loop` / `source_selector` / `gap_executor` / `analyzers` / `report_builder` 关键路径打日志 | 日志含"竞品识别 / 选源 / 采集状态 / 分析置信度 / 终止原因" |
| 14.4 | LLM 调用日志（脱敏） | 记录模型 / `base_url` / token / 耗时 / 成本，prompt 仅记长度不记全文 | 含成本字段；无密钥 / 长文本泄漏 |
| 14.5 | Web 日志端点 | `/api/logs/{session_id}` 返回该次分析日志；前端可切换查看 | 浏览器可看历史分析日志 |

### 出口条件
- 任意一次分析的全过程可在日志文件 / Web 端点完整回溯；"0 维度"类问题一眼可定位（如"竞品未识别 / 无候选源"）。
- detached 服务器日志实时可见，不再因缓冲丢失。

### 依赖
- `observability/logger.py`（已有基础）、`config/loader.py` 的 `observability.log_level` 应真正注入（呼应第 11.2 #5 配置未加载）。

---

## 15. P0 — Web 端显示 / 导出报告（待办，用户已确认）

> 触发：用户在 Web UI 跑出「报告生成完成，N 维度」后，页面只显示状态行，**报告正文不展示、也不导出文件**；
> 报告仅存档于 L1 记忆 JSON（`~/.competitor_agent/memory/memory/session_archive.json` 的 `raw.markdown_report`），看不到也拿不到。

### 目标
1. **Web 端展示报告正文**：`report` 事件的 SSE payload 携带 `markdown_report`，前端把 Markdown 渲染为可读报告（而非仅状态日志）。
2. **一键导出 / 自动落盘**：分析完成自动保存为 `reports/competitor/<竞品>.md`（对齐 `config.report.output_dir`）；前端提供"下载 / 复制"入口。

### 步骤清单（P0 待办）

| # | 任务 | 交付物 | 验证方式 |
|---|------|--------|----------|
| 15.1 | SSE 携带报告正文 | `web_app.py` 的 `report` 事件 `payload` 增加 `markdown_report` 字段 | 单测：事件 payload 含正文 |
| 15.2 | 前端渲染 Markdown | `index()` 页面在 `report` 事件后把 `markdown_report` 渲染为 HTML（前端 Markdown 解析或后端预渲染）；保留实时进度日志 | 浏览器：分析完直接在页面看到完整报告 |
| 15.3 | 自动落盘报告文件 | `facade/api.py` 或 `web_app.py` 分析结束写 `reports/competitor/<竞品>.md`（复用 `report.output_dir`） | 集成：跑一次后文件存在 |
| 15.4 | 前端导出入口 | 报告区提供「复制 Markdown」「下载 .md」按钮 | 浏览器可导出 |

### 出口条件
- Web 分析完成后，报告正文直接在页面可读，且 `reports/competitor/<竞品>.md` 自动生成可下载。

### 依赖
- 与 §14 日志完善可共用"分析完成"钩子；落盘路径复用 `config.report.output_dir`（呼应第 11.2 #5 配置未加载，应输出到该目录）。

---

## 16. 深度补充分析（广而不深：全模块 MVP 壳评估）

> 状态背景：设计文档 01–31 已全部实现并合入（见 `doc/plan/issue_designs/README.md`，§11 的"接线类"问题
> 已修复，§12 的产品缺口 23-31 已落地）。本节为 2026-08-14 全量代码复查的新结论：
> **广度已达标，深度仍不足**——15 个模块全部是"能跑通的最小实现"（MVP 壳），概念、文档、测试齐全，
> 但每个模块"再往下问一层"就答不上来。本节回答：下一步补什么、补到什么程度。

### 16.1 深度缺口清单（按模块，含代码证据）

| 模块 | 现状（能跑通） | 深度缺口（代码证据） | 补充方向 |
|------|--------------|-------------------|----------|
| RAG（`knowledge_base/`，300 行） | 文档/chunk/检索/持久化闭环 | 实为**纯 TF-IDF 词袋余弦**：`tokenize` 仅正则切词（competitor_store.py:49）无中文分词/词干；`chunk_text` 固定窗口硬切（:54）会从句中截断；`search` 手写余弦 + 维度硬编码 +0.15（:114/:133）；chromadb 向量检索只写在可选依赖 `[rag]` 里，从未实现 | 接入真向量检索（embedding 选型、语义 chunk、向量+词袋混合、重排序），对标设计文档 02 的原始承诺 |
| 多 Agent（`team/`，784 行） | 四 Agent + MessageBus + 编排闭环 | **顺序流水线非真协作**：`orchestrator.py:100-132` 逐步同步调用；`message_bus.py:75` 行 dict pub/sub 仅内存 log（:43-44）；`publish` 是事后记录（analyzer_agent.py:72），编排不靠订阅驱动——"事件驱动/多 Agent"名不副实 | 真异步协作（并行独立决策 + 结果协商/仲裁），或明确降级叙事为"流水线 + 状态机"，不再宣称多 Agent |
| 分析器（`analyzers/`，1047 行） | LLM 优先 + 规则兜底 + 低置信护栏 | 每个分析器仅 `_build_prompt`/`_parse_result`/`_rule_extract` 三件套（各几十行）；`feature_analyzer.py` 兜底是 13 个关键词扫描（`_FEATURE_MARKERS`）；LLM 路径（base.py:62-81）是"包原文 → 一次 complete → `json.loads`"，无链式推理/多轮验证/结构化约束 | 结构化输出（JSON Schema / tool-call 强制）、链式抽取、每维度专业规则库与真值校验 |
| 记忆（`memory/`，775 行） | 四层 + 时间线 + JSON 持久化 | "四层"= 四个 JSON 文件计数：`skill_store.py:47` 成功 +1.0 / :83 失败 -0.5 / 封顶 50（:20）；`evolution_memory.py` 仅 62 行；无向量记忆、无摘要压缩、无相关度召回 | 记忆摘要/压缩（替代原样存档）、向量召回、跨会话注意权重 |
| LLM 层（`llm/client.py`，128 行） | 调用 + 成本估算 + 脱敏日志 | 单次 `chat.completions.create`（:61）；token 估算用正则（:28）；无重试/退避、无多模型路由、无结构化输出框架 | 重试与退避、结构化输出、多模型 fallback（简历"工程可靠性"加分点） |
| 评测（`evaluation/`，1588 行） | benchmark/消融/失败归因/门禁——全项目最深 | 38 用例大量跑 mock LLM，**真实 LLM 端到端质量未量化** | 跑 `--llm real` 出一份真实质量报告（字段准确率/幻觉率/成本），补上"评测深但只测了 mock"的最后一环 |

### 16.2 补充优先级（按"面试被问概率 × 补齐成本"）

1. **RAG 接真向量检索**：面试最高频问题，代码已预留 `[rag]` 依赖与 chromadb 路径，性价比最高。
2. **真实 LLM 评测报告**：`python -m competitor_agent.evaluation.benchmark --llm real`，补上 mock 与真实之间的信任缺口（对应 16.1 评测行）。
3. **多 Agent 真协作或明确叙事**：消除"宣称多 Agent 实为顺序管道"的名不副实隐患。
4. **记忆摘要压缩**：四层记忆从"计数"升级为"会遗忘/会凝练"，深度加分项。

### 16.3 深度补充的验收口径

深度补充的验收**不是"能跑"**（MVP 已能跑），而是**能讲清 trade-off 并给出数据**：
- RAG：能说清 embedding 选型依据、chunk 策略对召回的影响（给出 top-k 命中率对比）。
- 多 Agent：能说清顺序管道与真协作在成本/正确性上的取舍（给出耗时与成功率对比）。
- 评测：真实 LLM 报告含字段准确率 / 幻觉率 / 单次成本，可复现。
- 记忆：能说明压缩/召回相对"原样存档"在长会话上的增益。

> 与 §11、§12 的关系：§11 是"接线类"问题（已由设计文档 01-31 修复），§12 是"产品能力"缺口（23-31 已落地），
> 本节是**"深度"缺口**——三者互补，是项目从"能跑"走向"经得起社招深挖"的第三层。

## 17. 第二轮评审待办（agent 交互面 / 成本 / 安全 / 行为评测，设计文档 38-42）

> 状态背景：§16 的 6 项深度补充（设计文档 32/36/37/33/34/35）已全部实现合入，工程面（记忆/观测/评测/可靠性）达标。
> 本节为 2026-08-15 第二轮评审的新结论：**agent 最核心的"LLM ↔ 工具"交互面是全项目最薄**，且
> URL 安全/行为可靠性是"显式能力但无实证"（39 成本控制已暂缓，见 17.1）。**38（工具层升级）、40（MCP↔ReAct 打通）、41（URL 防护）、42（行为级评测）已于 2026-08-15 全部实现**
> （38：`ToolSpec`/schema 校验/超时/四类反馈回灌；40：`TOOLS`+`TOOL_SPECS` 唯一工具源 + `build_react_dispatcher` 多工具 + `create_server` 同源生成；41：`url_guard` 私网黑名单 + DNS rebinding + 重定向逐跳，两入口接入；42：`behavior_eval.py` 自恢复 + 检索命中进 `BenchmarkReport` 门禁；全量 **819 passed / 6 skipped**）；agent 交互面从"裸调用"升级为
> "契约 + 校验 + 回灌 + 超时 + 多工具 + 安全 + 行为量化"的现代 agent 交互层。
> 设计文档见 `doc/plan/issue_designs/38_tool_layer_design.md` ~ `42_behavior_eval_design.md`，索引与待办状态见 `issue_designs/README.md`。

| 文档 | 待办 | 代码证据 | 优先级 | 预计 |
|------|------|---------|--------|------|
| 38 工具层升级 | `ToolSpec`（schema/描述/超时）+ dispatch 校验 + 失败回灌 + 超时 + 四类反馈 | `tool_dispatcher.py:16-48` 裸注册无契约；`response_parser.py:102-108` 解析失败静默 `{}`；`react_agent.py:64-74` 仅捕获 ValueError、无超时 | 高 | ✅ 已实现（2026-08-15） |
| 39 预算成本挂钩 | `snapshot_cost/snapshot_tokens` + GapExecutor 补记真实增量 + `record_iteration` 真实成本 | `gap_executor.py:127` 固定 `0.01`；`budget.py:61-68` diminishing 依赖恒 0 的 `delta_tokens`；`api.py:517/546` 常数记账 | 中高 | ~~0.5 天~~ ⏸ 暂缓 |
| 40 MCP↔ReAct 打通 | `TOOLS`+`TOOL_SPECS` 唯一工具源 + `build_react_dispatcher()` + `create_server()` 同源 | `mcp_server/server.py:42-148` 8 工具与 `api.py:474-476` 单工具两条路径互不相干，描述双份 | 高 | ✅ 已实现（2026-08-15） |
| 41 URL 防护 | `url_guard.py` 私网/环回黑名单 + DNS rebinding 全量校验 + 重定向逐跳 + 统一超时/大小 | `api.py:480-489` `_react_web_extract` 任意 URL 直抓；`web_tools.py:19` `httpx.get(follow_redirects=True)` 无防 | 高 | ✅ 已实现（2026-08-15） |
| 42 行为级评测 | `behavior_eval.py`（RecoveryEvaluator + RetrievalEvaluator）+ `BenchmarkReport.behavior` 门禁 | `benchmark.py:92-141` 全结果字段，无行为指标；`retriever.py:19-42` hybrid/lexical 无对比数据 | 中高 | ✅ 已实现（2026-08-15） |

### 17.1 实施顺序与依赖

```
38（工具契约/回灌，✅ 2026-08-15 已实现）→ 41（URL 防护，✅ 2026-08-15 已实现）→ 40（MCP↔ReAct 打通，✅ 2026-08-15 已实现）→ 42（行为级评测，✅ 2026-08-15 已实现）
39（预算成本挂钩）已暂缓——用户 2026-08-15 决定成本控制先不考虑，独立无依赖，后续可恢复
```

- **38 前置**：设计文档 34 的 `_validate_schema`（JSON Schema 子集）可直接复用。
- **40 ✅ 依赖 38 + 41**：工具注册表统一（38）后 `build_react_dispatcher` 只需接线；web_extract 两入口（ReAct/MCP）统一过 41 的守卫。（2026-08-15 已实现）
- **42 ✅ 依赖 38 + 32**：RecoveryEvaluator 依赖 38 的回灌闭环（否则"自恢复"无从测起）；RetrievalEvaluator 依赖 32 的 retriever hybrid/lexical。（2026-08-15 已实现，第二轮 38-42 待办全部完成，仅 39 暂缓）
- **39（暂缓）**：若恢复，对齐 dota_helper tactical_loop P0-2 模式（先预检配额、分析后按真实 token 补记），无 LLM/mock 路径增量恒 0（回归安全）；前置仅 37（`total_cost_usd` 已有）。

### 17.2 验收口径

- **38 ✅**：schema 校验（缺必填/类型错/enum 越界 → `ToolArgumentError` 可读回灌）、解析失败不再静默 `{}`（`args_error`）、超时不悬挂、四类反馈互不混淆、恢复链路端到端（错参数 → 回灌 → 合法重试）——已实现，新增 15 条测试。
- **39**：GapExecutor 闭环后 `used_cost` ≈ 真实增量（非固定 0.01）；diminishing 触发/不触发；`cost_limit` 触顶 → `COST_LIMIT_REACHED`/`PARTIAL`；无 LLM 时行为与现状逐字节一致。
- **40 ✅**：`build_react_dispatcher().tool_count == len(TOOLS)`；`create_server()` 工具名集合 == `TOOLS` 键集合、描述同源无重复；mock LLM 多工具 ReAct 链路（web_search→web_extract→Final）端到端成功 + 自恢复（不存在工具→回灌→改调合法）——已实现，新增 13 条测试。
- **41 ✅**：私网/环回/保留段/畸形 scheme 全拒；DNS rebinding（多 IP 含内网）拒；重定向到内网拒（逐跳重校验、不跟随）；超时/大小读 `CollectorConfig`；公网采集行为不变（`block_private_urls=False` 可豁免）——已实现，新增 28 条测试。
- **42 ✅**：mock 下 `react_recovery_rate ≥ 0.9`、`retrieval_hit_hybrid ≥ retrieval_hit_lexical`；`to_dict` 含 `behavior` 字段；`_write_markdown`/`_write_csv` 输出行为评测节/行；既有评测门禁零破坏——已实现，新增 17 条测试。

> 与 §16 的关系：§16 补齐"每个模块往深一层"；本节补齐"**agent 之所以是 agent**"的交互层——工具契约、错误恢复、
> 安全边界、行为量化。全部完成后项目可回答"工具调用怎么保稳 / SSRF 怎么防 / RAG 收益怎么证明"三类面试深挖问题。
> （"成本上限是否真实"属设计文档 39，已暂缓，后续想做再恢复。）
