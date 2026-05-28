# Trace 定位与日志追踪体系设计文档

> **优先级**: P0
> **创建时间**: 2026-05-21
> **预计工作量**: 大
> **影响范围**: 高

---

## 一、功能概述

### 1.1 目标

建立完整的日志追踪方案，支持根据 trace ID 快速获取完整调用链日志，实现问题快速定位。

### 1.2 核心功能

- ✅ Trace ID 生成与传递
- ✅ 日志与 Trace 关联
- ✅ 调用链可视化
- ✅ 日志查询接口
- ✅ Trace 数据存储

### 1.3 预期收益

| 收益维度 | 具体效果 |
|---------|---------|
| **调试效率** | 从 30 分钟定位问题 → 5 分钟定位问题 |
| **问题定位** | 快速定位问题根源，精确到具体代码行 |
| **调用链分析** | 完整调用链可视化，分析调用关系 |
| **日志分析** | 日志分析效率提升 10 倍 |

---

## 二、实现方案

### 2.1 实现位置

**主要文件**:
- `utils/trace_context.py` - Trace 上下文管理（新建）
- `utils/log_config.py` - 日志配置增强（修改）
- `core/agent_controller.py` - Trace ID 传递（修改）
- `web/app.py` - Trace ID 生成（修改）

**相关文件**:
- `utils/langfuse_adapter.py` - Langfuse 客户端适配器
- `config/logging_config.yaml` - 日志配置文件（新建）

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                   Trace 定位体系                             │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Web 层 - Trace ID 生成                                  ││
│  │  - 每个请求生成唯一 Trace ID                              ││
│  │  - 存储在 Flask g 对象中                                 ││
│  │  - 传递给下游组件                                         ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Trace Context - Trace ID 管理                           ││
│  │  - 使用 ContextVar 存储 Trace ID                         ││
│  │  - 提供 get_trace_id() 和 set_trace_id()                ││
│  │  - 自动传递给子线程                                       ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Log Config - 日志关联                                   ││
│  │  - TraceFormatter 自动添加 Trace ID                      ││
│  │  - 日志格式: [trace_id] [level] message                  ││
│  │  - 支持 Trace ID 过滤                                    ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Agent Controller - Trace 传递                           ││
│  │  - 从 Context 获取 Trace ID                              ││
│  │  - 传递给 Langfuse Trace                                 ││
│  │  - 传递给工具调用                                         ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Langfuse - Trace 存储                                   ││
│  │  - Trace ID 作为 metadata                                ││
│  │  - 关联所有 Span                                          ││
│  │  - 提供查询接口                                           ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 三、详细实现步骤

### 3.1 步骤 1: 创建 Trace Context 管理器

**文件**: `utils/trace_context.py`（新建）

```python
"""
Trace Context 管理器

使用 ContextVar 存储 Trace ID，支持跨线程传递
"""

import uuid
from contextvars import ContextVar
from typing import Optional

# 使用 ContextVar 存储 Trace ID（线程安全）
_trace_id: ContextVar[str] = ContextVar('trace_id', default='')
_session_id: ContextVar[str] = ContextVar('session_id', default='')

class TraceContext:
    """Trace 上下文管理器"""
    
    @staticmethod
    def get_trace_id() -> str:
        """获取当前 Trace ID"""
        trace_id = _trace_id.get()
        if not trace_id:
            # 自动生成 Trace ID
            trace_id = str(uuid.uuid4())
            _trace_id.set(trace_id)
        return trace_id
    
    @staticmethod
    def set_trace_id(trace_id: Optional[str] = None) -> str:
        """设置 Trace ID
        
        Args:
            trace_id: Trace ID（可选，不提供则自动生成）
        
        Returns:
            设置的 Trace ID
        """
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        _trace_id.set(trace_id)
        return trace_id
    
    @staticmethod
    def get_session_id() -> str:
        """获取当前 Session ID"""
        return _session_id.get()
    
    @staticmethod
    def set_session_id(session_id: str) -> None:
        """设置 Session ID"""
        _session_id.set(session_id)
    
    @staticmethod
    def clear() -> None:
        """清除 Trace Context"""
        _trace_id.set('')
        _session_id.set('')
    
    @staticmethod
    def get_context() -> dict:
        """获取完整上下文"""
        return {
            "trace_id": TraceContext.get_trace_id(),
            "session_id": TraceContext.get_session_id()
        }

# 提供便捷函数
def get_trace_id() -> str:
    """获取当前 Trace ID"""
    return TraceContext.get_trace_id()

def set_trace_id(trace_id: Optional[str] = None) -> str:
    """设置 Trace ID"""
    return TraceContext.set_trace_id(trace_id)

def get_current_trace() -> Optional[dict]:
    """获取当前 Trace 上下文"""
    trace_id = get_trace_id()
    if trace_id:
        return TraceContext.get_context()
    return None
```

