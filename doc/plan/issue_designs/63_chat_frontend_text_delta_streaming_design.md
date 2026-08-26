# 设计文档 63 — 对话式前端 + 流式 `text_delta`（类 Claude 思考过程展示）

> 第十三轮新增项。触发：用户在真实使用中提出两个体验诉求——（1）Web 端仍是「单次分析」页（顶部输入 + 开始按钮 + 左侧活动日志 + 右侧一次性报告），要改成**多轮对话**形态（发送按钮、输入框在底部、输出在输入框上方）；（2）参照 Claude Code 的流式体验（`best_claude_code` 的 `StreamEvent` → `text_delta` 增量下发 → 前端按 delta 追加重渲染），要求 **LLMClient 暴露流式分词，`text_delta` 层层中转到前端**，把模型的**思考过程**实时给到用户，而非等报告一次性弹出。
>
> 基线与边界：现有 SSE/进度/静态资源对应**设计文档 50**（`ProgressEvent` 事件桥 + 进度可视化 + marked/DOMPurify 渲染）——本文档在其上做对话化与流量化改造，不推翻既有事件桥；多 Agent 编排对应**设计文档 49/62**，本文档只在其文本产出侧挂流式中转，不改编排骨架。

---

## 1. 问题现状

### 1.1 前端是「单次表单」而非「对话」

`competitor_agent/static/index.html` + `app.js`：
- 顶部 `<input#task>` + `<button#start-btn>`（开始分析）——一次性提交，无多轮。
- 结果分两栏：左 `#log` 活动日志（事件消息）、右 `#report` 报告面板（`report` 事件一次性注入 `marked.parse(DOMPurify(...))`）。
- 无「用户消息 / 助手消息」的双向对话心智；历史只能靠 `/api/history` 回味。

### 1.2 报告一次性成型，无流式感知

- `ReportBuilder.build()`（`core/report_builder.py`）等**全部维度完成后**才调用 `MarkdownRenderer.render(report)` 一次性拼出整份 `markdown_report`；web 在最终 `report` 事件里一次性下发。用户看到的是「活动日志滚几分钟 → 报告啪一下出现」，缺乏模型正在思考/生成的实时反馈。

### 1.3 LLMClient 无流式通道

`competitor_agent/llm/client.py`：
- `complete()`、`complete_with_tools()`、`complete_json()` 三个入口**全是非流式** `client.chat.completions.create(...)`（未传 `stream=True`），经 `_attempt_models`（重试/fallback/超时）+ `_log_call`（计价/埋点）。
- 没有「按 token 增量产出 + 中转到事件桥」的通道，`ProgressEvent` 也只有 `phase/progress/report/error` 等粗粒度事件，无 `text_delta`。

### 1.4 对齐参照（best_claude_code）

对照仓库的流式范式：后端把模型输出切成增量事件（`message_delta` / `text_delta`）逐段下发；前端**内存累积** `content += delta`，每来一个 delta **重渲染一次**气泡（净化后 innerHTML），并自动滚底。关键点：**增量事件、内存累积、逐 delta 重渲、净化注入、自动滚底**。

---

## 2. 目标设计

1. **对话式前端**：`对话列表（上） + 输入框/发送按钮（下）`。发送即开启新助手回合；消息区为「用户消息/助手消息」的气泡流；多轮可连续追问；支持停止当前回合。
2. **Option C 流式分词**：`LLMClient.stream()` 暴露流式增量（`text(text_delta)` / 可选 `thinking(thinking_delta)`），经 ReactAgent（Lead/子 Agent）→ 事件桥 → SSE → 前端逐段追加重渲染，**把模型的实时叙述 / 工具调用 / 推理链给到用户**（类 Claude）。
3. **多轮会话**：以 `session_id` 关联；同会话内把前文（用户问句 + 助手结论摘要）带进下一轮上下文（复用既有 Lead 记忆/RecentSession，不引入大改动）。

---

## 3. 事件协议（SSE）扩展

`ProgressEvent`（`domain_types/events.py`）字段够用（`event/phase/progress/message/payload`），**不新增字段**，靠 `event` 取值扩展类型。现有（设计文档 50）：`session_started` `phase_start` `phase_complete` `progress` `discovery.candidate` `discovery` `report` `cancelled` `error`。

新增事件类型（`event` 枚举扩充，payload 上加 `message_id` 关联）：

