# AI Coding Agent 竞品分析 Agent — 架构设计文档

> 复用 `dota_helper` 的可插拔 Agent 框架与核心思想，落地一个**分析不同 AI Coding Agent（Claude Code / Cursor / Copilot / Codex / Windsurf 等）的竞品情报系统**。
> 代码目录与 `dota_helper` **完全隔离**，只做架构与思想的复用，不做代码级 import 耦合。

---

## 1. 项目定位

### 1.1 一句话定位

> 一个**企业级多 Agent 协作的 AI Coding Agent 竞品情报系统**：输入"竞品 A"或"对比 A vs B"，系统自主制定采集路线图、按信息缺口动态选源采集、跨来源交叉验证、沉淀记忆与技能、输出带置信度的对比报告。

### 1.2 目标场景

| 场景 | 示例输入 | 期望产出 |
|------|---------|---------|
| 单竞品画像 | "分析 Claude Code" | 功能矩阵、定价、性能评测（SWE-bench 等）、生态、用户口碑、版本节奏 |
| 竞品对比 | "对比 Cursor 和 Windsurf" | 维度对齐的对比表 + 差异洞察 + 适用建议 |
| 竞品监控 | "监控 Claude Code 本月更新" | 增量 diff：新功能、定价变化、口碑变化 |
| 决策支持 | "我们做 Agent 终端，定价怎么定？" | 竞品定价区间 + 缺口机会 + 数据证据链 |

### 1.3 成功指标（MVP 验收）

| 指标 | 目标值 | 度量方式 |
|------|--------|---------|
| 核心字段准确率（定价/功能/版本号） | ≥ 90% | `evaluation/accuracy_eval.py` 对已标注数据集 |
| 工具选择准确率 | ≥ 85% | `evaluation/strategy_eval.py` |
| 幻觉率（无证据支撑结论占比） | ≤ 5% | `evaluation/accuracy_eval.py` 证据链校验 |
| 端到端单竞品分析耗时 | ≤ 5 min | 基准报告 |
| 信息缺口自动关闭率 | ≥ 80% | 会话结束统计 |

---

## 2. 复用基线：`dota_helper` 架构要点

`dota_helper` 的核心不是"Dota 2"，而是一套**垂直领域可插拔的自主执行 Agent 框架**。本次竞品分析 Agent 复用的思想清单：

| # | dota_helper 核心思想 | 本次复用的方式 |
|---|----------------------|---------------|
| 1 | **领域解耦**：框架层（编排/引擎/记忆/可观测）与领域层（数据源/分析器/工具）严格隔离，`interfaces/` 用 Protocol 定义契约 | 框架层整体迁移，只替换领域层 |
| 2 | **双循环编排**：战略循环定策略（先规划），战术循环按策略迭代执行（后执行） | 战略循环生成**信息缺口清单**，战术循环逐个缺口闭环 |
| 3 | **可控执行**：迭代预算 + Token 预算 + 边际递减检测 + Stop Hook 可验证终止 | `BudgetController` 四条件终止 |
| 4 | **四层记忆**：会话归档 / 持久笔记 / 技能沉淀 / 进化记录 | 四层记忆 + `SkillStore` 自进化 |
| 5 | **能力开放**：50+ 工具封装为标准 MCP Server | 竞品采集工具封装为 MCP Server |
| 6 | **可观测性**：结构化日志 + Tracer Span + 指标采集 | 全部保留 |
| 7 | **安全护栏**：SecretVault 凭据池 / ToolGuard 参数校验+限速 / 提示注入防护 / 错误分类熔断 | 全部保留 |
| 8 | **RAG 知识注入**：RagEngine 将领域知识注入上下文 | 竞品文档/Changelog 向量化 |
| 9 | **并行子代理**：ParallelRunner + SubAgent 并行阶段分析 | 竞品维度并行采集分析 |
| 10 | **Facade 门面**：`PostMatchReviewAPI` 作为外部唯一入口 | `CompetitorAnalysisAPI` |

---

## 3. 目录规划（与 dota_helper 隔离）

