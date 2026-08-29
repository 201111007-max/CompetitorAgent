# 设计文档 65 — 报告 JSON 提取健壮化 + 多轮会话历史回灌（长期会话处理）

> 第十五轮新增项。触发：真实使用（doc 64 §8.3 之后）暴露两个体验问题——
> （1）**报告 JSON 原样进正文**：Lead 的 Final Answer 带散文前缀（"数据已齐备。以下是最终竞品分析报告。\n\n{...json...}"）时，
> `_parse_report` 因 `startswith("{")` 严格校验失败 → 兜底把**整段 JSON** 塞进单个 `react` 维度 → markdown 报告正文出现一坨 JSON；
> （2）**多轮会话不记得前文**：用户问"为什么维度结论 [PARTIAL] react 是 json 格式的"后再问"你能根据代码分析我刚才提到的问题吗"，
> 新一轮 `/api/analyze` 只拿到孤立的一句 user 消息，模型说"对话是从这条消息开始的"——Web 层会话无状态、`session_id` 只用于取消/归档。
>
> 基线与边界：报告组装对应 **doc 49/64**（`react_report.assemble` / `comparison_report.assemble_comparison`）、
> 意图门控对话分支对应 **doc 64 §5**（`_run_chat` + `ChatResult`）、流式/前端对应 **doc 63/64**、上下文压缩对应 **doc 46/56**
> （`_compress_history` + `kb_recall`）、会话/记忆基础设施对应 **doc 35/50**（四层记忆 / JsonStore / session log）。
> 本文档在这四者之上做两件事：**① 报告 JSON 提取从"严格前导校验"改为"括号配平提取 + 兜底净化"**；
> **② Web 层引入按 `session_id` 的多轮会话历史——持久化、注入、长期压缩**。不改动 doc 64 已落地的双通道/门控语义。

---

## 1. 两个症状与根因（附代码证据）

### 1.1 报告 JSON 原样进正文（doc 64 §8.3 之后的新发现）

doc 64 已保证 JSON **不进打字机正文**（Payload 通道），但**报告面板正文**（`report` 事件的 `markdown_report`）仍可能含 JSON：

1. Lead Final Answer 被 `final_as_payload=True` 归 Payload 通道，`reply.content` 即为该 JSON（doc 64 §3.2）；
2. `facade/api.py:1576` `run()` → `react_report.assemble(lead_answer=result.answer, ...)`；
3. `react_report.py:94-106` `_parse_report`：**`text.strip().startswith("{")` 才 `json.loads`**，且须含 `dimensions` 列表；
4. 本次答案是"散文前缀 + JSON"（模型在纯 JSON 前加了"数据已齐备。以下是最终竞品分析报告。"）→ `startswith` 失败 → 返回 `None`；
5. `react_report.py:157-187` `_fallback_single_dimension`：把**整段原始答案**（含完整 JSON）当 `summary` 塞进单个 `react` 维度、`PARTIAL`；
6. `markdown_renderer.py:65-69` `_render_dimension` 对 `summary` **原样输出** → 报告正文 = `### [PARTIAL] react` + 一整段 JSON。

**为什么看起来像"前端没渲染"**：前端 `renderReport`（app.js:206-208）确实 `marked.parse` 了，但渲染的是"内容本身含 JSON dump"的 markdown——JSON 不是被当成代码块渲染，而是作为普通段落原文输出。根因在后端解析与兜底，不在前端。

旁证：本次任务其实是多竞品 DISCOVERY，但 `make_plan` 只声明了 `competitor`、无 `resolution`/`competitors`
→ `_plan_resolution`（api.py:429-440）判成 `registry`，走了单竞品 `react_report.assemble` 而非 `assemble_comparison`
矩阵路径（comparison 组装器 `_extract_conclusion`，comparison_report.py:82-106 已有 `{` 开头与 `【市场格局核心结论】` 标记双处理，但同样不做"散文前缀中提取 JSON"）。

### 1.2 多轮会话不记得前文（Web 层会话无状态）

1. `web_app.py:452-474` `/api/analyze`：每次请求新建 `CompetitorAnalysisAPI`，`_sessions[sid] = {"task": task, ...}` 每次覆盖；
2. `web_app.py:99-157` `_event_generator`：`api_with_sink.run(task, session_id=sid)` 只传当前 `task`；
3. `react_agent.py:174-177` `_run_native`：`messages = [system, (extra_system_messages), user(task)]`，**每轮重建、不读历史**；
4. `session_id` 仅用于：取消协作（`set_cancel`）、会话归档（`archive_session`）、日志落盘——**不用于消息上下文**；
5. 前端 `app.js:346` 已复用 `sessionId`（`newSession()` 才重置），每次请求都带——但后端不消费历史。

