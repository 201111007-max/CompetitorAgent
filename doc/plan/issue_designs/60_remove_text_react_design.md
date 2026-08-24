# 设计文档 60 — 删除文本 ReAct 协议，只保留 function calling

> 触发：2026-08-24 复核协议面——文本 ReAct（`ResponseParser` 5 正则 + `run` 文本循环 react_agent.py:146-213 +
> `_dispatch`(:325) + `_compress_history`）与原生 function calling（`_run_native`:215）并存（doc 53 Q1 双协议，
> 默认 native），每个新能力两套实现、mock 双形态、测试矩阵 ×2；且 **LangGraph 引擎节点依赖文本协议**
> （langgraph_engine/nodes.py:54/183 `llm.complete` + `ResponseParser.parse`），删文本协议会连坐 langgraph 引擎。
> 用户拍板：**彻底删除文本 ReAct，只保留 function calling（原生协议）**；LangGraph 节点迁移 native；
> 不支持 tools 的端点按 doc 53 Q4 语义报错（`LLMUnavailableError` 引导换模型），不做文本降级。
> 前置：53（native 循环/`complete_with_tools`）、51（langgraph 引擎）、54（trace）、56（native 压缩）。

## 1. 问题现状

### 1.1 双协议消费方盘点（核实后）

| 消费方 | 位置 | 文本协议部分 |
|---|---|---|
| 文本解析器 | `agent/response_parser.py` | `ResponseParser` + `ReActStep`（整文件） |
| Agent 文本循环 | `agent/react_agent.py:146-213` | `run` 的 `llm.complete`+`parse`+`_dispatch`+`_compress_history` 分支 |
| 文本分发 | `react_agent.py:325` | `_dispatch`（Thought/Action 分发） |
| 文本压缩 | `react_agent.py` | `_compress_history`（assistant 文本+Observation 对折叠） |
| 协议参数 | `react_agent.py:52-70`、`react_loop.py`、`facade/api.py:141/148/596/609/682/720`、`subagent_registry.py`、`cli.py`、`benchmark.py` | `protocol` / `--protocol` |
| **LangGraph 引擎** | `langgraph_engine/nodes.py:17/40/47/54/167/174/183` | `llm.complete` + `ResponseParser.parse` 的节点 mini 循环 |
| mock 文本形状 | `benchmark.py BenchmarkMockLLM`、`conftest.py react_mock_llm`、`behavior_eval.py ScriptedLLM` | 按"是否收到 tools="出文本/ToolCallReply 双形态 |
| 对照实验 | `benchmark.py:1676/1720` | `--protocol both` 协议对比表 |
| 报错指引 | `llm/client.py:269` | "请改用 protocol='react' 或更换支持工具调用的模型" |

### 1.2 三个具体问题

1. **维护面翻倍**：每个新能力（压缩、trace、记忆注入）要在文本/native 两条路径各做一遍或留不对称缺口
   （doc 56 kb_recall/压缩明确只覆盖 ReactLoop 路径）；mock 双形态、测试矩阵 ×2。
2. **行为漂移风险**：两条路径对预算/取消/记忆的实现程度不同，`protocol="react"` 长期无人维护，是宣称能力
   （"function calling 优先"）与实际接线（还有一整套文本路径）的落差。
3. **LangGraph 依赖遗留协议**：langgraph 引擎节点跑 `llm.complete`+正则解析（nodes.py:54/183），是文本协议的
   唯一生产依赖——删文本协议必须先迁 langgraph 节点，否则双引擎对照实验直接失效。

### 1.3 现有可复用资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| native 循环 | `_run_native`（react_agent.py:215-310） | 成为唯一循环，`run` 收敛为薄壳 |
| native 压缩 | `_compress_history_native` | 保留（可改名 `_compress_history`），删文本折叠 |
| 工具 schema | `build_openai_tools`（tool_registry.py）+ `complete_with_tools`（client.py:215） | 单协议唯一入口，零改动 |
| 错误语义 | doc 53 Q4 `LLMUnavailableError` | 保留，仅更新报错文案 |

## 2. 目标设计