### 3.2 步骤 2: 增强日志配置

**文件**: `utils/log_config.py`（修改）

```python
"""
日志配置增强

支持 Trace ID 自动添加和过滤
"""

import logging
import sys
from pathlib import Path
from typing import Optional

# 导入 Trace Context
try:
    from utils.trace_context import get_trace_id
    TRACE_CONTEXT_AVAILABLE = True
except ImportError:
    TRACE_CONTEXT_AVAILABLE = False
    get_trace_id = lambda: ''

class TraceFormatter(logging.Formatter):
    """带 Trace ID 的日志格式化器"""
    
    def format(self, record):
        # 添加 Trace ID
        if TRACE_CONTEXT_AVAILABLE:
            record.trace_id = get_trace_id()
        else:
            record.trace_id = ''
        
        # 添加其他字段
        record.component = getattr(record, 'component', 'unknown')
        
        return super().format(record)

class TraceFilter(logging.Filter):
    """Trace ID 过滤器"""
    
    def __init__(self, trace_id: str):
        super().__init__()
        self.trace_id = trace_id
    
    def filter(self, record):
        # 只保留指定 Trace ID 的日志
        return getattr(record, 'trace_id', '') == self.trace_id

def get_logger(name: str, component: str = "core") -> logging.Logger:
    """获取带 Trace 支持的 logger
    
    Args:
        name: logger 名称
        component: 组件名称
    
    Returns:
        配置好的 logger
    """
    logger = logging.getLogger(name)
    
    # 如果已经配置过，直接返回
    if logger.handlers:
        return logger
    
    # 设置日志级别
    logger.setLevel(logging.INFO)
    
    # 创建 TraceFormatter
    formatter = TraceFormatter(
        fmt='[%(asctime)s] [%(trace_id)s] [%(levelname)s] [%(component)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件输出
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    file_handler = logging.FileHandler(
        log_dir / f"{component}.log",
        mode='a',
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 设置 component 属性
    logger.component = component
    
    return logger

def get_logs_by_trace_id(trace_id: str, log_file: str = None) -> list:
    """根据 Trace ID 获取日志
    
    Args:
        trace_id: Trace ID
        log_file: 日志文件路径（可选）
    
    Returns:
        日志列表
    """
    logs = []
    
    # 默认日志文件
    if log_file is None:
        log_file = Path("logs") / "core.log"
    
    # 读取日志文件
    if Path(log_file).exists():
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if f'[{trace_id}]' in line:
                    logs.append(line.strip())
    
    return logs
```

### 3.3 步骤 3: 在 Web 层生成 Trace ID

**文件**: `web/app.py`（修改）