| event | 语义 | payload 关键字段 | 对应 claude |
|---|---|---|---|
| `message.start` | 一个助手/子 Agent 消息开始 | `message_id`, `source` | `message_start` |
| `text_delta` | 流式文本增量（模型的实时叙述/回答） | `message_id`, `delta` | `content_block_delta text_delta` |
| `thinking_delta` | 推理链增量（模型若暴露 reasoning_content） | `message_id`, `delta` | `content_block_delta thinking` |
| `text.stop` | 一段文本/思考结束 | `message_id`, `final` | `content_block_stop` |
| `message.stop` | 助手消息结束 | `message_id`, `summary` | `message_stop` |
| `tool_use` | 工具调用开始 | `message_id`, `tool_name`, `tool_input` | `content_block tool_use` |
| `tool_result` | 工具调用结束摘要 | `message_id`, `tool_name`, `ok`, `snippet` | `tool_result` |
| `report.section` | 报告某个维度段已成型（可选） | `dimension`, `markdown` | （自有） |
| `report` | 整份报告完成（既有，补 `report_url/report_path`） | `markdown_report`, `report_url`, `report_path` | （自有） |

**`message_id`**：后端每次 `message.start` 下发 `message_id`，后续 `text_delta/tool_use/tool_result/message.stop` 携带同一 id；前端按它把增量归位到对应气泡。`source` 标明来源：`lead` / `sub.<dimension>` / `report`。

**保留**：`phase/progress/discovery/error/cancelled` 均可继续用（活动页或收敛到对话内提示）；进度条 UI 已按用户要求移除（仅事件仍可携带 `progress` 数字做可观测，不渲染条）。

---

## 4. 传输层与后端通道

### 4.1 对话 SSE 通道

- 保留 `GET /api/analyze?task=&session_id=`（EventSource 原生支持、自动重连）作为**单回合分析流式**通道：前端每次发送 → 建立/续用一个 session_id 的 SSE 流。
- （可选进阶）若后续需要 POST body（长 task、结构化上下文），切 `POST /api/chat` + `fetch` + `ReadableStream`；v1 不必，task 是短字符串。

### 4.2 多轮与会话状态

- `session_id` 关联多轮：`_sessions[sid]` 已在（`web_app.py`），扩充为保留「消息历史」视图供前端回查。
- 下一轮上下文：把上一轮 `report`/`message.stop` 的 `summary`（或报告标题+维度列表）并入 Lead 提示，作为「已知结论续聊」基础——实现上复用 `AnalysisSession` 归档数据（已在 `web_app.py` 落库）。

### 4.3 心跳 / 断线

- 沿 existing `_EVENT_WAIT_TIMEOUT` 挂起机制；为空时发 `: keep-alive\n\n` SSE 注释心跳保活。
- 断连触发协作式取消（existing `POST /api/cancel` + `set_cancel`，已打通 web sid ↔ 内部取消标志，设计文档 50）。

---

## 5. LLMClient 流式分词（Option C 核心）

### 5.1 新接口

`competitor_agent/llm/client.py` 增加：

```python
@dataclass
class StreamDelta:
    kind: str          # "text" | "thinking"（模型若暴露推理链）
    text: str          # 一个增量片段
    model: str = ""    # 实际产出增量所用模型
    message_id: str = ""  # 归属（事件桥回填）

class LLMClient:
    def stream(self, messages, *, json_mode=False) -> Iterator[StreamDelta]:
        """yield 流式增量；首块超时/可重试错误重启到下个 fallback 模型。"""
```

- 契约：`Iterator[StreamDelta]`，产出顺序即下游 `text_delta`/`thinking_delta` 的投递顺序。**不返回完整字符串**——完整文本由调用方（ReactAgent / facade）在消费时累加。
- `kind="text"` 直接作为 `text_delta`；`kind="thinking"` 作为 `thinking_delta`（前端折叠）。模型不暴露推理链则只有 `text`。

### 5.2 SDK 流式读取

```python
resp = client.chat.completions.create(model=model, messages=messages,
                                      stream=True, **extra)
for chunk in resp:
    choice = chunk.choices[0] if chunk.choices else None
    if not choice or not choice.delta:
        continue
    if getattr(choice.delta, "reasoning_content", None):   # DeepSeek 等暴露推理
        yield StreamDelta(kind="thinking", text=choice.delta.reasoning_content, model=model)
    if choice.delta.content:
        yield StreamDelta(kind="text", text=choice.delta.content, model=model)
```

