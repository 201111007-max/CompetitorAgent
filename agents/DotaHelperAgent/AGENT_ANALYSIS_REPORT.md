# DotaHelperAgent 分析报告

## 概述

本文档是对 DotaHelperAgent 的深度分析，评估其当前架构，并提出使其"更像 Agent"的优化建议。

**分析日期**: 2026-04-22  
**Agent 版本**: 1.0.0

---

## 一、当前架构评估

### 1.1 项目结构

```
DotaHelperAgent/
├── core/               # 核心模块
│   ├── agent.py       # 主 Agent 类
│   ├── config.py      # 配置管理
│   └── hybrid_base.py # 混合模式基类
├── analyzers/          # 分析器
│   ├── hero_analyzer.py      # 英雄克制分析
│   ├── item_recommender.py   # 出装推荐
│   ├── skill_builder.py      # 技能加点
│   └── hybrid_hero_analyzer.py
├── utils/              # 工具模块
│   ├── api_client.py   # OpenDota API 客户端
│   ├── llm_client.py   # LLM 客户端
│   └── localization.py # 本地化
├── strategies/         # 评分策略
│   └── score_strategies.py
├── cache/              # 缓存系统
│   └── cache_manager.py
├── config/             # 配置文件
│   └── llm_config.yaml
├── tests/              # 测试套件
└── examples/           # 使用示例
```

### 1.2 核心特性

| 特性 | 状态 | 说明 |
|------|------|------|
| 英雄推荐 | ✅ | 基于克制关系推荐 |
| 出装推荐 | ✅ | LLM 优先 + 数据兜底 |
| 技能加点 | ✅ | LLM 优先 + 规则兜底 |
| 混合模式 | ✅ | LLM + 数据驱动 |
| 智能缓存 | ✅ | 内存 + 文件两级缓存 |
| 速率限制 | ✅ | 60次/分钟限制 |
| 中文本地化 | ✅ | 英雄/物品中文名 |
| 配置化 | ✅ | YAML + 代码配置 |
| 策略模式 | ✅ | 可扩展评分策略 |
| 测试覆盖 | ✅ | 100+ 测试用例 |

### 1.3 当前架构优点

1. **混合模式设计优秀**: LLM 优先 + 数据驱动兜底，兼顾智能性和可靠性
2. **模块化程度高**: 分析器、策略、缓存等职责分离清晰
3. **配置灵活**: 支持 YAML 配置和代码配置
4. **缓存系统完善**: 两级缓存、LRU淘汰、线程安全
5. **测试覆盖全面**: 90%+ 代码覆盖率

---

## 二、Agent 能力评估

### 2.1 Agent 定义

真正的 Agent 应该具备以下核心能力：

| 能力 | 定义 | 当前状态 |
|------|------|----------|
| **自主性** | 能自主决策，不依赖人工逐步指导 | ⚠️ 部分具备 |
| **反应性** | 能感知环境并做出响应 | ⚠️ 被动响应 |
| **主动性** | 能主动发起行动 | ❌ 不具备 |
| **推理能力** | 能进行逻辑推理和规划 | ⚠️ 基础推理 |
| **记忆能力** | 能记住历史信息和上下文 | ❌ 无状态 |
| **工具使用** | 能选择和使用工具 | ⚠️ 固定流程 |
| **学习能力** | 能从经验中学习 | ❌ 不具备 |

### 2.2 当前定位

**现状**: DotaHelperAgent 目前是一个**智能工具库**而非真正的 Agent

```
用户请求 → Agent.recommend() → 返回结果
     ↑                              ↓
   一次性调用                    无状态返回
```

**理想 Agent 模式**:

```
用户请求 → Agent.think() → Agent.plan() → Agent.execute() → 结果
                ↑              ↓               ↓
            推理分析        制定计划        工具调用
                ←←←←←← 记忆/反馈 ←←←←←←
```

---

## 三、优化建议

### 3.1 高优先级：核心 Agent 能力

#### 3.1.1 添加记忆系统 (Memory)

**问题**: 当前 Agent 是无状态的，每次调用都是独立的

**解决方案**:

