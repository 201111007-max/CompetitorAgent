# 赛后复盘 Agent 架构设计文档

> **版本**: v1.0
> **创建时间**: 2026-07-15
> **定位**: 赛后复盘 Agent 的顶层架构设计蓝图
> **状态**: 设计中

## 文档说明

本文档是赛后复盘 Agent 的**完整独立架构设计**，作为上层统领蓝图指导后续实现。

- 本文档聚焦：架构理念、系统分层、核心机制、组件职责、数据流、接口契约
- 详细实现方案见 `docs/superpowers/plans/` 下的对应文档
- 历史架构演进记录见 `docs/architecture_upgrade/ARCHITECTURE_ANALYSIS.md`

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

赛后复盘 Agent 是 DotaHelperAgent 从"查询工具"升级为"自主执行的 Agent 产品"的**旗舰功能**。

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
│  │  /api/review│  │  Vue 3 + TS  │  │  python -m review            │  │
│  └──────┬──────┘  └──────┬───────┘  └──────────────┬──────────────┘  │
├─────────┼────────────────┼─────────────────────────┼─────────────────┤
│         │           编排层 (Orchestration)          │                 │
│  ┌──────▼──────────────────────────────────────────▼──────────────┐  │
│  │                    ReviewOrchestrator                           │  │
│  │  ┌────────────┐ ┌──────────────┐ ┌──────────────────────────┐  │  │
│  │  │ 战略循环    │ │ 战术循环      │ │ 后台自我审查              │  │  │
│  │  │ Strategic  │ │ Tactical     │ │ BackgroundReview         │  │  │
│  │  │ Loop       │ │ Loop         │ │ Spawner                  │  │  │
│  │  └────────────┘ └──────────────┘ └──────────────────────────┘  │  │
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
├──────────────────────────────────────────────────────────────────────┤
│                         基础设施层 (Infrastructure)                   │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌─────────┐ │
│  │ LLM      │ │ OpenDota  │ │ 记忆系统  │ │ 技能注册表 │ │ Trace   │ │
│  │ Client   │ │ API       │ │ Memory   │ │ Skill     │ │ Langfuse│ │
│  │          │ │ Client    │ │          │ │ Registry  │ │         │ │
│  └──────────┘ └───────────┘ └──────────┘ └───────────┘ └─────────┘ │
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

### 3.3 模块目录结构

```
DotaHelperAgent/
├── core/
│   └── review/                           # 赛后复盘 Agent 模块
│       ├── __init__.py
│       ├── orchestrator.py               # ReviewOrchestrator 编排器
│       ├── strategic_loop.py             # 战略循环
│       ├── tactical_loop.py              # 战术循环
│       ├── budget.py                     # 迭代预算控制
│       ├── stop_verifier.py              # 停止验证器
│       ├── compressor.py                 # 上下文压缩器
│       ├── prompt_builder.py             # 提示词构建器
│       ├── background_review.py          # 后台自我审查
│       ├── report.py                     # 复盘报告生成
│       ├── types.py                      # 枚举和数据类型
│       └── state.py                      # Agent 状态管理
├── analyzers/
│   └── review/                           # 复盘分析器
│       ├── __init__.py
│       ├── base.py                       # BaseReviewAnalyzer 抽象基类
│       ├── laning.py                     # 对线期分析器
│       ├── teamfight.py                  # 团战分析器
│       ├── economy.py                    # 经济分析器
│       ├── decision.py                   # 决策分析器
│       └── vision.py                     # 视野分析器
├── tools/
│   └── review_tools.py                   # 复盘相关工具
├── skills/
│   └── post_match_review/                # 复盘 Skill
│       ├── __init__.py
│       └── skill.py
├── config/
│   └── review_config.yaml                # 复盘配置
└── data/
    └── reviews/                          # 复盘报告存储
```

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
# skills/post_match_review/skills/against_pa.md
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

### 6.4 基础设施层组件

| 组件 | 职责 | 复用现有 |
|------|------|---------|
| **LLMClient** | LLM 调用 | 复用 `utils/llm_client.py` |
| **OpenDotaClient** | OpenDota API 调用 | 复用 `utils/api_client.py`（新增 `get_player_matches()` 和 `get_match_details()`） | 小 |
| **AgentMemory** | 记忆系统 | 复用 `memory/memory.py`（扩展四层） | 中 |
| **SkillRegistry** | 技能注册与管理 | 复用 `skills/registry.py` |
| **TraceContext** | 可观测性 | 复用 `utils/trace_context.py` |

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

    def get_partial_result(self) -> Optional[PartialReviewReport]:
        """获取中断后的部分结果"""
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