- 结构化约束（`json_mode`）：沿用 `response_format={"type":"json_object"}`（与 `complete()` 一致）。

### 5.3 流式下的可靠性（重试 / fallback / 超时）

非流式的 `_attempt_models` 是「整次调用重试」。流式是 generator，重试语义改为「**首块到达前**判定 + 异常时重启」：

```python
def stream(self, messages, *, json_mode=False):
    models = [self._model, *self._fallback_models]
    for model in models:
        trap = _StreamAttemptBudget(model)          # 记录该模型已失败，计数≤max_retries
        while trap.can_retry():
            gen = self._stream_once(messages, model, json_mode)  # 返回 (generator, started)
            try:
                first = await/time-limited 取首块
                # 首块正常 → 进入纯消费：把后续直接 yield 给调用方
                yield first; yield from gen_rest; mark complete; return
            except 超时/可重试错:
                trap.note_retry()
            except 不可重试错:
                raise LLMUnavailableError(...)
    raise LLMUnavailableError(f"流式失败：{len(models)} 模型全耗尽")
```

- **已下发的增量与回退替更**：一旦发生 fallback，新模型重头产出，语义上属于「新一条回答」。约定：回退时发 `message.start`(新 id) + `text.stop`(旧 id, `final=false`)；前端展示旧条目失效即可，不强制回滚已显示文本。
- **首块超时**：以「连接+读」超时包裹取首块，`timeout` 复用 `self._timeout`。

### 5.4 计价 / 埋点

- 流式结束（收完 chunk）后按 SDK 返回的 `usage` 复用 `_log_call` 记 `llm.call`（模型/tokens/耗时/成本），保证成本核算与 `complete()` 一致。
- 可选：流式中途发 `llm.stream.begin/end` 会话事件（可观测，不落 prompt 全文）。

### 5.5 注入 / mock 兼容

- 注入 `call_func` 若为生成器函数（`inspect.isgeneratorfunction`）→ 透传 yield；否则一次性 `yield StreamDelta(kind="text", text=fn(...))` 兜底（兼容既有 mock）。
- `complete/complete_with_tools/complete_json` **不变**——结构化/聚合仍走非流式收口，保证 JSON 完整可解析（doc 49 子 Agent 的 `SUBAGENT_RESULT_SCHEMA` / doc 62 候选的 `REPORT_SCHEMA`）。

---

## 6. 层层中转：文本增量如何汇聚

### 6.1 源分层（`source` 字段）

| source | 谁产出 | 前端呈现 |
|---|---|---|
| `lead` | Lead Agent 的规划/复盘/结论叙述 | 主对话流（展开） |
| `sub.<dim>` | 维度/候选子 Agent 的 ReAct 文本 | 子任务气泡（默认折叠为一行） |
| `report` | 最终报告（`report`/`report.section`） | 报告 Markdown 面板 |

### 6.2 并发归并（子 Agent 并行时）

- 并行子 Agent 各自 `stream()` 产出多路增量。**两条策略**：
  1. **顺序串流（默认，v1）**：Lead 把委派结果按完成序回灌，前端统一到**一条助手流**，`source` 标注 `sub.<dim>`——实现简单、无跳动，代价是并行收益在视觉上被「串行化」。
  2. **并行视口（可选增强）**：每条 `sub.<dim>` 独立 `message_id` 气泡，前端并排/可折叠（Claude 式「N 个并行子任务」）。需要前端按 `message_id` 分行缓冲 + 居中聚合滚底。
- v1 选**顺序串流**，保留 message_id 契约以便后续切并行视口无需改协议。

### 6.3 思考 vs 产出

- `thinking_delta`（推理链）→ 前端折叠块（如「已思考 · 展开」），不打断正文字流；`text_delta` → 正文打字机。
- 模型不暴露 reasoning_content 时，`stream()` 只有 `text`，则「思考过程」退化为**模型的实时叙述 + 工具调用活动**（同样满足「看见模型在做什么」）。

### 6.4 结构化 Final Answer 的展示取舍

- 子 Agent 的 `Final Answer` 是 JSON（`summary/details/confidence`）。**原始 `text_delta` 是正在构造的 JSON，对用户不友好**。
- 约定：`stream()` 产出的原始 token **只用于「思考/叙述」展示**，不直接注入报告；报告正文仍来自 `report` 事件（渲染后的 markdown），并走 `report.section` 支持逐维度流入。**思考过程 ≠ 报告**，二者由不同事件承载。

