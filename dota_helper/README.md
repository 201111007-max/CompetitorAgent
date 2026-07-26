# dota_helper

> Dota 2 赛后复盘 Agent — 从单轮查询工具到自主多步分析 Agent 的转型

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-226%20passed-green.svg)]()

## 概览

`dota_helper` 是一个 Dota 2 赛后复盘智能代理，能够对指定比赛进行自主、多阶段、深度的赛后分析，输出结构化复盘报告并提供可执行的改进建议。

**核心特性：**

- 🔍 **自主多步分析** — 双循环引擎（战略循环 + 战术循环）自动编排分析流程
- 🧠 **LLM 驱动评估** — 基于 LLM 的深度分析，未配置时自动降级为规则驱动
- 📊 **五阶段分析** — 对线(laning)、团战(teamfight)、经济(economy)、决策(decisions)、视野(vision)
- 💾 **四层记忆系统** — Prompt Memory → Session Archive → Persistent Notes → Dynamic Skills
- 🛠️ **53 个 MCP 工具** — 通过 MCP Server 提供英雄、比赛、玩家、视野等完整工具集
- 🔄 **迭代预算控制** — 令牌桶机制 + 边际递减检测，智能终止分析迭代
- ⚡ **并行子代理** — 多阶段并行分析，加速复盘生成
- 🎯 **技能自动沉淀** — 从复盘中提取经验，持续改进分析能力

## 快速开始

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd dota_helper

# 安装依赖
pip install -e .

# 安装 MCP Server 额外依赖
pip install -e ".[mcp]"
```

### 配置

创建 `.env` 文件（或复制项目根目录的 `.env.example`）：

```env
# DeepSeek API Key（推荐，用于 LLM 驱动分析）
DEEPSEEK_API_KEY=your_deepseek_api_key

# OpenAI API Key（可选，作为备选 LLM 提供方）
OPENAI_API_KEY=your_openai_api_key

# OpenDota API Key（可选，提高 API 请求限制）
OPENDOTA_API_KEY=your_opendota_api_key
```

> **无 LLM 密钥也可运行**：系统会自动降级为 `FallbackAnalyzer` 规则分析模式。

### 基本用法

```python
import asyncio
from dota_helper import PostMatchReviewAPI, create_default_api

# 方式 1：零配置创建（自动检测环境变量）
api = create_default_api()

# 方式 2：手动创建
api = PostMatchReviewAPI()

# 执行复盘
report = await api.review(match_id="8909780728")

# 查看结果
print(f"总体评分: {report.overall_score:.1f}/10")
print(f"置信度: {report.overall_confidence:.1%}")
print(f"关键发现: {report.key_findings}")
print(f"改进建议: {report.improvement_areas}")
```

### 流式复盘（SSE）

```python
async for event_sse in api.review_stream(match_id="8909780728"):
    print(event_sse)  # SSE 格式事件行
```

### MCP Server

```bash
# 直接启动 MCP Server（stdio 模式）
python -m dota_helper.mcp_server.server
```

```python
# 编程方式创建 MCP Server
from dota_helper.mcp_server.server import create_server