```python
class AgentMemory:
    """Agent 记忆系统"""
    
    def __init__(self):
        self.short_term = {}   # 短期记忆（当前会话）
        self.long_term = {}    # 长期记忆（持久化）
        self.episodic = []     # 情景记忆（历史事件）
    
    def remember(self, key, value, memory_type="short"):
        """记住信息"""
        pass
    
    def recall(self, key, memory_type="short"):
        """回忆信息"""
        pass
    
    def get_relevant_context(self, query):
        """获取相关上下文"""
        pass
```

**应用场景**:
- 记住用户的英雄偏好
- 记录历史推荐结果和反馈
- 维护游戏会话状态

#### 3.1.2 实现 ReAct 模式 (Reasoning + Acting)

**问题**: 当前是直接调用，缺乏推理过程

**解决方案**:

```python
class ReActAgent(DotaHelperAgent):
    """ReAct 模式 Agent"""
    
    def recommend_with_reasoning(self, our_heroes, enemy_heroes):
        # Thought: 分析当前局势
        thought = self.think(f"""
        我方阵容: {our_heroes}
        敌方阵容: {enemy_heroes}
        需要分析: 1) 阵容优缺点 2) 缺少什么角色 3) 克制关系
        """)
        
        # Action: 决定调用哪些工具
        actions = self.plan([
            {"tool": "analyze_composition", "params": {...}},
            {"tool": "get_counter_heroes", "params": {...}},
            {"tool": "check_meta", "params": {...}}
        ])
        
        # Observation: 收集结果
        observations = self.execute_actions(actions)
        
        # Final Thought: 综合决策
        final_decision = self.synthesize(thought, observations)
        
        return final_decision
```

#### 3.1.3 工具使用能力 (Tool Use)

**问题**: 工具调用是硬编码的，Agent 不能自主选择

**解决方案**:

```python
class ToolUsingAgent:
    """具备工具使用能力的 Agent"""
    
    def __init__(self):
        self.tools = {
            "get_hero_stats": Tool(
                func=self.api_client.get_hero_stats,
                description="获取英雄统计数据",
                parameters={"hero_id": "int"}
            ),
            "analyze_matchups": Tool(
                func=self.hero_analyzer.analyze_matchups,
                description="分析英雄克制关系",
                parameters={"hero_id": "int", "enemy_id": "int"}
            ),
            "query_llm": Tool(
                func=self.llm_client.chat,
                description="向 LLM 提问",
                parameters={"prompt": "str"}
            ),
        }
    
    def solve(self, query: str) -> dict:
        """自主解决问题"""
        # Agent 决定使用哪些工具
        plan = self.create_plan(query, self.tools)
        
        results = []
        for step in plan.steps:
            tool = self.tools[step.tool_name]
            result = tool.func(**step.parameters)
            results.append(result)
            
            # 根据结果决定下一步
            if step.needs_follow_up:
                plan.add_follow_up_step(result)
        
        return self.synthesize_results(results)
```

### 3.2 中优先级：交互与协作

#### 3.2.1 多轮对话支持

**问题**: 单次调用，无法澄清需求

**解决方案**:

```python
class ConversationAgent:
    """支持对话的 Agent"""
    
    def create_session(self) -> Session:
        return Session(self)
    
    def chat(self, user_input: str, session: Session) -> str:
        """对话式交互"""
        session.add_message("user", user_input)
        
        # 判断信息是否足够
        if not self.has_sufficient_info(session):
            question = self.ask_clarifying_question(session)
            session.add_message("assistant", question)
            return question
        
        # 信息足够，给出推荐
        recommendation = self.generate_recommendation(session)
        session.add_message("assistant", recommendation)
        return recommendation
```

**示例对话**:
```
用户: "我方选了 Anti-Mage"
Agent: "请问 Anti-Mage 是打几号位？对方目前选了哪些英雄？"
用户: "1号位，对方有 Pudge 和 Phantom Assassin"
Agent: "基于这个阵容，我推荐..."
```

#### 3.2.2 自我反思机制

**问题**: 推荐结果没有自我验证

**解决方案**:

