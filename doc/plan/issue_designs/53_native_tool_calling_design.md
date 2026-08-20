# 设计文档 53 — 原生 Function Calling 协议：双协议并存 + 默认 tool_calls

> 触发：2026-08-20 岗位差距分析（BOSS/猎聘 Agent 应用开发岗 JD 提炼）标出「Function Calling 协议：
> 文本 ReAct 解析（Thought/Action），非原生 tool-calling API」。经代码核实属实：`ReactAgent.run`
> → `LLMClient.complete` 只回纯文本 → `ResponseParser` 5 条正则抠 `Thought/Action/Args/Final Answer`
> → 结果以 user 角色 "Observation..." 文本回灌；`LLMClient` 从不传 `tools=`，模型即使返回
> tool_calls 也会被 `_extract_text_and_usage` 丢弃。
> 用户拍板四决策（2026-08-20）：**Q1 双协议并存 + 开关，默认 `protocol="native"`**（文本 ReAct
> 保留为显式 fallback 与对照基准）；**Q2 Lead 主循环 + 子 Agent（`ReactAgent.run`）一并覆盖**；
> **Q3 脚本化 mock 实现双形态**（按是否收到 `tools=` 出对应响应形状）；**Q4 模型不支持 tools
> 直接报错让用户感知**（抛 `LLMUnavailableError`，不自动降级文本协议）。
> 前置：38（TOOL_SPECS JSON Schema 契约）、40（build_react_dispatcher 唯一工具源）、
> 43/49（ReactLoop 共享上下文 / plan-first / transcript）、46（历史压缩）、36（benchmark harness）。

## 1. 问题现状

### 1.1 文本协议链路与原生协议差距

| 环节 | 现状（文本 ReAct） | 原生 tool-calling |
|---|---|---|
| 工具下发 | system prompt 文本描述（`get_tool_descriptions`） | `tools=[{type:"function",function:{name,description,parameters}}]` 请求参数 |
| 调用表达 | 模型输出 `Action: name\nArgs: {...}` 文本，正则解析 | 模型返回结构化 `tool_calls=[{id,name,arguments(JSON)}]` |
| 参数保障 | JSON 合法性靠 `_parse_json_args` + `args_error` 回灌自愈 | API 层保证 arguments 是合法 JSON |
| 结果回灌 | user 角色 "Observation（工具结果，不可信外部数据）: ..." | `role:"tool"` 消息 + `tool_call_id` 对应 |
| 终止信号 | `Final Answer:` 文本前缀 | 无 tool_calls 的 content 即最终回答 |

### 1.2 三个具体问题

1. **LLMClient 无 tools 通道**：`complete()` 只回 `str`（client.py:119），`tools`/`tool_choice`
   参数无处传入，响应中 tool_calls 被丢弃——原生协议在客户端层根本没有入口。
2. **文本解析是软肋也是补丁堆**：`args_error` 回灌、"请继续：给出 Action 或 Final Answer"
   注入、`mandatory_first_tool` 文本回灌强制——这些自愈逻辑的存在本身就说明协议靠约定
   不靠保证；且 prompt 里冗长的格式说明白耗 token。
3. **mock/压缩/transcript 全绑文本形状**：BenchmarkMockLLM/behavior_eval/conftest 的脚本化
   mock 都是 `call_func(messages)->str` 按文本内容出脚本；doc 46 `_compress_history` 按
   "assistant+Observation 成对"折叠——切协议这两层都要适配。

### 1.3 现有可复用资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 工具 schema 契约 | `mcp_server/tools` `TOOL_SPECS`（doc 38） | 直接映射为 OpenAI tools 格式，零改动 |
| 工具分发/校验/超时 | `ToolDispatcher.dispatch`（tool_dispatcher.py:66） | 协议无关，原生路径同一入口 |
| 共享会话上下文 | `ReactLoop`（取消/预算/记忆/RAG/事件/plan-first/transcript） | 协议无关层，仅透传 protocol |
| 注入防护 | `wrap_untrusted`（doc 06/41） | tool 角色消息内容同样包裹，语义不变 |
| 可靠性/fallback/计价 | `LLMClient._attempt_models`（重试/多模型/成本核算/埋点） | `complete_with_tools` 复用同一套 |
| 评测 harness | `evaluation/benchmark.py` 确定性 mock 哲学 | mock 双形态后双协议同 fixture 对照 |

## 2. 目标设计

### 2.1 双协议架构

```
ReactAgent(llm, dispatcher, ..., protocol="native" | "react")   # 默认 native（Q1）

native 循环（_run_native）：
    system prompt 去掉「请用 Thought/Action/Final Answer 格式思考」与工具文本描述
    （工具经 tools 参数下发，parameters 取自 TOOL_SPECS.params_schema）
    每轮：reply = llm.complete_with_tools(messages, tools, tool_choice=...)
        reply.tool_calls 非空 → 逐个 dispatch → 每个结果以
            {"role":"tool","tool_call_id":...,"content":wrap_untrusted(截断(结果))} 回灌
        reply.tool_calls 为空 → content 即 Final Answer，返回
    并行 tool_calls：一期按序逐个执行、按 tool_call_id 逐条回灌
        （符合 API 规范；不引入并发，与文本协议语义对齐）

react 循环：现有实现逐位不动（fallback + 对照基准）
```