对照参考项目（claude-code-best_claude-code）的会话模型：长驻进程内 `state.messages` 数组**跨轮累积**
（`src/query.ts:459-465` 每轮解构、`1884 messagesForQuery.concat(...)` 增量追加），同会话所有轮次都带完整消息调 LLM；
`session_id` 关联的 transcript 落盘，`--resume`/`/resume` 从磁盘恢复（`src/utils/sessionStorage.ts:3482 loadTranscriptFile`、`sessionRestore.ts`）。
我们的 Web 是**无状态 HTTP**，既无进程内累积，也无按会话的持久化消息。

---

## 2. 目标设计 ①：报告 JSON 提取健壮化（`facade/react_report.py`）

### 2.1 新增 `_extract_json_block(text) -> dict | None`：括号配平提取

目标：从"散文前缀 + JSON"或"JSON + 散文后缀"中**可靠取出首个平衡 JSON 对象**，而非要求整体以 `{` 开头。

算法（纯 Python，无新依赖，确定性）：
1. **快路径**：`text.strip().startswith("{")` → 直接 `json.loads`（现状行为，覆盖绝大多数场景）；
2. **慢路径（括号配平）**：在文本中定位首个 `{` 下标 `i`；从 `i` 起按字符扫描，维护深度 `depth`：
   - `{` → `depth += 1`；`}` → `depth -= 1`；
   - **字符串字面量感知**：命中 `"` 时进入字符串态，跳过 `\"` 转义，直到闭合 `"` 才恢复结构态——防止 JSON 字符串内部的 `{`/`}` 干扰配平；
   - `depth == 0` 时截取 `text[i:j+1]` 为候选 JSON 块，`json.loads`；成功且为 dict → 返回；
   - 首个候选失败（非 JSON）→ 尝试 `re.search(r'\{.*\}', text, re.DOTALL)` 懒提取兜底，再失败返回 `None`。
3. 配平扫描失败（未闭合）→ 返回 `None`，交兜底净化（§2.2）。

### 2.2 `_parse_report` 改用提取器 + 兜底净化

- `_parse_report`（react_report.py:94-106）改调 `_extract_json_block`，语义不变：取出 dict 且含 `dimensions` 列表 → 正常多维度组装；
- 取出 dict 但**缺 `dimensions`** → 尝试取 `conclusion`/`summary`/`answer` 字段作为单 react 维度的正文（可溯源），不再整段倾销；
- **兜底净化**（`_fallback_single_dimension`，react_report.py:157-187）：即使最终无有效 JSON，赋给 `react` 维度 summary 前**先剔除文中的 JSON 块**（复用配平提取结果/失败位置），只保留纯散文。用户看到的将是"数据已齐备。以下是最终竞品分析报告。"而非一坨 JSON。

### 2.3 复用面

- `comparison_report._extract_conclusion`（comparison_report.py:82-106）同步改为复用 `_extract_json_block`（它已有 `{` 开头与标记双处理，补"散文前缀提取"）；
- 顺带修正 §1.1 旁证：`_plan_resolution`（api.py:429-440）在 `plan` 缺 `resolution` 时，若 plan 含多候选/`competitors` 或 Lead 实际做了枚举/委派 → 归 `discovery`/`compare`，避免多竞品任务误判 `registry` 走单报告路径。

### 2.4 不做的事

- 不改 `final_as_payload` 双通道语义（doc 64 §3.2）：提取只发生在报告组装侧，正文打字机依然由 Stream 通道独占；
- 不引入 LLM 二次解析（JSON 提取是确定性文本任务，LLM 会引入非确定性与额外成本）。

---

## 3. 目标设计 ②：多轮会话历史回灌（含长期会话）

### 3.1 目标形态

长期控制的作用域是**单个 `session_id`**：同会话多次对话累积进同一份历史并持续被压缩注入；
只有用户点"新会话"（换 `session_id`）才断开——新会话从空历史开始，旧会话历史不再注入。

```
前端（sessionId 稳定复用，app.js:346 已满足；"新会话"才换新 session_id）
        │ task + session_id（每次请求）
        ▼
/ api / analyze（web_app.py）
        │ 按 session_id 取历史 + 追加本轮 user task
        ▼
SessionHistory（新模块，JsonStore 持久化）
        │ history_messages: list[{role, content}]（截断/压缩后）
        ▼
CompetitorAnalysisAPI.run(task, session_id, history=[...])
        │
        ▼
ReactLoop → ReactAgent._run_native
        │ messages = [system] + extra_system_messages + history_messages + [user(task)]
        ▼
LLM 完整看到此前各轮 user/assistant 对话
        │ 收尾：把本轮结果（chat→answer / 分析→紧凑摘要）追加进历史
        ▼
SessionHistory（落盘，刷新后仍可续）
```

**不变量**：同 `session_id` 的每一轮请求，LLM 都收到"截至上一轮的完整（或压缩后）会话上下文"；
历史是**追加式**的（user 任务 + assistant 结果），绝不覆盖。

