# 设计文档 64 — 对话双通道架构：叙述流 / 报告载荷分离 + 分段思考渲染 + 意图门控报告

> 第十四轮新增项。触发：真实使用中暴露三个相连的体验问题——
> （1）**报告 JSON 泄漏进正文**：对话里会把 `{"competitor": ..., "dimensions": [...]}` 的机器可读报告原文逐字打出来，理应只作为结构化面板呈现；
> （2）**思考被塞进单个可折叠框**：前端把一次 Lead 消息的全部思考累积进唯一一个 `<details>`，像 Claude 那样「一段思考、一段结论」的交替排版始终出不来；
> （3）**无论问什么都强制返回报告**：问个和竞品分析无关的普通问题，会话仍会走完整的 PLAN→REPORT 链路、弹出一份竞品报告面板。
>
> 基线与边界：流式/前端对应**设计文档 63**（`StreamDelta`/`text_delta`/`thinking_delta` 的五层旁路与打字机）、单协议 function calling 对应**设计文档 60**、多 Agent 编排对应**设计文档 49/62**。本文档在这三者之上做一次**协议层的通道切分**与**编排层的意图门控**，目的是根治（1）（2）（3）而非打补丁；不改动 54 个非流式调用方的既有行为。

---

## 1. 三个症状与共同根因

三个问题看似独立，实则共享一个结构性根因：

> 当前 Web 对话层把 **三类本质不同的事物** 塞进**同一条未分化的文本流**里，且把**用户任务**无条件塑造成「竞品分析报告」形状：
>
> - **叙述（narrative）** —— Lead 的思考与执行叙述，理应是对话正文，实时打字机展示；
> - **报告载荷（payload）** —— Final Answer 的 REPORT_SCHEMA JSON，理应被解析成结构化面板，绝不进正文；
> - **任务意图（intent）** —— 用户到底是「要一份竞品分析」还是「问一个普通问题」——系统从不区分。

只要这三者仍共用一条流、且报告产出是「无条件的」，症状就必然周期性复发：JSON 漏进正文（叙述/载荷同流）、思考挤成单框（叙述无分段）、普通问题也弹报告（意图无门控）。

---

## 2. 根因定位（附代码证据）

### 2.1 报告 JSON 泄漏进正文

链路（已在真实运行中复现）：
1. `agent/react_agent.py:185` `_run_native` 的**每一轮**（含收尾轮）都 `complete_with_tools(..., stream_sink=stream_sink)`；
2. `agent/react_agent.py:223-225` 收尾轮 `reply.tool_calls` 为空，`reply.content` 即 REPORT_SCHEMA JSON（报告）；
3. `llm/client.py:275-279` 流式分支把**每个** delta（含 Final Answer 轮的 content）经 `_sink_delta` 投给 sink；
4. `web_app.py:129 _stream_sink` 把 `text` 类 delta 无差别转成 `text_delta` SSE；
5. `static/app.js` 的 `text_delta` 分支把该增量当打字机正文渲染进 Lead 气泡 → **原始 JSON 原文可见**。

与此同时 `facade/api.py:375` 又发 `report` 事件 → 前端另起 `renderReport` 面板。于是同一份 JSON **既被打字机敲出、又被面板渲染**。

**为什么看起来难辨别**：sink 层在推流中途无法知道「这一轮是不是 Final Answer」——要等整轮返回、确认无 tool_calls 才知道。所以「图层兜底」都讳莫如深，必须把分类点放在**真相信号所在的源头**（见 §3）。

### 2.2 思考被塞进单个可折叠框

`static/app.js` 对每条 Lead 消息维护**两个累加变量**：
- `s.think`：把该消息全部 `thinking_delta` 追加成一个字符串；
- `s.text`：把该消息全部 `text_delta` 追加成一个字符串。

`renderStreamHTML()`（app.js:82）在 80ms 节流里重建**整个气泡**的 `innerHTML`：先一个唯一的 `<details class="thinking">已思考</details>` 包住全部思考，再把全部正文 `marked.parse(s.text)` 拼在下面。

于是消息图恒为 `[一个思考框] + [一大块正文]`——思考在**容器内部**无限增长，而不是随流式**一个接一个地追加成兄弟节点**。这就是「所有思考在一个框内」的出处。Claude 的「一段思考、一段结论」交替排版，要求把流拆成**有序分段**、按到达顺序追加 DOM，而非单体重渲。