## 九、与现有系统的集成

### 9.1 集成点清单

| 集成点 | 现有组件 | 集成方式 | 改动量 |
|-------|---------|---------|--------|
| **LLM 调用** | `utils/llm_client.py` | 直接复用 | 无 |
| **API 客户端** | `utils/api_client.py` | 新增 `get_player_matches()` 和 `get_match_details()` | 小 |
| **记忆系统** | `memory/memory.py` | 扩展四层记忆（新增 Level 2/3） | 中 |
| **工具注册** | `core/tool_registry.py` | 注册复盘相关工具 | 小 |
| **Skill 注册** | `skills/registry.py` | 注册 `PostMatchReviewSkill` | 小 |
| **会话管理** | `core/conversation_manager.py` | 复盘对话作为独立会话 | 小 |
| **前端展示** | `web/app.py` + `frontend/` | 新增 `/api/review` 端点 + 复盘展示组件 | 中 |
| **Langfuse** | `utils/trace_context.py` | 复盘分析过程接入 trace | 小 |
| **并行执行** | `core/parallel_executor.py` | 复用并行执行框架 | 小 |
| **Prompt 管理** | `utils/prompt_manager.py` | 复用 Prompt 版本管理 | 小 |

### 9.2 新增 API 端点

```
POST /api/review
  Body: { "match_id": "8893253595" }
  Response: SSE 流式返回分析进度 + 最终报告

GET /api/review/{match_id}/status
  Response: { "status": "analyzing", "progress": 0.6, "current_phase": "teamfight" }

GET /api/review/{match_id}/report
  Response: 完整复盘报告 (Markdown)

POST /api/review/{match_id}/interrupt
  Response: { "status": "interrupted", "partial_report": {...} }

GET /api/review/history
  Response: 复盘历史记录列表
```

### 9.3 前端集成

```
新增前端组件:

  frontend/src/
  ├── components/
  │   └── ReviewPanel.vue            # 复盘面板（主组件）
  │       ├── ReviewProgress.vue     # 分析进度展示
  │       ├── ReviewReport.vue       # 复盘报告展示
  │       └── ReviewTimeline.vue     # 分析时间线
  ├── composables/
  │   └── useReview.ts              # 复盘 SSE 流式处理
  ├── stores/
  │   └── review.ts                 # 复盘状态管理
  └── types/
      └── review.ts                 # 复盘类型定义
```

---

## 十、配置体系

### 10.1 review_config.yaml

```yaml
# config/review_config.yaml
# 赛后复盘 Agent 配置

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

| 阶段 | 内容 | 验收标准 | 依赖 |
|------|------|---------|------|
| **阶段 1: 数据层** | API 扩展 + 数据模型定义 | OpenDota 数据获取完整、MatchData 模型验证 | 无 |
| **阶段 2: 核心骨架** | 预算控制 + 停止验证 + 提示词构建 | 单元测试覆盖、接口契约验证 | 阶段 1 |
| **阶段 3: 单阶段分析** | 战术循环 + 单个分析器（对线期） | 端到端完成一次对线期分析 | 阶段 2 |
| **阶段 4: 全流程** | 战略循环 + 全部分析器 + 报告生成 | 端到端完成一次完整复盘 | 阶段 3 |
| **阶段 5: 并行优化** | 并行子代理 + 上下文压缩 | 并行分析性能提升 > 30% | 阶段 4 |
| **阶段 6: 自我进化** | 后台审查 + 技能沉淀 + 记忆扩展 | 复盘后自动生成技能、记忆持久化 | 阶段 4 |
| **阶段 7: 前端集成** | API 端点 + SSE 流式 + 复盘展示组件 | 前端可实时展示分析进度和报告 | 阶段 4 |

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
| 赛后复盘 Agent 综合设计 | `docs/superpowers/plans/2026-07-13-post-match-review-agent.md` |
| Claude Code 设计模式分析 | `docs/superpowers/plans/2026-07-13-claude-code-patterns.md` |
| 前沿 Agent 理念融合 | `docs/superpowers/plans/2026-07-10-frontier-agent-concepts.md` |
| 产品定位转型 | `docs/superpowers/plans/2026-07-10-product-transformation.md` |
| OpenDota API 参考 | `docs/superpowers/plans/2026-07-10-opendota-api-reference.md` |

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
| v1.0 | 2026-07-15 | 初始版本，完整独立架构设计 |
