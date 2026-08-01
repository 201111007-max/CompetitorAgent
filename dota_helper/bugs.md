# DotaHelperAgent Agent 框架问题清单

> 从 Agent 框架完整性角度评估，按优先级排列。

---

## 🔴 P0 — 安全风险

### 1. 提示注入防御缺失

**位置**: `agent/react_loop.py:128`

**问题**: 用户输入直接作为 `user` 角色消息注入 LLM 上下文，无任何净化处理。攻击者可输入"忽略之前指令"、"你是 OpenAI 的模型"等注入模式劫持 Agent 行为。

```python
# react_loop.py:128 — 用户输入原样注入
context.messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": initial_message},  # ← 无净化
]
```

**影响**: 攻击者可完全控制 Agent 的系统提示词，绕过所有安全限制。

---

### 2. 工具护栏/参数校验缺失

**位置**: `agent/tool_dispatcher.py:110`

**问题**: `validate_tool()` 仅检查工具名是否在集合中，参数 `args: Dict[str, Any]` 原样透传给 MCP Server，无任何类型、范围、长度校验。

```python
# tool_dispatcher.py:110 — 唯一的"校验"
def validate_tool(self, tool_name: str) -> bool:
    return tool_name in self._tool_name_set
```

**影响**: 恶意参数（如 SQL 注入、路径遍历）可绕过校验直接调用 53 个 MCP 工具。

---

### 3. 凭据/密钥管理分散

**位置**: 散落于 `llm/client.py`、`mcp_server/server.py`、`mcp_server/tools/search_tools.py`、`observability/langfuse_adapter.py`

**问题**: API Key 通过 `os.getenv()` 分散在 4 个文件中读取，无统一凭据池、无加密存储、无密钥轮换机制。

| 位置 | 读取方式 |
|------|---------|
| `llm/client.py:35-41` | `os.getenv("OPENAI_API_KEY")` / `os.getenv("DEEPSEEK_API_KEY")` |
| `mcp_server/server.py:34` | `os.getenv("OPENDOTA_API_KEY")` |
| `mcp_server/tools/search_tools.py:49` | `os.getenv("SERPAPI_API_KEY")` |
| `observability/langfuse_adapter.py:34-35` | `os.getenv("LANGFUSE_PUBLIC_KEY")` / `os.getenv("LANGFUSE_SECRET_KEY")` |

**影响**: 密钥泄露无防护，无最小权限限制，Agent 拿到 LLM API Key 后可任意使用。

---

## 🟡 P1 — 可靠性问题

### 4. 错误分类与自动恢复缺失 ✅ 已修复

**位置**: `agent/error_classifier.py`（新增）

**修复**: 新增 `ErrorClassifier`，按 `ErrorCategory`（RECOVERABLE / DEGRADABLE / TERMINAL / UNKNOWN）分级处理异常：
- MCP 超时、LLM 限流（429/503/504）→ **RECOVERABLE**：自动重试
- MCP 连接断开、ValueError、RuntimeError → **DEGRADABLE**：跳过本轮继续
- LLM 认证错误（401/403/API Key）→ **TERMINAL**：终止推理
- 未知错误 → **UNKNOWN**：降级为 Thought 继续

**测试**: `tests/unit/test_error_classifier.py`（20 个用例）

---

### 5. Agent 层熔断器缺失 ✅ 已修复

**位置**: `agent/circuit_breaker.py`（新增）

**修复**: 新增 `CircuitBreaker` + `CircuitBreakerRegistry`：
- 连续失败 3 次 → OPEN（熔断 30s）
- 超时后 → HALF_OPEN（允许试探）
- HALF_OPEN 失败 → OPEN（超时加倍，最大 5min）
- 每个工具独立熔断，互不影响

**测试**: `tests/unit/test_circuit_breaker.py`（20 个用例）

---

### 6. 工具调用重试缺失 ✅ 已修复

**位置**: `agent/tool_dispatcher.py:150-175`

**修复**: `dispatch()` 集成熔断器检查 + 自动重试（超时/连接丢失重试 1 次，指数退避 1s→2s）。成功调用重置熔断器，重试耗尽记录失败。

**测试**: `tests/unit/test_tool_dispatcher_reliability.py`（11 个用例）

---

### 7. ReAct 循环状态无持久化 ✅ 已修复

