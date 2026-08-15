# 设计文档 40 — MCP ↔ ReAct 工具打通（统一工具注册表）

> 触发：2026-08-15 第二轮评审——`analyze_react`（`facade/api.py:469-478`）只注册 `web_extract` 一个工具，
> 而 MCP Server（`mcp_server/server.py:42-148`）已暴露 8 个工具（web_extract/web_search/analyze_pricing/github_stars/
> github_releases/github_commits/run_benchmark/analyze_competitor）。**两条工具路径互不相干**：agent 主循环用不上
> MCP 工具集，MCP 是独立服务器；工具定义分处两处，重复维护风险。
> 依赖：设计文档 38（`ToolSpec`/schema/校验/超时）、`mcp_server/tools/*`。

## 1. 问题现状

- `mcp_server/server.py` 的 8 个 `@mcp.tool()` 是**薄封装**，实现全在 `mcp_server/tools/*`（web_tools.py / github_tools.py / pricing_tools.py / benchmark_tools.py / review_tools.py）。
- `ReactAgent` 可调用的 `ToolDispatcher` 只有 `web_extract`（`facade/api.py:474-476`）——agent 的工具能力远弱于对外暴露的工具集。
- 工具描述字符串在 server.py 与各 tools 模块内**重复**（description 写两遍），schema 无一处声明。
- 影响：① agent 不能自主调用 github/pricing/benchmark 等丰富工具（如"查 Cursor 最近 release"只能靠单一 web_extract）；② 工具路径双份，改一处漏一处；③ 与设计文档 38 的 schema 契约机制脱节。

## 2. 目标设计

1. **统一工具注册表**：`mcp_server/tools` 提供 `TOOLS: dict[str, Callable]` + `TOOL_SPECS: dict[str, ToolSpec]`（含 description/params_schema/timeout，设计文档 38），作为**唯一工具定义源**。
2. **ReAct 接入多工具**：新 `build_react_dispatcher()` 把 `TOOLS`+`TOOL_SPECS` 注册进 `ToolDispatcher`；`analyze_react` 改用它——agent 可自主调用 web_search/github/pricing 等工具。
3. **MCP Server 同源**：`create_server()` 用 `TOOL_SPECS` 元数据生成 `@mcp.tool`（消除重复描述）。
4. `web_extract` 语义：ReAct 侧复用 `_react_web_extract`（真实采集链路 + 设计文档 41 URL 防护），与 MCP 侧实现等价。

## 3. 模块/接口设计

### 3.1 `mcp_server/tools/__init__.py` 扩展（唯一工具源）

```python
from competitor_agent.agent.tool_dispatcher import ToolSpec

TOOLS: dict[str, Callable[..., str]] = {
    "web_extract": web_extract, "web_search": web_search,
    "analyze_pricing": analyze_pricing,
    "github_stars": github_stars, "github_releases": github_releases, "github_commits": github_commits,
    "run_benchmark": run_benchmark, "analyze_competitor": analyze_competitor,
}

TOOL_SPECS: dict[str, ToolSpec] = {  # description/params_schema（设计文档 38 契约）
    "web_extract": ToolSpec("web_extract", web_extract,
                            description="采集指定 URL 的网页文本",
                            params_schema={"type": "object",
                                           "required": ["url"],
                                           "properties": {"url": {"type": "string"},
                                                          "selector": {"type": "string"}}},
                            timeout=...),  # 读 config.collector
    ...
}
```

- 各 `*_tools.py` 的 description 收敛到 `TOOL_SPECS`；server.py 不再手写描述。

### 3.2 新 `agent/tool_registry.py`（或并入 facade）

```python
def build_react_dispatcher(extractor=None, llm=None) -> ToolDispatcher:
    """把 MCP 工具集（含 schema）注册进 ToolDispatcher，供 ReAct agent 调用。"""
    d = ToolDispatcher()
    for name, spec in TOOL_SPECS.items():
        d.register(name, TOOLS[name], spec=spec)
    # web_extract 可覆盖为复用真实采集链路的实现（含 URL 防护，设计文档 41）
    return d
```

### 3.3 `facade/api.py::analyze_react`

```python
dispatcher = build_react_dispatcher(extractor=self._extractor)
agent = ReactAgent(llm=self._llm or LLMClient(), dispatcher=dispatcher)
```

### 3.4 `mcp_server/server.py` 同源

- `create_server()` 遍历 `TOOL_SPECS` 生成 `@mcp.tool()`（description 取 spec.description），web_extract/web_search 内部先经 `guard_http_url`（设计文档 41）。

## 4. 接入方式

```
build_react_dispatcher()（唯一工具源 TOOLS + TOOL_SPECS）
  ├─ ReactAgent（analyze_react）→ 多工具自主调用
  └─ MCP Server（create_server）→ 同源生成工具
工具描述/schema 只维护 mcp_server/tools 一份；URL 防护（41）在两入口统一生效
```

- 主流程（GapExecutor/team 采集）不走 ToolDispatcher，不受影响。
- 兼容：`analyze_react` 既有调用方（CLI/Web）签名不变；默认 `use_llm` 无 Key 时仍走降级。

## 5. 验证方式

- **单测（注册表一致）**：`build_react_dispatcher().tool_count == len(TOOLS)`；每个工具 `get_tool_descriptions()` 含参数类型与描述（schema 生效）。
- **单测（MCP 同源）**：`create_server()` 生成工具名集合 == `TOOLS` 键集合；描述与 `TOOL_SPECS` 一致（无重复文案）。
- **集成（多工具 ReAct 链路）**：mock LLM 输出 Action 序列 `web_search → web_extract → Final Answer`，ReAct 循环端到端成功（含工具结果回灌）。
- **集成（恢复）**：mock LLM 先调不存在工具收到"工具不可用"回灌后改调合法工具 → 自恢复。
- **回归**：既有 `test_react.py`、MCP server 相关测试全绿。

## 6. 实现优先级与工作量

- 优先级：**高**（消除工具双路径 + 让 agent 具备真实多工具能力）。
- 工作量：约 0.5-1 天。
  - `TOOLS`/`TOOL_SPECS` 收敛 + server.py 同源：0.3 天；
  - `build_react_dispatcher` + `analyze_react` 接线：0.2 天；
  - 测试：0.2-0.4 天。
- 前置：设计文档 38（`ToolSpec`/schema 契约）。与 41（URL 防护）同批落地，web_extract 两入口统一防护。
