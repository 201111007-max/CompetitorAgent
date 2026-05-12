# DotaHelperAgent Trace 跟踪系统设计方案

## 一、项目现状分析

### 1.1 项目架构

```
DotaHelperAgent/
├── web/
│   ├── index.html          # 前端单页应用 (原生 JS + SSE)
│   └── app.py              # Flask 后端 API
├── core/
│   ├── agent_controller.py # ReAct Agent 控制器
│   └── ...
├── utils/
│   ├── log_config.py       # 日志配置
│   └── memory_log_handler.py # 内存日志处理器
└── ...
```

### 1.2 现有日志系统特点

| 特性 | 现状 |
|------|------|
| 日志格式 | 支持文本 + JSON 双格式 |
| 存储方式 | 按日期分文件夹，每天按 300MB 分片 |
| 组件区分 | 支持 `session_id` 和 `component` 字段 |
| 实时展示 | SSE 推送到前端日志面板 |
| 前端会话 | 使用 `sessionId = 'sess_' + Math.random()` 生成 |

### 1.3 当前存在的问题

1. **无统一 TraceID**: 前端 `sessionId` 与后端日志的 `session_id` 虽同名但无强制关联
2. **跨层链路断裂**: Agent 内部调用、工具执行、API 请求的日志无法串联
3. **前端日志孤立**: 前端 console 日志无法与后端日志关联
4. **无父子关系**: 子目标、工具调用的嵌套关系无法体现

---

## 二、Trace 系统设计目标

### 2.1 核心目标

实现从前端到后端的全链路日志追踪，通过统一的 TraceID 串联所有相关日志，支持：

- **全链路追踪**: 从前端请求到后端 Agent、工具调用的完整链路
- **快速定位**: 通过 TraceID 一键查询某次请求的所有相关日志
- **性能分析**: 通过 Span 耗时分析各阶段性能瓶颈
- **可视化展示**: 前端直观展示调用链路树

### 2.2 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│  前端 Trace                                                     │
│  ┌──────────┐    HTTP/X-Trace-ID    ┌──────────────────────┐   │
│  │ Session  │ ─────────────────────> │   Flask Backend      │   │
│  │ TraceID  │                        │  ┌────────────────┐  │   │
│  └──────────┘                        │  │ Request Context │  │   │
│                                      │  │  - trace_id     │  │   │
│  ┌──────────┐                        │  │  - span_id      │  │   │
│  │ Console  │                        │  │  - parent_id    │  │   │
│  │   Logs   │                        │  └────────────────┘  │   │
│  └──────────┘                        │           │          │   │
│                                      │           ▼          │   │
│                                      │  ┌────────────────┐  │   │
│                                      │  │ Agent Controller│  │   │
│                                      │  │  - ReAct Loop   │  │   │
│                                      │  │  - Tool Calls   │  │   │
│                                      │  └────────────────┘  │   │
│                                      │           │          │   │
│                                      │           ▼          │   │
│                                      │  ┌────────────────┐  │   │
│                                      │  │  Tool Registry  │  │   │
│                                      │  │  - API Calls    │  │   │
│                                      │  │  - Cache Ops    │  │   │
│                                      │  └────────────────┘  │   │
│                                      └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Unified Logs   │
                    │  (trace_id =    │
                    │   session_id)   │
                    └─────────────────┘
```

---

## 三、详细设计方案

### 3.1 Trace 上下文模型

```python
# utils/trace_context.py

@dataclass
class TraceContext:
    """Trace 上下文 - 贯穿请求全生命周期"""
    trace_id: str           # 全局唯一追踪ID (UUID)
    span_id: str           # 当前操作SpanID
    parent_span_id: Optional[str] = None  # 父SpanID
    session_id: str        # 业务会话ID (与前端保持一致)
    operation: str         # 操作名称 (如: chat, analyze_hero)
    start_time: float      # 开始时间戳
    
    def create_child_span(self, operation: str) -> "TraceContext":
        """创建子Span上下文"""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=generate_span_id(),
            parent_span_id=self.span_id,
            session_id=self.session_id,
            operation=operation,
            start_time=time.time()
        )
