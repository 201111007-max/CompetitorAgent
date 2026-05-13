# DotaHelperAgent - Dota 2 英雄推荐助手

基于 OpenDota API 的智能 Dota 2 英雄推荐 Agent，提供英雄克制分析、出装推荐和技能加点建议。采用 **LLM 优先 + 数据驱动兜底**的混合模式架构。

## ✨ 核心特性

- 🤖 **英雄推荐** - 根据双方阵容推荐最佳英雄
- ⚔️ **克制分析** - 基于数据的英雄克制关系分析
- 🎒 **出装推荐** - 分阶段的最优物品搭配建议
- 📚 **技能加点** - 基于英雄定位的加点顺序
- 🧠 **元认知能力** - Agent 自我评估知识边界，主动请求澄清
- 💾 **智能缓存** - 两级缓存（内存 + 文件），减少 API 调用
- 🔄 **ReAct Agent** - 推理 - 行动循环，自主决策
- 📝 **日志系统** - 完整的日志记录和前端实时展示

## 🏗️ 架构设计

### 混合模式架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户请求                                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   HybridAnalyzer (基类)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 1. 优先尝试 LLM 执行                                     │  │
│  │    - 智能分析、灵活响应、结构化输出                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                  │
│                    [LLM 失败？]                               │
│                            │                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 2. 回退到数据驱动执行                                    │  │
│  │    - 可靠数据、规则分析、稳定输出                       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  返回结果 + 来源标识 (llm/data)               │
└─────────────────────────────────────────────────────────────┘
```

### 元认知能力架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      元认知评估层 (Metacognition)                 │
├──────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              LLMBasedKnowledgeBoundary                      │  │
│  │         使用 LLM 评估知识边界和数据覆盖度                    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│                              ▼                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              WeightedConfidenceCalculator                   │  │
│  │         加权计算置信度分数                                   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│                              ▼                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              RuleBasedClarificationGenerator                │  │
│  │         生成澄清请求（缺失信息、歧义意图等）                 │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      AgentController 集成点                       │
│  - assess_before_execution(): 执行前评估知识边界                  │
│  - assess_after_execution(): 执行后评估结果质量                   │
│  - should_request_clarification(): 判断是否需要澄清               │
└──────────────────────────────────────────────────────────────────┘
```

### 核心模块调用图

```
┌──────────────────────────────────────────────────────────────────┐
│                         用户接口层                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  Python API  │  │  Web API     │  │ CLI (可选)   │           │
│  └───────┬──────┘  └───────┬──────┘  └──────────────┘           │
└──────────┼─────────────────┼────────────────────────────────────┘
           │                 │
           ▼                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Agent 核心层                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    DotaHelperAgent                         │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │ │
│  │  │HeroAnalyzer  │  │ItemRecommender│  │SkillBuilder  │     │ │
│  │  └───────┬──────┘  └───────┬──────┘  └───────┬──────┘     │ │
│  └──────────┼─────────────────┼─────────────────┼────────────┘ │
│             │                 │                 │               │
│             ▼                 ▼                 ▼               │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              HybridAnalyzer (混合执行器基类)                │ │
│  │         LLM 优先 → 失败回退 → 数据驱动兜底                   │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      工具层 (Tools)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │Hero Tools    │  │Build Tools   │  │Analysis Tools│           │
│  └───────┬──────┘  └───────┬──────┘  └───────┬──────┘           │
│          │                 │                 │                   │
│          └─────────────────┴─────────────────┘                   │
│                            │                                     │
│                            ▼                                     │
│              ┌─────────────────────────┐                         │
│              │    ToolRegistry         │                         │
│              │  (工具注册表和管理)       │                         │
│              └─────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      数据层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │CacheManager  │  │AgentMemory   │  │OpenDota API  │           │
│  │(两级缓存)    │  │(记忆系统)    │  │(外部 API)    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────────────────────────────────────────────┘
```

### ReAct Agent 循环流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Controller                          │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
    ┌─────────┐
    │  Think  │  ← 理解用户意图，分析查询
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  Plan   │  ← 制定行动计划，选择工具
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ Execute │  ← 执行工具调用
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ Observe │  ← 观察工具执行结果
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ Reflect │  ← 反思是否需要调整
    └────┬────┘
         │
    ┌────┴─────┐
    │  完成？   │── 否 ──┐
    └────┬─────┘        │
         │是            │
         ▼              │
    ┌─────────┐         │
    │Synthesize│ ←──────┘
    │ 输出答案 │
    └─────────┘
