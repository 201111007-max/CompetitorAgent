"""Trace 上下文管理模块

实现分布式追踪的核心功能，包括:
1. TraceContext - Trace 上下文数据结构
2. TraceSpan - Span 上下文管理器
3. @traced 装饰器 - 自动为函数添加 Trace 支持

使用示例:
    # 方式1: 使用上下文管理器
    with TraceSpan("operation_name"):
        do_something()
    
    # 方式2: 使用装饰器
    @traced("operation_name")
    def my_function():
        do_something()
    
    # 方式3: 手动管理
    trace_ctx = TraceContext(trace_id="xxx", span_id="yyy", ...)
    set_current_trace(trace_ctx)
    # ... 执行业务逻辑
    set_current_trace(None)  # 清理
"""

import contextvars
import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable
from functools import wraps

# 全局 Trace 上下文变量
_current_trace: contextvars.ContextVar[Optional["TraceContext"]] = contextvars.ContextVar(
    'current_trace', default=None
)

# 使用 log_config 中的 get_logger 获取带 Trace 支持的 logger
# 注意：这里使用延迟导入，避免循环依赖
_logger = None

def _get_logger():
    global _logger
    if _logger is None:
        try:
            from utils.log_config import get_logger
            _logger = get_logger("trace_context", component="system")
        except ImportError:
            _logger = logging.getLogger(__name__)
    return _logger


@dataclass
class TraceContext:
    """Trace 上下文 - 贯穿请求全生命周期
    
    Attributes:
        trace_id: 全局唯一追踪ID，整个请求链路共享同一个 trace_id
        span_id: 当前操作SpanID，每个操作有独立的 span_id
        parent_span_id: 父SpanID，用于构建调用链路树
        session_id: 业务会话ID，与前端保持一致
        operation: 操作名称，如 chat, analyze_hero, execute_tool
        start_time: 开始时间戳（秒）
        metadata: 额外元数据
    """
    trace_id: str
    span_id: str
    session_id: str
    operation: str
    start_time: float = field(default_factory=time.time)
    parent_span_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_log_extra(self) -> Dict[str, Any]:
        """转换为日志 extra 字段"""
        return {
            'trace_id': self.trace_id,
            'span_id': self.span_id,
            'parent_span_id': self.parent_span_id,
            'session_id': self.session_id,
            'operation': self.operation,
            'duration_ms': int((time.time() - self.start_time) * 1000)
        }
    
    def create_child(self, operation: str, **metadata) -> "TraceContext":
        """创建子 Span 上下文
        
        Args:
            operation: 子操作名称
            **metadata: 额外元数据
            
        Returns:
            新的 TraceContext 实例，继承父级的 trace_id 和 session_id
        """
        child_metadata = self.metadata.copy()
        child_metadata.update(metadata)
        
        return TraceContext(
            trace_id=self.trace_id,
            span_id=generate_span_id(),
            parent_span_id=self.span_id,
            session_id=self.session_id,
            operation=operation,
            metadata=child_metadata
        )
    
    def get_duration_ms(self) -> int:
        """获取当前 Span 持续时间（毫秒）"""
        return int((time.time() - self.start_time) * 1000)


def generate_trace_id() -> str:
    """生成全局唯一的 Trace ID
    
    Returns:
        格式: trace_xxxxxxxxxxxxxxxx (16位十六进制)
    """
    return f"trace_{uuid.uuid4().hex[:16]}"


def generate_span_id() -> str:
    """生成 Span ID
    
    Returns:
        格式: xxxxxxxx (8位十六进制)
    """
    return uuid.uuid4().hex[:8]


def generate_session_id() -> str:
    """生成会话 ID（与前端格式保持一致）
    
    Returns:
        格式: sess_xxxxxxxxx
    """
    return f"sess_{uuid.uuid4().hex[:9]}"


def get_current_trace() -> Optional[TraceContext]:
    """获取当前线程/协程的 Trace 上下文
    
    Returns:
        当前的 TraceContext，如果没有则返回 None
    """
    return _current_trace.get()


def set_current_trace(trace_ctx: Optional[TraceContext]):
    """设置当前线程/协程的 Trace 上下文
    
    Args:
        trace_ctx: TraceContext 实例或 None（用于清理）
    """
    _current_trace.set(trace_ctx)


