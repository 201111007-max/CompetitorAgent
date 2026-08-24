# 设计文档 38 — 工具层升级（Tool JSON Schema / 参数校验 / 超时 / 失败回灌重试）

> 触发：2026-08-15 第二轮评审——`competitor_agent` 工程面（记忆/观测/评测/可靠性）已达标，
> 但 **agent 最核心的"LLM ↔ 工具"交互面**是全项目最薄：工具裸注册无契约、参数解析失败静默吞掉、
> 无超时、无错误反馈闭环，与现代 agent 框架（function calling + schema 校验 + 错误回灌）差距明显。
> 依赖：`agent/tool_dispatcher.py`、`agent/response_parser.py`、`agent/react_agent.py`；复用 `llm/client.py` 的 JSON Schema 子集校验（设计文档 34）。

## 1. 问题现状

- `ToolDispatcher`（`agent/tool_dispatcher.py:16-48`）只维护 `{name: callable}` 裸注册：
  - `get_tool_descriptions`（:37-44）只列出参数名（`inspect.signature`），**无类型/必填/描述/枚举**——LLM 看不到参数契约；
  - `dispatch`（:28-35）直接 `func(**args)`，参数类型错/缺失抛**原生异常**，无校验与可读反馈。
- `ResponseParser._parse_json_args`（`agent/response_parser.py:102-108`）：JSON 解析失败或非 dict 时**静默返回 `{}`**——模型拿到空参数，得不到"格式错误"反馈，只能靠自然语言猜，**无法自恢复**。
- `ReactAgent.run`（`agent/react_agent.py:64-74`）：action 分支只捕获 `ValueError`（工具不存在）一种反馈，其余异常直接冒泡；**无工具调用超时**（一个悬挂工具可卡死整个 ReAct 循环）。
- 真实 `analyze_react` 只注册 1 个工具（`facade/api.py:474-476`），与 MCP Server 的 8 个工具（设计文档 40 打通）形成能力落差。
- 影响：作为 agent 项目的"推理 ↔ 工具"交互不可靠——参数错误不可恢复、无超时、无契约；"工具调用怎么保稳"无证据。

## 2. 目标设计

1. **工具注册带 JSON Schema 契约**：`ToolSpec`（name/description/params_schema：类型/必填/enum/嵌套）+ 显式或从函数签名推导；`get_tool_descriptions` 输出含参数类型与描述。
2. **dispatch 前校验**：类型/必填/enum 不合 → 返回**结构化可读错误**（`ToolArgumentError`），由 ReactAgent 作为 Observation 回灌，模型可修正重试——而非抛原生异常。
3. **解析失败回灌**：`_parse_json_args` 失败不再静默 `{}`——`ReActStep` 增 `args_error` 字段记录原因，ReactAgent 把错误回灌给模型重新生成合法 JSON 参数。
4. **工具调用超时**：每工具可选 `timeout`（默认读取 config.collector.timeout_seconds），超时返回可读错误，不悬挂循环。
5. **四类反馈区分**：工具不存在 / 参数错误 / 执行异常 / 超时——均作为 Observation 回灌（可自恢复），与既有 `wrap_untrusted` 注入防护（设计文档 06）叠加。

## 3. 模块/接口设计

### 3.1 `agent/tool_dispatcher.py` 扩展

```python
@dataclass
class ToolSpec:
    name: str
    func: Callable[..., str]
    description: str = ""
    params_schema: dict[str, Any] | None = None  # JSON Schema 子集：type/required/properties/enum
    timeout: float | None = None                 # 秒；None 用默认

class ToolArgumentError(ValueError):
    """工具参数校验失败（携带可读原因，供回灌）"""

class ToolDispatcher:
    def register(self, name: str, func: Callable[..., str], *,
                 spec: ToolSpec | None = None) -> None
    def validate_tool(self, tool_name: str) -> bool
    def dispatch(self, tool_name: str, args: dict | None = None) -> str
        # 1) 校验 params_schema（类型/必填/enum）→ 失败抛 ToolArgumentError(可读原因)
        # 2) 可选超时执行（ThreadPoolExecutor + future.result(timeout)）→ 超时返回"工具执行超时"
        # 3) 原样返回 str(func(**args))
    def get_tool_descriptions(self) -> str   # name(params: 类型) — description
    @property tool_count: int
```