```
D:\trae_projects\first-agent\
├── dota_helper\                  # 既有项目（不动，作为参照）
├── competitor_agent\             # 新项目：竞品分析 Agent（本设计文档的目标落地目录）
│   ├── __init__.py               # 导出 CompetitorAnalysisAPI 等
│   ├── pyproject.toml            # 独立包，name=competitor_agent
│   ├── requirements.txt
│   ├── README.md
│   ├── config\
│   │   └── review_config.yaml    # 预算/维度/终止阈值配置
│   │
│   ├── domain_types\             # 领域数据模型（对标 dota_helper/domain_types）
│   │   ├── competitor.py         # Competitor, CompetitorProfile
│   │   ├── info_gap.py           # InfoGap, GapStatus（信息缺口驱动核心）
│   │   ├── strategy.py           # CompetitorStrategy, DimensionBudget
│   │   ├── observation.py        # Observation, SourceEvidence
│   │   ├── report.py             # CompetitorReport, ComparisonReport
│   │   ├── events.py             # ProgressEvent（SSE 复用）
│   │   └── enums.py              # DimensionType, TerminalState
│   │
│   ├── interfaces\               # 契约层（Protocol，对标 dota_helper/interfaces）
│   │   ├── collector.py          # ICompetitorDataCollector
│   │   ├── analyzer.py           # ICompetitorAnalyzer
│   │   ├── planner.py            # IStrategicPlanner
│   │   ├── memory.py             # IFourLayerMemory
│   │   ├── verifier.py           # IStopVerifier
│   │   ├── reporter.py           # IReportBuilder
│   │   └── data_source.py        # ICompetitorDataSource
│   │
│   ├── core\                     # 框架内核（从 dota_helper 迁移/抽象，通用化）
│   │   ├── strategic_loop.py     # 战略循环：任务→信息缺口清单
│   │   ├── tactical_loop.py      # 战术循环：单个缺口闭环
│   │   ├── budget.py             # IterationBudget（预算+边际递减）
│   │   ├── budget_controller.py  # BudgetController 四条件终止
│   │   ├── stop_verifier.py      # 停止验证器
│   │   ├── report_builder.py     # 报告构建
│   │   ├── markdown_renderer.py  # Markdown 渲染
│   │   ├── parallel_runner.py    # 并行子代理
│   │   └── subagent.py           # SubAgent
│   │
│   ├── agent\                    # ReAct 交互层（对标 dota_helper/agent）
│   │   ├── react_agent.py        # CompetitorReActAgent
│   │   ├── react_loop.py         # ReAct 循环（含错误分类/熔断/checkpoint）
│   │   ├── response_parser.py
│   │   ├── tool_dispatcher.py
│   │   ├── tool_guard.py         # 参数校验/敏感守卫/限速/审计
│   │   ├── injection_guard.py    # 提示注入防护
│   │   ├── error_classifier.py
│   │   ├── session_manager.py
│   │   └── prompts\
│   │       ├── react_system.py
│   │       └── strategic_planner.py
│   │
│   ├── collector\                # 领域层：竞品数据采集（对标 data_source/）
│   │   ├── web_extractor.py      # 官网/文档页抓取（BeautifulSoup/Playwright）
│   │   ├── github_source.py      # GitHub API（stars/releases/commits）
│   │   ├── pricing_source.py     # 定价页提取
│   │   ├── benchmark_source.py   # SWE-bench / Aider 榜单抓取
│   │   ├── review_source.py      # 用户评价（HN/Reddit/商店）
│   │   └── source_selector.py    # 信息缺口→数据源候选排序（降级策略）
│   │
│   ├── analyzers\                # 领域层：维度分析器（对标 analyzers/）
│   │   ├── base.py               # BaseCompetitorAnalyzer
│   │   ├── feature_analyzer.py   # 功能矩阵
│   │   ├── pricing_analyzer.py   # 定价/版本
│   │   ├── performance_analyzer.py  # 性能评测
│   │   ├── ecosystem_analyzer.py # 生态/集成/平台支持
│   │   ├── sentiment_analyzer.py # 用户口碑/舆情
│   │   ├── roadmap_analyzer.py   # 版本节奏/路线图
│   │   └── fallback_analyzer.py  # LLM 不可用时的规则降级
│   │
│   ├── knowledge_base\           # 竞品知识库（RAG）
│   │   ├── ingester.py           # 文档/Changelog 向量化
│   │   ├── retriever.py          # 检索 + 重排序
│   │   └── competitor_store.py   # 竞品维度向量索引
│   │
│   ├── memory\                   # 四层记忆（对标 memory/）
│   │   ├── four_layer_memory.py
│   │   ├── session_archive.py    # L1 会话归档
│   │   ├── persistent_notes.py   # L2 持久笔记
│   │   ├── skill_store.py        # L3 技能沉淀（自进化）
│   │   └── evolution_memory.py   # L4 策略进化记录
│   │
│   ├── team\                     # 多 Agent 协作（面试加分项）
│   │   ├── collector_agent.py
│   │   ├── analyzer_agent.py
│   │   ├── validator_agent.py
│   │   └── reporter_agent.py
│   │
│   ├── evaluation\               # 自动评测体系
│   │   ├── accuracy_eval.py      # 字段准确率/幻觉率
│   │   ├── strategy_eval.py      # 工具选择准确率/成本效率
│   │   └── benchmark.py          # 用例集基准
│   │
│   ├── mcp_server\               # MCP Server：竞品采集工具对外开放
│   │   ├── server.py             # FastMCP("Competitor Intelligence Agent")
│   │   └── tools\
│   │       ├── web_tools.py
│   │       ├── github_tools.py
│   │       └── review_tools.py
│   │
│   ├── observability\            # 可观测性（对标，可少量适配）
│   │   ├── logger.py
│   │   ├── tracer.py
│   │   └── metrics.py
│   │
│   ├── secret_vault.py           # 凭据池（直接复用 dota_helper 的 SecretVault 设计）
│   │
│   ├── facade\
│   │   └── api.py                # CompetitorAnalysisAPI（外部唯一入口）
│   │
│   ├── web_app.py                # Web / SSE 可视化（对标 web_app.py）
│   │
│   └── tests\
│       ├── unit\
│       ├── integration\
│       └── evaluation\           # 评测用例集
└── doc\                          # 本文档所在目录
```

