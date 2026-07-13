# 十九、前沿 Agent 理念融合计划 — 详细设计

> 更新时间：2026-07-13
> 来源: ARCHITECTURE_ANALYSIS.md 第十九章

## 19.1 Hermes Agent 核心理念

**来源**: Nous Research（2026.02）
**核心定位**: 自我进化的持久记忆 Agent 框架

### 19.1.1 六大技术支柱

| 支柱 | 核心理念 | 技术实现 |
|------|---------|---------|
| **GEPA 自我进化引擎** | 类反向传播优化 prompt | 100-500 次评估完成策略迭代（传统 RL 需上万次） |
| **持久记忆架构** | 跨会话记忆不丢失 | MEMORY.md（环境事实）+ USER.md（用户偏好）+ SQLite FTS5 |
| **技能自动学习** | 任务完成后自动沉淀技能 | 生成 SKILL.md，遵循 agentskills.io 标准，渐进式披露（Level 0/1/2） |
| **四层记忆系统** | 多粒度记忆管理 | Prompt Memory → Session Archive → Persistent Notes → Dynamic Skills |
| **子代理并行** | 复杂任务并发处理 | 隔离子代理，RPC 风格工具调用，失败隔离 |
| **MCP 深度融合** | 工具能力无限扩展 | 支持 stdio + HTTP 双传输，OAuth 2.1 认证 |

### 19.1.2 与 DotaHelperAgent 对比

| 维度 | Hermes Agent | DotaHelperAgent 当前 | 差距 |
|------|-------------|---------------------|------|
| 记忆持久化 | ✅ 跨会话持久化 | ⚠️ 三级记忆但缺少语义检索 | 中等 |
| 技能沉淀 | ✅ 自动生成 SKILL.md | ⚠️ 已有 Skill 架构但无自动学习 | 较大 |
| 自我进化 | ✅ GEPA 优化策略 | ❌ 无自我进化机制 | 大 |
| 子代理并行 | ✅ 隔离子代理 | ❌ 单 Agent | 大 |

## 19.2 Loop Agent 核心理念

**来源**: Anthropic Long-running Harness + Google ADK LoopAgent + Ralph Wiggum Loop
**核心定位**: 迭代式自主执行的 Agent 架构

### 19.2.1 三大来源与核心理念

| 来源 | 核心理念 | 关键技术 |
|------|---------|---------|
| **Anthropic Long-running Harness** | 模型不是产品，Harness 才是 | Stop Hooks + 终止条件 + 进度持久化 |
| **Google ADK LoopAgent** | 确定性循环执行 | 子代理序列执行 + 最大迭代 + 终止信号 |
| **Ralph Wiggum Loop** | 自主编码，无需人工干预 | 文件系统持久化 + Git 历史 + 无限重试 |

### 19.2.2 Anthropic 的 Long-running Agent Harness

**核心洞察**: Agent 失败的原因通常不是模型不够强，而是 Harness（执行框架）设计不当。

**两大失败模式**:

| 失败模式 | 表现 | 原因 |
|---------|------|------|
| **上下文焦虑** | 加速执行、跳过步骤、提前结束 | 模型感知到接近上下文窗口限制 |
| **过早宣布完成** | 声称"完成"但实际只完成 60% | 缺乏明确的终止条件验证 |

**解决方案: Stop Hooks**

```python
# 核心机制：每次模型回合后调用 hook
def stop_hook(result):
    if not tests_pass(result):
        return "continue"  # 继续执行
    return "stop"  # 允许停止
```

**关键设计原则**:
- **进度持久化**: 将状态存储在文件系统和 Git，而非对话历史
- **明确终止条件**: 用脚本验证"完成"的定义
- **上下文管理**: 60% 以下正常执行，60-80% 准备切换，80% 以上强制新上下文

### 19.2.3 Google ADK LoopAgent

**核心定位**: 确定性工作流代理，按顺序迭代执行子代理。

**架构设计**:

```python
LoopAgent(
    sub_agents=[WriterAgent, CriticAgent],
    max_iterations=5
)
```

**执行流程**:
1. **子代理执行**: 按顺序调用每个子代理
2. **终止检查**:
   - 最大迭代次数达到
   - 子代理发出终止信号（如 "STOP"）
   - 收敛检测（改进幅度 < 阈值）

**三种终止模式**:

| 模式 | 适用场景 | 示例 |
|------|---------|------|
| **固定迭代** | 已知需要多少轮 | "运行 3 轮质量改进" |
| **条件终止** | 有明确目标 | "优化直到响应时间 < 100ms" |
| **收敛检测** | 目标未知 | "重构直到 3 轮改进 < 5%" |

### 19.2.4 Ralph Wiggum Loop（自主编码）

**起源**: 澳大利亚开发者 Geoffrey Huntley 用 5 行 bash 脚本实现自主编码。

**核心脚本**:
```bash
while :; do cat PROMPT.md | claude-code ; done
```

**关键创新**:
- **文件系统持久化**: 进度存储在文件和 Git，而非对话历史
- **无限重试**: Agent 自主修复错误，无需人工干预
- **成本极低**: 5 万美元项目用 297 美元 API 费用完成

**上下文管理策略**:
- Token 使用 < 60%: 正常执行
- 60-80%: 完成当前任务后准备切换
- \> 80%: 强制新上下文，新 Agent 从文件继续

## 19.3 可融入 DotaHelperAgent 的补充方案

### 19.3.1 P0: Stop Hooks 终止验证（来自 Anthropic）

**现状**: DotaHelperAgent 的 ReAct 循环没有明确的终止验证。

**补充方案**:

```python
class StopHook:
    def check(self, result: AgentResult) -> bool:
        """验证是否满足终止条件"""
        # 1. 检查用户查询是否完整回答
        # 2. 检查工具调用是否成功
        # 3. 检查置信度是否达标
        return all([
            self._is_query_answered(result),
            self._tools_succeeded(result),
            self._confidence_adequate(result)
        ])
```

**实现要点**:
- 在 `AgentController.solve()` 中集成 StopHook
- 定义清晰的终止条件（查询回答、工具成功、置信度）
- 支持自定义终止规则

**预计工作量**: 3-5 天
**面试价值**: ⭐⭐⭐⭐⭐ 展现对长时间运行 Agent 的理解

### 19.3.2 P0: 技能自动沉淀机制（来自 Hermes）

**现状**: DotaHelperAgent 已有 Skill 架构，但技能是静态的，需要人工编写。

**补充方案**:

```
任务完成 → 反思评估 → 提取成功模式 → 生成 SKILL.md → 注册到 SkillRegistry
```

**实现要点**:
- 在 `ReflectionEvaluator` 中增加"技能提取"步骤
- 定义技能模板（输入/输出/步骤/注意事项）
- 实现技能版本管理（新技能覆盖旧技能需验证）

**预计工作量**: 1 周
**面试价值**: ⭐⭐⭐⭐⭐ 展现对"自我进化 Agent"的理解

### 19.3.3 P0: 迭代式技能优化（来自 Hermes + Loop）

**现状**: DotaHelperAgent 的 Skill 是静态的，无自动优化。

**补充方案**:

```
执行任务 → 评估结果 → 提取成功模式 → 更新 SKILL.md → 下次使用改进版
```

**实现要点**:
- 使用 LoopAgent 模式迭代优化技能
- 收敛检测：连续 3 次改进 < 5% 时停止
- 技能版本控制：保留历史版本，支持回滚

**预计工作量**: 1 周
**面试价值**: ⭐⭐⭐⭐⭐ 展现对自我进化 Agent 的理解

### 19.3.4 P1: 进度持久化机制（来自 Ralph Wiggum）

**现状**: DotaHelperAgent 的上下文压缩会丢失历史细节。

**补充方案**:

```python
class ProgressTracker:
    def save_state(self, state: AgentState):
        """将进度持久化到文件"""
        # 1. 写入 progress.md
        # 2. 提交 Git（可选）
        # 3. 新 Agent 从文件恢复状态
```

**实现要点**:
- 新增 `ProgressTracker` 类
- 支持从文件恢复状态
- 集成 Git 版本控制（可选）

**预计工作量**: 3-5 天
**面试价值**: ⭐⭐⭐⭐ 展现对长任务执行的理解

### 19.3.5 P1: 四层记忆架构（来自 Hermes）

**现状**: DotaHelperAgent 有三级记忆（短期/长期/情景），但缺少技能记忆层。

**补充方案**:

```
Level 0: Prompt Memory（当前会话上下文）
Level 1: Session Archive（SQLite 存储历史会话）
Level 2: Persistent Notes（MEMORY.md 存储长期事实）
Level 3: Dynamic Skills（SKILL.md 存储可复用技能）
```