```

## 📁 项目结构

```
DotaHelperAgent/
├── core/                    # 核心模块
│   ├── agent.py            # 主 Agent 类
│   ├── agent_controller.py # Agent 控制器 (ReAct 循环)
│   ├── config.py           # 配置管理
│   ├── react_agent.py      # ReAct Agent 实现
│   ├── tool_registry.py    # 工具注册表
│   └── metacognition/      # 元认知模块
│       ├── interfaces.py   # 接口定义
│       ├── rule_based.py   # 规则组件（置信度计算、澄清生成）
│       ├── llm_based.py    # LLM 驱动知识边界评估
│       └── factory.py      # 工厂类
│
├── analyzers/               # 分析器模块
│   ├── hero_analyzer.py    # 英雄克制分析
│   ├── item_recommender.py # 物品推荐
│   └── skill_builder.py    # 技能加点
│
├── tools/                   # 工具模块
│   ├── base.py             # Tool 基类
│   ├── hero_tools.py       # 英雄相关 Tools
│   └── build_tools.py      # 出装/技能 Tools
│
├── utils/                   # 工具类模块
│   ├── api_client.py       # OpenDota API 客户端
│   ├── llm_client.py       # LLM 客户端
│   └── localization.py     # 中文本地化
│
├── cache/                   # 缓存模块
│   └── cache_manager.py    # 两级缓存管理器
│
├── memory/                  # 记忆模块
│   └── memory.py           # Agent 记忆系统
│
├── web/                     # Web API
│   ├── app.py              # Flask 后端
│   └── index.html          # 前端界面
│
├── tests/                   # 测试目录
│   ├── api/                # API 层测试
│   ├── core/               # 核心组件测试
│   ├── unit/               # 单元测试
│   └── e2e/                # 端到端测试
│
└── config/                  # 配置文件
    └── llm_config.yaml     # LLM 配置
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install requests flask flask-cors
```

### 2. 基础使用（Python API）

```python
from DotaHelperAgent import DotaHelperAgent

# 创建 Agent
agent = DotaHelperAgent()

# 英雄推荐
result = agent.recommend_heroes(
    our_heroes=["Anti-Mage"],
    enemy_heroes=["Phantom Assassin", "Pudge"],
    top_n=3
)
print(agent.format_recommendation(result))

# 出装推荐
build = agent.recommend_build(
    hero_name="Anti-Mage",
    role="core",
    game_stage="all"
)
print(agent.format_build(build))
```

### 3. 使用 ReAct Agent（高级）

```python
from core.agent import DotaHelperAgent
from core.agent_controller import AgentController
from core.tool_registry import ToolRegistry
from tools.agent_tools import create_all_tools

# 创建 Agent 和工具
agent = DotaHelperAgent(enable_memory=True)
registry = ToolRegistry()
tools = create_all_tools(
    hero_analyzer=agent.hero_analyzer,
    item_recommender=agent.item_recommender,
    skill_builder=agent.skill_builder,
    client=agent.client
)
registry.register_batch(tools)

# 创建 Agent Controller（启用元认知）
controller = AgentController(
    tool_registry=registry,
    memory=agent.memory,
    max_turns=5,
    enable_reflection=True,
    metacognition_config={"type": "llm_based"}  # 启用 LLM 驱动的元认知
)

# 执行查询（自动进行 ReAct 循环）
result = controller.solve(
    "推荐克制敌方帕吉和斧王的英雄",
    context={"enemy_heroes": ["pudge", "axe"]}
)

print(f"推理过程：{result['reasoning']}")
print(f"最终答案：{result['answer']}")
```

### 4. 使用元认知能力

```python
from core.metacognition.factory import MetacognitionFactory

# 创建元认知评估器
evaluator = MetacognitionFactory.create_evaluator(
    config={"type": "llm_based"},
    tool_registry=registry,
    llm_client=llm_client
)

# 执行前评估
assessment = evaluator.assess_before_execution(
    query="克制谁？",
    context={}
)

print(f"置信度：{assessment.confidence_score}")
print(f"置信等级：{assessment.confidence_level}")
print(f"限制：{assessment.limitations}")

# 判断是否需要澄清
if evaluator.should_request_clarification(assessment):
    clarification = evaluator.generate_clarification(
        query="克制谁？",
        assessment=assessment,
        missing_info=["英雄名称"]
    )
    print(f"需要澄清：{clarification.questions}")
```

### 5. 启动 Web API

```bash
# 启动服务器
cd web
python app.py

# 访问 http://localhost:5000
```

#### API 调用示例

```bash
# 英雄推荐
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "推荐克制帕吉的英雄",
    "context": {"enemy_heroes": ["pudge"]}
  }'

# 出装推荐
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "幻影刺客怎么出装",
    "context": {"hero_name": "phantom_assassin"}
  }'
```

### 6. 配置 LLM（可选）

```bash
# 复制配置文件
cp config/llm_config.yaml.example config/llm_config.yaml