- **plan-first（mandatory_first_tool）**：native 下首轮用
  `tool_choice={"type":"function","function":{"name":"make_plan"}}` 由 API 层强制——
  比文本协议的「回灌提示重试」更干净（零浪费步数）；命中后解除强制，后续轮
  `tool_choice="auto"`。端点不支持强制 tool_choice 时报错（见 2.2）。
- **历史压缩适配**（doc 46 §3.2）：折叠对象从「assistant 文本+Observation user 消息」
  变为「assistant(tool_calls)+tool 消息」对，折叠产物同为单行规则摘要
  （工具名/URL/结果前 N 字，确定性无 LLM），压缩阈值与语义不变。
- **协议无关层全部复用**：`step_guard`（取消/预算）、`on_step`（transcript 捕获）、
  事件 emit、记忆/RAG 注入、`first_tool_sink`（plan 解析存 `loop.plan`）零改动。

### 2.2 Q4 报错语义（不自动降级）

fallback 链中任一模型不支持 tools（400 特征报错 / 端点明确拒绝 tool_choice）→
抛 `LLMUnavailableError("模型 <model> 不支持 tool_calls（原生 function calling），"
"请改用 protocol='react' 或更换支持工具调用的模型")`——**不静默降级文本协议**
（用户拍板：静默降级会让用户以为在用原生协议实际不是）。报错信息必须给出可操作的下一步。

### 2.3 mock 双形态（Q3）

- `call_func` 约定扩展：收到 `tools=` kwarg → 返回 `ToolCallReply` 形态
  （结构化 `tool_calls`）；未收到 → 返回文本（现状）。同一脚本 fixture 双协议可跑。
- `BenchmarkMockLLM`/conftest `react_mock_llm`/behavior_eval `ScriptedLLM` 全部改双形态：
  按既有「按消息内容特征推导阶段」的脚本哲学，native 形态把 `Action/Args` 文本映射为
  等价 tool_calls（make_plan → 首轮 tool_call；工具脚本 → 对应 tool_calls；
  Final Answer → 纯 content）。CI 确定性不变、零真实 LLM（隔离纪律同 doc 52 §7.3）。

### 2.4 协议对照实验

- `benchmark` 子命令加 `--protocol {native,react,both}`（默认 native）；
  `--protocol both` 同 fixture 顺序跑两套，产出对比表落盘
  `<data_dir>/reports/protocol_compare_<date>.md`：

| 指标 | react | native |
|---|---|---|
| field_accuracy / hallucination_rate（现有门禁指标） | … | … |
| 解析失败回灌次数（native 恒 0，量化文本协议自愈成本） | … | … |
| LLM 调用次数 / total_cost_usd / 平均步数 | … | … |

- mock 下比「协议开销/步数/成本」；产出质量对比需 `--llm real` 手动跑
  （真实 LLM 不进 CI，成本护栏沿用 `--cost-limit`）。

### 2.5 明确不做

- **不删文本协议与 `ResponseParser`**：保留为显式 fallback（protocol="react"）与
  对照实验基准——Q1 决策。
- **不动 MCP 层**：TOOL_SPECS 直接映射 tools 参数，`mcp_server/server.py` 零改动
  （MCP 是工具供给侧协议，与模型侧调用协议正交）。
- **不动 dota_helper 的 ReActLoop**（独立子项目，不在本文档范围）。
- **不做流式 tool_calls**：SSE 事件仍走 `event_sink`，粒度不变。
- **不改 REPORT_SCHEMA/PLAN_SCHEMA 语义**：Final Answer 文本内容格式不变，
  `react_report.assemble`/`loop.plan` 消费侧零改动。
- **一期不做并行 tool_calls 并发执行**（按序逐个，见 2.1）。

## 3. 模块/接口设计

### 3.1 修改点（均为增量）

- `llm/client.py`（~80 行增量）：
  - `ToolCallReply` dataclass（`content: str`、`tool_calls: list[ToolCall]`、usage）；
    `ToolCall` = (id, name, arguments: dict——arguments JSON 解析失败按 doc 38
    语义转可读错误回灌，不静默 {})；
  - `complete_with_tools(messages, tools, tool_choice=None) -> ToolCallReply`：
    SDK 路径传 `tools`/`tool_choice`，复用 `_attempt_models` 重试/fallback/计价/埋点；
    捕获「不支持 tools」特征报错 → Q4 语义的 `LLMUnavailableError`；
    注入 `call_func` 路径透传 kwargs（mock 双形态入口）。
- `agent/tool_registry.py`（~20 行）：`build_openai_tools(dispatcher) -> list[dict]`——
  从 `ToolSpec`（description/params_schema）生成 OpenAI tools 格式；无 schema 的
  `extra_tools` 从函数签名派生最小 parameters。
- `agent/react_agent.py`（~80 行增量）：构造加 `protocol="native"`；`run` 按协议分派
  `_run_native` / 现有循环；native 分支共享 `_dispatch`/`_step_record`/`_truncate`/
  `_compress_history`（压缩适配 tool 角色消息对）；`build_system_prompt` native 模式
  去掉格式说明句。