```python
"""
Web 应用 - Trace ID 生成
"""

from flask import Flask, g, request
from utils.trace_context import set_trace_id, set_session_id, get_trace_id
from utils.log_config import get_logger

logger = get_logger("app", component="web")

app = Flask(__name__)

@app.before_request
def before_request():
    """请求前处理 - 生成 Trace ID"""
    
    # 生成 Trace ID
    trace_id = set_trace_id()
    
    # 获取 Session ID（从请求中）
    session_id = request.headers.get('X-Session-ID') or request.args.get('session_id')
    if session_id:
        set_session_id(session_id)
    
    # 存储在 Flask g 对象中
    g.trace_id = trace_id
    g.session_id = session_id
    
    logger.info(f"请求开始: {request.path}, Trace ID: {trace_id}")

@app.after_request
def after_request(response):
    """请求后处理"""
    
    # 添加 Trace ID 到响应头
    trace_id = getattr(g, 'trace_id', '')
    if trace_id:
        response.headers['X-Trace-ID'] = trace_id
    
    logger.info(f"请求结束: {request.path}, Trace ID: {trace_id}")
    
    return response

@app.route('/api/logs/<trace_id>')
def get_logs(trace_id):
    """获取指定 Trace ID 的日志"""
    
    from utils.log_config import get_logs_by_trace_id
    
    logs = get_logs_by_trace_id(trace_id)
    
    return {
        "trace_id": trace_id,
        "logs": logs,
        "count": len(logs)
    }
```

### 3.4 步骤 4: 在 Agent Controller 中传递 Trace ID

**文件**: `core/agent_controller.py`（修改）

```python
"""
Agent Controller - Trace ID 传递
"""

from utils.trace_context import get_trace_id, get_current_trace
from utils.log_config import get_logger

logger = get_logger("agent_controller", component="core")

class AgentController:
    """Agent 控制器"""
    
    def solve(self, query: str, context: Optional[Dict] = None) -> Dict:
        """执行 Agent 推理循环"""
        
        # 获取 Trace ID
        trace_id = get_trace_id()
        trace_ctx = get_current_trace()
        
        logger.info(f"Agent 开始推理, Trace ID: {trace_id}, Query: {query}")
        
        # 创建 Langfuse Trace（带 Trace ID）
        if langfuse_client and langfuse_client.enabled:
            agent_trace = langfuse_client.observation(
                name="react_agent",
                as_type="agent",
                input={"query": query, "context": context},
                metadata={
                    "trace_id": trace_id,
                    "session_id": trace_ctx.get("session_id") if trace_ctx else None,
                    "max_turns": self.max_turns
                }
            )
        
        # 执行推理循环
        try:
            result = self._execute_react_loop(query, context, agent_trace)
            
            logger.info(f"Agent 推理完成, Trace ID: {trace_id}, Result: {result.get('answer')}")
            
            return result
        except Exception as e:
            logger.error(f"Agent 推理失败, Trace ID: {trace_id}, Error: {e}")
            return {"error": str(e)}
```

### 3.5 步骤 5: 创建日志配置文件

**文件**: `config/logging_config.yaml`（新建）

```yaml
logging:
  level: INFO
  
  # 日志格式
  format:
    pattern: '[%(asctime)s] [%(trace_id)s] [%(levelname)s] [%(component)s] %(name)s: %(message)s'
    date_format: '%Y-%m-%d %H:%M:%S'
  
  # 日志文件配置
  files:
    core:
      path: 'logs/core.log'
      level: DEBUG
      max_size: 10MB
      backup_count: 5
    
    web:
      path: 'logs/web.log'
      level: INFO
      max_size: 10MB
      backup_count: 5
    
    tools:
      path: 'logs/tools.log'
      level: INFO
      max_size: 10MB
      backup_count: 5
  
  # Trace 配置
  trace:
    enabled: true
    auto_generate: true  # 自动生成 Trace ID
    store_in_context: true  # 存储在 ContextVar
    add_to_logs: true  # 自动添加到日志
  
  # 过滤配置
  filters:
    enable_trace_filter: true  # 启用 Trace ID 过滤
    max_logs_per_trace: 1000  # 每个 Trace 最大日志数
```

---

## 四、测试方案

### 4.1 单元测试

**文件**: `tests/utils/test_trace_context.py`