# 编辑配置
# base_url: "http://127.0.0.1:1234/v1"
# model: "qwen3.5-9b"
```

## 🧠 元认知能力详解

### 什么是元认知能力？

元认知能力让 Agent 能够"知道自己知道什么，不知道自己不知道什么"。在 DotaHelperAgent 中，这意味着：

1. **执行前评估** - 在回答之前，评估是否有足够的信息和数据
2. **置信度计算** - 量化对答案的信心程度
3. **主动澄清** - 当信息不足时，主动请求用户提供缺失信息
4. **执行后评估** - 评估生成答案的质量

### 元认知评估流程

```
用户查询
    │
    ▼
┌─────────────────────┐
│ 1. 知识边界评估      │ ← LLM 评估数据覆盖度
│    - 数据覆盖度      │
│    - 数据质量        │
│    - 工具匹配度      │
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ 2. 置信度计算        │ ← 加权公式
│    - 综合分数        │
│    - 置信等级        │
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ 3. 判断是否需要澄清  │
│    [置信度 < 阈值?]  │
└─────────────────────┘
    │
    ├── 是 → 生成澄清请求 → 返回给用户
    │
    └── 否 → 继续执行 → 生成答案
```

### 置信度等级

| 等级 | 分数范围 | 说明 |
|------|----------|------|
| VERY_HIGH | 0.9 - 1.0 | 数据充分，高度自信 |
| HIGH | 0.7 - 0.9 | 数据较充分，比较自信 |
| MEDIUM | 0.5 - 0.7 | 数据一般，谨慎回答 |
| LOW | 0.3 - 0.5 | 数据不足，建议澄清 |
| VERY_LOW | 0.0 - 0.3 | 数据严重不足，必须澄清 |

### 澄清请求类型

- **missing_hero** - 缺少英雄信息
- **missing_context** - 缺少上下文信息
- **ambiguous_intent** - 意图不明确
- **version_dependent** - 版本相关，需要确认
- **insufficient_data** - 数据不足

## 🧪 测试

```bash
# 运行所有测试
cd tests
python run_tests.py

# 按模块运行
pytest api/ -v      # API 测试
pytest core/ -v     # 核心测试
pytest unit/ -v     # 单元测试
pytest e2e/ -v      # E2E 测试

# 运行元认知模块测试
python tests/core/test_metacognition.py
```

## 📝 日志系统

DotaHelperAgent 内置了完整的日志系统，支持文件持久化和前端实时展示。

### 日志特性

- 📁 **文件持久化** - 自动轮转，多组件分离
- 🔄 **实时推送** - SSE 流式传输到前端
- 🔍 **灵活筛选** - 按级别、组件、会话筛选
- 📊 **结构化存储** - JSON 格式便于解析

### 日志文件结构

```
logs/
├── app.log           # 主应用日志
├── app.json.log      # 结构化 JSON 日志
├── error.log         # 错误日志
├── agent.log         # Agent 组件日志
├── tool.log          # 工具调用日志
├── cache.log         # 缓存操作日志
├── api.log           # API 请求日志
└── web.log           # Web 服务日志
```

### 在代码中使用日志

```python
from utils.log_config import get_logger

# 获取日志记录器
logger = get_logger("my_component", component="agent")

# 普通日志
logger.info("普通信息日志")

# 带上下文的日志（自动记录 session_id 和 extra_data）
logger.info_ctx(
    "执行某个操作",
    session_id="sess_xxx",
    extra_data={"param1": "value1", "param2": 123}
)
```

### 日志 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/logs` | GET | 获取日志（支持筛选） |
| `/api/logs/stream` | GET | SSE 流式日志 |
| `/api/logs/files` | GET | 获取日志文件列表 |
| `/api/logs/files/<name>` | GET | 获取日志文件内容 |
| `/api/logs/clear` | POST | 清空内存日志 |

### 前端日志面板

Web 界面右侧提供日志侧边栏，功能包括：

- **实时日志** - 实时显示应用运行日志
- **日志文件** - 查看历史日志文件
- **筛选过滤** - 按日志级别、组件筛选
- **导出功能** - 导出日志为 JSON 文件

## 📖 详细文档

- [TESTING_GUIDE.md](DotaHelperAgent/tests/TESTING_GUIDE.md) - 测试指南
- [tests/README.md](DotaHelperAgent/tests/README.md) - 测试套件说明
- [tests/STRUCTURE_OVERVIEW.md](DotaHelperAgent/tests/STRUCTURE_OVERVIEW.md) - 目录结构总览

## 🔗 外部链接

- [OpenDota API 文档](https://docs.opendota.com/)
- [Dota 2 中文维基](https://dota2.fandom.com/zh/wiki/Dota_2_Wiki)

---

**最后更新**: 2026-05-13  
**维护者**: DotaHelperAgent Team