```python
def recommend_with_reflection(self, our_heroes, enemy_heroes):
    """带反思的推荐"""
    
    # 初始推荐
    initial = self._generate_recommendations(our_heroes, enemy_heroes)
    
    # 自我反思
    reflection_prompt = f"""
    请检查以下推荐是否合理：
    推荐英雄: {initial}
    我方阵容: {our_heroes}
    敌方阵容: {enemy_heroes}
    
    检查点：
    1. 是否考虑了阵容平衡性？
    2. 是否遗漏了重要的克制关系？
    3. 推荐的英雄是否适合当前版本？
    4. 是否有更好的替代选择？
    """
    
    reflection = self.llm_client.complete(reflection_prompt)
    
    # 根据反思优化
    if reflection.has_issues:
        optimized = self._optimize(initial, reflection.issues)
        return {
            "recommendations": optimized,
            "initial": initial,
            "reflection": reflection,
            "improved": True
        }
    
    return {"recommendations": initial, "improved": False}
```

### 3.3 低优先级：架构扩展

#### 3.3.1 事件驱动架构

```python
class EventDrivenAgent:
    """事件驱动的 Agent"""
    
    def __init__(self):
        self.event_bus = EventBus()
        self._register_handlers()
    
    def _register_handlers(self):
        @self.event_bus.on(HeroSelectedEvent)
        def on_hero_selected(event):
            # 自动分析阵容变化
            analysis = self.analyze_composition()
            if analysis.has_issues:
                self.event_bus.emit(RecommendationEvent(analysis.suggestions))
```

#### 3.3.2 多 Agent 协作 (A2A)

```python
class AgentOrchestrator:
    """Agent 协调器"""
    
    def __init__(self):
        self.agents = {
            "composition": CompositionAgent(),      # 阵容分析专家
            "build": BuildAgent(),                  # 出装专家
            "laning": LaningAgent(),                # 对线专家
            "meta": MetaAgent(),                    # 版本专家
        }
    
    def collaborate(self, query: str) -> dict:
        """多 Agent 协作解决问题"""
        
        # 并行调用多个专家 Agent
        results = {}
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(agent.solve, query): name
                for name, agent in self.agents.items()
            }
            for future in futures:
                name = futures[future]
                results[name] = future.result()
        
        # 整合结果
        return self.synthesize(results)
```

#### 3.3.3 强化学习支持

```python
class LearningAgent(DotaHelperAgent):
    """具备学习能力的 Agent"""
    
    def __init__(self):
        super().__init__()
        self.feedback_history = []
        self.policy_model = PolicyNetwork()
    
    def learn_from_feedback(self, recommendation, user_feedback, game_result):
        """从反馈中学习"""
        
        # 记录反馈
        self.feedback_history.append({
            "recommendation": recommendation,
            "feedback": user_feedback,
            "result": game_result
        })
        
        # 计算奖励
        reward = self.calculate_reward(user_feedback, game_result)
        
        # 更新策略
        self.policy_model.update(recommendation, reward)
    
    def calculate_reward(self, feedback, result):
        """计算奖励值"""
        reward = 0
        if feedback == "positive":
            reward += 1
        if result == "win":
            reward += 2
        if result == "mvp":
            reward += 3
        return reward
```

---

## 四、实施路线图

### 阶段一：基础 Agent 能力（1-2 周）

- [ ] 实现记忆系统（短期 + 长期）
- [ ] 添加会话管理
- [ ] 实现基础 ReAct 模式

### 阶段二：高级 Agent 能力（2-3 周）

- [ ] 工具使用能力
- [ ] 自我反思机制
- [ ] 多轮对话支持

### 阶段三：架构升级（3-4 周）

- [ ] 事件驱动架构
- [ ] 插件系统
- [ ] 多 Agent 协作框架

### 阶段四：智能化（4-6 周）

- [ ] 强化学习集成
- [ ] 个性化推荐
- [ ] 预测性分析

---

## 五、代码示例：优化后的 Agent

```python
# 优化后的 Agent 使用示例
from agents.DotaHelperAgent import SmartDotaAgent

# 创建智能 Agent
agent = SmartDotaAgent(
    enable_memory=True,
    enable_reasoning=True,
    enable_learning=True
)

# 开始会话
session = agent.create_session()

# 对话式交互
response1 = session.chat("我方选了 Anti-Mage")
# Agent: "请问 Anti-Mage 是打几号位？对方选了谁？"

response2 = session.chat("1号位，对方有 Pudge")
# Agent: "了解，让我分析一下..."

# Agent 自主推理和行动
result = session.get_recommendation()
# {
#     "thought": "Anti-Mage 是后期核心，需要保护...",
#     "actions": ["analyze_matchups", "check_meta", "query_llm"],
#     "recommendations": [...],
#     "confidence": 0.85,
#     "reasoning": "基于克制关系和版本强势..."
# }

# 用户反馈
session.provide_feedback(result["recommendations"][0], rating=5)
# Agent 学习用户偏好
```

