# 设计文档 96 —— 第四十五轮：报告生成工具化（入口统一对话环，parse_task 入口分型退役）

> 第四十五轮。来源：2026-09-17 用户架构方向拍板——"理论上应该不区分 chat 和生成
> 报告，生成报告应该作为一个 skill 或者工具，LLM 自行根据用户输入判断要不要使用
> 这个 skill"。
>
> 状态：**✅ 已实施（2026-09-18）**。§5 五项待决策点已拍板（全部采纳推荐项）：
> ① generate_report 沿用共享服务预算 + 会话级联取消（复用对话 sid，零新取消机制）；
> ② parse_task 完全退役（task_parser.py/ResolutionDecision 删除，竞品解析回退改
> 注册表子串匹配 `competitor_registry.match_competitor()`，误判由确定性路由测试守）；
> ③ 两段式工具面（对话环常驻 {web_search, kb_recall, generate_report}，报告工具面
> 全量只在 generate_report 内部子 loop）；④ CLI run/MCP analyze 保留直通报告路径
> （新 `run_report()` 直通方法，web 为唯一对话环入口）；⑤ 一次性切换（HARNESS_VERSION
> 升版 + mock 对话环分支 + golden 改走 run_report + 路由测试补"应触发未触发"用例）。
>
> 实施偏差（相对本文草案）：代价 #4 的"tool 语义消息"简化为 assistant 摘要消息
> （"[报告已生成: 标题] 摘要"，SessionHistory 零 schema 变化——tool 角色会破坏
> user/assistant 交替压缩逻辑）；doc 66 §3.2 的 parse_task 判型回退随 parse_task
> 退役而移除（generate_report 结构化参数并入子任务文本，由子 loop make_plan 补偿）。

---

## 1. 背景与动机

现状入口链路（doc 62 §3.5 + doc 64 §5）：

```
用户输入 → parse_task（LLM 分类，~300 token/5s）
  ├─ CHAT → _run_chat（对话环，无报告）
  └─ registry/discovery/compare → 单 Lead ReAct loop（LLM 自主调工具）
       → 按 plan.resolution 分型组装（CompetitorReport / ComparisonReport）
```

- 工具选择层面已高度自主：三种分析 resolution 同走一条单 Lead loop、无分派
  if-else，`make_plan` 本身就是 Lead 自调工具——**"预路由"实际只剩 CHAT 门控
  一处**。
- 用户方向：连这最后一处也不要——入口统一为对话环，"生成报告"降格为一个
  工具/skill，由 LLM 依输入自行决定是否调用。

## 2. 目标架构

```
用户输入 → 常驻对话环（chat-first Lead loop，带全量工具注册表）
  ├─ 普通提问 → 环内直接 prose 回答（现状 chat 语义）
  └─ 分析意图 → Lead 调用 generate_report 工具
       → 工具内部 = 现报告流水线（make_plan → 收集 → delegate → aggregate
         → 组装 → writer pass）
       → 返回类型化报告（CompetitorReport / ComparisonReport）
       → 环将报告作为工具结果回灌，可继续追问（多轮分析对话）
```

- **输出类型在工具边界自然收口**：默认产物是对话；报告是工具返回值——web 层
  按"generate_report 是否触发"切换渲染（报告面板 vs 对话气泡），不再依赖入口
  预判。比"入口猜意图"更符合 agent 本能，且天然支持"边聊边补一轮分析"。
- **`generate_report` 工具契约**（草案）：`generate_report(task, competitors?:
  list, dimensions?: list, custom_sources?: dict)`——把今日 parse_task 产出的
  结构化字段（competitors/dimensions/custom_sources）变成工具参数，由 Lead 在
  调用时填；resolution 判定（registry/discovery/compare）由 Lead 在 make_plan
  里自行给出（现状已如此）。
- **`parse_task` 退役**：CHAT 门控删除；其结构化提取职责被工具参数取代。可保留
  为影子分类器跑对照（只记 metrics 不参与路由），评估误判率与成本差后再删。

## 3. 收益

1. 单一入口、单一心智模型：所有输入都是对话，报告是 Conversation 中的一次工具调用；
2. "先聊清楚再分析"成为自然能力（当前 chat 与 run 的历史通过 history_messages
   勉强互通，工具化后同环同上下文）；
3. 删除入口分类调用与 `_run_chat`/`run()` 双入口分叉（facade/web/CLI 三入口
   适配面收敛）；
4. 多轮"追问式分析"（上一轮报告太浅 → 追问 → 增量分析）解锁，doc 65 §3.3 的
   会话历史语义真正闭环。

## 4. 代价与对策（须逐项正视）

| # | 代价 | 对策 |
|---|------|------|
| 1 | **成本倒挂**：纯闲聊也付 ReAct 系统提示 + 工具注册表注入（数 k token/轮），vs 今日门控 300 token 一次 | 分级上下文：对话环基础提示轻量；generate_report 触发后才注入完整报告工具面（两段式注册，对齐 doc88 两段式经验） |
| 2 | **误判方向反转**：分析请求被环内闲聊直接回答（现状风险是反向：chat 被误入报告流水线） | generate_report 工具描述强约束（"一切竞品/市场分析类请求必须调用本工具"）；影子 parse_task metrics 监控误判率；验收集（doc 42 behavior eval）补"应触发未触发"用例 |
| 3 | **benchmark/评测重做**：HARNESS 按 resolution 分型 scripted（DISCOVERY/COMPARE 分支），golden 断言含入口语义 | HARNESS_VERSION 升版；mock LLM 增加"对话环 + generate_report 触发"分支；golden 分两期迁移 |
| 4 | **会话历史双语义**：chat 落 user/assistant 消息、报告落紧凑摘要（web_app.py 收尾两套），同环后须统一 | 工具调用轮落 `tool` 语义消息（含 report 引用），web 收尾逻辑合并 |
| 5 | **流式协议**：报告生成期间的事件（phase_start/delegate/report）与对话 text_delta 同流混排 | 事件 schema 不变（doc 63/64/66），前端按 message_id/turn 归位已支持；补"工具触发中"活动事件（与 doc95 排查中暴露的"收集期零反馈"缺陷一并治理） |

## 5. 待决策点（已拍板 2026-09-18：五项均采纳推荐项，结论见头注）

1. `generate_report` 触发后的预算/取消语义：报告子流程沿用独立 budget 还是共享
   对话环 budget（doc 39 成本钩子挂点）；
2. `parse_task` 完全退役 vs 长期保留影子观测（影响 doc 47"仅 LLM 无降级"叙事）；
3. 对话环的基础工具面最小集（kb_recall/web_search 是否常驻，还是也走两段式注册）；
4. CLI/MCP 入口是否同步工具化（MCP 的 analyze 工具语义）；CLI `run` 命令保留
   直通报告路径还是同样走环；
5. 迁移节奏：一次性切换 vs 双轨对照期（影子 parse_task metrics 观察多久）。

## 6. 与既有设计的关系

- doc 62 §3.5（单 Lead loop 统一）：本设计是其延伸——把"统一"从分析 resolution
  推进到 chat；
- doc 64 §5（意图门控）：本设计是它的退役方案，§5.4"畸形缺省落 CHAT"的原则
  （宁可普通回答不强造报告）在工具描述约束下继续成立；
- doc 88（researcher/writer 两段式）：generate_report 工具内部即 researcher/writer
  流水线，两段式注册经验复用于代价 #1；
- doc 95（结论 writer 化）：报告工具化后报告出口质量继续由 writer 体系兜底。