```python
import pytest
from utils.trace_context import TraceContext, get_trace_id, set_trace_id

class TestTraceContext:
    
    def test_trace_id_generation(self):
        """测试 Trace ID 自动生成"""
        trace_id = get_trace_id()
        
        # 验证 Trace ID 格式
        assert trace_id is not None
        assert len(trace_id) == 36  # UUID 格式
        assert '-' in trace_id
    
    def test_trace_id_setting(self):
        """测试 Trace ID 设置"""
        custom_trace_id = "custom-trace-123"
        set_trace_id(custom_trace_id)
        
        # 验证 Trace ID
        assert get_trace_id() == custom_trace_id
    
    def test_trace_context_clear(self):
        """测试 Trace Context 清除"""
        set_trace_id("test-trace")
        TraceContext.clear()
        
        # 验证清除
        assert get_trace_id() != "test-trace"
    
    def test_context_vars_thread_safety(self):
        """测试 ContextVar 线程安全"""
        import threading
        
        results = []
        
        def worker(trace_id):
            set_trace_id(trace_id)
            results.append(get_trace_id())
        
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(f"trace-{i}",))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # 验证每个线程有独立的 Trace ID
        assert len(results) == 5
        assert len(set(results)) == 5  # 所有 Trace ID 不同
```

### 4.2 单元测试 - 日志配置

**文件**: `tests/utils/test_log_config.py`

```python
import pytest
import logging
from utils.log_config import TraceFormatter, TraceFilter, get_logger

class TestLogConfig:
    
    def test_trace_formatter(self):
        """测试 TraceFormatter"""
        formatter = TraceFormatter(
            fmt='[%(trace_id)s] %(message)s'
        )
        
        # 创建日志记录
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None
        )
        
        # 格式化
        formatted = formatter.format(record)
        
        # 验证格式
        assert '[trace_id]' in formatted or formatted.startswith('[]')
    
    def test_trace_filter(self):
        """测试 TraceFilter"""
        filter = TraceFilter("trace-123")
        
        # 创建日志记录
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None
        )
        
        # 设置 Trace ID
        record.trace_id = "trace-123"
        
        # 过滤
        assert filter.filter(record) is True
        
        # 不同 Trace ID
        record.trace_id = "trace-456"
        assert filter.filter(record) is False
    
    def test_logger_creation(self):
        """测试 logger 创建"""
        logger = get_logger("test_logger", component="test")
        
        # 验证 logger
        assert logger is not None
        assert logger.name == "test_logger"
        assert len(logger.handlers) > 0
```

### 4.3 集成测试

**文件**: `tests/integration/test_trace_integration.py`

```python
import pytest
from utils.trace_context import set_trace_id, get_trace_id
from utils.log_config import get_logs_by_trace_id
from core.agent_controller import AgentController

class TestTraceIntegration:
    
    def test_full_trace_flow(self):
        """测试完整 Trace 流程"""
        # 设置 Trace ID
        trace_id = set_trace_id("test-trace-123")
        
        # 执行 Agent
        agent = AgentController()
        result = agent.solve("推荐克制帕吉的英雄")
        
        # 获取日志
        logs = get_logs_by_trace_id(trace_id)
        
        # 验证日志
        assert len(logs) > 0
        assert any('test-trace-123' in log for log in logs)
    
    def test_web_trace_generation(self):
        """测试 Web Trace 生成"""
        from web.app import app
        
        with app.test_client() as client:
            # 发送请求
            response = client.post('/api/chat', json={"query": "test"})
            
            # 获取 Trace ID
            trace_id = response.headers.get('X-Trace-ID')
            
            # 验证 Trace ID
            assert trace_id is not None
            assert len(trace_id) == 36
```

---

## 五、配置说明

### 5.1 Trace 配置

**文件**: `config/trace_config.yaml`（新建）

```yaml
trace:
  enabled: true
  
  # Trace ID 配置
  id:
    auto_generate: true  # 自动生成
    format: uuid  # UUID 格式
    length: 36  # 长度
  
  # 存储配置
  storage:
    type: context_var  # ContextVar 存储
    thread_safe: true  # 线程安全
    auto_clear: true  # 自动清除
  
  # 传递配置
  propagation:
    to_langfuse: true  # 传递给 Langfuse
    to_tools: true  # 传递给工具
    to_logs: true  # 传递给日志
  
  # 查询配置
  query:
    enabled: true  # 启用查询接口
    max_logs: 1000  # 最大日志数
    cache_enabled: true  # 启用缓存
```

### 5.2 日志配置

**文件**: `config/logging_config.yaml`（见上文）