**隔离规则**：
1. 新代码全部位于 `competitor_agent/` 下，包名 `competitor_agent`，不 import 任何 `dota_helper.*`。
2. 需要复用的**通用能力**（SecretVault、Tracer、预算、ReAct、护栏）以"参考实现 → 抽象复制 → 通用化"方式迁入 `competitor_agent/core/`，保持双向零耦合。
3. `pyproject.toml` 独立；数据目录独立（`~/.competitor_agent/`）；`chromadb` 向量库独立目录。

---

## 4. 总体架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                    外部调用方（Web / CLI / MCP Client）          │
├─────────────────────────────────────────────────────────────┤
│  Facade: CompetitorAnalysisAPI  （唯一入口，任务状态/历史/中断） │
├─────────────────────────────────────────────────────────────┤
│  编排层 core/                                                 │
│   StrategicLoop ──► InfoGap 清单 ──► TacticalLoop（逐缺口）    │
│        │                                  │                  │
│        ▼                                  ▼                  │
│  BudgetController ◄── 四条件终止    ReActLoop（Thought→Action） │
│  StopVerifier                        │  ToolDispatcher → MCP  │
│  ReportBuilder ◄──────────── 维度结果汇总                      │
├─────────────────────────────────────────────────────────────┤
│  框架支撑                                                   │
│  memory/ 四层记忆    knowledge_base/ RAG    agent/ 护栏+注入防 │
│  observability/ 日志+Trace+指标    secret_vault/ 凭据池       │
├─────────────────────────────────────────────────────────────┤
│  领域层                                                     │
│  collector/ 数据源（web/github/pricing/benchmark/review）      │
│  analyzers/ 维度分析器（feature/pricing/perf/eco/sentiment）   │
│  mcp_server/ 工具集     team/ 多Agent    evaluation/ 评测     │
└─────────────────────────────────────────────────────────────┘
```

**决策原则**：LLM 驱动优先，规则/缓存自动降级（与 dota_helper 一致）。LLM 不可用时走 `fallback_analyzer` + 缓存，系统不崩溃。

---

## 5. 核心设计

### 5.1 信息缺口驱动（InfoGap-Driven）— 全系统的"Agent 味"核心

不采用"按固定顺序爬 5 个网站"的静态 Pipeline。所有行为由**信息缺口清单**驱动：

```python
# domain_types/info_gap.py
class GapStatus(Enum):
    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"