### 3.2 新增 `memory/session_history.py`（复用 `JsonStore`）

- 复用 `memory/json_store.py:22 JsonStore`（`get/put/save`，落盘 `get_data_dir()/memory`），命名空间 `chat_history`，key = `session_id`；
- 接口：
  - `append(session_id, role, content)`：追加一条 `{role, content, ts}`；写穿 `put` + `save`（幂等，重开页面不丢）；
  - `messages(session_id, limit=...)`：返回该会话历史（含类型归一：仅 `user`/`assistant`，`tool` 类不入会话历史）；
  - `truncate(session_id, max_turns)`：超过保留轮数时折叠最旧轮为摘要（见 §3.4）；
  - `drop(session_id)`：`newSession` 显式清空。
- 内容策略：**chat 轮**存 `answer` 原文；**分析轮**存紧凑摘要（如"完成报告 <竞品>：<维度> 终态 <state>"），**不**存整份 markdown/JSON（避免历史膨胀与污染）。

### 3.3 注入链路（改签名，向后兼容）

- `CompetitorAnalysisAPI.run(task, *, session_id=None, history=None)`（api.py:1531）；
- `run()` → `_run_chat`（api.py:1594）与 `_react_loop`（api.py:761）透传 `history_messages`；
- `ReactLoop.run_with_result` → `ReactAgent.run(..., history_messages=None)`（react_agent.py:78 新参数，None 行为不变）；
- `_run_native`（react_agent.py:174-177）：`messages = [system] + extra_system_messages + (history_messages or []) + [user]`；
  - **角色交替校验**：`history_messages` 最后一条必须是 `assistant`（上轮已收尾）；若最后一轮被中断（user 后无 assistant）则丢弃该悬空 user，防止 user/user 连续；
  - 历史与当前 `task` 之间不强制压缩——`max_history_steps` 只作用于**本轮内部**工具步（doc 46），会话历史单独按 §3.4 压缩。
- `web_app.py` `_event_generator`：开头 `history = _history.messages(sid)` + `append(sid, "user", task)`；
  收尾处（`ChatResult` / `CompetitorReport` / `ComparisonReport` / `CancelledResult` 各分支）`append(sid, "assistant", 摘要)`。

### 3.4 长期多轮会话的处理（不止一轮）

**控制的作用域 = 单个 `session_id` 内**：同一个会话里多次对话（无论 chat 轮还是分析轮）累积进同一份历史，
长期压缩只作用于这份历史；**只有用户点击"新会话"（`newSession`，app.js:372）才断开长期控制**——换新 `session_id`
即从空历史重新开始，上一会话的历史**不再注入**新会话（跨会话不串味）。

单会话历史可无限增长，需分层控制（对照 doc 56 压缩思想 + 参考项目 compact 语义）：

1. **窗口保留（verbatim 近端）**：最近 `session.max_verbatim_turns`（默认 10）轮**原文注入**——保证"分析我上一个问题"这类指代能准确还原；
2. **远端折叠（summary 远端）**：超过窗口的旧轮折叠为**确定性规则摘要**（一行一轮：`user: <前 80 字> → assistant: <前 80 字>`，无 LLM，可配 `kb_recall` 取回全文——复用 doc 56 的指针模式）；
3. **总量上限**：`session.max_history_chars`（默认约 16k）封顶，超限截断加标记；
4. **成本/次数护栏**：不强制——`LLMClient` 已有 `timeout/max_retries`，历史过长主要由 §3.4 ①②③ 约束；会话数上限 `session.max_sessions`（默认 200，LRU 淘汰，防无界磁盘）；
5. **显式重置（唯一断开长期控制的途径）**：前端"新会话"按钮（`newSession`，app.js:372）**换新 `session_id`**（生成 `sess_<新时间戳>`）并 `drop(旧 sid)`——旧会话历史留在磁盘可查（`/api/history`），但**不再参与任何后续轮次注入**；同一 `session_id` 内的所有对话始终受 §3.4 ①②③ 的长期控制，**不存在"第 N 轮之后豁免"的机制**。

### 3.5 边界与回退

- `history=None`（CLI/既有调用方）→ 行为逐字节不变（默认空历史）；
- 历史持久化失败（磁盘写异常）→ 仅告警，不阻塞分析（`_event_generator` 已整体 try/except）；
- 历史读取失败/损坏 → 视为空历史，按新会话处理；
- 意图门控（doc 64 §5）语义不变：`CHAT` 轮与分析轮都能带历史，门控只看当前 `task`；
- **长期控制的边界**：只作用于同 `session_id` 的后续轮次；新 `session_id`（用户点"新会话"）历史从空开始，
  旧会话历史仅保留在磁盘（`/api/history` 可查）与归档记忆，不注入新会话；