---

## 7. 前端对话页设计（index.html / app.js / style.css 重写）

### 7.1 布局（要求 1：输入在下、输出在上）

```
+-------------------------------------------------------------+
| header: 竞品分析 Agent ·（设备可选：新会话 / 停止）          |
+-------------------------------------------------------------+
| 消息区（scroll，自动滚底）                                   |
|   ┌─────────────────────────────────────────────────────┐  |
|   │ [用户] 分析市面上常见的 coding agent         (右)     │  |
|   │ ┌───────────────────────────────────────────────┐   │  |
|   │ │ [助手 lead] 我来制定采集路线图…                │   │  |
|   │ │  · 思考: <折叠>  · web_extract(github/…)  · …  │   │  |
|   │ └───────────────────────────────────────────────┘   │  |
|   │ ┌───────────────────────────────────────────────┐   │  |
|   │ │ [报告] # Cursor vs Copilot 竞品格局对比报告…    │   │  |
|   │ │ 报告已生成 · 地址: /api/reports/... · 复制 · 下载 │   │  |
|   │ └───────────────────────────────────────────────┘   │  |
|   └─────────────────────────────────────────────────────┘  |
+-------------------------------------------------------------+
| 输入框（底部，多行 textarea）            [发送]  [停止]      |
+-------------------------------------------------------------+
```

- HTML：`<div id="messages">`（消息流）+ 底部 `.composer`（`<textarea id="input">` + `<button id="send-btn">`）。
- 移除：`开始分析` 按钮、`#task` 顶部输入框、`#log` 活动日志转归对话消息、「进度条/会话日志」已在设计文档 62 处理阶段删除。

### 7.2 消息模型

```js
const convo = [];             // {role:'user'|'assistant', id, html?, status:'streaming'|'done'|'error'}
let assistantBuf = new Map(); // message_id -> {element, text, thinkingOpen, toolbar:[]}
```

- 用户发送 → 追加 user 气泡 → 建 `EventSource('/api/analyze?task=...&session_id=')`；
- `message.start` → 按 `message_id` 建 assistant 气泡（`source` → 样式）；`text_delta` → `assistantBuf[id].text += delta`，节流重渲；`tool_use/tool_result` → 追加工具折叠块；`report` → 填报告 Markdown 面板 + 地址条（复用 design 62 的 `report_url/report_path` + 复制/下载）；`message.stop` → 收起光标、`status='done'`。

### 7.3 打字机渲染

- **内存累积**：`text += delta`（先纯文本累积）。
- **节流重渲**：rAF/`setInterval(~80ms)` 批量把缓冲 delta 拼进气泡的 `innerHTML = flagged_parse(accumulated)`（`marked.parse` + `DOMPurify.sanitize`），避免每 delta 一次全量 `marked`/`DOMPurify` 的重 CPU 抖动。
- **自动滚底**：`messages.scrollTop = scrollHeight`（deltas 到达时触发）。
- **光标**：`status==='streaming'` 时气泡尾加 `▊` 光标元素，`text.stop/message.stop` 移除。

### 7.4 工具折叠块

`tool_use`：渲染 `[工具名](输入摘要)` 可折叠行 + `tool_result` 时补状态徽标（✓/✗）与 snippet。工具名/输入来自 `payload`，用 `textContent`/`escapeHtml`，杜绝注入。

### 7.5 报告面板

- `report` 事件注入 `MarkdownRenderer` 产物（`marked.parse`+`DOMPurify`），复用现有 `#report` 渲染 + 地址条/复制/下载（design 62 已实现 client-Blob 下载）。
- `report.section` 启用时：报告面板随维度段增量 append + 节流重渲（同打字机策略）。

### 7.6 多轮 / 新会话 / 停止

- **多轮**：每发送一轮复用 `session_id`；新 user 气泡追加在历史下方。若后端回灌上轮摘要，前端无需特殊处理。
- **停止**：`send-btn` 暂停、显示 `stop-btn` → `fetch('/api/cancel/'+sid,{method:'POST'})`（existing）+ 关流。
- **新会话**：`convo=[]; session_id='sess_'+Date.now()`；清空消息区。

---

## 8. 数据流时序（一次对话）