```

### 3.2 核心组件职责

| 组件 | 文件路径 | 职责 |
|------|----------|------|
| TraceContext | `utils/trace_context.py` | 定义 Trace 上下文数据结构，管理上下文变量 |
| TraceSpan | `utils/trace_context.py` | 上下文管理器，自动记录 Span 生命周期 |
| @traced 装饰器 | `utils/trace_context.py` | 为函数自动添加 Trace 支持 |
| TraceFormatter | `utils/log_config.py` | 日志格式化器，自动注入 Trace 信息 |
| Flask 中间件 | `web/app.py` | 请求级 Trace 初始化与清理 |

### 3.3 数据流图

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   前端请求   │────>│  Flask App  │────>│ TraceContext│
│  (trace_id) │     │  初始化     │     │   设置      │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
       ┌───────────────────────────────────────┼───────────┐
       │                                       │           │
       ▼                                       ▼           ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐ ┌─────────────┐
│ Agent       │     │ Tool        │     │ API Client  │ │ Cache       │
│ Controller  │     │ Registry    │     │             │ │ Manager     │
│ (Span:      │     │ (Span:      │     │ (Span:      │ │ (Span:      │
│  agent_solve)│     │  tool_exec) │     │  api_call)  │ │  cache_op)  │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘ └──────┬──────┘
       │                   │                   │               │
       └───────────────────┴───────────────────┴───────────────┘
                               │
                               ▼
                    ┌─────────────────┐
                    │   统一日志输出    │
                    │ (含 trace_id,    │
                    │  span_id, etc)   │
                    └─────────────────┘
```

---

## 四、实施计划

### 4.1 实施步骤

| 阶段 | 任务 | 文件 | 优先级 |
|------|------|------|--------|
| 1 | 创建 Trace 上下文模块 | `utils/trace_context.py` | P0 |
| 2 | 修改日志格式化器 | `utils/log_config.py` | P0 |
| 3 | 添加请求级 Trace 初始化 | `web/app.py` (before_request) | P0 |
| 4 | 前端传递 TraceID | `web/index.html` | P0 |
| 5 | Agent Controller 添加 Span | `core/agent_controller.py` | P1 |
| 6 | 工具调用添加 Span | `core/tool_registry.py` | P1 |
| 7 | 添加 Trace 查询 API | `web/app.py` | P1 |
| 8 | 前端 Trace 可视化 | `web/index.html` | P2 |

### 4.2 文件修改清单

#### 新增文件
- `utils/trace_context.py` - Trace 上下文管理

#### 修改文件
- `utils/log_config.py` - 增强日志格式化器
- `web/app.py` - 添加 Trace 中间件和 API
- `web/index.html` - 前端 Trace 支持
- `core/agent_controller.py` - Agent 方法添加 Trace

---

## 五、预期日志格式

### 5.1 JSON 日志示例

```json
{
    "timestamp": "2026-05-12T10:30:45.123456",
    "level": "INFO",
    "logger": "web_app",
    "message": "Tool execution completed",
    "trace": {
        "trace_id": "trace_a1b2c3d4e5f67890",
        "span_id": "span_tool_exec_01",
        "parent_span_id": "span_react_01",
        "operation": "execute_tool",
        "duration_ms": 245
    },
    "component": "agent",
    "extra": {
        "tool": "analyze_counter_picks",
        "result_count": 5
    }
}
```

### 5.2 Span 树结构示例

```
trace_a1b2c3d4e5f67890 (总耗时: 1.2s)
├── span_root (operation: agent_solve, duration: 1.2s)
│   ├── span_001 (operation: goal_decomposition, duration: 50ms)
│   ├── span_002 (operation: sub_goal_0, duration: 400ms)
│   │   └── span_003 (operation: execute_tool/analyze_counter_picks, duration: 380ms)
│   │       └── span_004 (operation: api_call/opendota, duration: 350ms)
│   ├── span_005 (operation: sub_goal_1, duration: 300ms)
│   └── span_006 (operation: synthesize_answer, duration: 150ms)
```

---

## 六、风险与注意事项

### 6.1 性能考虑
- Trace 上下文使用 `contextvars`，对性能影响极小
- Span 记录仅在需要时创建，不会过度消耗资源
- 日志输出仍为异步，不会阻塞主流程

### 6.2 兼容性
- 保持现有 `session_id` 机制不变，Trace 是增强而非替换
- 日志格式向后兼容，新增字段不会影响现有解析
- 前端可选择性使用 Trace 功能

### 6.3 调试建议
- 开发阶段开启 DEBUG 级别，查看完整 Span 树
- 生产环境建议仅记录关键 Span，避免日志过大
- 可通过 `trace_id` 快速过滤相关日志

---

## 七、实施状态

### 7.1 已完成任务 ✓

| 任务 | 文件 | 状态 |
|------|------|------|
| 创建 Trace 上下文模块 | `utils/trace_context.py` | ✅ 已完成 |
| 修改日志格式化器 | `utils/log_config.py` | ✅ 已完成 |
| 添加请求级 Trace 初始化 | `web/app.py` | ✅ 已完成 |
| 前端传递 TraceID | `web/index.html` | ✅ 已完成 |
| Agent Controller 添加 Span | `core/agent_controller.py` | ✅ 已完成 |
| 添加 Trace 查询 API | `web/app.py` | ✅ 已完成 |

### 7.2 实施详情