class InfoGap:
    """信息缺口：Agent 自主决策的驱动力"""
    field: str                 # 缺什么：pricing / features / performance / ...
    priority: int              # 优先级 1-10
    confidence: float          # 当前置信度 0-1
    sources_tried: List[str]   # 已尝试的数据源
    status: GapStatus
    evidence: List[SourceEvidence]  # 证据链（防幻觉）
```

**战略循环**产出缺口清单；**战术循环**针对单个缺口，自主决定用哪个工具、什么参数、失败后如何降级。

### 5.2 双循环编排

```
StrategicLoop.evaluate(task):
    1. 解析目标竞品 + 维度集合（可 LLM 解析）
    2. 结合记忆（该竞品历史经验/技能）生成 InfoGap 清单（含优先级/初始置信度）
    3. 分配维度预算（对标 match_type → budget_allocation）
    4. 产出 CompetitorStrategy（缺口清单 + 预算 + 终止阈值）

TacticalLoop.execute(gap, context):
    1. 预算 consume（迭代 + Token + 边际递减）
    2. SourceSelector 给候选数据源排序（含降级链：官网→缓存→替代源→Playwright）
    3. 调用 collector 采集 → Observation
    4. ReActLoop 或 analyzer 分析 → 更新缺口置信度
    5. validate_result → 通过则关闭缺口，未通过生成 feedback 迭代
    6. Reflection：结果与历史/记忆冲突时触发交叉验证
```

### 5.3 BudgetController — 四条件终止

```python
class BudgetController:
    def __init__(self, max_iterations=10, cost_limit=1.0):
        ...

    def should_stop(self, gaps) -> StopDecision:
        # 1) 所有缺口关闭
        if all(g.status == CLOSED):   return Stop(stop=True, reason="all_gaps_closed")
        # 2) 迭代预算耗尽
        if self.iteration_count >= self.max_iterations:
                                      return Stop(stop=True, reason="iteration_budget_exhausted")
        # 3) 成本上限（美元）
        if self.total_cost >= self.cost_limit:
                                      return Stop(stop=True, reason="cost_limit_reached")
        # 4) 核心信息满足度（优先级≥8 的缺口 confidence≥0.8）
        core = [g for g in gaps if g.priority >= 8]
        if core and all(g.confidence >= 0.8 for g in core):
                                      return Stop(stop=True, reason="core_satisfaction_reached")
        return Stop(stop=False)

    def on_stop(self, gaps) -> FinalReport:
        # 输出 completed/pending/confidence，未关闭缺口给出说明
```

### 5.4 ReAct Agent + MCP 工具集

- `CompetitorReActAgent`：LLM 驱动 Thought→Action→Observation 流式循环（SSE 9 事件类型，复用 dota_helper 契约）。
- 工具经 `ToolDispatcher` 分发到 MCP Server；工具描述动态注入 System Prompt。
- 工具护栏（ToolGuard）：参数校验 / 敏感守卫 / 速率限制 / 审计日志，全部保留。
- 错误分类（ErrorClassifier）：RECOVERABLE 重试 / DEGRADABLE 跳过 / TERMINAL 终止 / UNKNOWN 降级。
- 提示注入防护：用户输入净化 + Observation `<observation>` 封装 + 输出校验三层防御。

### 5.5 四层记忆 + 自进化

| 层级 | 载体 | 竞品分析场景示例 |
|------|------|-----------------|
| L1 会话归档 | `session_archive.db` | 每次分析的原始采集证据与结论 |
| L2 持久笔记 | `persistent_notes.json` | "Cursor 定价页是 JS 渲染，需 Playwright" |
| L3 技能沉淀 | `skill_store` | "分析 Claude Code pricing 时优先查 docs/pricing，其次官网"，下次自动优先 |
| L4 进化记录 | `evolution_memory` | 统计各数据源成功率，SPA 站点自动升级为 Playwright 优先 |

```python
def enrich_prompt(prompt, task):
    skills = memory.skills.retrieve(task.competitor_name)
    failures = memory.long_term.get_failures(task.competitor_name)
    return f"{prompt}\n\n【已沉淀技能】{skills}\n【历史失败教训】{failures}"