```
用户(发送 task) → 前端 user 气泡 + EventSource(sid)
  POST/GET /api/analyze?sess_id&task          (web_app._event_generator)
  → [message.start msg=A source=lead]
  → [text_delta msg=A "针对市面上常见的 coding agent…"]   # Lead 规划，打字机
  → [thinking_delta msg=A …]                               # 若模型暴露推理链,折叠
  → [tool_use msg=A delegate make_plan]  → [tool_result ✓]
  → [discovery.candidate claude-code] [discovery.candidate copilot]  # 既有
  → [message.start msg=B source=sub.feature] [text_delta msg=B …]    # 子 Agent 思考
  → [tool_use msg=B web_extract github.com/…] → [tool_result]
  → [report.section dimension=feature markdown=…]   # 报告逐段流入(可选)
  → [message.stop msg=B]
  → (其它维度 …) → [report markdown_report report_url report_path]
  → [message.stop msg=A]
  → SSE EOF
前端：user 气泡 → lead 气泡打字机 → 子任务气泡 → 报告面板落定 +「报告已生成·地址…」
```

---

## 9. 兼容与降级

| 场景 | 行为 |
|---|---|
| 无 LLM Key / LLM 不可用 | 走既有 `error` SSE（design 50），前端助手气泡标错，不崩溃 |
| 端点不支持流式 | `stream()` 退化为 '''一次性 `yield StreamDelta(kind="text", text=<完整文本>)`'''（`_stream_once` 探测 `stream=True` 抛 400 → 降级一次性），体验无损仅无明显打字机 |
| 模型不暴露 reasoning_content | 无 `thinking_delta`，仅 `text_delta` + 工具活动 |
| 注入 mock（call_func） | 生成器透传；非生成器包成单一 delta（兼容既有测试） |
| CLI / MCP / 既有测试 | 不改：仅新增 `stream()`，非流式入口原样 |

---

## 10. 验证方式

1. **单测（`client`）**：`llm/client_test` — `stream()` 用 fake `call_func`/fake SDK resp（choices.delta 序列）断言增量顺序、`kind` 分类、首块超时重启、fallback 模型切换、不可重试错误上抛、全灭 `LLMUnavailableError`。
2. **后端中转（`agent`）**：ReactAgent/Lead 的流式中转——断言 `event_sink` 收到合法 `message.start/text_delta/message.stop` 顺序，且 `message_id` 一致。
3. **协议（`web`）**：`test_web_sse_events` 扩展——mock 一次分析，校验 SSE 输出含 `message.start/text_delta/tool_use/report` 且 `message_id` 贯穿、`report` 带 `report_url/report_path`。
4. **E2E（手动）**：web 发「分析 Cursor」→ 浏览器可见 Lead 叙述打字机 + 工具折叠 + 报告面板依次出现；并发一轮对比任务；点停止立即收口；新会话再开正常。
5. **回归**：既有 `test_*.py` 全绿（非流式路径零改动）。

---

## 11. 里程碑拆解

| 里程碑 | 内容 | 依赖 |
|---|---|---|
| M1 | 事件协议扩展（`message.* / text_delta / thinking_delta / tool_use / tool_result`）+ `LLMClient.stream()` + 单测 | 无 |
| M2 | Lead/子 Agent ReAct 文本接 `text_delta` 中转 + `source` 分层（顺序串流，v1） | M1 |
| M3 | 后端对话通道：`session_id` 多轮回灌、心跳、`message.stop` 摘要 | M2 |
| M4 | 前端对话页重构（布局/打字机/工具折叠/报告面板/停止/新会话） | M3 |
| M5 | `report.section` 逐维流式 + 端到端体验打磨（节流/滚底/光标） | M4 |

优先级：M1→M4 为 P0（对话 + 流式核心）；M5 为 P1（报告段流式增强，可选）。

---

## 12. 风险与取舍

- **并行子 Agent 思考的展示**：并行实现简单（顺序串流），为拉开与「一次性弹出」的差距足够；并行视口留作增强，协议已预留 `message_id`。
- **原始 token 含 JSON/中间态**：`text_delta` 只用于「思考/叙述」呈现，报告正文走 `report`（渲染后），避免把半成品 JSON 直接怼给用户。
- **高频 `text_delta`**：`marked+DOMPurify` 全量重渲昂贵 → 必须 80ms 节流；长报告可退化为 `report.section` 或仅正文 `text`，表/JSON 块 `text_delta` 外。
- **回调替更**：fallback 换模型会重头产出，契约用「新 message.start + 旧 text.stop(final=false)」表达，前端不强制回滚，避免实现负担。