1. **单协议**：原生 function calling 为唯一实现。删除文本循环/`ResponseParser`/`_dispatch`/`_compress_history`/
   协议参数/文本 mock 形态/`--protocol both` 对照实验。
2. **LangGraph 节点迁移 native**：`llm.complete`+`parse` → `complete_with_tools`+tool_calls 循环；
   双引擎统一同协议，doc 51 双引擎对照的控变量更纯。
3. **错误语义保留**：端点不支持 tools → `LLMUnavailableError`（doc 53 Q4），报错文案去掉 `protocol='react'`
   指引，改为"更换支持工具调用的模型"。
4. **测试矩阵收敛**：mock 双形态 → native 单形态；4 组合（native/react × 双引擎）→ 2（native × 双引擎）。
5. **回归安全**：默认路径行为不变（native 本就是默认）；所有既有测试迁 native 后全绿。

## 3. 模块/接口设计

### 3.1 删除清单

| 文件 | 删除内容 |
|---|---|
| `agent/response_parser.py` | 整文件（`ResponseParser`/`ReActStep`） |
| `agent/react_agent.py` | `parser` 参数(:52/59)、`protocol` 参数与 setter(:53-70)、`_PROTOCOLS`；`run` 文本循环体(:146-213)；`_dispatch`(:325)；`_compress_history`；`build_system_prompt` 文本分支(:87-89) |
| `facade/api.py` | `protocol` 参数(:141)/校验(:148)/透传(:682/720)；langgraph 构建处 `protocol="react"`(:596/609) |
| `agent/react_loop.py`/`agent/subagent_registry.py` | `protocol` 参数透传 |
| `cli.py`/`evaluation/benchmark.py` | `--protocol`；`--protocol both` 对照表(:1676/1720) |
| `llm/client.py` | 报错文案(:269)去 `protocol='react'` 指引 |
| mock | `BenchmarkMockLLM`/`conftest react_mock_llm`/`behavior_eval ScriptedLLM` 的文本形状分支与文本状态机 |

### 3.2 LangGraph 节点迁移（`agent/langgraph_engine/nodes.py`，~40 行）

- `subagent_node`/`report_node`：`reply = llm.complete(messages); parsed = parser.parse(reply)`
  （:54-55/:183-184）→ 改 native 循环：
  ```python
  reply = llm.complete_with_tools(messages, tools=openai_tools)     # build_openai_tools(dispatcher)
  if reply.tool_calls:
      for call in reply.tool_calls:
          result = dispatch_call(call)                                # 复用 _dispatch_call 语义
          messages.append({"role": "tool", "tool_call_id": call.id,
                           "content": wrap_untrusted(截断(result))})
      continue
  return reply.content or ""                                          # 无 tool_calls 即最终回答
  ```
- **优先复用 native `ReactAgent`**：若节点可整体委托 `ReactAgent(llm, dispatcher).run(...)`（doc 51 本意
  "子 Agent 循环复用 ReactAgent.run"），则删除节点内 mini 循环、统一走 `_run_native`——单实现，
  压缩/transcript/trace 全复用。仅当节点需要 StateGraph 内 step 级事件时保留 mini 循环（复用
  `_dispatch_call` 逻辑，抽成协议无关 helper）。
- 移除 `ResponseParser` import 与 `parser` 参数（nodes.py:17/40/47/167/174）。

### 3.3 `run` 收敛

- `ReactAgent.run` 删文本分支，恒走 `_run_native`（或直接内联为 `run` 本体）；签名删 `parser`/`protocol`。
- `_compress_history_native` 改名 `_compress_history`（文档同步 doc 46/53/56 引用）。
- 保留：`build_openai_tools`/`complete_with_tools`/`ToolCallReply`/`wrap_untrusted`/`_dispatch_call`/`_step_record`/
  `_compress_history`(native)/`max_history_steps`/`max_parallel_tool_calls`(doc 59)。

### 3.4 mock 单形态

