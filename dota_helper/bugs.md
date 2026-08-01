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

### 4. 错误分类与自动恢复缺失

**位置**: `agent/react_loop.py:235-246`

**问题**: 异常处理为 `catch Exception → yield error → break`，无分级恢复策略。任何异常（包括可恢复的瞬时故障）都直接终止推理循环。

```python
# react_loop.py:235-246 — 当前错误处理
except Exception as e:
    logger.error("推理循环异常 (iteration=%d): %s", context.iteration, str(e))
    yield {"type": "error", ...}
    break  # 直接终止，无重试/降级/恢复
```

**影响**: 网络抖动、LLM 临时限流等可恢复错误也会导致整个推理失败。

---

### 5. Agent 层熔断器缺失

**位置**: `agent/tool_dispatcher.py:124-132`

**问题**: MCP 客户端层有超时重连（3 次指数退避），但 Agent 层无熔断机制。连续失败的工具调用不会被暂时屏蔽，导致反复重试浪费资源。

**影响**: 某个工具持续故障时，Agent 会在每次推理循环中都尝试调用它，直到预算耗尽。

---

### 6. 工具调用重试缺失

**位置**: `agent/tool_dispatcher.py:124-132`

**问题**: `dispatch()` 无重试逻辑，工具调用失败直接抛出异常。

**影响**: 瞬时故障（如网络超时）导致整个推理步骤失败，无法自动重试。

---

### 7. ReAct 循环状态无持久化

**位置**: `agent/react_loop.py:27-44`（`ReActContext`）

**问题**: 复盘流程有 `ProgressStore` 快照机制，但 ReAct 循环的 `ReActContext`（推理历史、迭代计数、Token 消耗）无持久化。Agent 重启后推理上下文完全丢失。

**影响**: 无法从中断点恢复推理，长对话场景下进程重启意味着全部重来。

---

## 🟡 P2 — 扩展性问题

### 8. 插件系统缺失

**位置**: 全局

**问题**: 无 `register_plugin()` API、无生命周期钩子（`before_action` / `after_action` / `before_llm_call` / `after_llm_call`）、无中间件管道。

**影响**: 所有功能硬编码，无法热插拔。添加新能力必须修改核心代码。

---

### 9. 本地工具注册机制缺失

**位置**: `agent/tool_dispatcher.py`

**问题**: 工具发现完全依赖 MCP 的 `list_tools()`，无本地 `register_tool(name, handler, schema)` API。无法注册本地工具或组合多个工具为复合操作。

**影响**: 所有工具必须通过 MCP Server 暴露，无法轻量级注册本地函数作为工具。

---

### 10. Agent 间协作机制缺失

**位置**: `parallel/subagent.py:108-113`

**问题**: `SubAgent` 完全独立执行，无消息总线、无投票/共识机制。子代理之间不能交换中间结果。

```python
# subagent.py:108-113 — 子代理完全隔离
context = AnalysisContext(
    phase=self._name,
    budget=budget,
    completed_results=[],  # ← 硬编码为空，不共享结果
)
```

**影响**: 无法实现多 Agent 协同推理（如交叉验证、分工协作）。

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