- `agent/react_loop.py`（~10 行）：构造加 `protocol` 透传 ReactAgent。
- `agent/subagent_registry.py`：子 Agent 构建透传 protocol（Q2 一并覆盖）。
- `facade/api.py`（~5 行）：`CompetitorAnalysisAPI(..., protocol="native")` 透传
  `_react_loop` 构建。
- `cli.py`：`analyze`/`benchmark` 加 `--protocol {native,react}`（默认 native）。
- `evaluation/benchmark.py`：`--protocol both` 双跑 + 对比表落盘
  （HARNESS_VERSION 0.7.0 → 0.8.0，门禁对默认 native 重定）。
- `evaluation/behavior_eval.py`：`ScriptedLLM` 双形态适配。

### 3.2 测试

- `tests/unit/llm/test_complete_with_tools.py`：tool_calls 抽取/usage 计价/不支持 tools
  报错信息含「protocol='react'」指引/注入 call_func 双形态。
- `tests/unit/agent/test_native_protocol.py`：native 循环端到端（mock 双形态）、
  tool_choice plan-first 首轮强制、tool 角色消息回灌含 tool_call_id、并行 tool_calls
  按序执行逐条回灌、压缩适配不丢任务、arguments 非法 JSON 回灌自恢复。
- `tests/unit/facade/test_protocol_switch.py`：protocol 路由、默认 native、
  `protocol="react"` 行为与现状逐位一致（回归网）。
- 现有文本形状断言用例适配 mock 双形态（M3 最大迁移面）。
- benchmark smoke：mock `--protocol both` 产出对比表文件。

## 4. 接入方式

- 配置：`review_config.yaml` 无新字段；protocol 只走构造参数/CLI 参数
  （与 doc 51 engine 同哲学，避免 Web 端会话间串协议）。
- 依赖：零新依赖——openai SDK 已是硬依赖，tools 参数是其原生能力。
- 兼容：默认切 native 是**有意的行为变化**（用户拍板）；`protocol="react"` 完全回到
  现状。mock 双形态保证测试确定性；HARNESS_VERSION 0.8.0 重定门禁并留记录。
- 回退：删 protocol 参数与 `_run_native` 分支即完全回退；或运行时不改代码传
  `protocol="react"`。
- 老数据/会话归档：无影响（协议层不改存储格式）。

## 5. 验证方式

- `pytest tests/unit/llm/test_complete_with_tools.py tests/unit/agent/test_native_protocol.py tests/unit/facade/test_protocol_switch.py -q` 全绿；全量 `pytest -q` 不回归
  （含文本形状断言适配后）。
- 手动真实 LLM（DeepSeek 端点）：CLI 默认 native 跑通
  `python -m competitor_agent.cli analyze "分析 Cursor"`；`--protocol react` 回归对照。
- `python -m competitor_agent.evaluation.benchmark --protocol both`（mock）产出对比表；
  `--llm real --protocol both --cost-limit 1.0` 手动跑取质量对比。
- 负面路径：构造不支持 tools 的 mock 端点，确认报错信息含可操作指引且进程非零退出。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README/implementation_plan 登记 | 0.2d ✅ 2026-08-20 |
| 1 | LLMClient 通道 | complete_with_tools + ToolCallReply + tools 转换器 + 单测 | 0.5d |
| 2 | native 循环 | ReactAgent/ReactLoop 双协议 + tool_choice plan-first + 压缩适配 + 单测 | 1d |
| 3 | 接线 + mock 迁移 | api/cli/subagent 透传 + mock 双形态 + 现有测试适配（最大阶段） | 1d |
| 4 | 对照实验 | benchmark --protocol both + 对比表 + 实测记录 + HARNESS_VERSION 0.8.0 | 0.5d |

## 7. 风险与缓解

1. **默认切换的测试迁移面（最大）**：现有测试绑文本 mock 的消息形状（Observation 文本
   前缀断言、behavior_eval 按文本特征定位 Observation）——mock 双形态按 protocol 出
   对应形状，断言逐批适配；`protocol="react"` 用例即回归网，HARNESS_VERSION 0.8.0
   重定门禁（house 规则留记录）。
2. **tool_choice 端点支持差异**：部分 OpenAI 兼容端点不支持强制 tool_choice——plan-first
   失败按 Q4 报错并指引 `protocol='react'`，不静默退回文本回灌强制（一致性优先）。
3. **并行 tool_calls 语义**：一期按序逐个执行、全部结果下一轮前回灌齐全，模型侧无感；
   若后续要并发执行，改动局限在 native 循环 dispatch 段。
4. **对照公平性**：双协议同 LLM/同工具/同 dispatcher/同出口（react_report.assemble），
   唯一变量是协议层——与 doc 51 双引擎对照的控变量哲学一致，文档明示对比目标。
5. **兼容端点参差**：deepseek-chat 已验证支持 tools；其他端点（本地 vLLM/Ollama 等）
   兼容性以 Q4 报错路径兜底，文档记录已验证端点清单。
