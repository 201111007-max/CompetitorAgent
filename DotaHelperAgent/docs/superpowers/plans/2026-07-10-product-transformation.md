# 二十、产品定位转型分析：从查询工具到真正的 Agent 产品 — 详细设计

> 更新时间：2026-07-13
> 来源: ARCHITECTURE_ANALYSIS.md 第二十章

## 20.1 核心问题：当前为什么不像 Agent 产品

```
当前模式：用户提问 → Agent 查表/调 API → 返回答案
本质是：带 LLM 包装的查询工具
```

**真正的 Agent 产品特征**：

| 特征 | 查询工具 | 真正的 Agent |
|------|---------|-------------|
| **目标** | 回答单个问题 | 完成复杂目标 |
| **执行** | 单轮响应 | 多步自主执行 |
| **决策** | 固定流程 | 自主决策下一步 |
| **学习** | 无记忆 | 从经验中学习 |
| **协作** | 单点 | 多角色协作 |

## 20.2 转型方向：4 个真正的 Agent 场景

### 20.2.1 场景 1：赛后复盘 Agent（Loop Agent）

**为什么需要 Agent**：
- 需要多步分析（对线期 → 团战 → 资源 → 决策点）
- 每局游戏情况不同，需要自主判断分析重点
- 需要对比多个时间节点的数据

**Agent 流程**：
```
输入：比赛 Match ID
    ↓
Loop 1: 数据收集（对线数据、团战数据、经济曲线）
    ↓
Loop 2: 问题识别（哪个阶段出了问题？）
    ↓
Loop 3: 根因分析（为什么会出现这个问题？）
    ↓
Loop 4: 改进建议（下次怎么避免？）
    ↓
输出：结构化复盘报告
```

**关键差异**：不是一次性回答，而是**自主执行多步分析**。

### 20.2.2 场景 2：多 Agent 战术讨论（Multi-Agent）

**为什么需要 Agent**：
- 需要不同视角（进攻、防守、经济、节奏）
- 需要 Agent 之间辩论和达成共识
- 模拟真实战队的战术讨论

**Agent 架构**：
```
CoachAgent（教练）：主持讨论，综合意见
    ↕
CarryAgent（ Carry 视角）：关注发育和输出环境
    ↕
SupportAgent（辅助视角）：关注视野和团队保护
    ↕
MidAgent（中单视角）：关注节奏和控符
```

**示例对话**：
```
Coach: "对面有 PA，我们怎么打？"
Carry: "出刃甲，她跳脸就开刃甲反打"
Support: "我建议先手控，PA 怕先手，我可以出吹风"
Mid: "我选宙斯，全球流抓她farm"
Coach: "综合意见：1. Carry 出刃甲 2. 辅助先手控 3. 中单全球流"
```

**关键差异**：不是单 Agent 回答，而是**多 Agent 协作讨论**。

### 20.2.3 场景 3：自我进化教练 Agent（Hermes 风格）

**为什么需要 Agent**：
- 需要记住用户的历史对局和习惯
- 需要从历史中总结用户的弱点
- 需要制定个性化训练计划

**Agent 能力**：
```
记忆层：
  - 用户最近 20 局的对局数据
  - 用户的英雄池和胜率
  - 用户的常见失误模式

自我进化：
  - 每次对局后自动提取经验
  - 生成 SKILL.md（如"对线 PA 的注意事项"）
  - 下次遇到类似情况时主动提醒

训练计划：
  - 分析用户弱点（如"补刀不稳定"）
  - 制定训练任务（如"每天练习 10 分钟补刀"）
  - 跟踪训练效果
```

**关键差异**：不是被动回答，而是**主动学习和个性化指导**。

## 20.3 技术架构改造

### 20.3.1 从单轮 ReAct 到 Loop Agent

```python
# 当前：单轮 ReAct
def solve(query):
    for turn in range(max_turns):
        thought = llm.think(...)
        action = llm.act(...)
        observation = tool.execute(action)
        if should_stop():
            break
    return answer

# 改造：Loop Agent
class ReplayAnalysisAgent:
    async def analyze(self, match_id: str):
        # Phase 1: 数据收集
        data = await self.collect_data(match_id)

        # Phase 2: 多轮分析循环
        insights = []
        for phase in ["laning", "mid_game", "late_game"]:
            insight = await self.analyze_phase(data, phase)
            insights.append(insight)

            # Stop Hook: 是否发现关键问题？
            if self.stop_hook.check(insight):
                break

        # Phase 3: 综合报告
        report = await self.generate_report(insights)
        return report
```