---

## 六、总结

### 6.1 当前状态

DotaHelperAgent 是一个**优秀的智能工具库**，具备：
- ✅ 完善的混合模式架构
- ✅ 良好的模块化和可扩展性
- ✅ 全面的测试覆盖

### 6.2 改进方向

要成为一个真正的 Agent，需要添加：
1. **记忆系统** - 维护状态和上下文
2. **推理能力** - ReAct 模式
3. **工具使用** - 自主选择工具
4. **交互能力** - 多轮对话
5. **学习能力** - 从反馈中改进

### 6.3 预期效果

优化后的 Agent 将具备：
- 更个性化的推荐
- 更自然的交互方式
- 更智能的决策过程
- 持续学习改进的能力

---

## 七、AutoGen 框架集成分析

### 7.1 AutoGen 简介

AutoGen 是微软研究院开发的多 Agent 对话框架，v0.4 版本进行了彻底重构，采用分层架构设计：

**AutoGen 0.4 架构分层**:

```
┌─────────────────────────────────────────────────────────┐
│                    应用层 (Applications)                  │
├─────────────────────────────────────────────────────────┤
│                   扩展层 (Extensions)                     │
│         (社区扩展、第三方工具、自定义组件)                  │
├─────────────────────────────────────────────────────────┤
│  AgentChat API  │  高级任务驱动 API，支持群聊、代码执行等   │
├─────────────────┴───────────────────────────────────────┤
│                   Core API (核心层)                       │
│     事件驱动的 Actor 模型、消息传递、状态管理、跨语言支持    │
└─────────────────────────────────────────────────────────┘
```

**核心特性**:
- ✅ **事件驱动架构**: 基于 Actor 模型的异步消息传递
- ✅ **多 Agent 协作**: 支持群聊、嵌套对话、人机协作
- ✅ **工具集成**: 内置代码执行、函数调用、MCP 协议支持
- ✅ **跨语言**: 支持 Python 和 .NET 互操作
- ✅ **可扩展**: 插件化设计，易于扩展

### 7.2 可行性分析

#### 7.2.1 集成可行性: ✅ 高度可行

| 评估维度 | 匹配度 | 说明 |
|---------|-------|------|
| 架构契合 | ⭐⭐⭐⭐⭐ | 当前混合模式与 AutoGen 工具调用完美契合 |
| 功能互补 | ⭐⭐⭐⭐⭐ | AutoGen 提供多 Agent 协作，弥补当前架构短板 |
| 迁移成本 | ⭐⭐⭐⭐ | 大部分分析器可直接封装为 Tools |
| 学习曲线 | ⭐⭐⭐ | 需要理解 Actor 模型和异步编程 |

#### 7.2.2 集成优势

1. **快速获得 Agent 核心能力**:
   - 无需从零实现记忆、规划、工具使用
   - 直接获得多 Agent 协作能力
   - 内置代码执行和函数调用

2. **架构升级**:
   - 从同步调用升级到异步事件驱动
   - 从单 Agent 升级到多 Agent 系统
   - 获得更好的扩展性和可维护性

3. **生态优势**:
   - 微软官方维护，持续更新
   - 活跃的社区和丰富的扩展
   - 完善的文档和示例

### 7.3 集成方案设计

#### 7.3.1 架构映射

```
当前架构                    AutoGen 架构
─────────────────────────────────────────────────
DotaHelperAgent      →    AssistantAgent (主 Agent)
HeroAnalyzer         →    Tool (英雄分析工具)
ItemRecommender      →    Tool (出装推荐工具)
SkillBuilder         →    Tool (技能加点工具)
LLMClient            →    OpenAIChatCompletionClient
CacheManager         →    保留，作为外部依赖
OpenDotaClient       →    Tool (数据获取工具)
```

#### 7.3.2 多 Agent 设计

