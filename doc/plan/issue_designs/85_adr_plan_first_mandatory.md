# 设计文档 85 —— 第三十五轮：ADR——为什么 plan-first 强制（make_plan 首步 tool_choice 强制）

> 形态：**ADR**（工单 11 三篇精选之二）。追溯性记录 doc 44（规划 LLM 化）→ doc 49（plan-first 编排）→ doc 53（tool_choice 强制落地）→ doc 70（规划层意图/格式决策）一路收敛出的取舍。

| ADR 字段 | 内容 |
|----------|------|
| 状态 | 已采纳（普通对话分支豁免，见 §3.4） |
| 关联文档 | doc 44/49/53/62/70；PLAN_SCHEMA（`agent/react_schemas.py`）；`_react_loop` plan_box 懒绑定 |

## 1. 背景

ReAct 循环让 LLM 自主决定每步动作。是否允许「先自由探索、想清楚了再规划」？项目选择了**强制首步规划**：Lead 第一回合必须调用 `make_plan`（native 协议下经 `tool_choice` API 级强制，非提示词软约束）。

## 2. 决策

**分析类任务 Lead 首回合强制 `make_plan` 落地 PLAN_SCHEMA（competitor XOR competitors / dimensions / resolution / scheduling / format_hint / need_history），命中后 tool_choice 放开为 auto。**

## 3. 理由

1. **下游硬依赖**：候选竞品数硬上限（`max_discover_candidates`）、delegate 并发上限、维度委派白名单、复核工具装配、kb_recall 的竞品懒绑定（`plan_box["loop"]` 落地前为全局检索、落地后按竞品过滤）——全部以 plan 为输入。无 plan 的自由探索会让这些护栏退化为「事后补救」。
2. **防开放式漂移**：竞品分析是长任务（多 Agent、多轮抓取）。无规划的探索在真实运行中倾向「抓到哪算哪」，预算与时间不可控；plan-first 把「信息要什么」前置成一次显式决策，可评审、可记录、可对比（format_hint/output_intent/need_history，doc 70）。
3. **API 级强制优于提示词**：doc 53 的教训——提示词约束「请先规划」在长系统提示下会被忽略；`tool_choice={"type":"function","function":{"name":"make_plan"}}` 是协议保证，零浪费步数。
4. **schema 宽松 + 归一容错**：PLAN_SCHEMA `required=[]`、`normalize_format_hint` 非法值回退 `open`——强制的是「先规划」这个动作，不是「规划得完美」；历史 plan 兼容。

### 3.4 豁免分支

对话式分支（doc 64 §5.2，CHAT 决议）：`plan_first=False` + `final_as_payload=False`——普通提问不产报告面板，强制规划是纯开销。豁免由意图门控（task_parser CHAT）自动化，非 LLM 自由裁量。

## 4. 后果

- 正面：编排护栏有确定输入；每次 run 的规划可观测（plan 进 transcript/事件流）；对比实验可控变量。
- 负面：首步固定消耗一次 LLM 调用；CHAT 判定错误时（分析意图被误判为对话）用户需重述——宁可普通回答也不强造空报告（doc 64 §5.4 已决策该侧向）。
- 缓解：`make_plan` 校验错误（competitor XOR competitors）回灌可读纠正文本，LLM 自恢复（doc 38 语义）。

## 5. 验证/证据

单测：`test_native_protocol.py`（plan-first tool_choice 强制/命中后放开）；`test_react_context` 系列（plan_box 懒绑定两态）；benchmark mock 全链路以 make_plan 为首步脚本锚点——规划是评测确定性的支点之一。