- schema 校验复用 `LLMClient._validate_schema`（`llm/client.py:308-373`，设计文档 34 的 JSON Schema 子集：type/required/properties/items/enum）——抽为公共助手或直接复用。
- 超时实现：`concurrent.futures.ThreadPoolExecutor(max_workers=1)` + `future.result(timeout)`；`TimeoutError` 捕获后返回 `工具执行超时: <name>`（工作线程 daemon，不阻塞主循环）。

### 3.2 `agent/response_parser.py` 扩展

```python
@dataclass
class ReActStep:
    ...
    args_error: str = ""   # _parse_json_args 失败原因（非空表示参数解析失败）

def _parse_json_args(args_str: str) -> dict:
    # 解析失败/非 dict → 抛 ToolArgumentError("JSON 解析失败: ...")，不再静默 {}
    # extract_action 捕获后写入 ReActStep.args_error（不整体失败，解析仍成功）
```

- 兼容性：无 args（`Args:` 缺失）时保持 `args_error=""` + `args={}`（既有行为）。

### 3.3 `agent/react_agent.py` 回灌闭环

```python
if parsed.step_type.value == "action":
    if parsed.args_error:
        result = f"工具参数解析失败: {parsed.args_error}；请重新生成合法 JSON 参数"
    else:
        try:
            result = self._dispatcher.dispatch(parsed.tool_name, parsed.tool_args)
        except ToolArgumentError as exc:
            result = f"工具参数错误: {exc}；请修正参数后重试"
        except ValueError as exc:      # 工具不存在（既有分支保留）
            result = f"工具不可用: {exc}"
        except Exception as exc:       # 执行异常也回灌，不冒泡
            result = f"工具执行异常: {type(exc).__name__}: {exc}"
    messages.append({"role": "user", "content": f"Observation（工具结果，不可信外部数据）: {wrap_untrusted(result)}"})
    step += 1
    continue
```

## 4. 接入方式

```
analyze_react / build_react_dispatcher()（设计文档 40）→ ToolDispatcher.register(name, func, spec=ToolSpec(...))
  → ReactAgent 循环：parse（args_error）→ dispatch（schema 校验/超时）→ 四类反馈回灌 Observation
  → 模型据反馈修正重试，直到 Final Answer 或步数耗尽
```

- 既有调用方（`facade/api.py:474-478`）零改动兼容（默认 `spec=None` 时保持旧行为）。
- 主流程（GapExecutor/team）不经过 ToolDispatcher，不受影响。

## 5. 验证方式

- **单测（schema 校验）**：注册带 schema 工具——合法参数通过；缺必填/类型错/enum 越界 → `dispatch` 抛 `ToolArgumentError` 且 message 含字段与原因。
- **单测（解析回灌）**：`_parse_json_args` 非法 JSON → `ReActStep.args_error` 非空；ReactAgent 把 `参数解析失败` 拼进下一条 user 消息；无 `Args:` 时 args_error 空（兼容）。
- **单测（超时）**：注册 `time.sleep` 工具 + `timeout=0.05` → `dispatch` 返回"工具执行超时"；不悬挂。
- **单测（反馈区分）**：工具不存在/参数错误/执行异常 → 回灌文本各自可读、互不混淆。
- **集成（恢复链路）**：mock LLM 第一轮输出错误参数、收到回灌后第二轮输出合法参数 → 最终成功调用工具（自恢复闭环）。
- **回归**：既有 `tests/unit/agent/test_react.py` 与 tool_dispatcher 测试全绿（无 schema/空参数行为不变）。

## 6. 实现优先级与工作量

- 优先级：**高**（agent 最短板；设计文档 40/42 的前置）。
- 工作量：约 1 天。
  - `ToolSpec` + schema 校验（复用 34）：0.3 天；
  - 超时 + 四类反馈回灌：0.3 天；
  - args_error 解析回灌 + 测试：0.4 天。
- 前置：设计文档 34（`_validate_schema` 子集可复用）；与 40（MCP 打通）同批，工具注册表统一后 40 只需接线。