server = create_server()  # 返回 FastMCP 实例，注册 53 个工具
```

## 架构

```
dota_helper/
├── __init__.py              # 包入口，导出 PostMatchReviewAPI, create_default_api
├── api.py                   # 备用 API 入口（含记忆和后台审查）
├── review_config.yaml       # 复盘配置文件
│
├── facade/                  # 门面层 — 外部唯一入口
│   ├── api.py               #   PostMatchReviewAPI（状态管理 + 流式支持）
│   └── entrypoint.py        #   create_default_api() 工厂方法
│
├── orchestrator/            # 编排层 — 双循环引擎
│   ├── review_orchestrator.py  # 复盘编排器（顶层调度）
│   ├── strategic_loop.py       # 战略循环（全局评估与策略制定）
│   ├── tactical_loop.py        # 战术循环（单阶段深度分析）
│   ├── runtime.py              # 运行时组件组装
│   ├── background_reviewer.py  # 后台自我审查器
│   └── review_config.py        # 配置加载
│
├── analyzers/               # 分析器层 — 各阶段具体分析
│   ├── base.py              #   模板方法基类（parse_response / build_prompt）
│   ├── laning_analyzer.py   #   对线阶段分析
│   ├── teamfight_analyzer.py#   团战阶段分析
│   ├── economy_analyzer.py  #   经济阶段分析
│   ├── decision_analyzer.py #   决策阶段分析
│   ├── vision_analyzer.py   #   视野阶段分析
│   ├── skill_driven.py      #   技能驱动分析器
│   └── fallback_analyzer.py #   规则驱动降级分析器
│
├── engines/                 # 引擎层 — Prompt 构建、预算控制、终止验证
│   ├── prompt_builder.py    #   Prompt 构建器
│   ├── data_formatter.py    #   数据格式化
│   ├── budget.py            #   迭代预算控制（令牌桶 + 边际递减）
│   ├── stop_verifier.py     #   停止验证器
│   └── compressor.py        #   上下文压缩器
│
├── data_source/             # 数据源层 — OpenDota API 集成
│   ├── opendota_client.py   #   OpenDota 异步客户端
│   ├── match_fetcher.py     #   比赛数据获取与解析
│   ├── cache.py             #   数据缓存
│   ├── data_validator.py    #   数据验证
│   └── exceptions.py        #   数据源异常
│
├── llm/                     # LLM 层 — 大语言模型调用
│   ├── client.py            #   LLM 客户端（OpenAI/DeepSeek 兼容）
│   └── token_counter.py     #   Token 计数器
│
├── memory/                  # 记忆层 — 四层记忆系统
│   ├── four_layer_memory.py #   四层记忆协调器
│   ├── session_archive.py   #   会话归档（SQLite）
│   ├── persistent_notes.py  #   持久笔记
│   ├── skill_store.py       #   技能存储
│   └── dream_recap.py       #   Dream/Recap 记忆整合
│
├── domain_types/            # 领域类型 — 核心数据模型
│   ├── match_data.py        #   比赛数据
│   ├── analysis.py          #   分析上下文与结果
│   ├── report.py            #   复盘报告
│   ├── events.py            #   事件（进度、验证）
│   ├── state.py             #   Agent 状态
│   ├── strategy.py          #   分析策略
│   ├── enums.py             #   枚举
│   └── exceptions.py        #   领域异常
│
├── interfaces/              # 接口契约 — Protocol 定义
│   ├── analyzer.py          #   IReviewAnalyzer
│   ├── data_source.py       #   IMatchDataSource
│   ├── llm.py               #   ILLMClient
│   ├── memory.py            #   IFourLayerMemory
│   ├── budget.py            #   IIterationBudget
│   ├── compressor.py        #   IContextCompressor
│   ├── report.py            #   IReportBuilder
│   ├── skill.py             #   ISkillStore, IAnalysisSkillStore
│   ├── strategy.py          #   IStrategicLoop
│   └── verifier.py          #   IStopVerifier
│
├── report/                  # 报告层 — 结果渲染
│   ├── report_builder.py    #   报告构建器
│   ├── markdown_renderer.py #   Markdown 渲染器
│   └── progress_emitter.py  #   进度事件发射器（SSE）
│
├── parallel/                # 并行层 — 子代理编排
│   ├── parallel_runner.py   #   并行运行器
│   ├── subagent.py          #   子代理
│   └── task_queue.py        #   任务队列
│
├── prompt/                  # Prompt 管理
│   └── loader.py            #   Prompt 模板加载器
│
├── prompts/                 # Prompt 模板（YAML）
│   ├── tactical_laning.yaml
│   ├── tactical_teamfight.yaml
│   ├── tactical_economy.yaml
│   ├── tactical_decisions.yaml
│   ├── tactical_vision.yaml
│   ├── background_review.yaml
│   ├── dream_recap.yaml
│   └── skills/              #   分析技能模板
│
├── mcp_server/              # MCP Server — 53 个工具
│   ├── server.py            #   FastMCP Server 入口
│   ├── helpers/             #   共享辅助模块
│   │   ├── opendota.py      #     AsyncOpenDotaClient
│   │   ├── hero_names.py    #     英雄中文名映射
│   │   ├── map_config.py    #     地图配置
│   │   ├── ward_visualization.py  眼位可视化
│   │   ├── rag_index.py     #     RAG 索引
│   │   └── text_processing.py    文本处理
│   ├── tools/               #   工具模块（@mcp.tool 装饰器注册）
│   │   ├── match_tools.py   #     比赛查询工具
│   │   ├── hero_tools.py    #     英雄查询工具
│   │   ├── player_tools.py  #     玩家查询工具
│   │   ├── team_tools.py    #     阵容分析工具
│   │   ├── ward_tools.py    #     视野/眼位工具
│   │   ├── search_tools.py  #     搜索工具
│   │   ├── stats_tools.py   #     统计工具
│   │   └── review_tools.py  #     复盘分析工具
│   └── resources/           #   静态资源
│       ├── heroes_txt/      #     英雄描述文本（124 个）
│       ├── maps/            #     小地图图片
│       ├── figure/          #     眼位示意图
│       └── ward_region_template.json
│
├── observability/           # 可观测性
│   └── logger.py            #   dh.* 命名空间 Logger
│
└── tests/                   # 测试
    ├── unit/                #   单元测试
    ├── integration/         #   集成测试
    └── performance/         #   性能测试