- 不改 SSE 契约：历史是**每轮请求内**注入的上下文，事件流/前端打字机照旧。

---

## 4. 与既有设计的关系与边界

| 设计文档 | 关系 |
|---|---|
| 49/64 报告组装 | §2 只改 `react_report._parse_report` 解析与 `_fallback_single_dimension` 净化，`assemble` 对外签名不变 |
| 64 §3/§5 双通道+意图门控 | §3 历史回灌在 `run()` 内做，不碰 `complete_with_tools` 分类与 `ChatResult` 门控 |
| 46/56 上下文压缩 | §3.4 会话级折叠复用 doc 56 的"规则摘要 + kb_recall 指针"思想，但作用于**会话历史**而非本轮工具步 |
| 63/50 SSE/事件桥 | §3.3 只在请求入口注入历史，SSE 事件流与 `session_id` 取消/归档语义不变 |
| 35 四层记忆 | `SessionHistory` 独立于竞品记忆（L1-L4）：前者是**会话对话上下文**，后者是**竞品知识沉淀**，互不替代 |

边界：本文档是**报告组装健壮性 + Web 会话层**设计，不改动 Lead/子 Agent 编排逻辑、记忆/知识库写入、前端打字机。

---

## 5. 验收标准

1. **JSON 提取**：`_parse_report` 对"散文前缀 + JSON"、"JSON"、纯散文、损坏 JSON 四类输入分别产出多维度报告 / 多维度报告 / 单 react 维度（无 JSON）/ 单 react 维度（无 JSON dump）。→ 单测 `test_react_report.py` 新增四类用例 + `_extract_json_block` 括号配平/字符串转义用例。
2. **兜底净化**：解析失败时 `react` 维度 summary **不含** `{...}` JSON 块（断言无 `"dimensions"` 子串）。
3. **多轮回灌**：模拟同 `session_id` 两轮（第一轮"为什么维度结论是 JSON"，第二轮"用代码分析我刚才的问题"），断言第二轮 LLM `messages` 含第一轮 user/assistant 对。→ 单测 `test_session_history.py`。
4. **长期会话**：>10 轮历史时，断言注入消息为「近端原文 + 远端折叠摘要」且总字符 ≤ 上限；`max_sessions` 淘汰生效；**同 `session_id` 第 15 轮仍收到第 1 轮的折叠摘要（长期控制持续生效），点"新会话"后新 `session_id` 第 1 轮收到空历史（断开长期控制）**。
5. **回归**：`history=None` 既有调用（CLI/非流式）逐字节不变；`test_stream.py`/`test_web_m2_streaming.py`/`test_chat_gate_64.py` 不回归；`ruff check .` + `mypy .` 涉及文件 0 error。

---

## 6. 实施顺序（分批）

1. **§2 JSON 提取健壮化（后端）**：`facade/react_report.py`（`_extract_json_block` + `_parse_report` + `_fallback_single_dimension` 净化）＋ `comparison_report._extract_conclusion` 复用 ＋ `_plan_resolution` 多候选推断。配单测。
2. **§3.2-3.3 会话历史核心（后端）**：`memory/session_history.py`（JsonStore）＋ `run/_run_chat/_react_loop/ReactAgent._run_native` 透传 `history_messages` ＋ `web_app._event_generator` 读写挂接。配单测。
3. **§3.4 长期会话压缩（后端）**：窗口保留 + 远端折叠 + 总量上限 + LRU 淘汰。配单测。
4. **端到端 + 文档状态表**：真实 LLM 手工验证两现象消除，回填本文档状态。

---

## 状态表

| 项 | 内容 | 涉及 | 状态 |
|---|---|---|---|
| §2.1 | `_extract_json_block` 括号配平 + 字符串感知提取 | `facade/react_report.py` | [ ] 未实现 |
| §2.2 | `_parse_report` 用提取器 + 兜底净化 | `facade/react_report.py` | [ ] 未实现 |
| §2.3 | `_extract_conclusion` 复用 + `_plan_resolution` 多候选推断 | `facade/comparison_report.py`、`facade/api.py` | [ ] 未实现 |
| §3.2 | `SessionHistory`（JsonStore 持久化） | `memory/session_history.py`（新） | [ ] 未实现 |
| §3.3 | `history_messages` 注入链路（run→_run_chat→_react_loop→ReactAgent） | `facade/api.py`、`agent/react_loop.py`、`agent/react_agent.py`、`web_app.py` | [ ] 未实现 |
| §3.4 | 长期会话压缩（窗口/折叠/上限/LRU） | `memory/session_history.py`、`config/loader.py` | [ ] 未实现 |
| §5 | 四类验收单测 | `tests/unit/facade/test_react_report.py`、`tests/unit/memory/test_session_history.py` | [ ] 未实现 |