```

### 5.6 RAG 竞品知识库

- `ingester`：竞品官方文档 / Changelog / 评测报告 → 分块 → embedding → 向量库（chromadb，兼容 dota_helper 已用栈）。
- `retriever`：混合检索（向量 + 关键词）→ 重排序。
- `competitor_store`：按竞品 × 维度建索引，支撑"这个竞品支持哪些 IDE？"类问答。
- 作为 ReAct Agent 的 RAG 插件注入（对标 RagPlugin）。

### 5.7 多 Agent 协作（team/）

```
CollectorAgent → AnalyzerAgent → ValidatorAgent → ReporterAgent
```

- **通信协议**：结构化 `Artifact`（任务 / 证据集 / 结论集 / 草稿报告），通过消息总线传递。
- **ValidatorAgent**：对结论做事实校验（引用证据、与历史冲突检测），冲突则打回 Analyzer 交叉验证。
- 3-4 个 Agent 足够，重点展示通信协议与任务分发。

### 5.8 评测体系（evaluation/）

```python
class AgentEvaluator:
    def evaluate_extraction(self, prediction, ground_truth) -> Metrics:
        return {"pricing_accuracy": 0.94, "feature_f1": 0.91, "hallucination_rate": 0.03}
    def evaluate_strategy(self, strategy, outcome) -> Metrics:
        return {"tool_selection_accuracy": 0.89, "cost_efficiency": 0.85}
    def run_benchmark(self, test_cases) -> Report: ...