class TraceSpan:
    """Trace Span 上下文管理器
    
    使用 with 语句自动管理 Span 的生命周期:
    - 进入时创建新的 Span 上下文
    - 退出时记录 Span 完成日志
    - 自动处理异常
    
    示例:
        with TraceSpan("database_query") as span:
            result = db.query(sql)
            # span 自动记录执行时间和结果
    """
    
    def __init__(self, operation: str, parent: Optional[TraceContext] = None, 
                 session_id: Optional[str] = None, **metadata):
        """初始化 TraceSpan
        
        Args:
            operation: 操作名称
            parent: 父级 TraceContext，为 None 则自动获取当前上下文
            session_id: 会话ID（仅在创建根 Span 时需要）
            **metadata: 额外元数据
        """
        self.operation = operation
        self.parent = parent or get_current_trace()
        self.session_id = session_id
        self.metadata = metadata
        self.trace_ctx: Optional[TraceContext] = None
        self._start_time: float = 0
        
    def __enter__(self) -> TraceContext:
        """进入上下文，创建新的 Span"""
        self._start_time = time.time()
        
        if self.parent:
            # 创建子 Span
            self.trace_ctx = self.parent.create_child(self.operation, **self.metadata)
        else:
            # 创建根 Span
            self.trace_ctx = TraceContext(
                trace_id=generate_trace_id(),
                span_id=generate_span_id(),
                session_id=self.session_id or generate_session_id(),
                operation=self.operation,
                metadata=self.metadata
            )
        
        # 设置当前上下文
        set_current_trace(self.trace_ctx)
        
        # 记录 Span 开始
        _get_logger().debug_ctx(
            f"Span started: {self.operation}",
            session_id=self.trace_ctx.session_id,
            extra_data={
                'trace_id': self.trace_ctx.trace_id,
                'span_id': self.trace_ctx.span_id,
                'parent_span_id': self.trace_ctx.parent_span_id,
                'operation': self.operation
            }
        )
        
        return self.trace_ctx
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文，记录 Span 完成"""
        if self.trace_ctx:
            duration_ms = int((time.time() - self._start_time) * 1000)
            
            # 构建日志数据
            extra_data = {
                'trace_id': self.trace_ctx.trace_id,
                'span_id': self.trace_ctx.span_id,
                'parent_span_id': self.trace_ctx.parent_span_id,
                'operation': self.operation,
                'duration_ms': duration_ms,
                'success': exc_type is None
            }
            
            # 如果有异常，记录错误信息
            if exc_type:
                extra_data['error'] = str(exc_val)
                extra_data['error_type'] = exc_type.__name__
                _get_logger().warning_ctx(
                    f"Span failed: {self.operation}",
                    session_id=self.trace_ctx.session_id,
                    extra_data=extra_data
                )
            else:
                _get_logger().debug_ctx(
                    f"Span completed: {self.operation}",
                    session_id=self.trace_ctx.session_id,
                    extra_data=extra_data
                )
        
        # 恢复父上下文
        set_current_trace(self.parent)


def traced(operation: Optional[str] = None, log_args: bool = False, log_result: bool = False):
    """装饰器：自动为函数添加 Trace 支持
    
    自动创建 Span，记录函数执行时间和结果。
    
    Args:
        operation: 操作名称，默认为函数名
        log_args: 是否记录函数参数（注意：可能包含敏感信息）
        log_result: 是否记录函数返回值
        
    示例:
        @traced("database_query")
        def query_user(user_id: int) -> User:
            return db.get_user(user_id)
        
        @traced(log_args=True)
        def process_data(data: dict) -> dict:
            return transform(data)
    """
    def decorator(func: Callable):
        op_name = operation or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 获取当前上下文
            parent_ctx = get_current_trace()
            
            # 构建元数据
            metadata = {}
            if log_args and (args or kwargs):
                # 谨慎记录参数，避免敏感信息泄露
                metadata['args_count'] = len(args)
                metadata['kwargs_keys'] = list(kwargs.keys())
            
            with TraceSpan(op_name, parent=parent_ctx, **metadata) as span:
                try:
                    result = func(*args, **kwargs)
                    
                    if log_result:
                        # 记录结果摘要
                        result_summary = _summarize_result(result)
                        _get_logger().debug_ctx(
                            f"Function result: {op_name}",
                            session_id=span.session_id,
                            extra_data={
                                'trace_id': span.trace_id,
                                'span_id': span.span_id,
                                'result_summary': result_summary
                            }
                        )
                    
                    return result
                    
                except Exception as e:
                    # 记录异常
                    _get_logger().error_ctx(
                        f"Function failed: {op_name}",
                        session_id=span.session_id,
                        extra_data={
                            'trace_id': span.trace_id,
                            'span_id': span.span_id,
                            'error': str(e),
                            'error_type': type(e).__name__
                        }
                    )
                    raise
        
        return wrapper
    return decorator


def _summarize_result(result: Any) -> Dict[str, Any]:
    """生成结果摘要（避免记录过大或敏感数据）
    
    Args:
        result: 函数返回值
        
    Returns:
        结果摘要字典
    """
    summary = {'type': type(result).__name__}
    
    if result is None:
        summary['value'] = None
    elif isinstance(result, (bool, int, float, str)):
        summary['value'] = result if isinstance(result, (bool, int, float)) else result[:100]
    elif isinstance(result, (list, tuple)):
        summary['length'] = len(result)
        if len(result) > 0:
            summary['first_type'] = type(result[0]).__name__
    elif isinstance(result, dict):
        summary['keys'] = list(result.keys())[:10]  # 最多10个key
    else:
        summary['repr'] = repr(result)[:100]
    
    return summary


# 便捷函数：快速创建 Trace 上下文
def create_trace_context(session_id: Optional[str] = None, 
                         operation: str = "root") -> TraceContext:
    """快速创建根 Trace 上下文
    
    Args:
        session_id: 会话ID，为 None 则自动生成
        operation: 操作名称
        
    Returns:
        新的根 TraceContext
    """
    return TraceContext(
        trace_id=generate_trace_id(),
        span_id=generate_span_id(),
        session_id=session_id or generate_session_id(),
        operation=operation
    )


# 便捷函数：获取当前 Trace 信息用于日志
def get_current_trace_info() -> Dict[str, Any]:
    """获取当前 Trace 信息，用于日志记录
    
    Returns:
        包含 trace 信息的字典，如果没有则返回空字典
    """
    ctx = get_current_trace()
    if ctx:
        return {
            'trace_id': ctx.trace_id,
            'span_id': ctx.span_id,
            'parent_span_id': ctx.parent_span_id,
            'session_id': ctx.session_id,
            'operation': ctx.operation
        }
    return {}