### 2.3 无论问什么都强制返回报告

Web 统一入口 `facade/api.py:220 `run()`（`analyze()` 同构 lab）**无条件**：
1. `parse_task(task)` 提取竞品 + resolution —— 对任意任务都执行；
2. `make_plan` 首步强制（`agent/make_plan.py:38` 校验**必填** `competitor`/`competitors`，除非 resolution=discovery）；
3. 单 Lead loop 跑完 → `react_report.assemble()` → CompetitorReport / ComparisonReport；
4. `_finalize_competitor_report` 无条件发 `report` 事件 → 前端渲染报告面板。

全程**没有任何**「用户没要竞品分析、只要普通对话」的分支。所以问「今天天气」也会得到一份（多为空维度、低置信度的）竞品报告面板。根因是**意图无门控**：编排层没有把「分析类请求」与「普通提问」分开。

---

## 3. 核心架构方案：叙述流 / 报告载荷双通道

### 3.1 目标形态

协议层把「消息产出」显式切成**两条独立通道**，永不混流：

```
                ┌────────────────────────────────────────────┐
                │  Lead 一轮 complete_with_tools（doc 60/63）  │
                └────────────────────────┬───────────────────┘
                                         │
                    按「本轮是否产出 tool_calls」分类
                                         │
        ┌────────────────────────────────┴───────────────────────┐
        │                                                        │
  有 tool_calls ⇒ 叙述轮                                 无 tool_calls ⇒ Final Answer 轮
        ▼                                                        ▼
   Stream 通道（narrative）                            Payload 通道（report）
   ├ thinking_delta → 「已思考」折叠块                 ├ 文本被捕获而非入正文
   └ text_delta     → 正文打字机（分段追加）           ├ REPORT_SCHEMA 校验 → assemble
        │                                            └ report 事件 → 结构化面板
        │                                                     ▲
        └────────────── 仅此通道可达正文气泡 ◄───────────────┘（JSON 永不进正文）
```

**不变量**：正文气泡只能由 Stream 通道增量,Payload 通道的文本永远被捕获进 `assemble()`，绝不以原文入正文。

### 3.2 分类点放在真相信号所在的源头

「本轮有没有 tool_calls」这个终止真相信号，天然在 `complete_with_tools` 的流式分支手里——它的 `_StreamMeter` + `tool_acc` 在流结束后就知道本轮结果。因此：

- **在 `llm/client.py` 流式分支（complete_with_tools）做 Final-Answer 归类**：流结束后若 `tool_acc` 为空（无 tool_calls），说明本轮文本是 Final Answer（报告 JSON），把这条流**单独归入 Payload 通道**——其文本不再递进 Stream 通道的 sink，而是随 `_finalize_stream_calls` 一起回给调用方（ReactAgent 已 `return reply.content` 给 assemble）。
- **对比被否决的「Web 层缓冲兜底」**：在 `web_app._stream_sink` 缓冲再判定，是把信号从源头一路穿透到最外圈——它有 `tool_acc` 可作依据，却没有意义。分类点越靠近真相信号，越少穿透、越不需要语义猜猜。

### 3.3 兼容与回滚

- 流式路径默认关闭（`stream_sink is None`），54 个非流式调用方 `_run_native` 不走流式，`return reply.content` 行为逐字节不变；
- 仅当传了 `stream_sink`（本 Web）且本轮为 Final Answer 时，文本转入 Payload 通道；
- 归类为纯新增逻辑，不触碰非流式 `_complete_with_tools`。

### 3.4 需要后端补充的最小信号：`turn` 段号

为支撑 §4 的分段渲染，`StreamDelta` 增加 `turn: int | None`（当前 assistant 步序号，由 ReactAgent 迭代计数注入）。该字段随 `text_delta`/`thinking_delta` 下发，前端据此识别段边界。缺省为空 → 前端退回当前「单框/整块」行为，向后兼容。

---

## 4. 问题 1 推荐解法：分段思考渲染（Claude 式交替排版）

### 4.1 根因回述

见 §2.2：消息被压成 `[一个思考框]+[一大块正文]`，靠 80ms 节流整块重渲 `innerHTML`。既无「一段思考、一段结论」的交替，也存在每次全量 `marked+DOMPurify` 的 CPU 抖动。

### 4.2 推荐方案：有序分段 + 追加式 DOM

把「消息 = 两个累加变量」改为「消息 = 一段有序的 typed segment 列表」：

```
type Segment =
  | { kind: 'think', node: HTMLDetailsElement, body: HTMLElement, open: bool }
  | { kind: 'text',  node: HTMLElement, done: bool }