---

## 六、预期收益分析

### 6.1 调试效率提升

**场景**: Agent 推理失败，需要定位问题

**当前状态**:
- ❌ 只能看到最终错误信息
- ❌ 无法定位具体哪个组件失败
- ❌ 无法查看完整调用链
- ❌ 日志分散在多个文件

**集成后**:
- ✅ 可根据 Trace ID 快速获取完整调用链日志
- ✅ 可定位到具体失败的组件（Web → Agent → Tool）
- ✅ 可查看完整调用链（从请求开始到结束）
- ✅ 日志集中管理，支持 Trace ID 过滤

**效率提升**: 从 30 分钟定位问题 → 5 分钟定位问题

---

### 6.2 问题定位

**场景**: 工具执行失败，需要定位失败原因

**当前状态**:
- ❌ 只能看到工具错误信息
- ❌ 无法查看工具调用上下文
- ❌ 无法分析工具调用链

**集成后**:
- ✅ 可查看工具调用的完整上下文（Trace ID）
- ✅ 可分析工具调用链（Agent → Tool → API）
- ✅ 可定位到具体失败的代码行

**定位效率**: 从 20 分钟定位 → 3 分钟定位

---

### 6.3 调用链分析

**场景**: 分析 Agent 推理调用链

**当前状态**:
- ❌ 无法查看调用链
- ❌ 无法分析调用关系
- ❌ 无法可视化调用过程

**集成后**:
- ✅ 可查看完整调用链（Web → Agent → Think → Plan → Execute → Tool → API）
- ✅ 可分析调用关系（哪个工具被调用，调用顺序）
- ✅ 可可视化调用过程（调用链图）

**分析效率**: 从无法分析 → 5 分钟分析

---

## 七、风险评估

### 7.1 性能影响

**风险**: Trace ID 传递可能影响性能

**缓解措施**:
- 使用 ContextVar（线程安全，性能高）
- 避免频繁的 Trace ID 生成
- 使用缓存减少日志查询开销

**预期影响**: 性能损耗 < 2%

---

### 7.2 存储开销

**风险**: Trace 数据存储可能占用大量空间

**缓解措施**:
- 设置日志文件大小限制（10MB）
- 设置备份文件数量（5 个）
- 定期清理过期日志（7 天）

**预期开销**: 日志文件总大小 < 50MB

---

## 八、实施计划

### 8.1 时间安排

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| **第 1 天** | 创建 Trace Context 管理器 | 3 小时 |
| **第 2 天** | 增强日志配置 | 3 小时 |
| **第 3 天** | 在 Web 层生成 Trace ID | 2 小时 |
| **第 4 天** | 在 Agent Controller 中传递 Trace ID | 2 小时 |
| **第 5 天** | 编写单元测试和集成测试 | 3 小时 |
| **第 6 天** | 配置优化和性能测试 | 2 小时 |
| **第 7 天** | 文档编写和验收测试 | 1 小时 |

**总预计时间**: 16 小时（约 3 个工作日）

---

### 8.2 验收标准

| 标准 | 验收方法 |
|------|---------|
| ✅ Trace ID 自动生成 | 测试 TraceContext |
| ✅ Trace ID 传递正常 | 测试 Agent Controller |
| ✅ 日志包含 Trace ID | 查看日志文件 |
| ✅ Trace ID 过滤正常 | 测试 TraceFilter |
| ✅ 日志查询接口正常 | 测试 API |
| ✅ 性能损耗 < 2% | 性能测试 |
| ✅ 单元测试通过 | pytest 运行 |
| ✅ 集成测试通过 | pytest 运行 |

---

## 九、总结

Trace 定位与日志追踪体系是 Langfuse 集成的核心基础设施，将显著提升问题定位效率和调试能力。

**关键收益**:
- ✅ 快速定位问题（从 30 分钟 → 5 分钟）
- ✅ 完整调用链追踪
- ✅ 日志分析效率提升 10 倍
- ✅ 调用链可视化

**下一步**: 完成 P0 优先级功能后，继续实现 P1 优先级功能（Prompt 版本管理）