- `call_func` 约定：删"未收到 tools= → 文本"分支；`BenchmarkMockLLM`/conftest/behavior_eval 恒按 native
  形状（`ToolCallReply`）出脚本。文本特征定位 Observation 的断言（如 "Observation（工具结果…" 前缀、
  "请继续：给出 Action…"）迁到 native 形状（tool 角色消息 + `tool_call_id`）。

## 4. 接入方式

```
protocol 参数全面移除；ReactAgent/ReactLoop/langgraph 节点恒走 native
  ├─ ReactAgent.run → _run_native（唯一循环）
  ├─ LangGraph subagent/report node → complete_with_tools（或复用 native ReactAgent.run）
  ├─ 不支持 tools 端点 → LLMUnavailableError（Q4 报错，去 protocol 指引）
  └─ benchmark：mock 单形态，门禁默认 native（HARNESS_VERSION 0.8.0 → 0.9.0，重定门禁并留记录）
```

- **默认路径行为不变**：native 本就是默认，删除后无感知（无 `protocol` 参数可配）。
- **受影响测试**：文本形状断言批量迁 native（doc 53 §7.1 已预判的最大迁移面，本轮收尾）；`protocol="react"`
  相关用例删除。
- **回退**：改动面大，回退 = git revert；无运行时开关（单协议是硬决定）。
- **文档同步**：doc 53 §2.5「不删文本协议」、doc 51 langgraph"文本节点"表述、doc 46 压缩章节、README 索引更新。

## 5. 验证方式

- **残留零命中**：`grep -rn "ResponseParser\|protocol=.react.\|--protocol" competitor_agent/` 为空；
  `grep -rn "_dispatch\|_compress_history\b" ` 仅剩 native 版本符号。
- **单测**：`test_native_protocol.py`/`test_complete_with_tools.py` 全绿（唯一循环）；删 `test_react.py` 文本形状
  用例或迁 native；新增 LangGraph 节点 native 端到端（mock）。
- **集成**：mock 下 `analyze` 全链路、LangGraph 引擎（`--engine langgraph`）走通；benchmark 门禁（mock 单形态）过。
- **负面**：构造不支持 tools 的 mock 端点 → `LLMUnavailableError`，报错含可操作指引且非零退出。
- **回归**：全量 `pytest -q` + ruff/mypy；`--engine both`（双引擎对照，doc 51）仍可跑（同协议更公平）。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README 登记 | 0.2d ✅ 2026-08-24 |
| 1 | 删除 + LangGraph 迁移 | response_parser 删除、run 收敛、nodes.py native 化、api/loop/subagent 去 protocol | 1d |
| 2 | mock 单形态 + 测试迁移 | BenchmarkMockLLM/conftest/behavior_eval 单形态 + 文本断言迁移（最大阶段） | 1d |
| 3 | 收口 | llm/client.py 文案、benchmark 去对照、HARNESS_VERSION、文档同步 | 0.3d |

- 前置：53（native 本体）；与 59（并行 tool_calls）正交（59 只改 `_run_native`）；57/58 独立并行。
- 风险最高里程碑为 M2（测试迁移面大），doc 53 §7.1 已为此预留。

## 7. 风险与缓解

1. **测试迁移面大（最大）**：文本形状断言遍布 `test_react.py`/behavior_eval/conftest/`test_react_context_cap.py`
   等。缓解：mock 单形态先落地 → 全量跑 → 失败断言按 native 形状逐批修正；`test_native_protocol.py` 作回归网。
2. **LangGraph 节点 native 化行为变化**：文本→native 可能改变节点内步数与事件序列。缓解：复用 native
   `ReactAgent.run`（若可行）保持单一实现；`--engine both` 对照跑确认 `field_accuracy` 不退化。
3. **端点兼容性变硬要求**：本地 vLLM/Ollama 等不支持 tools 的端点从"可显式降级"变硬错误。已与用户确认接受
   （doc 47 LLM-only 方向自洽）；报错文案给可操作指引（换模型）。
4. **双引擎对照公平性**：迁移后两引擎同协议，对照目标更纯（doc 51 控变量哲学）——文档明示这一变化。
5. **文档历史引用**：doc 46/51/53 多处描述文本协议，收口阶段一并更新，避免文档与代码脱节。