#### 1. Trace 上下文模块 (`utils/trace_context.py`)
- 实现了 `TraceContext` 数据类，包含 trace_id, span_id, parent_span_id, session_id, operation 等字段
- 实现了 `TraceSpan` 上下文管理器，支持嵌套 Span
- 提供了 `@traced` 装饰器用于自动追踪函数
- 使用 `contextvars` 实现线程安全的上下文存储

#### 2. 日志配置增强 (`utils/log_config.py`)
- 新增 `TraceJSONFormatter` 类，自动注入 Trace 信息到日志
- 修改 `get_logger()` 函数，支持从当前 Trace 上下文获取信息
- 日志格式包含：trace_id, span_id, parent_span_id, session_id, operation, duration_ms

#### 3. Flask 应用集成 (`web/app.py`)
- 添加 `before_request` 中间件，自动从 Header 或 Body 获取 trace_id
- 添加 `after_request` 中间件，自动清理 Trace 上下文
- 修改 `/api/chat/stream` 和 `/api/chat` 端点，支持 Trace 信息传递
- 新增 Trace 查询 API：
  - `GET /api/trace/<trace_id>` - 获取指定 Trace 的所有日志
  - `GET /api/trace/<trace_id>/spans` - 获取 Trace 的 Span 树结构

#### 4. 前端 Trace 支持 (`web/index.html`)
- 新增 `currentTraceId` 变量存储当前请求的 Trace ID
- 新增 `generateTraceId()` 函数生成 UUID 格式的 Trace ID
- 修改 `sendMessageStream()` 和 `sendMessage()` 函数：
  - 在请求 Header 中添加 `X-Trace-ID` 和 `X-Session-ID`
  - 在请求 Body 中添加 `trace_id` 字段
  - 在控制台输出 Trace ID 便于调试

#### 5. Agent Controller 增强 (`core/agent_controller.py`)
- 修改 `solve()` 方法，使用 `TraceSpan` 包装整个 Agent 执行流程
- 为目标分解、子目标执行、结果合并等关键步骤添加 Span
- 修改 `_execute_single_goal()` 方法，为 ReAct 循环的每个步骤添加 Span
- 支持嵌套 Span，形成完整的调用链路树

### 7.3 测试验证

Trace 上下文管理模块已通过独立测试：
```
=== 测试 Trace 上下文管理 ===
当前 Trace ID: test_trace_001
当前 Span ID: root

=== 测试 TraceSpan 上下文管理器 ===
父 Span: e41fa893
子 Span: 2795270e
子 Span 父 ID: e41fa893

=== 测试通过! ===
```

### 7.4 使用方法

#### 后端使用示例
```python
from utils.trace_context import TraceSpan, get_current_trace

# 方式1: 使用上下文管理器
with TraceSpan("my_operation"):
    do_something()

# 方式2: 使用装饰器
from utils.trace_context import traced

@traced("my_function")
def my_function():
    do_something()

# 获取当前 Trace 信息
current = get_current_trace()
if current:
    print(f"Trace ID: {current.trace_id}")
    print(f"Span ID: {current.span_id}")
```

#### 前端使用示例
```javascript
// Trace ID 会自动生成并传递到后端
// 在浏览器控制台查看：
// [Trace] Request started: trace_xxx
// [Trace] Request completed: trace_xxx
// [Trace] View logs: /api/trace/trace_xxx

// 手动查询 Trace 日志
fetch('/api/trace/trace_xxx')
  .then(r => r.json())
  .then(data => console.log(data));
```

#### 日志查询示例
```bash
# 通过 API 查询指定 Trace 的日志
curl http://localhost:5000/api/trace/trace_xxx

# 查询 Trace 的 Span 树结构
curl http://localhost:5000/api/trace/trace_xxx/spans
```

### 7.5 日志输出示例

```json
{
    "timestamp": "2026-05-12T10:30:45.123456",
    "level": "INFO",
    "logger": "agent_controller",
    "message": "开始处理查询",
    "module": "agent_controller",
    "function": "solve",
    "line": 210,
    "component": "agent",
    "trace": {
        "trace_id": "trace_a1b2c3d4e5f67890",
        "span_id": "agent_solve",
        "parent_span_id": null,
        "session_id": "sess_abc123",
        "operation": "agent_solve",
        "duration_ms": 1250
    }
}
```

## 八、后续扩展

1. **分布式追踪**: 如需接入 OpenTelemetry/Jaeger，Trace 结构已预留扩展点
2. **性能监控**: 基于 Span 耗时数据，可生成性能报表
3. **错误追踪**: 异常自动关联到具体 Span，快速定位问题根因
4. **前端性能**: 前端也可创建 Span，追踪页面渲染性能
5. **日志可视化**: 前端添加 Trace 链路可视化界面