**实现要点**:
- 新增 `SkillMemory` 类，管理技能记忆
- 实现记忆层级间的自动晋升机制（频繁使用的短期记忆 → 长期记忆）
- 支持语义检索（向量数据库）

**预计工作量**: 1 周
**面试价值**: ⭐⭐⭐⭐ 展现对记忆系统深度理解

### 19.3.6 P1: 双循环架构（来自 Cve2PoC）

**现状**: DotaHelperAgent 只有单层 ReAct 循环。

**补充方案**:

```
战略循环（Strategic Loop）：规划、评估、调整策略
    ↓
战术循环（Tactical Loop）：执行、验证、修复细节
```

**应用场景**:
- 英雄克制推荐：战略循环分析阵容，战术循环查询数据
- 出装推荐：战略循环确定方向，战术循环查询物品库

**实现要点**:
- 新增 `StrategicLoop` 和 `TacticalLoop` 类
- 实现循环间的协调机制
- 支持循环嵌套和递归

**预计工作量**: 1 周
**面试价值**: ⭐⭐⭐⭐ 展现对复杂任务分解的理解

### 19.3.7 P1: 子代理并行执行（来自 Hermes）

**现状**: DotaHelperAgent 有工具并行执行，但无子代理并行。

**补充方案**:

```
主 Agent → 分解任务 → 生成子代理 → 并行执行 → 聚合结果
```

**实现要点**:
- 新增 `SubAgent` 基类，定义接口
- 实现 `SubAgentExecutor`，管理子代理生命周期
- 支持失败隔离和结果聚合

**预计工作量**: 1-2 周
**面试价值**: ⭐⭐⭐⭐⭐ 展现对多 Agent 协作的理解

### 19.3.8 P2: 自适应上下文选择（来自 Loong）

**现状**: DotaHelperAgent 的上下文压缩是规则驱动的，缺少智能选择。

**补充方案**:

```
Observe → 评估上下文相关性 → Act → 选择最优上下文子集 → 执行任务
```

**实现要点**:
- 在 `ContextAugmenter` 中增加"观察-行动"推理步骤
- 使用 LLM 评估每段上下文的相关性（0-1 分）
- 只保留相关性 > 阈值的上下文

**预计工作量**: 3-5 天
**面试价值**: ⭐⭐⭐⭐ 展现对长上下文优化的理解

## 19.4 实施路线图

| 阶段 | 时间 | 任务 | 验收标准 |
|------|------|------|---------|
| **阶段 1** | 第 1-2 周 | Stop Hooks + 进度持久化 | Agent 可自主验证终止条件，支持长任务执行 |
| **阶段 2** | 第 2-3 周 | 技能自动沉淀 + 迭代优化 | 任务完成后自动生成技能，技能可迭代改进 |
| **阶段 3** | 第 3-4 周 | 四层记忆 + 子代理并行 | 记忆系统支持技能层，复杂任务可并行处理 |
| **阶段 4** | 第 4-5 周 | 双循环架构 + 自适应上下文 | 支持战略/战术双层循环，上下文智能选择 |

## 19.5 预期收益

| 维度 | 当前能力 | 融合后能力 | 收益 |
|------|---------|-----------|------|
| **自主执行** | 被动响应 | 自主终止验证 | Agent 可长时间运行，无需人工干预 |
| **自我进化** | 静态技能 | 技能自动沉淀 | 运行越久，能力越强 |
| **长任务处理** | 上下文限制 | 进度持久化 | 支持跨会话长任务 |
| **复杂任务** | 单层循环 | 双循环架构 | 可处理战略级复杂任务 |
| **多 Agent 协作** | 单 Agent | 子代理并行 | 复杂任务并发处理 |

## 19.6 参考资料

- [Hermes Agent 官方文档](https://hermesagentai.cn/) - 自我进化 Agent 框架
- [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/engineering/harness-design-long-running-apps) - 长时间运行 Agent 设计
- [Google ADK LoopAgent 文档](https://google.github.io/adk-docs/agents/workflow-agents/loop-agents/) - 循环代理模式
- [Ralph Wiggum Loop 介绍](https://blog.kwt.co.kr/랄프-위검-루프-자는-동안-ai가-코딩하는-시대가-왔다/) - 自主编码技术
- [Cve2PoC: Dual-Loop Agent Framework](https://arxiv.org/pdf/2602.05721) - 双循环 Agent 架构
- [Loong: Long Document Translation Agent](https://arxiv.org/pdf/2605.30274) - 自适应上下文选择