### 20.3.2 从单 Agent 到 Multi-Agent

```python
# 新增：多 Agent 协作框架
class TacticalDiscussion:
    def __init__(self):
        self.coach = CoachAgent()
        self.carry = CarryAgent()
        self.support = SupportAgent()
        self.mid = MidAgent()

    async def discuss(self, question: str):
        # 多轮讨论
        for round in range(max_rounds):
            carry_opinion = await self.carry.speak(question)
            support_opinion = await self.support.speak(question)
            mid_opinion = await self.mid.speak(question)

            # Coach 综合意见
            consensus = await self.coach.synthesize([
                carry_opinion, support_opinion, mid_opinion
            ])

            # 达成共识则停止
            if consensus.confidence > 0.8:
                break

        return consensus
```

### 20.3.3 新增：技能自动沉淀

```python
# 新增：从对局中自动学习技能
class SkillExtractor:
    async def extract(self, match_data, result):
        """从对局结果中提取经验"""
        # 分析胜负原因
        reasons = await self.analyze_reasons(match_data, result)

        # 生成技能文档
        for reason in reasons:
            skill = SkillDocument(
                name=f"对线{reason.hero}的注意事项",
                situation=reason.situation,
                actions=reason.recommended_actions,
                confidence=reason.confidence,
            )
            await self.skill_registry.register(skill)
```

## 20.4 产品定位重新设计

| 维度 | 当前定位 | 新定位 |
|------|---------|--------|
| **产品名** | DotaHelperAgent | **DotaCoach AI** |
| **一句话描述** | Dota 2 智能助手 | **AI Dota 教练，自主分析你的对局并制定训练计划** |
| **核心功能** | 查询英雄克制/出装 | 赛后复盘 + 多 Agent 战术讨论 + 个性化训练 |
| **交互方式** | 单轮问答 | 多轮对话 + 主动提醒 + 长任务执行 |
| **技术亮点** | ReAct + Langfuse | Loop Agent + Multi-Agent + 自我进化 |

## 20.5 核心功能优先级

| 优先级 | 功能 | Agent 类型 | 面试价值 |
|--------|------|-----------|---------|
| **P0** | 赛后复盘 Agent | Loop Agent | ⭐⭐⭐⭐⭐ |
| **P0** | 多 Agent 战术讨论 | Multi-Agent | ⭐⭐⭐⭐⭐ |
| **P1** | 自我进化教练 | Hermes 风格 | ⭐⭐⭐⭐⭐ |
| **P2** | 原查询功能 | 保留（降级为工具） | ⭐⭐⭐ |

## 20.6 实施路线图

```
第 1-2 周：赛后复盘 Agent（Loop Agent 模式）
    - 实现多阶段分析循环
    - 集成 Stop Hooks
    - 输出结构化复盘报告

第 3-4 周：多 Agent 战术讨论
    - 实现 4 个角色 Agent
    - 实现讨论协议（发言 → 综合 → 共识）
    - 输出讨论记录

第 5-6 周：自我进化教练
    - 实现技能自动沉淀
    - 实现用户画像记忆
    - 实现个性化训练计划
```

## 20.7 转型核心总结

**转型核心**：从"查询工具"变为"自主执行的 Agent"

| 改变 | 说明 |
|------|------|
| **从单轮到多轮** | 不是一次回答，而是多步自主分析 |
| **从单 Agent 到多 Agent** | 不是单一视角，而是多角色协作 |
| **从被动到主动** | 不是等用户提问，而是主动分析和建议 |
| **从无记忆到有记忆** | 不是每次从零开始，而是从历史中学习 |
| **从即时到长任务** | 不是秒级响应，而是分钟级深度分析 |

这样改造后，DotaHelperAgent 就是一个**真正的 Agent 产品**，而不是"带 LLM 的查询工具"。