```

## 核心机制

### 双循环分析引擎

```
┌─────────────────────────────────────────────┐
│           Strategic Loop（战略循环）           │
│  全局评估 → 策略制定 → 阶段调度 → 收敛检测    │
└──────────────────────┬──────────────────────┘
                        │ 调度各阶段
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Tactical Loop │ │ Tactical Loop │ │ Tactical Loop │
│  对线/团战    │ │  经济/决策    │ │  视野/...    │
│ 深度迭代分析  │ │ 深度迭代分析  │ │ 深度迭代分析  │
└──────────────┘ └──────────────┘ └──────────────┘
```

- **战略循环**：决定分析哪些阶段、顺序和并行度，检查全局收敛条件
- **战术循环**：在每个阶段内迭代调用分析器，直到置信度达标或预算耗尽

### 迭代预算控制

- **令牌桶机制**：每个阶段分配独立预算，控制最大迭代次数和 Token 消耗
- **边际递减检测**：当连续迭代收益低于阈值时提前终止，避免无效消耗

### 四层记忆系统

| 层级 | 名称 | 生命周期 | 用途 |
|------|------|---------|------|
| L1 | Prompt Memory | 单次会话 | 上下文窗口内的即时记忆 |
| L2 | Session Archive | 会话归档 | SQLite 持久化的会话历史 |
| L3 | Persistent Notes | 跨会话 | JSON 持久化的关键笔记 |
| L4 | Dynamic Skills | 永久 | YAML 持久化的分析技能 |

### MCP 工具集（53 个）

| 类别 | 工具数 | 说明 |
|------|--------|------|
| 比赛查询 | ~8 | 比赛详情、近期比赛、比赛趋势等 |
| 英雄查询 | ~8 | 英雄信息、克制关系、英雄胜率等 |
| 玩家查询 | ~6 | 玩家信息、近期比赛、队友/对手等 |
| 阵容分析 | ~5 | 阵容优势、搭配分析等 |
| 视野/眼位 | ~8 | 眼位效率、放置建议、可视化等 |
| 搜索 | ~4 | 英雄搜索、物品搜索等 |
| 统计 | ~8 | 排行榜、元数据统计等 |
| 复盘分析 | 6 | 视野效率、肉山时机、后期决策、完整报告、玩家趋势、比赛对比 |

## 配置

核心配置文件为 `review_config.yaml`：

```yaml
# LLM 配置
api_base_url: "https://api.openai.com/v1"
model: "gpt-4o-mini"
temperature: 0.3
max_tokens: 4000

# 战略循环
strategic_loop:
  max_iterations: 3
  min_confidence: 0.6
  required_phases: ["laning", "teamfight", "economy", "decisions"]

# 战术循环
tactical_loop:
  max_iterations_per_phase: 3
  default_budgets:
    laning: 3
    teamfight: 3
    economy: 2
    decisions: 2
    vision: 1

# 并行优化
enable_parallel_phases: false
max_concurrency: 4
```

## API 参考

### `PostMatchReviewAPI`

复盘模块的统一外部入口。

| 方法 | 说明 | 返回 |
|------|------|------|
| `review(match_id)` | 执行完整复盘 | `ReviewReport` |
| `review_stream(match_id)` | SSE 流式复盘 | `AsyncGenerator[str]` |
| `get_status(match_id)` | 获取复盘状态 | `Dict[str, Any]` |
| `get_report(match_id)` | 获取复盘报告 | `Optional[ReviewReport]` |
| `interrupt(match_id)` | 中断复盘 | `Dict[str, Any]` |
| `list_history()` | 复盘历史列表 | `List[Dict]` |
| `list_analysis_skills()` | 列出分析技能 | `List[Dict]` |
| `register_analysis_skill(name, def)` | 注册自定义技能 | `None` |

### `create_default_api()`

零配置工厂方法，自动检测环境变量、组装数据源和 LLM 客户端，未配置 LLM 时降级为规则分析。

```python
from dota_helper import create_default_api

api = create_default_api()
report = await api.review("8909780728")
```

## 测试

```bash
# 运行单元测试
pip install -e ".[test]"
pytest tests/unit -v

# 运行集成测试（需要网络和 API Key）
pytest tests/integration -v -m integration

# 运行全部测试
pytest -v
```

## 设计原则

1. **LLM 驱动优先** — 核心评估逻辑由 LLM 驱动，规则驱动仅作降级方案
2. **自包含设计** — 所有组件（LLM、记忆、缓存、可观测性）均在包内自包含
3. **接口 + 策略模式** — 核心模块通过 Protocol 定义接口，便于扩展和替换
4. **可靠终止** — Stop Hook 验证确保分析完整且质量达标后才输出
5. **向后兼容** — LLM/MCP/Langfuse 均为可选组件，项目可在无外部依赖时运行

## 许可证

Private — 仅供学习和研究使用。