```python
# AutoGen 多 Agent 架构
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

# 专家 Agent
composition_agent = AssistantAgent(
    name="composition_expert",
    model_client=model_client,
    tools=[analyze_composition_tool],
    system_message="你是阵容分析专家，负责分析阵容平衡性和协同性"
)

counter_agent = AssistantAgent(
    name="counter_expert", 
    model_client=model_client,
    tools=[analyze_matchups_tool],
    system_message="你是克制关系专家，负责分析英雄克制关系"
)

build_agent = AssistantAgent(
    name="build_expert",
    model_client=model_client,
    tools=[recommend_items_tool, recommend_skills_tool],
    system_message="你是出装专家，负责推荐出装和技能加点"
)

# 协调者 Agent
orchestrator = AssistantAgent(
    name="orchestrator",
    model_client=model_client,
    system_message="""你是协调者，负责整合各专家的意见，给出最终推荐。
    你需要：
    1. 向各专家询问专业意见
    2. 整合所有信息
    3. 给出结构化的最终建议"""
)

# 创建群聊团队
team = RoundRobinGroupChat(
    participants=[orchestrator, composition_agent, counter_agent, build_agent],
    max_turns=10
)
```

#### 7.3.3 工具封装方案

```python
from autogen_core.tools import FunctionTool
from typing import Annotated

# 将现有分析器封装为 AutoGen Tools

def analyze_hero_matchups(
    our_heroes: Annotated[list[str], "我方已选英雄列表"],
    enemy_heroes: Annotated[list[str], "敌方已选英雄列表"],
    top_n: Annotated[int, "推荐数量"] = 3
) -> dict:
    """分析英雄克制关系，推荐最佳英雄"""
    analyzer = HeroAnalyzer(client)
    return analyzer.analyze_matchups(our_heroes, enemy_heroes, top_n)

analyze_matchups_tool = FunctionTool(
    analyze_hero_matchups,
    description="分析英雄克制关系，基于数据推荐克制敌方的英雄"
)

def recommend_item_build(
    hero_name: Annotated[str, "英雄名称"],
    game_stage: Annotated[str, "游戏阶段 (early/mid/late/all)"] = "all",
    enemy_heroes: Annotated[list[str], "敌方英雄列表"] = None
) -> dict:
    """推荐英雄出装"""
    recommender = ItemRecommender(client)
    return recommender.recommend_items(hero_name, game_stage, enemy_heroes)

recommend_items_tool = FunctionTool(
    recommend_item_build,
    description="根据游戏阶段和敌方阵容推荐最优出装"
)

def recommend_skill_build(
    hero_name: Annotated[str, "英雄名称"],
    role: Annotated[str, "角色定位 (core/support/offlane)"] = "core"
) -> dict:
    """推荐技能加点"""
    builder = SkillBuilder(client)
    return builder.recommend_skill_build(hero_name, role)

recommend_skills_tool = FunctionTool(
    recommend_skill_build,
    description="根据英雄定位推荐技能加点顺序"
)
```

### 7.4 需要修改的地方

#### 7.4.1 核心改动清单

| 模块 | 改动类型 | 改动内容 |
|------|---------|---------|
| `core/agent.py` | 重写 | 继承 AssistantAgent，使用 AutoGen API |
| `analyzers/` | 封装 | 将分析器方法封装为 FunctionTool |
| `utils/api_client.py` | 保留 | 作为底层数据获取工具 |
| `utils/llm_client.py` | 替换 | 使用 AutoGen 的模型客户端 |
| `cache/` | 保留 | 作为外部依赖，为 Tools 提供缓存 |
| `tests/` | 重写 | 使用 AutoGen 测试模式 |

#### 7.4.2 代码迁移示例

**当前代码**:
```python
class DotaHelperAgent:
    def recommend_heroes(self, our_heroes, enemy_heroes, top_n=3):
        if self.llm_enabled:
            recommendations = self.llm_analyzer.recommend_heroes(...)
        else:
            recommendations = self.hero_analyzer.analyze_matchups(...)
        return recommendations
```