**位置**: `agent/react_loop.py:27-44`（`ReActContext`）

**修复**: `ReActContext` 新增 `checkpoint_dir` + `save_checkpoint()` / `load_checkpoint()` / `clear_checkpoint()`。`execute()` 启动时优先从 checkpoint 恢复，每轮迭代后自动保存，推理完成后清理。

---

## 🟡 P2 — 扩展性问题

### 8. 插件系统缺失 ✅ 已修复

**位置**: `agent/plugin.py`

**修复**: 新增 `Plugin` 抽象基类（7 个生命周期钩子：`on_start`/`on_end`/`before_llm_call`/`after_llm_call`/`before_action`/`after_action`/`on_error`）+ `PluginRegistry`（注册/卸载/事件分发，管道模式，单个插件异常不中断链）。`react_loop.py` 的 `execute()` 中集成了 6 个钩子点。

---

### 9. 本地工具注册机制缺失 ✅ 已修复

**位置**: `agent/tool_registry.py`、`agent/tool_dispatcher.py`

**修复**: 新增 `ToolSchema`/`LocalTool`/`ToolRegistry`，支持 `register(name, handler, description, schema)`、同步/异步 handler 自动检测、`get_descriptions()` 格式化输出。`ToolDispatcher.dispatch()` 优先检查本地工具（本地 > MCP），`get_tool_descriptions()` 合并本地和 MCP 工具描述。

---

### 10. Agent 间协作机制缺失 ✅ 已修复

**位置**: `agent/message_bus.py`

**修复**: 新增 `MessageBus` 发布/订阅模式，`EventType` 枚举（`RESULT_READY`/`ERROR`/`STATUS_CHANGE`/`CUSTOM`），支持 `sender_filter`、消息历史查询、`max_history` 限制。子代理可通过共享 `MessageBus` 实例交换中间结果。

---

## 🟢 P3 — 效率问题

### 11. LLM 调用缓存缺失

**位置**: `llm/client.py:83-155`

**问题**: `chat()` 方法每次调用都直接请求 LLM API，无响应缓存。相同输入（messages + model + temperature）的重复调用浪费 Token。

**影响**: 重复查询浪费 Token 和成本，增加响应延迟。

---

### 12. RAG 未集成到 Agent 循环

**位置**: `mcp_server/helpers/rag_index.py` vs `agent/react_loop.py`

**问题**: MCP Server 内有完整的 TF-IDF/FAISS 向量检索实现，但 Agent 必须通过 MCP 工具显式调用才能使用，ReAct 循环无自动 RAG 检索能力。

**影响**: Agent 无法在推理过程中自动检索相关知识，依赖 LLM 自身知识或用户显式触发。

---

### 13. 输出验证/合规检查缺失

**位置**: `agent/response_parser.py:93-135`

**问题**: LLM 输出解析失败时直接返回 `THOUGHT` 类型，无格式校验。无事实性校验、无内容安全过滤、无隐私信息泄露检查。

**影响**: LLM 输出可能包含幻觉信息、有害内容或敏感数据泄露。

---

## 优先级建议

| 优先级 | 模块 | 建议行动 |
|--------|------|---------|
| **P0** | 提示注入防御 | 添加输入净化层，检测注入模式，隔离用户输入与系统提示词 |
| **P0** | 工具护栏 | 添加参数类型/范围校验，敏感操作二次确认，速率限制 |
| **P0** | 凭据管理 | 实现统一凭据池，加密存储，支持密钥轮换 |
| **P1** | 错误分类与恢复 | 实现错误分类器，分级恢复策略（重试→降级→跳过→终止） |
| **P1** | 熔断器 | 实现工具级熔断器，连续失败后自动暂停 |
| **P1** | 状态持久化 | 为 ReActContext 添加 checkpoint 机制 |
| **P2** | 插件系统 | 定义生命周期钩子，实现插件注册 API |
| **P2** | 工具注册 | 实现本地 register_tool API |
| **P2** | Agent 协作 | 实现 Agent 间消息总线 |
| **P3** | LLM 缓存 | 添加语义缓存，配置 TTL |
| **P3** | RAG 集成 | 将向量检索集成到 ReAct 循环 |
| **P3** | 输出验证 | 添加格式校验和内容安全过滤 |
