# 赛后复盘 Agent 架构设计文档

> **版本**: v1.8
> **创建时间**: 2026-07-15
> **最新修订**: 2026-07-27
> **定位**: 赛后复盘 Agent 的顶层架构设计蓝图
> **状态**: 实施中（阶段 1-9 已完成；阶段 10 ReAct Agent Chat 待实施）

## 文档说明

本文档是赛后复盘 Agent 的**完整独立架构设计**，作为上层统领蓝图指导后续实现。

- 本文档聚焦：架构理念、系统分层、核心机制、组件职责、数据流、接口契约
- 详细实现方案见 `docs/superpowers/plans/` 下的对应文档
- 历史架构演进记录见 `docs/architecture_upgrade/ARCHITECTURE_ANALYSIS.md`

> **v1.1 重要变更**: 复盘 Agent 重构为 `dota_helper/` 独立顶级包，
> 所有组件（LLM 客户端、记忆、技能、缓存、可观测性、Prompt）均在包内自包含实现，
> 不再依赖 `core/`、`analyzers/`、`skills/`、`memory/`、`utils/` 等已有目录的代码。
> 详见 §3.3 与 §9。

### 设计理念来源

| 来源 | 核心贡献 |
|------|---------|
| **Hermes Agent** (Nous Research) | 自我进化引擎、四层记忆架构、技能自动沉淀、子代理并行 |
| **Loop Agent** (Anthropic + Google ADK) | 迭代式自主执行、Stop Hooks 终止验证、进度持久化、收敛检测 |
| **Claude Code** (Anthropic) | Token 预算控制与边际递减检测、Dream/Recap 记忆整合、Batch 并行子代理、QueryEngine 生命周期 |

---

## 目录