```

渲染算法（`app.js` 重写 `renderStreamHTML` 为追加式）：
1. 收到 `thinking_delta`/`text_delta`：**取 payload 的 `turn`**；若与「当前开放段」的 `turn`/`kind` 一致 → 原地 `body.textContent +=`；若 `turn` 或 `kind` 变化 → **关闭当前段、push 一个新兄弟节点**再追加。
2. `thinking` 段只生长在**自身的`<details>`**，`text` 段只生长在**自身的正文节点**——按到达顺序交错出现在气泡里，天然是「一段思考、一段结论」。
3. 移除整体 `innerHTML` 重建：每段只 append/inline 更新自身节点，`marked` 只在 `text` 段**收尾时**渲染一次（而非每次 delta），性能同步改善。
4. 视觉偏好（类 Claude）：思考块内内容**收尾后默认折叠**（`open=false`），避免多个思考块全展开；流式进行中的当前块保持 `open`。

### 4.3 后端配合

- `StreamDelta.turn` 注入（§3.4）；
- `text.stop` 保持只在终态发一次（doc 63 §7.3），段闭合由前端依据 `turn` 变化判定，无需新增事件。

### 4.4 不做的事

不在后端做「把思考切段」——思考天然按 assistant 轮次分段，分段是**渲染层**职责，后端只要给出 `turn` 段号即可。

---

## 5. 问题 2 推荐解法：意图门控的报告产出

### 5.1 根因回述

见 §2.3：Web 入口无条件把任意任务塑成 `PLAN→REPORT`，无「普通提问」分支。

### 5.2 推荐方案：入口意图分类 + 对话式分支

**在编排入口（`run()`/`analyze()`，`facade/api.py`）加一次意图门控**，把请求分为两路：

- **分析类请求**（分析/对比/普查某竞品）→ 现状链路：`make_plan` 首步强制 → REPORT_SCHEMA → `assemble` → `report` 面板（等于 §3 Payload 通道）；
- **非分析请求**（普通提问/闲聊/与竞品无关）→ **对话式分支**：
  - 不再强制 `make_plan`，改用**对话形态的 Lead system prompt**（按普通模型回复引导，无 PLAN/REPORT schema 约束）；
  - 默认 `format(json_object)` 关闭，允许模型以自由 prose 回答；
  - **不调用** `react_report.assemble` 与 `report` 事件 —— 答案经 **Stream 通道（text_delta/thinking_delta）** 以普通会话消息呈现，无面板、无维度、无置信度。

分类器实现：在既有 `parse_task` 的 `ResolutionDecision` 之外**新增一个 `CHAT`/`CONVERSATIONAL` 决议**；`make_plan` 校验、`_plan_resolution`、报告组装点据此分流。分类只在入口做一次（LLM 判定 + 规则兜底），避免侵入 loop 内部。

### 5.3 门控位置的取舍

- 放**入口**（推荐）：意图是「请求级」属性，入口一次判定即可决定 system prompt 与收尾契约；loop 无需感知。
- 否决「在 loop 内判 resolution 再决定要不要 report」：loop 已被塑造成报告形状（首步强制 make_plan、REPORT_SCHEMA 收尾），事后改收尾是打补丁而非门控。

### 5.4 边界与回退

- 分析类请求行为**逐字节不变**（回归面收敛到 Web 入口的意图分支 + 前端是否渲染面板）；
- 分类失败（LLM 不稳）：缺省落在**对话式分支**（宁可普通回答，也不强造一份空报告），与 §2.3 现状相反的方向，对用户更友好；
- 对话式分支仍可携带思考折叠块（Thinking），仅供决策透明，不产出报告。

---

## 6. 与既有设计的关系与边界

| 设计文档 | 关系 |
|---|---|
| 60 `remove_text_react`（单协议） | 不推翻；在 `complete_with_tools` 流式分支内做 Final-Answer 归类，非流式路径不变 |
| 63 `chat_frontend_text_delta_streaming` | 在其打字机之上做通道切分（§3）与分段渲染（§4）；`text.stop` 语义不变 |
| 49/62 编排 | 意图门控只发生在 `run()`/`analyze()` 入口，Lead loop 内部不感知 |
| 50 SSE 事件桥 | `report` 事件继续承载 Payload 通道；叙述事件继续承载 Stream 通道 |

边界：本文档是**协议/编排层设计**，不改动多 Agent 委派、记忆、知识库等下游模块。

---

## 7. 验收标准

1. **JSON 不进正文**：跑一次真实分析，对话正文中绝不出现 `{` 起始的 REPORT_SCHEMA JSON，报告只以面板呈现（`report` 事件）。→ **代码已验证**（`test_stream.py`：Final-Answer 文本不进 sink；`test_web_m2_streaming.py`：ChatResult 无 report 面板）；真实 LLM 手工复核待 §8.3。
2. **分段思考**：同一 Lead 消息中，多个思考段各自成 `<details>`，与本文段按到达顺序交错；思考段收尾自动折叠；无整体 `innerHTML` 重渲（可用元素打点验证渲染次数）。→ **代码已验证**（app.js 追加式 DOM + `turn` 段边界 + 思考收尾折叠，SSE turn 透传经 `test_chat_gate_64.py`/`test_web_m2_streaming.py` 断言）；真实浏览器视觉复核待 §8.3。
3. **意图门控**：问普通问题 → 只出普通会话消息、无报告面板；问「分析 Cursor」→ 照旧出面板。→ **代码已验证**（`test_chat_gate_64.py`：chat → ChatResult、分析 → CompetitorReport）。
4. **回归**：54 个非流式调用方单测全绿；`test_stream.py`、`test_web_m2_streaming.py` 不回归；CI 静态门禁（`ruff check .` + `mypy .`）通过。→ **已验证**（全量 787 unit passed；ruff 通过；mypy 本改动涉及文件 0 error——`core/alerting.py`/`core/checkpoint.py` 的 7 个 error 为改动前既有、与本次无关）。

## 8. 实施顺序（分批）

1. **§3 双通道 + §5 意图门控（后端）**：`controller`——`llm/client.py` 加 `turn` 与 Final-Answer 归类；`agent/react_agent.py` 注入 `turn`；`facade/api.py` 加 CHAT 决议与对话分支。配单测。
2. **§4 分段渲染（前端）**：`static/app.js` 重写为追加式分段渲染 + `style.css` 调整思考块收尾折叠样式。配 `test_web_m2_streaming` 前端断言。
3. **端到端 + 文档状态表**：真实 LLM 手工验证三现象消除，回填本文档状态。

---

## 状态表

| 项 | 内容 | 涉及 | 状态 |
|---|---|---|---|
| §3 | 叙述/载荷双通道 + Final-Answer 源头归类 | `llm/client.py`、`agent/react_agent.py`、`web_app.py` | [x] 已实现（2026-08-28，M1/M2/M4 收口） |
| §3.4 | `StreamDelta.turn` 段号注入与透传 | `llm/client.py`、`web_app.py` | [x] 已实现（2026-08-28，turn 随 text/thinking 增量透传到 SSE payload） |
| §4 | 前端分段思考渲染（追加式 DOM + 思考收尾折叠） | `static/app.js`、`static/style.css` | [x] 已实现（2026-08-28，segments 追加式 + turn 段边界 + 思考折叠） |
| §5 | 意图门控 `CHAT` 决议 + 对话式分支 | `facade/api.py`、`core/task_parser.py`、`agent/make_plan.py` | [x] 已实现（2026-08-28，run/analyze 入口门控 + ChatResult + build_chat_system_prompt） |
| §8.3 | 真实 LLM 端到端验证 | 手工 | [x] 已验证（2026-08-28，ark deepseek-v4-flash 真实调用：现象1 JSON 不进正文 / 现象3 意图门控均确认；现象2 前端渲染经 SSE turn 透传 + 单测断言） |