**AutoGen 版本**:
```python
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

class DotaHelperAgent(AssistantAgent):
    def __init__(self):
        model_client = OpenAIChatCompletionClient(
            model="gpt-4o",
            base_url="http://127.0.0.1:1234/v1"
        )
        
        tools = [
            analyze_matchups_tool,
            recommend_items_tool,
            recommend_skills_tool,
        ]
        
        super().__init__(
            name="dota_helper",
            model_client=model_client,
            tools=tools,
            system_message="""你是 Dota 2 专家助手，帮助玩家进行英雄推荐、出装建议和技能加点。
            你可以使用以下工具：
            1. analyze_matchups: 分析英雄克制关系
            2. recommend_items: 推荐出装
            3. recommend_skills: 推荐技能加点
            
            请根据用户需求选择合适的工具，并给出详细的解释。"""
        )

# 使用方式
async def main():
    agent = DotaHelperAgent()
    result = await agent.run(
        task="我方选了 Anti-Mage，对方有 Pudge 和 Phantom Assassin，推荐一个克制英雄"
    )
    print(result)
```

#### 7.4.3 异步改造

AutoGen 0.4 使用异步编程模型，需要改造现有同步代码：

```python
# 同步代码 → 异步代码
class OpenDotaClient:
    # 当前: 同步请求
    def get_heroes(self):
        response = requests.get(url)
        return response.json()
    
    # 改造后: 异步请求
    async def get_heroes_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.json()
```

### 7.5 集成实施步骤

#### 阶段一：环境准备（1-2 天）

```bash
# 安装 AutoGen
pip install autogen-agentchat autogen-ext

# 安装可选依赖
pip install autogen-ext[openai]  # OpenAI 支持
pip install autogen-ext[docker]  # Docker 代码执行
```

#### 阶段二：工具封装（3-5 天）

1. 将 `HeroAnalyzer` 方法封装为 `analyze_matchups_tool`
2. 将 `ItemRecommender` 方法封装为 `recommend_items_tool`
3. 将 `SkillBuilder` 方法封装为 `recommend_skills_tool`
4. 将 `OpenDotaClient` 封装为数据获取工具

#### 阶段三：Agent 重构（5-7 天）

1. 创建 `DotaHelperAgent` 类继承 `AssistantAgent`
2. 配置系统消息和工具列表
3. 实现多 Agent 协作（可选）
4. 添加记忆和会话管理

#### 阶段四：测试和优化（3-5 天）

1. 编写 AutoGen 风格的测试用例
2. 性能测试和调优
3. 文档更新

### 7.6 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|-------|------|---------|
| 学习成本 | 中 | 中 | 团队培训，渐进式迁移 |
| 异步编程复杂度 | 中 | 中 | 使用 asyncio 封装，保持接口简洁 |
| 依赖增加 | 低 | 低 | AutoGen 是微软官方维护，稳定性好 |
| 性能开销 | 低 | 低 | 事件驱动架构性能优秀 |

### 7.7 总结与建议

#### 7.7.1 集成建议: ✅ 强烈推荐

引入 AutoGen 框架是**高度可行且强烈推荐**的方案：

1. **快速获得 Agent 能力**: 无需从零构建记忆、规划、工具使用等基础设施
2. **架构现代化**: 升级到事件驱动、异步、多 Agent 架构
3. **未来可扩展**: 易于添加更多专家 Agent 和协作模式
4. **社区支持**: 微软官方维护，生态活跃

#### 7.7.2 两种方案对比

| 维度 | 自研 Agent | AutoGen 集成 |
|------|-----------|-------------|
| 开发周期 | 2-3 个月 | 2-3 周 |
| 维护成本 | 高 | 低 |
| 功能丰富度 | 有限 | 丰富 |
| 扩展性 | 需自行设计 | 内置支持 |
| 学习曲线 | 平缓 | 中等 |
| 长期演进 | 依赖团队 | 跟随社区 |

#### 7.7.3 最终建议

**建议采用 AutoGen 集成方案**，原因：

1. 当前架构与 AutoGen 理念高度契合
2. 大部分代码可以复用（封装为 Tools）
3. 可以快速获得生产级的 Agent 能力
4. 为未来多 Agent 协作打下基础

**实施策略**: 渐进式迁移
- 第一阶段：将现有分析器封装为 Tools
- 第二阶段：创建 AutoGen Agent 包装器
- 第三阶段：逐步添加多 Agent 协作
- 第四阶段：优化和扩展

---

**文档版本**: 1.1  
**最后更新**: 2026-04-22