```

- `benchmark.py`：内置 10-20 个已标注竞品用例（定价/版本/功能等 ground truth），CI 可跑。
- 数据文件：`tests/evaluation/fixtures/*.json`。

### 5.9 可观测性

- `logger.py`：结构化日志（每次工具调用输入/输出、LLM 耗时、异常堆栈）。
- `tracer.py`：Span 追踪（strategic / tactical / llm.chat / collector.*），TUI/控制台输出，Langfuse 可选。
- `metrics.py`：计数器（llm.calls、collector.success、gap.closed 等）。
- SecretVault 审计：`get_access_log()` 记录每次凭据读取。

---

## 6. 数据模型（domain_types 核心）

```python
@dataclass
class Competitor:
    name: str                     # 规范名（小写+连字符）
    aliases: List[str]            # 别名（cursor → anysphere/cursor）
    category: str                 # ai_coding_agent
    official_links: Dict[str, str]# docs/home/changelog/pricing

@dataclass
class CompetitorStrategy:
    competitor: Competitor
    gaps: List[InfoGap]           # 信息缺口清单
    budget_allocation: Dict[str, int]   # dimension -> iterations
    terminal_thresholds: Dict[str, float] # 终止阈值

@dataclass
class Observation:
    gap_field: str
    source: str
    raw_text: str
    extracted: Dict[str, Any]
    evidence: SourceEvidence      # url/时间/可信度
    status: str                   # ok / blocked / degraded

@dataclass
class CompetitorReport:
    competitor: Competitor
    dimension_results: List[DimensionResult]   # 每维度结论+置信度+证据
    overall_score: float
    overall_confidence: float
    gaps_pending: List[InfoGap]   # 未关闭缺口及原因
    markdown_report: str
    terminal_state: str
```

---

## 7. 关键流程（时序）

```
User ──► CompetitorAnalysisAPI.analyze("Claude Code")
            │
            ▼
        StrategicLoop
            │ 1. 解析竞品与维度
            │ 2. 记忆注入（技能/教训）
            │ 3. 生成 InfoGap 清单 + 预算
            ▼
        TacticalLoop × N（每缺口，可并行）
            │ consume budget → SourceSelector → collector.collect()
            │   ↓
            │ analyzer.analyze(obs, gap) → 置信度更新
            │   ↓
            │ validate_result ? 关闭缺口 : 生成 feedback 再迭代
            │   ↓
            │ Reflection（冲突→交叉验证）
            ▼
        BudgetController.should_stop(gaps)
            ▼
        ValidatorAgent 校验 → ReportBuilder 汇总
            ▼
        CompetitorReport（含 markdown + 置信度 + 未关闭缺口）
```

并行模式：高优先级独立维度（pricing / features / performance）走 `ParallelRunner` + `SubAgent` 并行采集分析。

---

## 8. 复用清单（迁移策略）

| 能力 | 处置 | 说明 |
|------|------|------|
| SecretVault + CredentialError | **复制 + 保留** | 无 dota_helper 依赖，可直接拷贝，改日志前缀 |
| IterationBudget / BudgetController | **复制 + 通用化** | 预算与领域无关，直接迁移到 core/budget.py |
| Tracer / Logger / Metrics | **复制 + 适配** | 弱依赖领域，抽取到 core/observability |
| ReActLoop / ResponseParser / ErrorClassifier | **复制 + 去 Dota 字段** | 去掉 match_id 自动补全，改为 gap 上下文补全 |
| ToolGuard / InjectionGuard | **复制** | 纯通用，原样迁移 |
| SessionManager / Checkpoint | **复制** | 通用 |
| FourLayerMemory / SkillStore | **复制 + 领域化** | 归档键从 match_id → competitor_name |
| RagEngine / RagPlugin | **复制 + 领域化** | 索引 schema 换竞品维度 |
| StrategicLoop / TacticalLoop | **重写领域逻辑** | 保持双循环骨架，策略内容换成 InfoGap |
| Collectors / Analyzers | **全新领域实现** | 竞品采集与 Dota 完全无关 |
| MCP Server / tools | **重写工具集** | FastMCP 骨架复用，工具换成 web/github/pricing/benchmark/review |
| Facade API / Web App | **重写门面** | 入口方法从 review() → analyze() |

**注意事项**：迁移时同步带上 `dota_helper` 已验证的测试模式（`tests/unit/` + respx mock + pytest-asyncio），新项目落地时直接为 core 模块补齐单元测试，避免重蹈 bugs.md P0 #1「无单元测试」覆辙。

---

## 9. 里程碑规划

### M1 骨架（Week 1）：跑通"官网采集 → 维度分析 → 报告"
- 目录骨架 + pyproject + Facade API + Strategic/TacticalLoop + WebExtractor
- core 层单元测试（预算/循环/报告）
- 验收：输入"分析 Claude Code"，输出含功能/定价/版本的 Markdown 报告

### M2 记忆与自进化（Week 2）
- 四层记忆 + SkillStore + RagEngine（竞品文档向量化）
- 记忆注入 prompt + 技能自动沉淀
- 验收：第二次分析同一竞品时自动优先命中记忆源

### M3 多 Agent + 评测（Week 3）
- Collector/Analyzer/Validator/Reporter 协作
- evaluation/ 基准（10+ 标注用例，跑出字段准确率/幻觉率）
- 验收：benchmark 报告输出量化指标

### M4 工程化（Week 4）
- Web SSE 可视化 + MCP Server 对外开放 + CI（pytest + ruff）
- 断点续跑 / 中断 / 历史查询
- 验收：全部单测通过，MCP Client 可调用采集工具

---

## 10. 面试话术映射（可选参考）

- "我的系统不是按剧本演的爬虫，是按目标演的：接到任务先建信息缺口清单，每个缺口都是自主决策触发器。"
- "四层记忆：短期管当前任务、长期存历史结论、技能沉淀提取技巧、进化层统计数据源成功率自动调整工具选择。"
- "四层终止机制，最妙的是核心信息满足度——次要缺口没关，只要定价/功能置信度超 80% 就主动停，不为 5% 信息烧 50% 预算。"
- "框架层与领域层严格解耦，Dota 复盘到竞品情报只换了数据源、分析器和知识库，内核零改动。"
