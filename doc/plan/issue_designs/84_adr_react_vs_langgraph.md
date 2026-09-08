# 设计文档 84 —— 第三十四轮：ADR——为什么自研 ReAct 引擎而非只用 LangGraph

> 形态：**ADR**（工单 11 三篇精选 ADR 之一）。本文档是对既有架构决策的**追溯性记录**（决策已随 doc 51/53/60/62 落地），为 README 的 ADR 索引提供正式锚点。

| ADR 字段 | 内容 |
|----------|------|
| 状态 | 已采纳（2026-08-20 起，doc 51 落地时形成，doc 60/62 强化的取舍） |
| 决策者 | 项目维护者 + 历轮评审 |
| 关联文档 | doc 51（双引擎对照）、doc 53/60（原生 function calling、删文本协议）、doc 62（全链路编排收敛）、doc 84 结论进 doc 75 §3 |

## 1. 背景

LangGraph 提供 StateGraph 编排（plan→Send fan-out→aggregate），是社区标准方案之一。项目在 doc 51 实现了**可切换的 LangGraph 引擎**（真实可用，非 demo），与自研 ReactLoop 形成 `engine="react"/"langgraph"` 双路由。问题：主引擎为什么不是 LangGraph？

## 2. 决策

**主路径采用自研 ReactLoop（native function calling 单协议）；LangGraph 引擎保留为对照实验引擎，不承载生产主路径。**

## 3. 理由

1. **可控面深度耦合**：主路径需要的能力在自研引擎中是一等公民——`pinned_facts`（已核验事实跨步保活，doc 56）、`plan_first` 的 `tool_choice` 强制（doc 53）、`max_parallel_tool_calls` 并发分发与按序回灌（doc 59）、`stream_sink` 双通道流式（doc 63/64）、`DelegateRunner` 跨线程子 Agent span 归属（doc 54）、历史压缩可逆化（doc 56）。这些在图编排中要么绕行要么对不齐。
2. **对照实验的差异化结论已实证**：doc 51 明确记录 LangGraph 路径「取消/预算/checkpoint 不做图级对齐」——即在同一 LLM/工具/记忆下，图编排的交付面天然窄一截；这不是实现不努力，是抽象层差异。
3. **单协议收敛降低维护熵**：doc 60 删除文本 ReAct 后，引擎只剩一条 function calling 通路；自研层是这条通路的最薄实现（ReactAgent + ReactLoop 两个类），换成 LangGraph 并不减少状态管理，只是把复杂度换了个存放位置。

## 4. 后果

- 正面：编排细节（停滞检测/压缩/pinning/流式）全程可控；对照实验有真引擎背书而非稻草人。
- 负面：双引擎双维护；LangGraph 路径功能集冻结在对照所需的最小面。
- 缓解：双引擎只在 benchmark 对照时同时跑；功能演进以 react 路径为准，langgraph 路径不承诺对齐（差异化结论写进 doc 51，是特性不是欠账）。

## 5. 验证/证据

benchmark 双引擎对照表（llm_calls / cost / wall / field_accuracy）——「编排层是唯一变量」的控变量设计本身即证据；README ADR 索引引用本文档与 doc 51 数据表。