- [一、产品定位与目标](#一产品定位与目标)
- [二、设计原则](#二设计原则)
- [三、系统架构总览](#三系统架构总览)
- [四、核心机制设计](#四核心机制设计)
  - [4.1 双循环分析引擎](#41-双循环分析引擎)
  - [4.2 迭代预算与智能终止](#42-迭代预算与智能终止)
  - [4.3 上下文管理与压缩](#43-上下文管理与压缩)
  - [4.4 四层记忆系统](#44-四层记忆系统)
  - [4.5 技能自动沉淀与进化](#45-技能自动沉淀与进化)
  - [4.6 并行子代理编排](#46-并行子代理编排)
- [五、核心流程](#五核心流程)
- [六、组件职责清单](#六组件职责清单)
- [七、接口契约](#七接口契约)
- [八、数据模型](#八数据模型)
- [九、与现有系统的集成](#九与现有系统的集成)
- [十、配置体系](#十配置体系)
- [十一、可观测性](#十一可观测性)
- [十二、错误处理与降级](#十二错误处理与降级)
- [十三、实施路线图](#十三实施路线图)
- [附录](#附录)

---

## 一、产品定位与目标

### 1.1 核心定位

赛后复盘 Agent 是 dota_helper 从"查询工具"升级为"自主执行的 Agent 产品"的**旗舰功能**。

```
传统模式: 用户提问 → Agent 查表/调 API → 返回答案（被动、单轮、无记忆）
复盘模式: 用户提供 match_id → Agent 自主多步分析 → 输出结构化复盘报告 → 从对局中学习
```

### 1.2 核心目标

| 目标 | 描述 | 衡量标准 |
|------|------|---------|
| **自主分析** | 多阶段自主执行分析，无需人工干预 | 单次复盘全流程自动化率 > 95% |
| **深度洞察** | 不止于数据罗列，提供根因分析和可执行建议 | 每条建议有数据支撑，置信度 >= 0.6 |
| **持续进化** | 从每次复盘中提取经验，改进分析能力 | 分析质量评分随复盘次数递增 |
| **可靠终止** | 分析完整且质量达标后才输出，不提前宣布完成 | Stop Hook 验证通过率 > 90% |

### 1.3 与查询工具的本质区别

| 维度 | 查询工具 | 赛后复盘 Agent |
|------|---------|---------------|
| 执行模式 | 单轮响应 | 多步自主执行（Loop Agent） |
| 决策能力 | 固定流程 | 自主判断分析重点和深度 |
| 学习能力 | 无记忆 | 四层记忆 + 技能自动沉淀 |
| 终止机制 | 返回即结束 | Stop Hooks 验证后才终止 |
| 任务粒度 | 秒级响应 | 分钟级深度分析 |

---

## 二、设计原则

### 2.1 架构原则

| 原则 | 说明 | 来源 |
|------|------|------|
| **Harness 优先于模型** | Agent 失败的原因通常不是模型不够强，而是执行框架设计不当 | Anthropic |
| **进度持久化到文件** | 状态存储在文件系统和结构化数据中，而非仅依赖对话历史 | Ralph Wiggum Loop |
| **明确终止条件** | 用可验证的脚本定义"完成"的含义，而非依赖模型自判 | Anthropic Stop Hooks |
| **有损压缩** | 上下文管理是有损的艺术，关键是保护什么、丢弃什么 | Hermes ContextCompressor |
| **运行越久越强** | 每次复盘都应产生可复用的经验，形成正向飞轮 | Hermes GEPA |

### 2.2 工程原则

| 原则 | 说明 |
|------|------|
| **接口 + 策略模式** | 核心组件通过接口定义，具体实现可替换（LLM 驱动优先，规则驱动降级） |
| **依赖注入** | 所有组件通过构造函数注入依赖，便于测试和替换 |
| **Langfuse 可选** | 可观测性接入 Langfuse，但系统必须在无 Langfuse 时正常运行 |
| **Type Hints** | 所有方法必须包含 type-hint 格式的返回类型标注 |

---

## 三、系统架构总览

### 3.1 分层架构

```
┌───────────────────────────────────────────────────────────────────────┐
│                          接入层 (Gateway)                             │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────────┐  │
│  │  Web API    │  │  Frontend    │  │  CLI / 脚本入口              │  │
│  │  /api/chat  │  │  Vue 3 + TS  │  │  python -m review            │  │
│  │  /api/review│  │  Chat UI     │  │                              │  │
│  └──────┬──────┘  └──────┬───────┘  └──────────────┬──────────────┘  │
├─────────┼────────────────┼─────────────────────────┼─────────────────┤
│         │           编排层 (Orchestration)          │                 │
│  ┌──────▼──────────────────────────────────────────▼──────────────┐  │
│  │  ReviewOrchestrator          │          ReAct Agent            │  │
│  │  ┌────────────┐ ┌──────────────┐  ┌────────────────────────┐  │  │
│  │  │ 战略循环    │ │ 战术循环      │  │ Thought→Action→Observ  │  │  │
│  │  │ Strategic  │ │ Tactical     │  │ → Final Answer          │  │  │
│  │  │ Loop       │ │ Loop         │  │ (MCP 工具调用)          │  │  │
│  │  └────────────┘ └──────────────┘  └────────────────────────┘  │  │
│  └───────────────────────────┬────────────────────────────────────┘  │
├──────────────────────────────┼───────────────────────────────────────┤
│                         核心引擎层 (Engine)                          │
│  ┌───────────┐ ┌──────────────┐ ┌──────────────┐ ┌───────────────┐  │
│  │ 迭代预算   │ │ 停止验证器    │ │ 上下文压缩器  │ │ 提示词构建器   │  │
│  │ Budget    │ │ StopVerifier │ │ Compressor   │ │ PromptBuilder │  │
│  │ Controller│ │              │ │              │ │               │  │
│  └───────────┘ └──────────────┘ └──────────────┘ └───────────────┘  │
├──────────────────────────────────────────────────────────────────────┤
│                         分析能力层 (Analysis)                        │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌─────────┐ │
│  │ 对线期    │ │ 团战执行   │ │ 经济效率  │ │ 决策质量   │ │ 视野    │ │
│  │ Laning   │ │ Teamfight │ │ Economy  │ │ Decision  │ │ Vision  │ │
│  │ Analyzer │ │ Analyzer  │ │ Analyzer │ │ Analyzer  │ │ Analyzer│ │
│  └──────────┘ └───────────┘ └──────────┘ └───────────┘ └─────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ Skill 驱动扩展层 (Layer C)                                   │    │
│  │ SkillDrivenAnalyzer ← YAML 技能定义 + SkillDrivenPromptBuilder│   │
│  │ 内置: roshan_timing / ward_efficiency / late_game_decisions  │    │
│  └──────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────┤
│                         基础设施层 (Infrastructure)                   │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌─────────┐ │
│  │ LLM      │ │ OpenDota  │ │ 记忆系统  │ │ 技能注册表 │ │ Trace   │ │
│  │ Client   │ │ API       │ │ Memory   │ │ Skill     │ │ Langfuse│ │
│  │          │ │ Client    │ │          │ │ Registry  │ │         │ │
│  └──────────┘ └───────────┘ └──────────┘ └───────────┘ └─────────┘ │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ MCP Server 工具层 (53 tools)                                  │    │
│  │ ┌────────┐ ┌──────┐ ┌────────┐ ┌──────┐ ┌────────┐          │    │
│  │ │match   │ │hero  │ │player  │ │team  │ │ward    │ ...      │    │
│  │ │6 tools │ │12    │ │7 tools │ │9     │ │5 tools │          │    │
│  │ └────────┘ └──────┘ └────────┘ └──────┘ └────────┘          │    │
│  │ helpers: AsyncOpenDotaClient / hero_names / map_config / RAG  │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心数据流

```
match_id
  │
  ▼
[数据获取] ─── OpenDota API ───▶ 结构化比赛数据 (MatchData)
  │
  ▼
[战略循环] ─── 全局态势评估 ───▶ 分析策略 (AnalysisStrategy)
  │                                ├─ 分析重点排序
  │                                ├─ 各阶段迭代预算分配
  │                                └─ 预期分析深度
  ▼
[战术循环] ─── 多阶段分析（可并行） ───▶ 阶段分析结果 (PhaseResult)
  │           ├─ 对线期分析                ├─ 分析结论
  │           ├─ 团战分析                  ├─ 数据支撑
  │           ├─ 经济分析                  ├─ 置信度
  │           ├─ 决策分析                  └─ 迭代次数
  │           └─ 视野分析
  │
  ▼
[停止验证] ─── Stop Hooks ───▶ 验证结果 (VerificationResult)
  │                              ├─ 通过 → 进入报告生成
  │                              └─ 未通过 → 返回战术循环补充分析
  ▼
[报告生成] ─── 聚合 + 格式化 ───▶ 复盘报告 (ReviewReport)
  │
  ▼
[后台自我审查] ─── 异步 ───▶ 质量评估 + 经验提取 + 技能沉淀
  │
  ▼
[输出] ─── Markdown 报告 + 前端展示 + 记忆持久化
```

### 3.3 模块目录结构（自包含独立包 v1.1）

> **设计原则**: 复盘 Agent 作为 `dota_helper/` 下的**独立顶级包** `dota_helper/`,
> 所有 LLM 客户端、记忆、技能、缓存、可观测性、Prompt 模板均在包内自包含实现,
> 不依赖 `core/`、`analyzers/`、`skills/`、`memory/`、`utils/` 等已有目录的代码。
> 外部仅通过 `dota_helper.facade` 暴露的公共 API 与之交互。

```
dota_helper/
└── dota_helper/                       # 独立顶级包,与既有代码零耦合
    ├── __init__.py                         # 公共 API 导出
    ├── README.md                           # 模块说明
    ├── pyproject.toml                      # 独立依赖声明(可选,见附录 D)
    │
    ├── interfaces/                         # ── 接口契约层(Protocol/ABC)
    │   ├── __init__.py
    │   ├── orchestrator.py                 # IReviewOrchestrator
    │   ├── analyzer.py                     # IReviewAnalyzer
    │   ├── budget.py                       # IIterationBudget
    │   ├── verifier.py                     # IStopVerifier
    │   ├── compressor.py                   # IContextCompressor
    │   ├── memory.py                       # IFourLayerMemory / ILevelN
    │   ├── llm.py                          # ILLMClient
    │   ├── data_source.py                  # IMatchDataSource
    │   ├── skill.py                        # ISkillStore / IAnalysisSkillStore
    │   └── tracer.py                       # ITracer
    │
    ├── domain_types/                       # ── 数据模型/枚举/状态（v1.4: 重命名避免与标准库冲突）
    │   ├── __init__.py
    │   ├── enums.py                        # BudgetDecision / TerminalState / ContinueState / MatchType
    │   ├── match_data.py                   # MatchData / PlayerData / PickBan / LaneData / TeamfightData
    │   ├── analysis.py                     # AnalysisResult / Conclusion / AnalysisContext
    │   ├── report.py                       # ReviewReport / MatchSummary
    │   ├── state.py                        # ReviewAgentState
    │   ├── strategy.py                     # AnalysisStrategy
    │   └── events.py                       # ProgressEvent / VerificationResult
    │
    ├── orchestrator/                       # ── 编排层
    │   ├── __init__.py
    │   ├── review_orchestrator.py          # ReviewOrchestrator(主入口)
    │   ├── strategic_loop.py               # StrategicLoop
    │   ├── tactical_loop.py                # TacticalLoop
    │   ├── background_reviewer.py          # BackgroundReviewer
    │   └── runtime.py                      # Runtime(依赖注入容器,组装所有组件)
    │
    ├── engines/                            # ── 核心引擎层
    │   ├── __init__.py
    │   ├── budget.py                       # IterationBudget(令牌桶 + 边际递减)
    │   ├── stop_verifier.py                # StopVerifier(三段验证)
    │   ├── compressor.py                   # ContextCompressor(修剪+保护+LLM 摘要)
    │   ├── prompt_builder.py               # PromptBuilder(Stable/Context/Volatile 三层)
    │   └── data_formatter.py               # DataFormatter(YAML 声明驱动的数据格式化,层 B)
    │
    ├── analyzers/                          # ── 分析能力层
    │   ├── __init__.py
    │   ├── base.py                         # BaseLLMReviewAnalyzer / BaseRuleReviewAnalyzer
    │   ├── laning_analyzer.py              # 对线期分析
    │   ├── teamfight_analyzer.py           # 团战分析
    │   ├── economy_analyzer.py             # 经济分析
    │   ├── decision_analyzer.py            # 关键决策点分析
    │   ├── vision_analyzer.py              # 视野分析
    │   ├── fallback_analyzer.py            # 规则驱动降级(LLM 不可用时)
    │   └── skill_driven.py                 # SkillDrivenAnalyzer + SkillDrivenPromptBuilder（层 C）
    │
    ├── data_source/                        # ── 数据源层(独立 OpenDota 客户端)
    │   ├── __init__.py
    │   ├── opendota_client.py              # OpenDotaClient(独立 HTTP 客户端)
    │   ├── match_fetcher.py                # MatchFetcher(数据获取+结构化)
    │   ├── data_validator.py               # 数据完整性校验
    │   └── cache.py                        # 比赛数据本地缓存
    │
    ├── llm/                                # ── LLM 抽象层(独立实现)
    │   ├── __init__.py
    │   ├── client.py                       # LLMClient(可替换实现)
    │   ├── prompt_manager.py               # PromptManager(版本管理)
    │   └── token_counter.py                # TokenCounter
    │
    ├── memory/                             # ── 记忆系统(独立四层实现)
    │   ├── __init__.py
    │   ├── four_layer_memory.py            # FourLayerMemory(统一入口)
    │   ├── session_archive.py              # Level 1: SessionArchive(SQLite)
    │   ├── persistent_notes.py             # Level 2: PersistentNotes(JSON + 倒排索引)
    │   ├── skill_store.py                  # Level 3: SkillStore(SKILL.md 文件)
    │   └── dream_recap.py                  # DreamRecap(Claude Code 整合模式)
    │
    ├── parallel/                           # ── 并行编排
    │   ├── __init__.py
    │   ├── subagent.py                     # SubAgent(独立上下文)
    │   ├── task_queue.py                   # TaskQueue(结果收集)
    │   └── parallel_runner.py              # ParallelRunner(批量并发)
    │
    ├── report/                             # ── 报告生成
    │   ├── __init__.py
    │   ├── report_builder.py               # ReportBuilder(聚合+交叉验证)
    │   ├── markdown_renderer.py            # MarkdownRenderer
    │   └── progress_emitter.py             # ProgressEmitter(SSE 事件)
    │
    ├── observability/                      # ── 可观测性(模块内独立)
    │   ├── __init__.py
    │   ├── logger.py                       # 模块独立 logger(命名: pmr.*)
    │   ├── tracer.py                       # Tracer(本地 trace 实现)
    │   ├── langfuse_adapter.py             # LangfuseAdapter(可选,SDK 缺失时静默降级)
    │   └── metrics.py                      # MetricsCollector
    │
    ├── facade/                             # ── 公共 API 门面(外部唯一入口)
    │   ├── __init__.py
    │   ├── api.py                          # PostMatchReviewAPI
    │   └── entrypoint.py                   # create_default_api() 工厂函数
    │
    ├── prompts/                            # ── 提示词模板(YAML)
    │   ├── strategic_loop.yaml
    │   ├── tactical_laning.yaml
    │   ├── tactical_teamfight.yaml
    │   ├── tactical_economy.yaml
    │   ├── tactical_decision.yaml
    │   ├── tactical_vision.yaml
    │   ├── report_generation.yaml
    │   ├── background_review.yaml
    │   ├── dream_recap.yaml
    │   ├── stop_verification.yaml
    │   └── skills/                        # ── 内置分析技能定义(层 C)
    │       ├── roshan_timing.yaml          # Roshan 时机分析
    │       ├── ward_efficiency.yaml        # 守卫效率分析
    │       └── late_game_decisions.yaml    # 后期决策分析
    │
    ├── config/                             # ── 配置文件
    │   └── review_config.yaml
    │
    ├── data/                               # ── 运行时数据(本地存储,git 忽略)
    │   ├── reviews/                        # 复盘报告(Markdown + JSON)
    │   ├── progress/                       # 中断恢复进度文件 {match_id}.json
    │   ├── memory/                         # 记忆持久化(SQLite + JSON)
    │   ├── skills/                         # 提取/进化的技能(SKILL.md)
    │   │   └── analysis/                  # 用户自定义分析技能(YAML,层 C)
    │   └── cache/                          # 比赛数据缓存
    │
    ├── tests/                              # ── 测试(独立 pytest 配置)
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── unit/
    │   │   ├── __init__.py
    │   │   ├── test_budget.py
    │   │   ├── test_stop_verifier.py
    │   │   ├── test_compressor.py
    │   │   ├── test_prompt_builder.py
    │   │   ├── test_data_formatter.py         # DataFormatter 测试(层 B)
    │   │   ├── test_base_analyzer.py          # BaseLLMReviewAnalyzer 基类测试(层 A)
    │   │   ├── test_skill_driven_analyzer.py  # SkillDrivenAnalyzer 测试(层 C)
    │   │   ├── test_skill_driven_prompt_builder.py  # SkillDrivenPromptBuilder 测试(层 C)
    │   │   ├── test_skill_store_enhanced.py   # IAnalysisSkillStore 双协议测试(层 C)
    │   │   └── test_runtime.py
    │   ├── analyzers/
    │   │   ├── __init__.py
    │   │   ├── test_laning_analyzer.py
    │   │   ├── test_teamfight_analyzer.py
    │   │   ├── test_economy_analyzer.py
    │   │   ├── test_decision_analyzer.py
    │   │   └── test_vision_analyzer.py
    │   ├── integration/
    │   │   ├── __init__.py
    │   │   └── test_orchestrator_e2e.py
    │   └── fixtures/
    │       └── match_8893253595.json
    │
    └── docs/                               # ── 模块独立文档
        ├── README.md
        ├── ARCHITECTURE.md                 # 详细架构说明
        ├── INTERFACES.md                   # 接口契约参考
        └── USAGE.md                        # 使用指南

    └── mcp_server/                          # ── MCP Server 工具层(统一 FastMCP 入口)
        ├── __init__.py                      # 包初始化
        ├── server.py                        # FastMCP 入口 + 生命周期管理(startup/shutdown)
        │
        ├── helpers/                         # ── 辅助基础设施
        │   ├── __init__.py
        │   ├── opendota.py                  # 统一异步 OpenDota 客户端(AsyncOpenDotaClient)
        │   │                                #   特性: httpx.AsyncClient + 指数退避 + 429 处理
        │   │                                #         实例级缓存 + 单例模式 + Python 3.9 兼容
        │   ├── hero_names.py                # 英雄中文名映射 + 段位格式化
        │   ├── map_config.py                # 地图配置 + 区域模板 + 时间格式化
        │   ├── rag_index.py                 # 英雄 RAG 检索(FAISS 可选)
        │   ├── text_processing.py           # 全文抓取 + 处理(SerpApi 搜索辅助)
        │   └── ward_visualization.py         # 眼位可视化核心(热力图/散点图/HTML报告)
        │
        ├── tools/                           # ── MCP 工具模块(53 个 @mcp.tool() 注册)
        │   ├── __init__.py                  # 统一导入所有工具模块
        │   ├── match_tools.py               # 6 工具: 比赛详情/物品/解析
        │   ├── hero_tools.py                # 12 工具: 英雄列表/克制/统计/RAG
        │   ├── player_tools.py              # 7 工具: 玩家信息/战绩/英雄池
        │   ├── team_tools.py                # 9 工具: 战队/职业比赛/联赛
        │   ├── ward_tools.py                # 5 工具: 眼位分析/热力图/HTML报告
        │   ├── search_tools.py              # 1 工具: Dota 历史搜索(SerpApi)
        │   ├── stats_tools.py               # 7 工具: MMR分布/记录/场景统计
        │   └── review_tools.py              # 6 工具: 赛后复盘/趋势/对比(新增)
        │
        └── resources/                       # ── 静态资源
            ├── maps/                        # Dota 2 地图图片(738-7401)
            ├── figure/                      # 眼位图标(天辉/夜魇 观察守卫/岗哨守卫)
            ├── heroes_txt/                  # 英雄文本数据(RAG 检索源)
            └── ward_region_template.json    # 眼位区域模板
```

**目录结构关键约束**:

| 约束 | 说明 |
|------|------|
| **禁止反向依赖** | `dota_helper/` 内的任何文件**不得** `import` `dota_helper.core.*` / `dota_helper.analyzers.*` / `dota_helper.skills.*` / `dota_helper.memory.*` / `dota_helper.utils.*` 等既有路径 |
| **外部唯一入口** | 外部代码仅可通过 `from dota_helper import PostMatchReviewAPI` 接入 |
| **包内依赖单向** | 包内依赖顺序: `interfaces`/`types` → `data_source`/`llm`/`memory`/`observability` → `engines`/`parallel` → `analyzers` → `orchestrator` → `facade` |
| **运行时数据隔离** | 所有读写文件均位于包内 `data/`,不污染 `dota_helper/data/` |
| **可选依赖** | `langfuse` SDK 缺失时,`observability/langfuse_adapter.py` 静默降级为空实现 |

---

## 四、核心机制设计

### 4.1 双循环分析引擎

> 来源: Cve2PoC Dual-Loop Agent Framework + Anthropic Long-running Harness

双循环架构将复盘分析分为**战略层**和**战术层**两个嵌套循环，实现"先规划后执行、边执行边调整"的智能分析。

#### 4.1.1 战略循环 (Strategic Loop)

**职责**: 全局态势评估、分析策略制定、跨阶段协调、质量把关

```
战略循环流程:

  比赛数据输入
       │
       ▼
  ┌─────────────┐
  │ 全局态势评估  │ ─── 比赛时长、比分差距、关键事件时间线
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │ 分析策略制定  │ ─── 确定分析重点、分配预算、设定优先级
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐     ┌──────────────┐
  │ 调度战术循环  │ ──▶ │ 战术循环执行   │
  └──────┬──────┘     └──────┬───────┘
         │◀──────────────────┘
         │
         ▼
  ┌─────────────┐
  │ 跨阶段评估   │ ─── 各阶段结果是否一致？是否有矛盾？
  └──────┬──────┘
         │
    ┌────┴────┐
    │ 需要补充? │
    └────┬────┘
     Yes │    No
     │   │     │
     │   ▼     ▼
     │  进入停止验证
     │
     └──▶ 调整策略，重新调度战术循环
```

**战略循环的关键决策**:

| 决策类型 | 触发条件 | 决策内容 |
|---------|---------|---------|
| **重点排序** | 比赛数据加载完成 | 根据比分差距、时长等确定分析重点（如逆风局重点分析失误） |
| **预算分配** | 分析策略制定时 | 为各分析阶段分配迭代预算（复杂阶段多分配） |
| **补充分析** | 战术循环返回结果后 | 置信度不足或结论矛盾时，要求补充分析 |
| **策略调整** | 跨阶段评估后 | 发现新线索时调整后续分析方向 |

#### 4.1.2 战术循环 (Tactical Loop)

**职责**: 单阶段深度分析、迭代优化、数据验证

```
战术循环流程（单个分析阶段）:

  阶段任务 + 预算配额
       │
       ▼
  ┌──────────────┐
  │ 构建阶段提示词 │ ─── 比赛数据 + 已有结论 + 分析指令
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ LLM 分析调用  │ ─── 生成本轮分析结论
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ 质量自评      │ ─── 结论是否有数据支撑？置信度多少？
  └──────┬───────┘
         │
    ┌────┴────────────┐
    │ 质量达标 or 预算  │
    │ 耗尽？            │
    └────┬────────────┘
     No  │    Yes
     │   │     │
     │   ▼     ▼
     │  退还剩余预算   返回阶段结果
     │  给总预算池
     │
     └──▶ 压缩上下文 → 补充提示 → 重新分析
```

#### 4.1.3 双循环协作规则

| 规则 | 说明 |
|------|------|
| 战略循环不做具体分析 | 只负责规划和评估，具体分析由战术循环执行 |
| 战术循环不跨阶段 | 每个战术循环只负责一个分析阶段 |
| 预算单向流动 | 战略循环分配预算 → 战术循环消费 → 未用完退还 |
| 信息单向聚合 | 战术循环产出结论 → 战略循环聚合评估 |
| 战略循环可重入 | 如果跨阶段评估发现矛盾，战略循环可重新调度战术循环 |

---

### 4.2 迭代预算与智能终止

> 来源: Hermes IterationBudget + Claude Code TokenBudget + Anthropic Stop Hooks

#### 4.2.1 迭代预算控制

融合 Hermes 的令牌桶机制和 Claude Code 的边际递减检测，实现双层预算控制：

```
预算控制层次:

  总预算 (Global Budget)
  ├─ 最大迭代次数: 15
  ├─ 最大 Token 消耗: 100,000
  └─ 边际递减检测: 连续 2 次增量 < 500 tokens → 判定递减

  阶段预算 (Phase Budget)
  ├─ 对线期: 3 次迭代
  ├─ 团战:   5 次迭代
  ├─ 经济:   2 次迭代
  ├─ 决策:   3 次迭代
  └─ 视野:   2 次迭代

  预算决策类型:
  ├─ CONTINUE           → 继续执行
  ├─ STOP_BUDGET_USED   → 迭代次数耗尽
  ├─ STOP_TOKEN_LIMIT   → Token 达到完成阈值 (90%)
  ├─ STOP_DIMINISHING   → 边际收益递减
  └─ REFUND             → 质量达标，退还剩余配额
```

**预算退还机制** (来源: Hermes):

当某个分析阶段一次 LLM 调用就得到高质量结论时，将剩余迭代配额退还给总预算池，供其他更复杂的阶段使用。

#### 4.2.2 停止验证 (Stop Hooks)

> 来源: Claude Code `stopHooks.ts` + Hermes `verification_stop`

Agent 在尝试停止前，必须通过 Stop Verifier 的验证。验证器检查三类条件：

```
停止验证流程:

  Agent 尝试停止
       │
       ▼
  ┌─────────────────────────────────────────┐
  │ 检查 1: 必要分析阶段是否全部完成          │
  │ (来源: Hermes verification_stop)         │
  │                                          │
  │ REQUIRED_PHASES = [laning, teamfight,    │
  │                     economy, decisions]   │
  └──────────────────┬──────────────────────┘
                     │
                     ▼
  ┌─────────────────────────────────────────┐
  │ 检查 2: 每个结论是否有数据支撑            │
  │ (来源: Hermes verification_stop)         │
  │                                          │
  │ 遍历所有 conclusions:                    │
  │   conclusion.has_evidence == True?       │
  └──────────────────┬──────────────────────┘
                     │
                     ▼
  ┌─────────────────────────────────────────┐
  │ 检查 3: 整体置信度是否达标               │
  │ (来源: Claude Code stop hook)            │
  │                                          │
  │ state.confidence >= MIN_CONFIDENCE(0.6)? │
  └──────────────────┬──────────────────────┘
                     │
              ┌──────┴──────┐
              │ 全部通过?    │
              └──────┬──────┘
               Yes   │   No
               │     │    │
               ▼     │    ▼
            允许停止  │  返回 blocking_reasons
                     │  + suggestions
                     │  → 返回战术循环补充分析
```

**终态类型** (来源: Claude Code `transitions.ts`):

| 终态 | 含义 | 触发条件 |
|------|------|---------|
| `COMPLETED` | 所有分析阶段完成且验证通过 | 正常路径 |
| `MAX_ITERATIONS` | 达到最大迭代次数 | 预算耗尽 |
| `BUDGET_EXHAUSTED` | Token 预算耗尽 | Token 达到上限 |
| `VERIFICATION_BLOCKED` | 验证阻止继续 | 多次验证未通过 |
| `INTERRUPTED` | 用户主动中断 | 外部中断信号 |

---

### 4.3 上下文管理与压缩

> 来源: Hermes ContextCompressor + Claude Code Dream/Recap

#### 4.3.1 三层提示词结构

> 来源: Hermes `system_prompt.py` 三层分离

```
提示词三层结构:

  ┌─────────────────────────────────────────┐
  │ Layer 1: Stable（稳定层）                │
  │                                          │
  │ 内容: 分析角色定义、分析框架、输出格式要求  │
  │ 特点: 跨所有分析阶段不变                   │
  │ 缓存: 可安全缓存，无需每次重建              │
  └─────────────────────────────────────────┘
  ┌─────────────────────────────────────────┐
  │ Layer 2: Context（上下文层）              │
  │                                          │
  │ 内容: 比赛数据、已完成阶段的分析结论摘要    │
  │ 特点: 随分析推进逐步增长，可被压缩          │
  │ 缓存: 比赛原始数据可缓存，结论摘要需动态生成  │
  └─────────────────────────────────────────┘
  ┌─────────────────────────────────────────┐
  │ Layer 3: Volatile（易变层）               │
  │                                          │
  │ 内容: 当前阶段的具体分析指令、上一轮反馈    │
  │ 特点: 每轮迭代都不同                       │
  │ 缓存: 不可缓存                            │
  └─────────────────────────────────────────┘
```

#### 4.3.2 有损压缩策略

> 来源: Hermes ContextCompressor

当上下文 Token 数超过阈值时，执行有损压缩：

```
压缩算法:

  Phase 1: 修剪工具结果（零 LLM 调用，最低成本）
  ├─ OpenDota API 原始数据在分析完成后截断
  ├─ 保留前 500 字符 + "[...已截断...]"
  └─ 分析结论完整保留

  Phase 2: 保护区域划分
  ├─ 头部保护: 系统提示 + 比赛基本信息（2 条消息）
  ├─ 尾部保护: 最近 20K tokens 的消息完整保留
  └─ 中间区域: 待压缩内容

  Phase 3: LLM 摘要（仅中间区域）
  ├─ 使用 LLM 将中间内容压缩为 3-5 句话摘要
  └─ 摘要消息插入头部和尾部之间

  压缩后结构: [头部保护] + [摘要] + [尾部保护]
```

**各消息类型的压缩策略**:

| 消息类型 | 压缩策略 | 原因 |
|---------|---------|------|
| 系统提示（Stable 层） | 完整保留 | 分析指令不可丢失 |
| 比赛原始数据（API 返回） | 分析完成后修剪 | 数据量大，分析结论已提取关键信息 |
| 已完成阶段分析结论 | 摘要保留 | 后续阶段可能引用 |
| 最近分析上下文（~20K tokens） | 完整保留 | 当前分析上下文不可丢失 |

#### 4.3.3 Dream/Recap 记忆整合

> 来源: Claude Code `dream.ts`

复盘完成后，使用 Dream/Recap 模式整合本次分析的关键发现：

```
Dream/Recap 流程:

  复盘分析完成
       │
       ▼
  ┌──────────────────────┐
  │ 读取本次分析全部记录   │
  │ (transcript)          │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ buildConsolidation   │
  │ Prompt()             │ ─── 构建反思提示词
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ LLM Review           │ ─── 模型审视、组织、修剪
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 生成结构化记忆条目     │ ─── 持久化到记忆系统
  │ (持久化、可检索)       │
  └──────────────────────┘
```

---

### 4.4 四层记忆系统

> 来源: Hermes Agent 四层记忆架构

```
四层记忆架构:

  ┌─────────────────────────────────────────────────────────┐
  │ Level 0: Prompt Memory（提示记忆）                       │
  │                                                          │
  │ 生命周期: 单次复盘会话内                                  │
  │ 存储内容: 当前分析上下文、中间结论、工具调用结果            │
  │ 实现方式: 对话历史 + 状态对象                              │
  │ 容量: 受 LLM 上下文窗口限制                              │
  └─────────────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────────────┐
  │ Level 1: Session Archive（会话归档）                     │
  │                                                          │
  │ 生命周期: 跨会话持久化                                    │
  │ 存储内容: 每次复盘的完整报告、分析轨迹、质量评分            │
  │ 实现方式: SQLite + JSON 文件                              │
  │ 检索: 按 match_id / hero / 时间范围查询                   │
  └─────────────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────────────┐
  │ Level 2: Persistent Notes（持久笔记）                    │
  │                                                          │
  │ 生命周期: 跨会话持久化                                    │
  │ 存储内容: 用户游戏风格、常见失误模式、英雄熟练度画像        │
  │ 实现方式: 结构化 JSON + 向量索引                           │
  │ 更新: 后台自我审查时自动更新                               │
  └─────────────────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────────────────┐
  │ Level 3: Dynamic Skills（动态技能）                      │
  │                                                          │
  │ 生命周期: 永久，可版本化                                  │
  │ 存储内容: 从复盘中提取的可复用分析模式和战术经验            │
  │ 实现方式: SKILL.md 文件 + SkillRegistry                   │
  │ 进化: 新复盘可覆盖和改进已有技能                            │
  └─────────────────────────────────────────────────────────┘
```

**记忆晋升机制**:

```
Level 0 → Level 1: 复盘完成时，自动归档完整报告
Level 1 → Level 2: 后台审查发现重复出现的模式时，晋升为持久笔记
Level 2 → Level 3: 持久笔记被多次引用且验证有效时，沉淀为技能
```

---

### 4.5 技能自动沉淀与进化

> 来源: Hermes Agent GEPA 自我进化引擎 + 技能自动学习

#### 4.5.1 技能沉淀流程

```
技能沉淀流程:

  复盘分析完成 + 后台审查完成
       │
       ▼
  ┌──────────────────────┐
  │ 提取成功模式          │ ─── 哪些分析结论被验证有效？
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 生成技能草案          │ ─── 格式化为 SKILL.md 模板
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 冲突检测              │ ─── 是否与已有技能矛盾？
  └──────────┬───────────┘
             │
      ┌──────┴──────┐
      │ 有冲突?      │
      └──────┬──────┘
       Yes   │   No
       │     │    │
       │     │    ▼
       │     │  注册新技能
       │     │
       ▼     ▼
  ┌──────────────────────┐
  │ 版本化更新            │ ─── 新证据覆盖旧技能，保留历史版本
  └──────────────────────┘
```

#### 4.5.2 技能模板

```yaml
# skills/dota_helper/skills/against_pa.md
---
name: against_pa
description: 对抗幻影刺客的分析模式
source_match: 8893253595
confidence: 0.75
version: 2
created_at: 2026-07-15
updated_at: 2026-07-20
tags: [hero_counter, pa, carry]
---

# 对抗幻影刺客分析要点

## 对线期
- PA 在 6 级前较弱，关注其补刀数和血量消耗比
- 如果 PA 补刀低于理论值 60%，说明对线压制成功

## 关键时间节点
- 6 级: PA 解锁大招，gank 能力质变
- 15-20 分钟: 狂战斧/暴击披风时间节点
- 25 分钟+: 团战威胁峰值期

## 反制策略评估维度
- 是否出了刃甲/绿杖等克制物品
- 团战站位是否避开 PA 跳切路线
- 视野是否覆盖 PA 常见 farm 路线
```

---

### 4.6 并行子代理编排

> 来源: Claude Code `batch.ts` + Hermes 子代理并行

#### 4.6.1 Batch 并行模式

```
并行分析编排:

  战略循环确定分析策略
       │
       ▼
  ┌──────────────────────────────────────┐
  │ Phase 1: 任务分解                     │
  │                                       │
  │ 根据比赛特点确定需要并行的分析任务       │
  │ 例: 常规局 → 4 个分析阶段全部并行       │
  │ 例: 速推局 → 重点并行对线+决策          │
  └──────────────────┬───────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────┐
  │ Phase 2: 并行执行                     │
  │                                       │
  │  ┌────────┐ ┌────────┐ ┌────────┐    │
  │  │对线分析 │ │团战分析 │ │经济分析 │    │
  │  │SubAgent│ │SubAgent│ │SubAgent│    │
  │  └────┬───┘ └────┬───┘ └────┬───┘    │
  │       │          │          │         │
  │  ┌────┴───┐                              │
  │  │决策分析 │    每个 SubAgent:            │
  │  │SubAgent│    - 独立上下文               │
  │  └────┬───┘    - 独立预算配额             │
  │       │        - 失败隔离                 │
  └───────┼────────┼──────────┼─────────────┘
          │        │          │
          ▼        ▼          ▼
  ┌──────────────────────────────────────┐
  │ Phase 3: 结果聚合                     │
  │                                       │
  │ 通过统一任务队列收集结果                │
  │ 处理部分失败（降级策略）                │
  │ 交叉验证各阶段结论一致性                │
  └──────────────────────────────────────┘
```

#### 4.6.2 子代理隔离规则

| 规则 | 说明 |
|------|------|
| 独立上下文 | 每个子代理有独立的消息列表，互不干扰 |
| 独立预算 | 从总预算池分配的独立配额 |
| 失败隔离 | 单个子代理失败不影响其他子代理执行 |
| 结果回注 | 完成后通过统一队列回注结果给主循环 |
| 工具限制 | 每个子代理只能使用分配给它的工具集 |

---

## 五、核心流程

### 5.1 完整复盘流程

```
完整复盘流程:

Phase 0: 数据获取
├─ 调用 OpenDota API 获取比赛详情
├─ 解析并结构化为 MatchData
├─ 数据完整性校验（duration、players、picks_bans）
└─ 缓存比赛数据（避免重复请求）

Phase 1: 战略循环 — 全局评估
├─ 比赛类型分类（常规/速推/碾压/翻盘）
├─ 确定分析重点和优先级
├─ 为各分析阶段分配迭代预算
└─ 输出: AnalysisStrategy

Phase 2: 战术循环 — 多阶段分析
├─ 对线期分析（0-10 分钟）
│   ├─ 补刀效率评估
│   ├─ 消耗换血质量
│   └─ 神符利用率
├─ 团战执行分析
│   ├─ 团战参与率
│   ├─ 技能释放时机
│   └─ 走位和站位
├─ 经济效率分析
│   ├─ GPM/XPM 曲线
│   ├─ 装备购买效率
│   └─ 关键装备时间节点
├─ 关键决策点分析
│   ├─ Roshan 时机
│   ├─ 推塔节奏
│   └─ 团战发起/撤退
└─ 视野控制分析
    ├─ 守卫放置热力图
    ├─ 关键视野盲区
    └─ 反野效率

[每个阶段受迭代预算控制 + 边际收益递减检测]
[各阶段可并行执行]

Phase 3: 停止验证
├─ 所有必要分析阶段是否完成？
├─ 每个结论是否有数据支撑？
├─ 整体置信度是否 >= 0.6？
└─ 未通过 → 返回 Phase 2 补充分析（受总预算约束）

Phase 4: 报告生成
├─ 聚合各阶段分析结果
├─ 交叉验证结论一致性
├─ 生成 Markdown 结构化报告
├─ 包含评分（1-10）和改进建议
└─ 导出到文件 + 前端展示

Phase 5: 后台自我审查（异步，不阻塞主流程）
├─ 评估分析质量（数据支撑度、分析深度、可操作性）
├─ 提取可复用的分析模式
├─ 更新用户画像（Persistent Notes）
└─ 沉淀/更新技能（Dynamic Skills）
```

### 5.2 中断恢复流程

> 来源: Claude Code QueryEngine 生命周期

```
中断恢复流程:

  复盘分析进行中
       │
    [中断信号]
       │
       ▼
  ┌──────────────────────┐
  │ 保存当前进度          │
  │ ├─ 已完成阶段结果     │
  │ ├─ 当前阶段部分结果   │
  │ ├─ 预算消耗状态       │
  │ └─ 上下文消息列表     │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 持久化到文件          │
  │ review_progress/      │
  │   {match_id}.json     │
  └──────────────────────┘

  === 恢复时 ===

  ┌──────────────────────┐
  │ 加载进度文件          │
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ 恢复状态              │
  │ ├─ 跳过已完成阶段     │
  │ ├─ 从当前阶段断点继续  │
  │ └─ 恢复预算配额       │
  └──────────────────────┘
```

---

## 六、组件职责清单

### 6.1 编排层组件

| 组件 | 职责 | 关键接口 |
|------|------|---------|
| **ReviewOrchestrator** | 复盘全流程编排，协调战略/战术循环 | `review(match_id) -> ReviewReport` |
| **StrategicLoop** | 全局评估、策略制定、跨阶段协调 | `evaluate(match_data) -> AnalysisStrategy` |
| **TacticalLoop** | 单阶段深度分析，迭代优化 | `execute_phase(phase, strategy) -> PhaseResult` |
| **BackgroundReviewSpawner** | 异步自我审查，不阻塞主流程 | `spawn(match_data, report) -> None` |

### 6.2 引擎层组件

| 组件 | 职责 | 关键接口 |
|------|------|---------|
| **ReviewIterationBudget** | 迭代预算控制（令牌桶 + 边际递减） | `consume() -> BudgetDecision`, `refund() -> None` |
| **ReviewStopVerifier** | 停止条件验证（类型化终态 + 验证钩子） | `verify(state) -> VerificationResult` |
| **ReviewContextCompressor** | 有损上下文压缩（修剪 + 保护 + LLM 摘要） | `compress(messages) -> List[Message]` |
| **ReviewPromptBuilder** | 三层提示词构建（stable/context/volatile） | `build(match_data, phase_results) -> List[Message]` |

### 6.3 分析层组件

| 组件 | 职责 | 关键接口 |
|------|------|---------|
| **BaseReviewAnalyzer** | 分析器抽象基类，定义通用接口 | `analyze(match_data, context) -> AnalysisResult` |
| **LaningAnalyzer** | 对线期分析（补刀、消耗、神符） | 继承 BaseReviewAnalyzer |
| **TeamfightAnalyzer** | 团战分析（参与率、技能释放、走位） | 继承 BaseReviewAnalyzer |
| **EconomyAnalyzer** | 经济分析（GPM/XPM、装备效率） | 继承 BaseReviewAnalyzer |
| **DecisionAnalyzer** | 决策分析（Roshan、推塔、团战决策） | 继承 BaseReviewAnalyzer |
| **VisionAnalyzer** | 视野分析（守卫、盲区、反野） | 继承 BaseReviewAnalyzer |
| **SkillDrivenAnalyzer** | Skill 驱动分析器（YAML 技能定义动态生成） | `from_yaml()`, `from_skill_store()`, 继承 BaseReviewAnalyzer |
| **SkillDrivenPromptBuilder** | Skill 驱动提示词构建器（从 YAML 加载模板） | 继承 PromptBuilder |
| **DataFormatter** | YAML 声明驱动的通用数据格式化器 | `format(match_data, data_requirements) -> str` |

### 6.4 基础设施层组件（包内自包含 v1.1）

> **重要**: v1.1 起,所有基础设施组件均位于 `dota_helper/` 包内,**不复用**
> `dota_helper/utils/`、`dota_helper/memory/`、`dota_helper/skills/`
> 等既有目录的代码。这保证复盘 Agent 可独立演进、独立测试、独立部署。

| 组件 | 职责 | 包内位置 |
|------|------|---------|
| **LLMClient** | LLM 调用抽象 | `dota_helper/llm/client.py` |
| **OpenDotaClient** | OpenDota API HTTP 客户端 | `dota_helper/data_source/opendota_client.py` |
| **MatchFetcher** | 比赛数据获取与结构化 | `dota_helper/data_source/match_fetcher.py` |
| **FourLayerMemory** | 四层记忆(Prompt/Session/Persistent/Skills) | `dota_helper/memory/four_layer_memory.py` |
| **SessionArchive** | Level 1: 复盘报告归档(SQLite) | `dota_helper/memory/session_archive.py` |
| **PersistentNotes** | Level 2: 用户画像(结构化 JSON) | `dota_helper/memory/persistent_notes.py` |
| **SkillStore** | Level 3: 技能沉淀 + 分析技能管理（双协议 ISkillStore + IAnalysisSkillStore） | `dota_helper/memory/skill_store.py` |
| **DreamRecap** | 复盘后整合与持久化 | `dota_helper/memory/dream_recap.py` |
| **Tracer** | 链路追踪(本地 + Langfuse) | `dota_helper/observability/tracer.py` |
| **LangfuseAdapter** | Langfuse 可选适配器(SDK 缺失时降级) | `dota_helper/observability/langfuse_adapter.py` |
| **Logger** | 模块独立 logger(`pmr.*` 命名空间) | `dota_helper/observability/logger.py` |
| **PromptManager** | Prompt 版本管理(YAML) | `dota_helper/llm/prompt_manager.py` |
| **TokenCounter** | Token 计数(支撑预算控制) | `dota_helper/llm/token_counter.py` |
| **DataCache** | 比赛数据本地缓存 | `dota_helper/data_source/cache.py` |
| **DataValidator** | 数据完整性校验 | `dota_helper/data_source/data_validator.py` |
| **DataFormatter** | YAML 声明驱动数据格式化(5 种格式 + 值变换) | `dota_helper/engines/data_formatter.py` |

### 6.5 MCP Server 工具层组件

> **v1.7 新增**: MCP Server 从单体文件 `dota2_fastmcp.py`（6503 行）拆分为模块化结构，
> 位于 `dota_helper/mcp_server/`。包含 47 个迁移工具 + 6 个新增复盘工具 = 53 个工具。
> 所有同步 `requests` 调用已转换为异步 `httpx.AsyncClient`，CPU 密集型操作使用 `asyncio.to_thread()`。

| 组件 | 职责 | 包内位置 |
|------|------|---------|
| **FastMCP Server** | MCP Server 入口，生命周期管理，工具注册 | `mcp_server/server.py` |
| **AsyncOpenDotaClient** | 统一异步 OpenDota HTTP 客户端（含 `AsyncOpenDotaClient` 别名） | `mcp_server/helpers/opendota.py` |
| **match_tools** | 6 工具: get_match_details / get_match_items / get_item_id_map / request_match_parse / request_match_parses / get_parse_request | `mcp_server/tools/match_tools.py` |
| **hero_tools** | 12 工具: get_heroes / rag_hero_intro / get_hero_matchups / get_hero_item_popularity 等 | `mcp_server/tools/hero_tools.py` |
| **player_tools** | 7 工具: get_player_info / get_player_matches / get_player_win_loss 等 | `mcp_server/tools/player_tools.py` |
| **team_tools** | 9 工具: get_pro_matches / get_teams / get_team_matches / search_team 等 | `mcp_server/tools/team_tools.py` |
| **ward_tools** | 5 工具: analyze_match_wards / analyze_multi_match_wards / get_ward_statistics 等 | `mcp_server/tools/ward_tools.py` |
| **search_tools** | 1 工具: search_dota_history（SerpApi + 中文/英文回退） | `mcp_server/tools/search_tools.py` |
| **stats_tools** | 7 工具: get_mmr_distribution / get_records / get_constants 等 | `mcp_server/tools/stats_tools.py` |
| **review_tools** | 6 新增工具: analyze_ward_efficiency / analyze_roshan_timing / generate_review_report 等 | `mcp_server/tools/review_tools.py` |
| **WardDataExtractor** | 眼位数据提取（从比赛数据提取守卫/反眼/击杀事件） | `mcp_server/helpers/ward_visualization.py` |
| **WardAnalyzer** | 眼位分析（区域分析/热力图/散点图/HTML报告生成） | `mcp_server/helpers/ward_visualization.py` |
| **hero_names** | 英雄中文名映射 + 段位格式化（get_cn_name / get_rank_display） | `mcp_server/helpers/hero_names.py` |
| **map_config** | 地图配置 + 区域模板加载 + 时间格式化 | `mcp_server/helpers/map_config.py` |
| **rag_index** | 英雄 RAG 检索（FAISS 可选，SerpApi 文本嵌入） | `mcp_server/helpers/rag_index.py` |

---

## 七、接口契约

### 7.1 ReviewOrchestrator 接口

```python
class IReviewOrchestrator(Protocol):
    """复盘编排器接口"""

    async def review(self, match_id: str) -> ReviewReport:
        """执行完整的赛后复盘分析

        Args:
            match_id: OpenDota 比赛 ID

        Returns:
            ReviewReport: 结构化复盘报告

        Raises:
            ReviewError: 数据获取失败或分析异常
        """
        ...

    async def review_with_progress(
        self, match_id: str
    ) -> AsyncGenerator[ReviewProgress, None]:
        """执行复盘分析，流式返回进度

        Args:
            match_id: OpenDota 比赛 ID

        Yields:
            ReviewProgress: 分析进度更新
        """
        ...

    def interrupt(self) -> None:
        """中断当前复盘分析"""
        ...

    def get_partial_result(self) -> Optional[ReviewReport]:
        """获取中断后的部分结果

        返回当前已生成的 ReviewReport,其中 completed_phases 可能不完整,
        terminal_state 反映中断原因(INTERRUPTED)。
        """
        ...
```

### 7.2 分析器接口

```python
class IReviewAnalyzer(Protocol):
    """复盘分析器接口"""

    @property
    def phase_name(self) -> str:
        """分析阶段名称"""
        ...

    async def analyze(
        self,
        match_data: MatchData,
        context: AnalysisContext
    ) -> AnalysisResult:
        """执行分析

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文（包含已有结论、预算等）

        Returns:
            AnalysisResult: 分析结果（结论 + 置信度 + 数据支撑）
        """
        ...

    def validate_result(self, result: AnalysisResult) -> bool:
        """验证分析结果是否有效

        Args:
            result: 待验证的分析结果

        Returns:
            bool: 结果是否有效（有数据支撑、置信度达标）
        """
        ...
```

### 7.3 预算控制接口

```python
class IIterationBudget(Protocol):
    """迭代预算控制接口"""

    def consume(self, delta_tokens: int = 0) -> BudgetDecision:
        """消费一个迭代配额

        Args:
            delta_tokens: 本轮消耗的 token 数

        Returns:
            BudgetDecision: 预算决策（继续/停止/递减）
        """
        ...

    def refund(self) -> None:
        """退还一个迭代配额"""
        ...

    @property
    def remaining_iterations(self) -> int:
        """剩余迭代次数"""
        ...

    @property
    def remaining_tokens(self) -> int:
        """剩余 token 配额"""
        ...
```

### 7.4 停止验证接口

```python
class IStopVerifier(Protocol):
    """停止验证器接口"""

    def verify(self, state: ReviewAgentState) -> VerificationResult:
        """验证是否满足终止条件

        Args:
            state: 当前 Agent 状态

        Returns:
            VerificationResult: 验证结果
        """
        ...
```

### 7.5 分析技能存储接口

```python
class IAnalysisSkillStore(Protocol):
    """分析技能存储接口（YAML 格式）

    分析技能以纯 YAML 文件存储，包含分析框架、数据需求、
    输出 Schema 等完整定义，供 SkillDrivenAnalyzer 使用。
    与 ISkillStore（经验技能，Markdown 格式）互补，
    共同构成 SkillStore 的双协议支持。
    """

    def save_analysis_skill(
        self,
        name: str,
        skill_definition: Dict[str, Any],
    ) -> None:
        """保存分析技能定义

        Args:
            name: 技能名称（不含扩展名）
            skill_definition: 完整的 YAML 技能定义字典
        """
        ...

    def load_analysis_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """加载分析技能定义

        Args:
            name: 技能名称（不含扩展名）

        Returns:
            Optional[Dict[str, Any]]: 技能定义字典，不存在时返回 None
        """
        ...

    def list_analysis_skills(self) -> List[Dict[str, Any]]:
        """列出所有分析技能

        Returns:
            List[Dict[str, Any]]: 分析技能定义列表
        """
        ...
```

### 7.6 SkillDrivenAnalyzer 创建接口

```python
class SkillDrivenAnalyzer(BaseLLMReviewAnalyzer):
    """Skill 驱动分析器

    从 YAML 技能定义文件动态创建分析能力，无需编写 Python 子类。
    """

    @classmethod
    def from_yaml(
        cls, llm_client: ILLMClient, yaml_path: Path
    ) -> "SkillDrivenAnalyzer":
        """从 YAML 文件创建分析器

        Args:
            llm_client: LLM 客户端实例
            yaml_path: YAML 技能定义文件路径

        Returns:
            SkillDrivenAnalyzer: 分析器实例
        """
        ...

    @classmethod
    def from_skill_store(
        cls, llm_client: ILLMClient, skill_store: IAnalysisSkillStore,
        skill_name: str, use_builtin: bool = False,
    ) -> "SkillDrivenAnalyzer":
        """从 SkillStore 加载技能定义并创建分析器

        Args:
            llm_client: LLM 客户端实例
            skill_store: 技能存储实例
            skill_name: 技能名称
            use_builtin: 是否从内置目录加载

        Returns:
            SkillDrivenAnalyzer: 分析器实例
        """
        ...
```

---

## 八、数据模型

### 8.1 核心数据类型

```python
# === 比赛数据 ===

@dataclass
class MatchData:
    """结构化比赛数据"""
    match_id: str
    duration: int                     # 比赛时长（秒）
    radiant_win: bool                 # 天辉是否胜利
    radiant_score: int                # 天辉得分
    dire_score: int                   # 夜魇得分
    game_mode: int                    # 游戏模式
    players: List[PlayerData]         # 所有玩家数据
    picks_bans: List[PickBan]         # Ban/Pick 记录
    lane_data: Optional[LaneData]     # 对线期数据
    teamfight_data: Optional[List[TeamfightData]]  # 团战数据
    economy_data: Optional[EconomyData]  # 经济数据

@dataclass
class PlayerData:
    """玩家数据"""
    account_id: str
    hero_id: int
    hero_name: str
    kills: int
    deaths: int
    assists: int
    last_hits: int
    denies: int
    gpm: int
    xpm: int
    hero_damage: int
    tower_damage: int
    is_radiant: bool
    is_user: bool                     # 是否为目标用户

# === 分析结果 ===

@dataclass
class AnalysisResult:
    """单个分析阶段的结果"""
    phase: str                        # 分析阶段名称
    conclusions: List[Conclusion]     # 分析结论列表
    confidence: float                 # 整体置信度 (0-1)
    iterations_used: int              # 使用的迭代次数
    tokens_consumed: int              # 消耗的 token 数
    analysis_text: str                # 分析文本（Markdown）

@dataclass
class Conclusion:
    """单条分析结论"""
    title: str                        # 结论标题
    content: str                      # 结论内容
    evidence: List[str]               # 数据支撑（引用具体数据）
    has_evidence: bool                # 是否有数据支撑
    impact: str                       # 影响程度: high/medium/low
    suggestion: Optional[str]         # 改进建议

# === 复盘报告 ===

@dataclass
class ReviewReport:
    """完整复盘报告"""
    match_id: str
    match_summary: MatchSummary       # 比赛摘要
    phase_results: List[AnalysisResult]  # 各阶段分析结果
    overall_score: float              # 整体评分 (1-10)
    overall_confidence: float         # 整体置信度 (0-1)
    key_findings: List[str]           # 关键发现
    improvement_areas: List[str]      # 改进方向
    markdown_report: str              # Markdown 格式报告
    terminal_state: str               # 终态类型
    created_at: str                   # 创建时间

# === 状态与进度 ===

@dataclass
class ReviewAgentState:
    """复盘 Agent 状态"""
    match_id: str
    match_data: Optional[MatchData]
    strategy: Optional[AnalysisStrategy]
    completed_phases: List[str]       # 已完成的分析阶段
    conclusions: List[Conclusion]     # 所有结论
    confidence: float                 # 当前整体置信度
    is_interrupted: bool              # 是否被中断
    total_iterations: int             # 总迭代次数
    total_tokens: int                 # 总 token 消耗

@dataclass
class AnalysisStrategy:
    """分析策略"""
    match_type: str                   # 比赛类型分类
    priority_phases: List[str]        # 分析优先级排序
    budget_allocation: Dict[str, int] # 各阶段预算分配
    expected_depth: Dict[str, str]    # 各阶段预期分析深度
```

### 8.2 枚举类型

```python
class BudgetDecision(Enum):
    """预算决策"""
    CONTINUE = "continue"
    STOP_BUDGET_USED = "stop_budget_used"
    STOP_TOKEN_LIMIT = "stop_token_limit"
    STOP_DIMINISHING = "stop_diminishing"

class ReviewTerminalState(Enum):
    """复盘终态"""
    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    BUDGET_EXHAUSTED = "budget_exhausted"
    VERIFICATION_BLOCKED = "verification_blocked"
    INTERRUPTED = "interrupted"

class ReviewContinueState(Enum):
    """复盘继续态

    当 StopVerifier 验证未通过时，根据具体原因决定下一步动作:
    - NEXT_PHASE: 当前阶段完成，进入下一阶段
    - LOW_CONFIDENCE: 置信度不足，需补充数据或深入分析
    - VERIFICATION_RETRY: 验证未通过，需重新分析特定阶段
    - TOKEN_BUDGET_OK: 预算充足，可继续迭代
    """
    NEXT_PHASE = "next_phase"
    LOW_CONFIDENCE = "low_confidence"
    VERIFICATION_RETRY = "verification_retry"
    TOKEN_BUDGET_OK = "token_budget_ok"

class MatchType(Enum):
    """比赛类型"""
    NORMAL = "normal"                 # 常规局
    STOMP = "stomp"                   # 碾压局
    COMEBACK = "comeback"             # 翻盘局
    QUICK_PUSH = "quick_push"         # 速推局
    CLOSE_GAME = "close_game"         # 焦灼局
```

---

## 九、与现有系统的集成（最小化接入 v1.1）

> **核心原则**: 复盘 Agent 是**自包含**的独立包,与 `dota_helper` 既有模块**零代码依赖**。
> 外部仅通过 `dota_helper.facade` 暴露的 `PostMatchReviewAPI` 接入。
> 既有组件**不感知**复盘 Agent 存在,反之亦然。

### 9.1 集成策略:Adapter 模式（单向解耦）

```
┌──────────────────────────────────────────────────────────────────────┐
│                       既有 dota_helper                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ web/app.py   │  │  frontend/   │  │  其余 core/analyzers/     │  │
│  │ (FastAPI)    │  │  Vue 3 + TS  │  │  skills/memory/utils/     │  │
│  └──────┬───────┘  └──────┬───────┘  └─────────────┬─────────────┘  │
│         │                 │                         │                │
│         │    通过 HTTP/SSE / WS 接入（仅契约层）      │                │
│         │                 │                         │                │
└─────────┼─────────────────┼─────────────────────────┼────────────────┘
          │                 │                         │
          ▼                 ▼                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│         dota_helper/  (独立顶级包,零 import 既有模块)            │
│                                                                       │
│   facade/PostMatchReviewAPI  ←  外部唯一入口                          │
│        │                                                              │
│        ▼                                                              │
│   orchestrator/ReviewOrchestrator                                    │
│        │                                                              │
│   engines/ + analyzers/ + memory/ + llm/ + data_source/              │
│   parallel/ + report/ + observability/  (全部包内自包含)              │
└──────────────────────────────────────────────────────────────────────┘
```

**集成约束**:

| 约束 | 说明 |
|------|------|
| **零 import 既有代码** | `dota_helper/` 任何文件**不得** `import dota_helper.core.*` / `analyzers.*` / `skills.*` / `memory.*` / `utils.*` |
| **单向接入** | 仅允许既有代码 → `dota_helper.facade` 单向调用,反向调用被禁止 |
| **配置文件独立** | `dota_helper/config/review_config.yaml` 与 `dota_helper/config/*.yaml` 解耦,可独立维护 |
| **数据目录独立** | 复盘报告/记忆/缓存/技能存于 `dota_helper/data/`,不污染 `dota_helper/data/` |
| **日志命名空间独立** | 所有日志以 `pmr.*` 为前缀(如 `pmr.orchestrator` / `pmr.analyzer.laning`),便于过滤 |
| **LLM 配置可独立** | `dota_helper/llm/client.py` 通过环境变量读取 `OPENAI_API_KEY` 等,与 `utils/llm_client.py` 共享底层 env,但实现隔离 |

### 9.2 唯一外部接入点:PostMatchReviewAPI

```python
# 既有代码中的接入示例(web/app.py)
from dota_helper import PostMatchReviewAPI

review_api = PostMatchReviewAPI()  # 默认从 dota_helper/config/review_config.yaml 加载

# FastAPI 端点
@app.post("/api/review")
async def start_review(match_id: str) -> StreamingResponse:
    return StreamingResponse(
        review_api.review_stream(match_id),
        media_type="text/event-stream",
    )

@app.get("/api/review/{match_id}/report")
async def get_report(match_id: str) -> dict:
    return await review_api.get_report(match_id)
```

### 9.3 新增 API 端点

```
POST /api/review
  Body: { "match_id": "8893253595" }
  Response: SSE 流式返回分析进度 + 最终报告
  接入: review_api.review_stream(match_id)

GET /api/review/{match_id}/status
  Response: { "status": "analyzing", "progress": 0.6, "current_phase": "teamfight" }
  接入: review_api.get_status(match_id)

GET /api/review/{match_id}/report
  Response: 完整复盘报告 (Markdown)
  接入: review_api.get_report(match_id)

POST /api/review/{match_id}/interrupt
  Response: { "status": "interrupted", "partial_report": {...} }
  接入: review_api.interrupt(match_id)

GET /api/review/history
  Response: 复盘历史记录列表
  接入: review_api.list_history()

GET /api/review/skills
  Response: 所有可用分析技能列表（内置 + 用户自定义）
  接入: review_api.list_analysis_skills()

POST /api/review/skills
  Body: { "name": "my_custom", "skill_definition": {...} }
  Response: { "success": true }
  接入: review_api.register_analysis_skill(name, definition)

GET /api/review/{match_id}/stream/ws        # 可选 WebSocket 端点
  接入: review_api.review_ws(match_id)
```

### 9.3a MCP Server 集成

> **v1.7 新增**: `core/agent.py` 中的 `dota_helper` 集成了 MCP Client，
> 可通过 `connect_mcp_server()` 连接 `dota_helper/mcp_server` 获取 53 个扩展工具。

```
MCP 集成架构:

  ┌──────────────────────────────────────────────────────┐
  │  dota_helper (core/agent.py)                      │
  │                                                        │
  │  connect_mcp_server() ──stdio──▶ MCP Server            │
  │  call_mcp_tool(name, args) ──▶ 53 个工具                │
  │  get_mcp_tools() ──▶ 工具发现列表                       │
  │  disconnect_mcp_server() ──▶ 断开连接                   │
  └──────────────────────────────────────────────────────┘
         │ stdio
         ▼
  ┌──────────────────────────────────────────────────────┐
  │  dota_helper/mcp_server/                         │
  │  FastMCP("Dota2 Helper Agent")                        │
  │                                                        │
  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
  │  │ match   │ │ hero     │ │ player   │ │ team     │  │
  │  │ 6 tools │ │ 12 tools │ │ 7 tools  │ │ 9 tools  │  │
  │  └─────────┘ └──────────┘ └──────────┘ └──────────┘  │
  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
  │  │ ward    │ │ search   │ │ stats    │ │ review   │  │
  │  │ 5 tools │ │ 1 tool   │ │ 7 tools  │ │ 6 tools  │  │
  │  └─────────┘ └──────────┘ └──────────┘ └──────────┘  │
  │                                                        │
  │  helpers: AsyncOpenDotaClient (单例, 实例级缓存)        │
  └──────────────────────────────────────────────────────┘
```

**启动命令**:

```bash
# 方式 1: 作为 MCP Server 独立运行
python -m dota_helper.dota_helper.mcp_server

# 方式 2: 通过 dota_helper MCP Client 连接
agent = dota_helper()
await agent.connect_mcp_server()  # 默认连接 dota_helper.mcp_server
```

**MCP Server 启动生命周期**:
1. `startup()` — 初始化 `AsyncOpenDotaClient`，预加载英雄列表缓存
2. 工具注册 — `tools/__init__.py` 导入 8 个工具模块，触发 `@mcp.tool()` 注册
3. `mcp.run_stdio()` — 进入 stdio 事件循环
4. `shutdown()` — 关闭 `AsyncOpenDotaClient`，释放 httpx 连接

### 9.4 前端集成

> 前端采用 **Vue 3 + TypeScript + Vite** 实现，通过 HTTP/SSE 与后端交互，
> 不直接 `import` 任何 `dota_helper.*` 模块。
>
> v1.8 新增：聊天界面组件，交互模式从
> "输入 match_id → 一键触发复盘"改为"自由文本聊天 → ReAct Agent 推理"。
> 既有 Vue 3 复盘组件与新增聊天组件并存。

```
前端文件结构:

  frontend/src/
  ├── components/
  │   ├── chat/                            # 新增：聊天组件
  │   │   ├── ChatView.vue                 # 聊天主页面
  │   │   ├── ChatInput.vue                # 消息输入框
  │   │   ├── ChatMessage.vue              # 单条消息渲染（含 Markdown）
  │   │   ├── ChatBubble.vue               # Agent 思考/行动/观察气泡
  │   │   ├── WardIframe.vue               # Ward HTML iframe 嵌入
  │   │   └── PresetCards.vue              # 预设问题卡片
  │   └── review/                          # 既有：复盘组件（保留）
  │       ├── ReviewPanel.vue
  │       ├── ReviewProgress.vue
  │       ├── ReviewReport.vue
  │       ├── ReviewTimeline.vue
  │       └── ReviewHistory.vue
  ├── composables/
  │   ├── useChat.ts                       # 新增：聊天 SSE 流式处理
  │   └── useReview.ts                     # 既有：复盘 SSE 流式处理
  ├── stores/
  │   ├── chat.ts                          # 新增：聊天状态管理(Pinia)
  │   └── review.ts                        # 既有：复盘状态管理(Pinia)
  ├── types/
  │   ├── chat.ts                          # 新增：聊天类型定义
  │   └── review.ts                        # 既有：复盘类型定义
  └── api/
      ├── chat.ts                          # 新增：聊天 API 客户端
      └── review.ts                        # 既有：复盘 API 客户端
```

**聊天界面核心功能**（详见 §13.1.2 阶段 10）：

| 功能 | 说明 |
|------|------|
| 自由文本输入 | 用户输入任意问题（如"分析比赛 XXX 的视野"） |
| SSE 流式展示 | 实时展示 Agent Thought/Action/Observation 推理过程 |
| 最终答案渲染 | Markdown 渲染 Final Answer 内容 |
| Ward HTML 嵌入 | 检测 ward_html 路径，通过 iframe 嵌入交互式眼位分析 |
| 会话历史 | 侧边栏展示聊天会话历史，支持回看和继续 |
| 预设问题卡片 | 首页展示快速入口卡片 |

### 9.5 LLM 配置共享（最小耦合）

复盘 Agent 不复用 `utils/llm_client.py`,但通过**环境变量**共享 LLM 凭证,
避免配置重复。

```python
# dota_helper/llm/client.py 内部示例
import os
from openai import AsyncOpenAI

class LLMClient:
    """独立 LLM 客户端,仅通过环境变量读取凭证"""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )

    async def chat(self, messages: list[dict], **kwargs) -> str:
        # 独立实现,与 utils/llm_client.py 行为可不同
        ...
```

**LLM 凭证传递方式**:

| 凭证 | 来源 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | 环境变量 | 与既有模块共享 |
| `OPENAI_BASE_URL` | 环境变量 | 与既有模块共享 |
| `OPENAI_MODEL` | `dota_helper/config/review_config.yaml` | 模块独立配置 |
| `*_PROMPT_VERSION` | `dota_helper/config/review_config.yaml` | 模块独立配置 |

### 9.6 Langfuse 可选集成（包内独立）

> 与既有 `utils/trace_context.py` 隔离,复盘 Agent 在包内独立实现 Langfuse 适配器。

```python
# dota_helper/observability/langfuse_adapter.py
from typing import Protocol, Any

class ITracer(Protocol):
    """链路追踪接口"""
    def span(self, name: str, **kwargs: Any) -> "Span": ...
    def event(self, name: str, **kwargs: Any) -> None: ...

class LangfuseTracer:
    """Langfuse 实现 - SDK 缺失时降级为 NoOpTracer"""
    def __init__(self, config: dict) -> None:
        try:
            from langfuse import Langfuse  # type: ignore
            self._client = Langfuse(**config)
        except ImportError:
            self._client = None  # 静默降级

    def span(self, name: str, **kwargs: Any) -> "Span":
        if self._client is None:
            return NoOpSpan()
        return self._client.span(name=name, **kwargs)
```

### 9.7 集成测试隔离

为保证自包含属性,集成测试**仅在 `dota_helper/tests/` 内进行**,
不调用既有 `dota_helper/tests/` 下的任何 fixture 或测试函数。

```python
# dota_helper/tests/conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def package_root() -> Path:
    """指向 dota_helper/ 自身,绝不引用 dota_helper 上层目录"""
    return Path(__file__).parent.parent

@pytest.fixture
def match_fixture() -> dict:
    """独立测试 fixture(match_8893253595.json)"""
    import json
    fixture_path = Path(__file__).parent / "fixtures" / "match_8893253595.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)
```

---

## 十、配置体系

### 10.1 review_config.yaml

> 配置文件位于 `dota_helper/config/review_config.yaml`(v1.1 起移入独立包内)。

```yaml
# dota_helper/config/review_config.yaml
# 赛后复盘 Agent 配置（独立于 dota_helper 顶层 config）

review:
  # 全局配置
  max_total_iterations: 15          # 最大总迭代次数
  max_tokens: 100000                # 最大 Token 消耗
  enable_parallel_phases: true      # 是否并行执行分析阶段
  enable_background_review: true    # 是否启用后台自我审查
  enable_context_compression: true  # 是否启用上下文压缩

  # 预算控制
  budget:
    completion_threshold: 0.9       # Token 完成阈值 (90%)
    diminishing_threshold: 500      # 边际递减阈值 (tokens)
    min_continuations: 3            # 最少继续次数后才检测递减

  # 停止验证
  verification:
    min_confidence: 0.6             # 最低置信度
    required_phases:                # 必须完成的分析阶段
      - laning
      - teamfight
      - economy
      - decisions
    max_verification_retries: 2     # 验证未通过时最多重试次数

  # 上下文压缩
  compression:
    head_protect_count: 2           # 保护头部消息数
    tail_token_budget: 20000        # 尾部保护 Token 预算
    target_max_tokens: 15250        # 压缩后目标 Token 数
    summary_token_budget: 750       # 摘要 Token 预算

  # 分析阶段配置
  phases:
    laning:
      max_iterations: 3
      label: "对线期分析"
      time_range: [0, 600]          # 0-10 分钟
    teamfight:
      max_iterations: 5
      label: "团战分析"
      time_range: [600, 1500]       # 10-25 分钟
    economy:
      max_iterations: 2
      label: "经济分析"
      time_range: null              # 全时段
    decisions:
      max_iterations: 3
      label: "决策点分析"
      time_range: null              # 全时段
    vision:
      max_iterations: 2
      label: "视野分析"
      time_range: null              # 全时段

  # 记忆配置
  memory:
    enable_skill_extraction: true   # 是否自动提取技能
    skill_confidence_threshold: 0.7 # 技能沉淀最低置信度
    max_persistent_notes: 100       # 最大持久笔记数
    max_skills: 50                  # 最大技能数

  # 报告配置
  report:
    output_format: "markdown"       # 输出格式
    save_to_file: true              # 是否保存到文件
    output_dir: "data/reviews"      # 报告输出目录
    include_evidence: true          # 报告中是否包含数据引用
```

---

## 十一、可观测性

### 11.1 Trace 接入点

| 接入点 | Trace 类型 | 记录内容 |
|-------|-----------|---------|
| 复盘启动 | Span | match_id、比赛基本信息 |
| 数据获取 | Span | API 调用耗时、数据完整性 |
| 战略循环 | Span | 策略制定过程、预算分配 |
| 战术循环（每阶段） | Span | 迭代次数、Token 消耗、置信度变化 |
| LLM 调用 | Span | 提示词 Token、响应 Token、耗时 |
| 停止验证 | Span | 验证结果、blocking_reasons |
| 报告生成 | Span | 报告长度、各阶段结论数 |
| 后台审查 | Span | 质量评分、提取的模式数 |

### 11.2 日志规范

```python
# 关键日志事件
logger.info_ctx("复盘分析启动", extra_data={"match_id": match_id})
logger.info_ctx("数据获取完成", extra_data={"duration": duration, "players": 10})
logger.info_ctx("战略评估完成", extra_data={"match_type": "normal", "priority": "teamfight"})
logger.info_ctx("阶段分析完成", extra_data={"phase": "laning", "confidence": 0.82, "iterations": 2})
logger.info_ctx("停止验证通过", extra_data={"confidence": 0.78, "phases_completed": 4})
logger.warning_ctx("停止验证未通过", extra_data={"blocking_reasons": [...]})
logger.info_ctx("复盘报告生成", extra_data={"score": 7.5, "findings": 8})
logger.info_ctx("后台审查完成", extra_data={"quality": 0.85, "skills_extracted": 1})
```

---

## 十二、错误处理与降级

### 12.1 错误分类与处理

| 错误类型 | 处理策略 | 降级方案 |
|---------|---------|---------|
| **OpenDota API 超时** | 重试 3 次（指数退避） | 使用缓存数据 + 标记数据不完整 |
| **OpenDota API 数据不完整** | 等待后重试 | 基于可用数据分析 + 降低置信度 |
| **LLM 调用失败** | 重试 2 次 | 切换到备用模型或规则驱动分析 |
| **LLM 响应质量低** | 补充提示重新生成 | 使用简化分析模板 |
| **Token 预算耗尽** | 立即停止当前阶段 | 基于已有分析生成部分报告 |
| **单个分析阶段失败** | 跳过该阶段 | 标记为"未完成"，降低整体置信度 |
| **后台审查失败** | 静默失败 | 不影响主流程，仅记录日志 |

### 12.2 降级策略

```
降级层次:

  Level 0: 完整分析（所有阶段 + 并行 + 后台审查）
    ↓ [预算不足 / 部分失败]
  Level 1: 精简分析（仅必要阶段 + 串行）
    ↓ [LLM 不可用]
  Level 2: 规则驱动分析（基于预定义规则的分析模板）
    ↓ [数据不完整]
  Level 3: 数据摘要（仅输出比赛数据摘要，不做深度分析）
```

---

## 十三、实施路线图

### 13.1 分阶段实施

| 阶段 | 内容 | 验收标准 | 依赖 | 状态 |
|------|------|---------|------|------|
| **阶段 1: 数据层** | API 扩展 + 数据模型定义 | OpenDota 数据获取完整、MatchData 模型验证 | 无 | ✅ 已完成 (2026-07-16) |
| **阶段 2: 核心骨架** | 预算控制 + 停止验证 + 提示词构建 | 单元测试覆盖、接口契约验证 | 阶段 1 | ✅ 已完成 (2026-07-16) |
| **阶段 3: 单阶段分析** | 战术循环 + 单个分析器（对线期） | 端到端完成一次对线期分析 | 阶段 2 | ✅ 已完成 (2026-07-16) |
| **阶段 4: 全流程** | 战略循环 + 全部分析器 + 报告生成 | 端到端完成一次完整复盘 | 阶段 3 | ✅ 已完成 (2026-07-20) |
| **阶段 5: 并行优化** | 并行子代理 + 上下文压缩 | 并行分析性能提升 > 30% | 阶段 4 | ✅ 已完成 (2026-07-20) |
| **阶段 6: 自我进化** | 后台审查 + 技能沉淀 + 记忆扩展 | 复盘后自动生成技能、记忆持久化 | 阶段 4 | ✅ 已完成 (2026-07-21) |
| **阶段 7: 前端集成** | API 端点 + SSE 流式 + 复盘展示组件 | 前端可实时展示分析进度和报告 | 阶段 4 | ✅ 已完成 (2026-07-22) |
| **阶段 8: Skill 驱动重构** | 层 A 基类增强 + 层 B YAML 增强 + 层 C Skill 驱动扩展 | 分析逻辑声明化，代码精简约 70%，支持 YAML 技能扩展 | 阶段 4 | ✅ 已完成 (2026-07-24) |
| **阶段 9: MCP Server 集成** | 单体文件拆分为模块化 MCP Server + 异步转换 + Agent MCP Client 集成 | 53 个工具注册，MCP Client 可连接调用 | 阶段 8 | ✅ 已完成 (2026-07-26) |
| **阶段 10: ReAct Agent Chat** | ReAct Agent + 聊天前端 + SSE 思考过程流式展示 + 会话管理 | 用户可自由文本对话，Agent 自主推理并调用 MCP 工具，前端实时展示 Thought/Action/Observation 过程 | 阶段 9 | 🔲 待实施 |

#### 13.1.1 已完成阶段详情

**阶段 1: 数据层** (2026-07-16)
- ✅ OpenDotaClient: 独立 HTTP 客户端，支持重试、超时、错误处理
- ✅ MatchFetcher: 比赛数据获取与结构化
- ✅ DataValidator: 数据完整性校验
- ✅ Cache: 比赛数据本地缓存（TTL 支持）
- ✅ MatchData 数据模型: MatchData, PlayerData, PickBan, LaneData, TeamfightData
- ✅ 24 个单元测试全部通过

**阶段 2: 核心骨架** (2026-07-16)
- ✅ IterationBudget: 令牌桶 + 边际递减检测
- ✅ StopVerifier: 三段验证（必要阶段、数据支撑、置信度）
- ✅ PromptBuilder: Stable/Context/Volatile 三层提示词构建
- ✅ 25 个单元测试全部通过

**阶段 3: 单阶段分析** (2026-07-16)
- ✅ LLMClient: 独立 LLM 客户端（基于 OpenAI SDK）
- ✅ TacticalLoop: 战术循环（单阶段深度分析）
- ✅ LaningAnalyzer: 对线期分析器（补刀、消耗、经济）
- ✅ BaseLLMReviewAnalyzer / BaseRuleReviewAnalyzer: 分析器基类
- ✅ 14 个单元测试全部通过
- ✅ 总计 63 个测试全部通过（Phase 1-3）

**阶段 4: 全流程** (2026-07-20)
- ✅ StrategicLoop: 战略循环（比赛类型分类 + 分析策略制定）
- ✅ 5 个分析器全部实现:
  - TeamfightAnalyzer: 团战分析器
  - EconomyAnalyzer: 经济分析器
  - DecisionAnalyzer: 决策分析器
  - VisionAnalyzer: 视野分析器
  - FallbackAnalyzer: 降级分析器（规则驱动，按阶段分发逻辑）
- ✅ ReportBuilder: 报告构建器（聚合分析结果）
- ✅ MarkdownRenderer: Markdown 报告渲染器
- ✅ ReviewOrchestrator: 主编排器（串联完整分析流程）
- ✅ 提示词模板: 5 个阶段模板（tactical_laning/teamfight/economy/decisions/vision.yaml）
- ✅ 端到端测试通过（比赛 ID 8905359313）:
  - 整体置信度: 0.68（≥ 0.6）
  - 5 个分析阶段全部完成
  - 9 条关键发现，2 条改进建议
  - Markdown 报告 1888 字符
  - 6/7 验收标准通过（1 项因视野数据缺失未通过，属预期行为）
- ✅ Bug 修复:
  - JSON 解析: 支持从 markdown 代码块提取 JSON
  - 模板名不匹配: tactical_decision.yaml → tactical_decisions.yaml
  - 置信度计算: 基础置信度从 0.5 提高到 0.6
  - 模型配置: 默认模型改为 deepseek-v4-pro
- ✅ 总计测试通过（Phase 1-4）

**阶段 5: 并行优化** (2026-07-20)
- ✅ TokenCounter: Token 计数器（支持 tiktoken 精确计数 + 字符估算降级）
- ✅ ContextCompressor: 上下文压缩器（三阶段压缩：修剪工具结果、保护头尾、LLM 摘要中间）
- ✅ SubAgent: 独立上下文的子代理（独立消息列表、独立预算配额、失败隔离）
- ✅ TaskQueue: 任务结果收集队列（异步结果收集、顺序保持、部分失败记录）
- ✅ ParallelRunner: 基于 asyncio.Semaphore 的并发控制器（默认最大并发 4）
- ✅ TacticalLoop 集成压缩器: 战术循环支持可选的上下文压缩（每次迭代后检查并压缩）
- ✅ ReviewOrchestrator 并行模式: 支持通过配置切换串行/并行模式
- ✅ 日志增强: 核心分支添加详细 logger.info（步骤标记、迭代状态、压缩统计、并行执行详情）
- ✅ 配置文件: review_config.yaml（enable_parallel_phases、compression 参数）
- ✅ 单元测试: 压缩器三阶段逻辑、并行运行器并发控制和失败隔离
- ✅ 性能测试: 5 个阶段 mock LLM 延迟 500ms，串行 2500ms vs 并行 1020ms，**加速比 59.9%**（远超 30% 要求）
- ✅ 端到端测试: 比赛 ID 8904322271 完整复盘流程验证通过
- ✅ 总计测试通过（Phase 1-5）

**阶段 6: 自我进化** (2026-07-21)
- ✅ IFourLayerMemory / ISkillStore: 四层记忆系统接口定义
- ✅ SessionArchive: Level 1 会话归档（SQLite 存储，支持按 match_id/时间/英雄查询，自动清理旧条目）
- ✅ PersistentNotes: Level 2 持久笔记（JSON 存储，关键词检索，容量限制）
- ✅ SkillStore: Level 3 技能沉淀（SKILL.md + frontmatter，版本号自增，Jaccard 冲突检测）
- ✅ DreamRecap: 复盘后整合（LLM 驱动洞察提取 + 模式识别 + 持久化）
- ✅ FourLayerMemory: 四层记忆统一入口
- ✅ BackgroundReviewer: 异步后台审查（质量评估 + 模式提取 + 记忆沉淀，失败静默）
- ✅ PromptLoader: 提示词加载器（YAML 模板加载，文件修改时间缓存失效）
- ✅ 提示词模板: background_review.yaml, dream_recap.yaml
- ✅ 集成到 ReviewOrchestrator: 报告生成后自动 spawn() 后台审查，不阻塞主流程
- ✅ 单元测试: 33 个测试全部通过（17 个记忆系统 + 10 个后台审查 + 6 个集成测试）
- ✅ 代码审查: 9 个问题全部修复（2 个 major + 7 个 minor）
  - PersistentNotes ID 生成改为单调递增计数器，避免删除后重复
  - BackgroundReviewer.spawn 使用 asyncio.get_running_loop() 替代已弃用的 get_event_loop()
  - DreamRecap JSON 解析代码去重，提取通用方法
  - FourLayerMemory.load_skills 接口文档补充
  - SkillStore._parse_skill_file 正则表达式放宽，支持灵活格式
  - SessionArchive.__del__ 空实现移除
  - PromptLoader 缓存添加文件修改时间失效机制
  - BackgroundReviewer._serialize_report 效率优化
  - SessionArchive._cleanup_old_entries SQL 性能优化（使用主键索引）
- ✅ 模块重命名: types/ → domain_types/（避免与 Python 标准库 types 模块冲突）
- ✅ 总计测试通过（Phase 1-6）

**阶段 7: 前端集成** (2026-07-22)
- ✅ 后端 API 端点: 5 个 RESTful 端点全部实现
  - POST /api/review: SSE 流式返回分析进度
  - GET /api/review/{match_id}/status: 查询复盘状态
  - GET /api/review/{match_id}/report: 获取完整报告
  - POST /api/review/{match_id}/interrupt: 中断复盘
  - GET /api/review/history: 复盘历史列表
- ✅ 前端组件: 5 个 Vue 3 + TypeScript 组件
  - ReviewPanel.vue: 复盘面板（主组件）
  - ReviewProgress.vue: 分析进度展示
  - ReviewTimeline.vue: 分析时间线
  - ReviewReport.vue: 复盘报告展示（Markdown 渲染）
  - ReviewHistory.vue: 复盘历史列表
- ✅ 前端页面: ReviewView.vue（路由 /review）
- ✅ 状态管理: stores/review.ts（Pinia）
- ✅ 组合式函数: composables/useReview.ts（SSE 流式处理）
- ✅ API 客户端: api/review.ts（fetch 封装）
- ✅ 类型定义: types/review.ts（镜像后端类型）
- ✅ 路由注册: router/index.ts 添加 /review 路由
- ✅ 后端集成测试: tests/integration/test_api_endpoints.py（7 个测试用例）
- ✅ 前端单元测试: 6 个测试文件，13 个测试用例
- ✅ Bug 修复:
  - web/app.py: match_id 表达式运算符优先级问题
  - web/app.py: 缺少 asyncio 导入
  - dota_helper/domain_types/report.py: MatchSummary 和 ReviewReport 缺少 to_dict() 方法
  - dota_helper/data_source/opendota_client.py: OpenDotaClient 跨请求复用时的 event loop 关闭错误
- ✅ 端到端验证: 比赛 ID 8905359313 完整复盘流程
  - SSE 流式进度正常
  - 状态查询正常
  - 报告获取正常（45:57 时长，39:53 比分，Windranger 英雄，7.4/10 评分，68% 置信度）
  - 中断功能正常
  - 历史列表正常
- ✅ 前端构建成功
- ✅ 总计测试通过（Phase 1-7）

**阶段 8: Skill 驱动架构重构** (2026-07-24)

基于 `docs/superpowers/plans/post-match-review-agent/2026-07-22-skill-driven-refactor.md` 设计文档，分三层渐进重构分析器架构。

**层 A: 基类增强** — 消除 ~650 行重复代码
- ✅ BaseLLMReviewAnalyzer: 提升 `parse_response()` 和 `build_prompt()` 到基类
  - parse_response(): 5 层 JSON 解析降级链（conclusions → analysis → 单对象 → 文本提取）
  - build_prompt(): 模板方法模式，子类仅需实现 `_format_domain_data()`
  - 辅助方法: `_parse_conclusion()`、`_extract_from_analysis()`、`_fallback_single_conclusion()`、`_parse_conclusions_from_text()`
- ✅ 5 个分析器精简: 删除各自重复的 parse_response() 和 build_prompt()（每个约 130 行）
- ✅ VisionAnalyzer: 保留 `validate_result()` 降级逻辑（置信度阈值 0.4）
- ✅ 基类单元测试: 19 个测试全部通过

**层 B: YAML 增强** — 分析逻辑声明化
- ✅ 5 个 YAML 模板增强: 添加 analysis_framework / data_requirements / output_schema / metadata
  - tactical_laning.yaml: 4 个 data_requirements（player_stats × 3 + player_lane × 1），完全声明化
  - tactical_teamfight.yaml: 1 个 data_requirements（list_items），列表遍历声明化
  - tactical_economy/decisions/vision.yaml: data_requirements 使用 format: custom，Python 逻辑保留
- ✅ DataFormatter: 通用数据格式化器
  - 支持 5 种格式: player_stats / player_lane / list_items / simple / custom
  - 值变换: time_minutes / time_seconds / player_names / signed_int
  - secondary_field: 支持主字段+次字段联合输出（如补刀+反补）
  - 常量: LANE_NAMES（分路编号→名称映射）
- ✅ PromptBuilder 增强: 支持 YAML 声明注入
  - Stable 层: `{analysis_framework}` + `{output_schema}` 占位符替换
  - Context 层: 自动注入 DataFormatter 格式化的领域数据
  - Volatile 层: `{formatted_data}` 占位符替换
  - 向后兼容: 旧 YAML（无 data_requirements）行为不变
- ✅ 分析器精简:
  - LaningAnalyzer: 删除 `_format_domain_data()` 和 `_get_lane_name()`（代码量 -60%）
  - TeamfightAnalyzer: 精简为仅保留汇总统计逻辑
  - Economy/Decision/Vision: 保留 Python `_format_domain_data()`，YAML 仅声明文档价值
- ✅ base.py: `_format_domain_data()` 从抽象方法改为普通方法，默认返回空字符串
- ✅ DataFormatter 单元测试: 25 个测试全部通过
- ✅ PromptBuilder 增强测试: 6 个新增测试全部通过
- ✅ 端到端验证: 比赛 ID 8909780728
  - 5 个阶段提示词构建正常
  - Stable 层包含 analysis_framework 和 output_schema
  - Context/Volatile 层包含 DataFormatter 格式化的领域数据
  - 完整复盘流程正常（FallbackAnalyzer 降级模式）
- ✅ 总计 69 个层 B 相关测试通过

**层 C: Skill 驱动扩展** — YAML 技能定义动态生成分析能力
- ✅ IAnalysisSkillStore 协议: 分析技能存储接口（YAML 格式）
  - save_analysis_skill / load_analysis_skill / list_analysis_skills
  - 与 ISkillStore（经验技能，Markdown 格式）互补
- ✅ SkillStore 双协议实现: `SkillStore(ISkillStore, IAnalysisSkillStore)`
  - 经验技能: `{skills_dir}/*.md`（Markdown + YAML frontmatter）
  - 分析技能: `{skills_dir}/analysis/*.yaml`（纯 YAML）
  - 内置技能: `prompts/skills/*.yaml`（通过 load_builtin_skill / list_builtin_skills 访问）
- ✅ SkillDrivenAnalyzer: Skill 驱动分析器主类
  - 继承 BaseLLMReviewAnalyzer，复用 parse_response() 和 build_prompt()
  - 创建方式: `from_yaml()` / `from_skill_store()` / 构造函数
  - phase_name 和 _format_domain_data() 均从 YAML 技能定义动态生成
  - validate_result() 使用技能定义中的 min_confidence 阈值
  - _validate_skill_definition(): 验证必要字段（phase/name/stable_layer/volatile_layer）
- ✅ SkillDrivenPromptBuilder: 技能驱动提示词构建器
  - 继承 PromptBuilder，从 skill_definition 字典直接加载模板
  - 不依赖 prompts/tactical_{phase}.yaml 文件
  - 复用父类 _build_stable_layer / _build_context_layer / _build_volatile_layer
- ✅ 3 个内置分析技能 YAML:
  - roshan_timing.yaml: Roshan 时机分析（objectives + teamfight_data）
  - ward_efficiency.yaml: 守卫效率分析
  - late_game_decisions.yaml: 后期决策分析
- ✅ Runtime 集成: `_load_custom_skills()` 自动发现并注册 SkillDrivenAnalyzer
  - 不覆盖内置分析阶段（laning/teamfight/economy/decisions/vision）
- ✅ PostMatchReviewAPI 集成:
  - list_analysis_skills(): 列出所有可用分析技能（内置 + 用户自定义）
  - register_analysis_skill(): 注册用户自定义分析技能
- ✅ 层 C 单元测试:
  - test_skill_driven_analyzer.py: 19 个测试（创建、验证、格式化、SkillStore 集成）
  - test_skill_driven_prompt_builder.py: SkillDrivenPromptBuilder 测试
  - test_skill_store_enhanced.py: 12 个测试（IAnalysisSkillStore 双协议、内置技能加载）
- ✅ 总代码精简: ~70%（层 A -650 行 + 层 B 分析器精简 + 层 C 零 Python 扩展）

**阶段 9: MCP Server 集成** (2026-07-26)

基于 `docs/bugs/002_dota_helper_optimization_items.md` 优化清单，将单体 MCP Server 拆分为模块化结构。

- ✅ 单体拆分: `dota2_fastmcp.py`（6503 行）→ 8 个工具模块 + 6 个辅助模块
- ✅ 异步转换: 所有同步 `requests` 调用 → `httpx.AsyncClient`，`time.sleep()` → `asyncio.sleep()`
- ✅ 统一客户端: `AsyncOpenDotaClient`（单例模式，实例级缓存，指数退避重试 + 429 处理）
- ✅ 47 个迁移工具（8 个模块）:
  - match_tools: 6 工具（比赛详情/物品/解析请求）
  - hero_tools: 12 工具（英雄列表/克制/RAG/统计/能力）
  - player_tools: 7 工具（玩家信息/战绩/英雄池/队友/总计）
  - team_tools: 9 工具（职业比赛/战队/联赛/搜索）
  - ward_tools: 5 工具（眼位分析/热力图/HTML报告/统计）
  - search_tools: 1 工具（SerpApi 搜索，中文→英文回退）
  - stats_tools: 7 工具（MMR/记录/场景统计/常量）
- ✅ 6 个新增复盘工具（review_tools）:
  - analyze_ward_efficiency / analyze_roshan_timing / analyze_late_game_decisions
  - generate_review_report / search_player_trends / compare_match_performance
- ✅ 辅助模块:
  - opendota.py: 统一异步 OpenDota 客户端（含 `AsyncOpenDotaClient = OpenDotaClient` 别名）
  - hero_names.py: 英雄中文名映射 + 段位格式化
  - map_config.py: 地图配置 + 区域模板 + 时间格式化
  - rag_index.py: 英雄 RAG 检索（FAISS 可选降级）
  - text_processing.py: 全文抓取 + 处理
  - ward_visualization.py: 眼位可视化核心（热力图/散点图/交互HTML）
- ✅ 静态资源迁移: 地图图片 + 眼位图标 + 英雄文本 + 区域模板 → `mcp_server/resources/`
- ✅ MCP Client 集成: `core/agent.py` 添加 `connect_mcp_server()` / `call_mcp_tool()` / `get_mcp_tools()`
- ✅ 日志增强: 8 个工具文件添加 351 条 logger 调用（189 info / 125 warning / 26 error / 11 debug）
  - 所有 53 个工具函数均有入口日志、API 调用日志、异常日志、完成日志
  - 关键分支覆盖: API 错误/数据校验/重试逻辑/回退策略/缓存命中/文件 I/O
- ✅ Bug 修复:
  - ward_tools.py:993 中文引号与外层双引号冲突
  - opendota.py: 添加 `AsyncOpenDotaClient` 别名
  - tools/__init__.py: 补全所有 8 个工具模块导入
- ✅ 验证:
  - 53 个工具全部注册成功（`create_server()._tool_manager._tools` 验证）
  - 18 个 Python 文件语法检查通过
  - 226 个 PostMatchReview 单元测试通过

#### 13.1.2 待实施阶段详情

**阶段 10: ReAct Agent Chat** (待实施)

> **设计目标**: 将 dota_helper 从"输入 match_id → 一键触发复盘"模式升级为
> **"自由文本聊天 → ReAct Agent 推理"**模式，与 Dota2-Agent 交互范式对齐。
> 用户可自由提问（如"分析比赛 8909780728 的视野"、"幻影刺客克制谁"），
> Agent 通过 ReAct 循环（Thought → Action → Observation）自主调用 53 个 MCP 工具完成多步推理，
> 前端实时展示推理过程，历史记录以聊天会话形式组织。

**10.1 ReAct Agent 核心实现**

新建 `dota_helper/agent/` 模块，实现 ReAct 推理循环：

```
dota_helper/agent/
├── __init__.py
├── react_agent.py          # DotaHelperReActAgent 主类
├── react_loop.py           # ReAct 循环核心（think → act → observe）
├── tool_dispatcher.py      # MCP 工具调用分发器
├── response_parser.py      # LLM 响应解析（Action/Final Answer/Thought 提取）
├── session_manager.py      # 会话管理（会话创建/加载/持久化）
└── prompts/
    └── react_system.py     # ReAct 系统提示词构建
```

**DotaHelperReActAgent 类设计**（参照 Dota2-Agent `dota2_agent.py`）：

```python
class DotaHelperReActAgent:
    """dota_helper ReAct Agent
    
    ReAct (Reasoning + Acting) 范式:
    1. Thought — Agent 思考分析当前问题
    2. Action  — 调用 MCP 工具获取数据
    3. Observation — 观察工具返回结果
    4. 循环或给出 Final Answer
    """
    
    def __init__(
        self,
        mcp_server_path: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        max_iterations: int = 20,
        max_observation_chars: int = 12000,
        log_dir: str = "logs",
        enable_logging: bool = True,
    ) -> None: ...
    
    async def connect_mcp(self) -> None:
        """连接 MCP Server（stdio 模式）"""
        ...
    
    async def disconnect_mcp(self) -> None:
        """断开 MCP Server"""
        ...
    
    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """调用 MCP 工具"""
        ...
    
    async def run(self, user_input: str) -> str:
        """执行 ReAct 循环，返回最终答案"""
        ...
    
    async def run_stream(self, user_input: str) -> AsyncGenerator[Dict[str, Any], None]:
        """执行 ReAct 循环（流式输出）
        
        Yields:
            Dict: 事件字典，类型包括:
                - {"type": "session", "session_id": ..., "conversation_id": ...}
                - {"type": "thought", "content": "思考内容"}
                - {"type": "action", "content": "工具名", "input": {...}}
                - {"type": "observation", "content": "工具返回结果"}
                - {"type": "final", "content": "最终答案", "ward_html": "..."}
        """
        ...
    
    def start_new_session(self) -> None: ...
    def load_recent_context_from_session(self, conversations: List[Dict]) -> None: ...
```

**ReAct 循环流程**（与 Dota2-Agent `run_stream()` 对齐）：

```
用户自由文本输入
     │
     ▼
┌──────────────────┐
│ 构建消息列表      │ ─── 系统提示 + 历史上下文 + 记忆检索 + 用户输入
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│ ReAct 循环（最多 max_iterations 次迭代）          │
│                                                    │
│  1. 调用 LLM（流式）                               │
│     │                                              │
│     ▼                                              │
│  2. 解析 LLM 响应                                  │
│     │                                              │
│     ├── 检测到 "Thought:" → yield thought 事件     │
│     │                                              │
│     ├── 检测到 "Final Answer:" → 结束循环          │
│     │   yield final 事件（含 ward_html）           │
│     │                                              │
│     ├── 检测到 "Action:" + "Action Input:"         │
│     │   │                                          │
│     │   ├── yield action 事件                      │
│     │   ├── 调用 MCP 工具 → observation            │
│     │   ├── yield observation 事件                  │
│     │   └── 追加到消息列表，继续循环                │
│     │                                              │
│     └── 无有效格式 → 追加格式纠正提示，继续循环      │
│                                                    │
└──────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│ 后处理             │ ─── 记忆提交 + 日志归档 + ward HTML 提取
└──────────────────┘
```

**系统提示词构建**：将 53 个 MCP 工具的名称、参数 Schema 和功能描述注入系统提示，
使 LLM 知道可调用哪些工具。支持 Skill 懒加载（按需 load_skill 获取工具详细用法）。

**10.2 Web 服务层**

新建 `dota_helper/web_app.py`，基于 FastAPI 提供 Web 服务：

```python
# dota_helper/web_app.py
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Dota Helper ReAct Chat")
agent = DotaHelperReActAgent(enable_logging=True)

# 静态文件服务
app.mount("/ward_analysis", StaticFiles(directory="ward_analysis", html=True))

@app.get("/")
async def index() -> FileResponse:
    """主页"""
    return FileResponse(WEB_DIR / "index.html")

@app.get("/api/history")
async def history() -> Dict:
    """获取会话历史列表"""
    ...

@app.get("/api/sessions/{session_id}")
async def session(session_id: str) -> Dict:
    """获取指定会话的所有对话"""
    ...

@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """聊天流式响应（SSE/NDJSON）"""
    # 调用 agent.run_stream() → 流式返回 thought/action/observation/final 事件
    ...

@app.on_event("startup")
async def startup() -> None:
    await agent.connect_mcp()

@app.on_event("shutdown")
async def shutdown() -> None:
    await agent.disconnect_mcp()
```

**API 端点汇总**（与 Dota2-Agent 对齐 + 保留复盘专用端点）：

| 端点 | 方法 | 说明 | 事件源 |
|------|------|------|--------|
| `/` | GET | 主页（聊天界面） | — |
| `/api/chat` | POST | 聊天流式响应 | `agent.run_stream()` |
| `/api/history` | GET | 会话历史列表 | 日志文件 |
| `/api/sessions/{id}` | GET | 指定会话详情 | 日志文件 |
| `/api/conversations/{sid}/{cid}` | GET | 单条对话详情 | 日志文件 |
| `/ward_analysis/` | Static | Ward HTML 静态文件 | MCP 工具生成 |

**保留既有复盘端点**（§9.3 中定义的端点仍然可用，供程序化接入）：
- `POST /api/review` → `PostMatchReviewAPI.review_stream()`
- `GET /api/review/{match_id}/status` → `PostMatchReviewAPI.get_status()`
- `GET /api/review/{match_id}/report` → `PostMatchReviewAPI.get_report()`

**10.3 聊天前端**

新增 Vue 3 + TypeScript 聊天组件，位于 `frontend/src/components/chat/`：

```
frontend/src/
├── components/chat/
│   ├── ChatView.vue         # 聊天主页面（路由 /chat）
│   ├── ChatInput.vue        # 消息输入框
│   ├── ChatMessage.vue      # 单条消息渲染（Markdown 渲染）
│   ├── ChatBubble.vue       # Agent 推理气泡（Thought/Action/Observation）
│   ├── WardIframe.vue       # Ward HTML iframe 嵌入组件
│   └── PresetCards.vue      # 预设问题卡片
├── composables/useChat.ts   # 聊天 SSE 流式处理
├── stores/chat.ts           # 聊天状态管理（Pinia）
├── types/chat.ts            # 聊天类型定义
└── api/chat.ts              # 聊天 API 客户端（fetch 封装）
```

**前端交互模式**：

| 维度 | 设计 |
|------|------|
| **输入方式** | 自由文本聊天输入（非 match_id 输入框） |
| **推理展示** | SSE 流实时展示 Thought/Action/Observation 过程 |
| **最终答案** | Markdown 渲染 Final Answer 内容 |
| **可视化嵌入** | 检测到 `ward_html` 路径时，通过 `<iframe>` 嵌入交互式眼位分析 HTML |
| **历史记录** | 侧边栏显示聊天会话历史，点击可回看 |
| **预设问题** | 首页展示预设问题卡片（"分析比赛 XXX 的视野"、"英雄克制关系"等） |

**SSE 事件消费**（`useChat.ts` composable）：

```typescript
// composables/useChat.ts
export function useChat() {
  const messages = ref<ChatMessage[]>([]);
  const isConnected = ref(false);

  async function sendMessage(text: string, sessionId?: string) {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });

    // NDJSON 流解析
    for await (const event of parseNDJSON(response)) {
      switch (event.type) {
        case "session":
          // 更新会话信息
          break;
        case "thought":
          // 追加思考气泡
          messages.value.push({ role: "agent", type: "thought", content: event.content });
          break;
        case "action":
          // 追加行动气泡
          messages.value.push({ role: "agent", type: "action", content: event.content, input: event.input });
          break;
        case "observation":
          // 追加观察气泡
          messages.value.push({ role: "agent", type: "observation", content: event.content });
          break;
        case "final":
          // 追加最终答案 + 嵌入 Ward HTML
          messages.value.push({ role: "agent", type: "final", content: event.content, wardHtml: event.ward_html });
          break;
      }
    }
  }

  return { messages, isConnected, sendMessage };
}
```

**预设问题卡片**（引导用户快速开始）：

| 卡片标题 | 触发消息 |
|---------|---------|
| 📊 分析最近比赛 | "分析我最近的一场比赛" |
| 👁️ 视野分析 | "分析比赛 [match_id] 的视野" |
| ⚔️ 英雄克制 | "[英雄名]的克制英雄有哪些" |
| 🏆 战队分析 | "分析 [战队名] 最近的比赛" |
| 📈 玩家趋势 | "查看 [玩家名] 的最近趋势" |

**10.4 会话管理**

| 组件 | 说明 |
|------|------|
| **会话创建** | 新对话自动创建 session，分配 session_id |
| **会话持久化** | 每次对话完成后保存到 `logs/session_{id}.json` |
| **会话加载** | 从历史列表选择会话后，加载历史对话到 Agent 上下文 |
| **上下文窗口** | 保留最近 N 轮对话作为 Agent 上下文，超出部分摘要压缩 |
| **Ward HTML 关联** | 对话中产生的 ward_html 路径记录到会话数据，历史回看时恢复 iframe |

**10.5 与既有模块的集成关系**

```
┌──────────────────────────────────────────────────────────────┐
│                    新增: ReAct Agent 层                       │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  agent/react_agent.py  (DotaHelperReActAgent)          │  │
│  │  ├─ ReAct 循环: Thought → Action → Observation         │  │
│  │  ├─ MCP Client → 调用 53 个工具                        │  │
│  │  ├─ 会话管理: 日志持久化 + 上下文维护                    │  │
│  │  └─ 记忆检索: 四层记忆系统                               │  │
│  └──────────────┬─────────────────────────────────────────┘  │
├─────────────────┼────────────────────────────────────────────┤
│                 │ 复用                                       │
│  ┌──────────────▼─────────────────────────────────────────┐  │
│  │  既有模块 (零修改)                                      │  │
│  │  ├─ mcp_server/ — 53 个 MCP 工具                       │  │
│  │  ├─ facade/ — PostMatchReviewAPI (复盘专用)             │  │
│  │  ├─ llm/ — LLMClient                                   │  │
│  │  ├─ memory/ — 四层记忆系统                              │  │
│  │  └─ data_source/ — OpenDotaClient                      │  │
│  └────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│  新增: Web 层                                                │
│  ├─ web_app.py — FastAPI 入口 (chat + review API)          │
│  └─ frontend/src/components/chat/ — Vue 3 聊天组件          │
└──────────────────────────────────────────────────────────────┘
```

**关键约束**：
- `agent/` 模块仅依赖 `mcp_server/`、`llm/`、`memory/`，**不依赖** `orchestrator/` 或 `analyzers/`
- ReAct Agent 和 PostMatchReviewAPI **并存**：前者面向聊天交互，后者面向程序化复盘
- `web_app.py` 同时暴露聊天端点和复盘端点
- 前端使用 **Vue 3 + TypeScript + Vite**，聊天组件与既有复盘组件并存于 `frontend/src/`
- 前端**不包含解析逻辑**，所有业务逻辑和解析由后端统一处理（§D.3 约定保留）

**10.6 实施子任务**

| 子任务 | 依赖 | 产出 |
|--------|------|------|
| 10a. ReAct Agent 核心实现 | 阶段 9 | `agent/react_agent.py` + `react_loop.py` + `response_parser.py` + 单元测试 |
| 10b. MCP 工具分发器 | 10a | `agent/tool_dispatcher.py`（MCP Client stdio 连接 + 工具调用） |
| 10c. 会话管理 | 10a | `agent/session_manager.py`（会话创建/持久化/加载/上下文维护） |
| 10d. ReAct 系统提示词 | 10a | `agent/prompts/react_system.py`（53 工具描述注入 + Skill 懒加载） |
| 10e. Web 服务层 | 10a-10d | `web_app.py`（FastAPI + 静态文件 + chat/review 端点） |
| 10f. 聊天前端 | 10e | Vue 3 聊天组件（ChatView/Input/Message/Bubble/WardIframe/PresetCards）+ useChat.ts + chat.ts store |
| 10g. 集成测试 | 10e-10f | 端到端测试（自由文本 → ReAct 推理 → 工具调用 → 前端展示） |

### 13.2 执行方式

**采用 Subagent-Driven Development（子代理驱动开发）**

每个任务分派一个独立子代理执行，任务间进行两阶段审查（Spec Compliance + Code Quality），快速迭代。

**执行流程:**

```
实施计划 (本文档 13.1)
  │
  ▼
详细任务清单 (docs/superpowers/plans/2026-07-15-post-match-review-implementation.md)
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  Subagent-Driven Development 循环                       │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐   │
│  │ 分派任务  │ ─▶ │ 子代理执行 │ ─▶ │ 两阶段审查        │   │
│  │ Task N   │    │ TDD 模式  │    │ 1. Spec 合规审查   │   │
│  └──────────┘    └──────────┘    │ 2. 代码质量审查    │   │
│       ▲                          └────────┬─────────┘   │
│       │                                   │              │
│       │         ┌──────────┐              │              │
│       └──────── │ 通过审查  │ ◀────────────┘              │
│                 │ 进入下一任务│                             │
│                 └──────────┘                              │
└─────────────────────────────────────────────────────────┘
```

**审查要点:**

| 审查阶段 | 检查内容 |
|---------|---------|
| **Spec Compliance** | 实现是否覆盖设计文档中对应组件的所有要求？接口契约是否匹配？ |
| **Code Quality** | 代码是否遵循项目规范（Type Hints、依赖注入、接口+策略模式）？测试是否充分？ |

**子代理分派规则:**

| 规则 | 说明 |
|------|------|
| 一个任务一个子代理 | 每个 Task 分派独立子代理，避免上下文污染 |
| 提供完整上下文 | 子代理需获得设计文档对应章节 + 实施计划对应 Task 的完整内容 |
| TDD 强制执行 | 子代理必须遵循 编写测试 → 验证失败 → 实现代码 → 验证通过 的流程 |
| 审查后合并 | 通过两阶段审查后才合并代码，进入下一任务 |

### 13.3 详细实现参考

| 设计主题 | 详细文档 |
|---------|---------|
| 赛后复盘 Agent 综合设计 | `docs/superpowers/plans/post-match-review-agent/2026-07-13-post-match-review-agent.md` |
| Claude Code 设计模式分析 | `docs/superpowers/plans/post-match-review-agent/2026-07-13-claude-code-patterns.md` |
| 前沿 Agent 理念融合 | `docs/superpowers/plans/post-match-review-agent/2026-07-10-frontier-agent-concepts.md` |
| 产品定位转型 | `docs/superpowers/plans/post-match-review-agent/2026-07-10-product-transformation.md` |
| OpenDota API 参考 | `docs/superpowers/plans/post-match-review-agent/2026-07-10-opendota-api-reference.md` |

---

## 附录

### A. 术语表

| 术语 | 定义 |
|------|------|
| **Loop Agent** | 迭代式自主执行的 Agent 架构，通过循环不断优化输出 |
| **Stop Hooks** | 在 Agent 尝试停止前执行的验证钩子，确保满足终止条件 |
| **双循环架构** | 战略循环（规划/评估）+ 战术循环（执行/验证）的嵌套循环结构 |
| **迭代预算** | 控制 Agent 迭代次数的令牌桶机制，防止无限循环 |
| **边际递减检测** | 当连续多轮分析的增量贡献低于阈值时，判定为边际收益递减 |
| **有损压缩** | 通过修剪、摘要等方式减少上下文大小，允许部分信息丢失 |
| **Dream/Recap** | 复盘完成后整合关键发现并持久化为结构化记忆的模式 |
| **GEPA** | Hermes Agent 的自我进化引擎，类似反向传播优化 prompt |
| **四层记忆** | Prompt Memory → Session Archive → Persistent Notes → Dynamic Skills |
| **Batch 并行** | Claude Code 的并行子代理模式，将任务分解后并发执行 |

### B. 参考资料

| 来源 | 链接/路径 |
|------|---------|
| Hermes Agent | https://hermesagentai.cn/ |
| Anthropic Long-running Harness | https://www.anthropic.com/engineering/harness-design-long-running-apps |
| Google ADK LoopAgent | https://google.github.io/adk-docs/agents/workflow-agents/loop-agents/ |
| Claude Code 项目分析 | `docs/architecture_upgrade/ARCHITECTURE_ANALYSIS.md` 第二十二章 |
| Cve2PoC Dual-Loop | https://arxiv.org/pdf/2602.05721 |
| Loong Adaptive Context | https://arxiv.org/pdf/2605.30274 |
| OpenDota API | https://docs.opendota.com/ |

### C. 文档版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-07-15 | 初始版本,完整独立架构设计 |
| v1.1 | 2026-07-15 | **目录结构重构**: 复盘 Agent 改为 `dota_helper/` 独立顶级包,与既有 `core/`/`analyzers/`/`skills/`/`memory/`/`utils/` 零代码依赖。所有 LLM 客户端、记忆、技能、可观测性、Prompt 模板、配置、运行时数据均在包内自包含。详见 §3.3 / §6.4 / §9 |
| v1.2 | 2026-07-16 | **实施进展更新**: 阶段 1-3 已完成（63 个测试全部通过）。阶段 1 实现数据层（OpenDotaClient/MatchFetcher/DataValidator/Cache/MatchData）；阶段 2 实现核心骨架（IterationBudget/StopVerifier/PromptBuilder）；阶段 3 实现单阶段分析（LLMClient/TacticalLoop/LaningAnalyzer/分析器基类）。下一步：阶段 4 全流程（战略循环 + 全部分析器 + 报告生成）。详见 §13.1.1 |
| v1.3 | 2026-07-20 | **阶段 4 全流程完成**: 实现战略循环（StrategicLoop）、5 个分析器（Teamfight/Economy/Decision/Vision/Fallback）、报告生成（ReportBuilder/MarkdownRenderer）、主编排器（ReviewOrchestrator）。端到端测试通过（比赛 ID 8905359313），整体置信度 0.68，5 个分析阶段全部完成。修复 4 个关键问题：JSON 解析支持 markdown 代码块、模板名不匹配、置信度计算优化、默认模型改为 deepseek-v4-pro。详见 §13.1.1 |
| v1.4 | 2026-07-21 | **阶段 6 自我进化完成**: 实现四层记忆系统（SessionArchive/PersistentNotes/SkillStore/DreamRecap）、后台审查器（BackgroundReviewer）、提示词加载器（PromptLoader）。33 个单元测试全部通过。代码审查修复 9 个问题（2 个 major + 7 个 minor）。模块重命名 types/ → domain_types/（避免与标准库冲突）。详见 §13.1.1 |
| v1.5 | 2026-07-23 | **阶段 8 层 A/B 完成**: 层 A 基类增强：将 parse_response() 和 build_prompt() 提升到 BaseLLMReviewAnalyzer，消除 ~650 行重复代码；层 B YAML 增强：5 个 YAML 模板添加 analysis_framework/data_requirements/output_schema/metadata，实现 DataFormatter 通用数据格式化器（5 种格式），PromptBuilder 支持 YAML 声明注入。LaningAnalyzer 代码量 -60%。69 个层 B 相关测试通过。详见 §13.1.1 |
| v1.6 | 2026-07-24 | **阶段 8 层 C Skill 驱动扩展完成**: 新增 IAnalysisSkillStore 协议（YAML 分析技能存储接口）；SkillStore 双协议实现（ISkillStore + IAnalysisSkillStore）；SkillDrivenAnalyzer 从 YAML 技能定义动态创建分析器（from_yaml/from_skill_store）；SkillDrivenPromptBuilder 从 YAML 加载模板；3 个内置技能（roshan_timing/ward_efficiency/late_game_decisions）；Runtime 自动注册自定义技能；PostMatchReviewAPI 暴露技能管理接口。31 个层 C 新增测试通过。总代码精简约 70%。详见 §13.1.1 |
| v1.7 | 2026-07-26 | **阶段 9 MCP Server 集成完成**: 将单体 `dota2_fastmcp.py`（6503 行）拆分为模块化 MCP Server（8 个工具模块 + 6 个辅助模块），位于 `dota_helper/mcp_server/`。47 个迁移工具全部异步化（`requests` → `httpx.AsyncClient`），新增 6 个复盘工具（review_tools）。统一 `AsyncOpenDotaClient`（单例 + 缓存 + 指数退避）。`core/agent.py` 集成 MCP Client（`connect_mcp_server()` / `call_mcp_tool()`）。8 个工具文件添加 351 条日志调用。53 个工具注册验证通过。详见 §6.5 / §9.3a / §13.1.1 |
| v1.8 | 2026-07-27 | **阶段 10 ReAct Agent Chat 设计**: 新增"自由文本聊天 → ReAct Agent 推理"交互模式设计，与 Dota2-Agent 范式对齐。新增 `agent/` 模块（DotaHelperReActAgent + ReAct 循环 + 工具分发器 + 响应解析器 + 会话管理），`web_app.py`（FastAPI 聊天端点 + 静态文件服务），Vue 3 聊天组件（ChatView/Input/Message/Bubble/WardIframe/PresetCards + useChat.ts composable + chat.ts Pinia store）。SSE 流式展示 Thought/Action/Observation + iframe 嵌入 Ward HTML。ReAct Agent 与 PostMatchReviewAPI 并存。详见 §13.1.2 |

### D. 自包含设计原则（v1.1 重要约定）

#### D.1 为什么选择自包含独立包?

| 理由 | 说明 |
|------|------|
| **避免架构污染** | 复盘 Agent 是新一代旗舰功能,设计理念(双循环/四层记忆/Stop Hooks)与既有模块(单轮查询式 Agent)差异巨大,混入既有目录会引入风格冲突 |
| **独立演进能力** | 既有 `dota_helper` 已趋稳定,新功能应能独立升级/独立回滚,不受历史模块制约 |
| **独立测试与部署** | 包内自带测试、配置、数据目录,可单独打包/单独 CI,减少回归影响面 |
| **清晰的所有权边界** | 未来该包可能由专门团队负责,自包含结构便于代码所有权交接 |
| **可复用潜力** | 独立包结构未来可被抽取为 `git submodule` 或独立 PyPI 包,跨项目复用 |

#### D.2 自包含性验证清单

代码 Review 与 CI 检查时,可通过以下清单验证自包含性:

- [ ] `grep -r "from dota_helper\." dota_helper/` 返回**空**(无反向依赖)
- [ ] `grep -r "from dota_helper\." dota_helper/tests/` 返回**空**
- [ ] `grep -r "import dota_helper" dota_helper/` 返回**空**
- [ ] 所有日志以 `pmr.` 前缀开头(`pmr.orchestrator` / `pmr.analyzer.laning` 等)
- [ ] 所有文件读写路径均位于 `dota_helper/data/` 或 `dota_helper/config/`
- [ ] LLM 凭证仅通过环境变量读取,不直接 `import utils.llm_client`
- [ ] 集成测试仅在 `dota_helper/tests/` 内,不复用既有 `dota_helper/tests/` 的 fixture
- [ ] `pyproject.toml` 中 `name = "dota_helper"`,独立于 `dota_helper` 顶层包

#### D.3 与既有模块共享约定的保留项

虽然代码隔离,但以下**约定**保持一致,保证工程风格统一:

| 约定 | 来源 |
|------|------|
| Type Hints 必须标注 | `dota_helper` 既有约定 |
| 接口 + 策略模式 | `dota_helper` 既有约定 |
| LLM 驱动优先 + 规则驱动降级 | `dota_helper` 既有约定(元认知模块) |
| Langfuse 可选,SDK 缺失时静默降级 | `dota_helper` 既有约定 |
| 所有评估步骤接入 logger + trace | `dota_helper` 既有约定 |
| 后端解析结果包含 `confidence` 字段 | `dota_helper` 既有约定 |
| 前端不得包含解析逻辑 | `dota_helper` 既有约定 |

#### D.4 何时可以放宽自包含约束?

以下情况下,可以考虑打破自包含约束(需在 PR 描述中明确说明):

1. **复盘 Agent 进入稳定期后**,需要共享某些工具(如时间格式化、英雄名称本地化)
2. **dota_helper 整体架构升级**,所有模块统一重构
3. **性能瓶颈**:独立实现某些组件导致性能下降超过 20%

任何打破约束的改动需:
- 在 `dota_helper/docs/ARCHITECTURE.md` 中记录依赖方向
- 在 PR 描述中说明打破自包含的理由
- 通过两阶段审查(Spec Compliance + Code Quality)
