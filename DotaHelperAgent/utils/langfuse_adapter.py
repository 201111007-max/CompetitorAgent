"""Langfuse 适配器模块

将 Langfuse SDK 包装为可选组件：
- 如果 langfuse SDK 已安装且配置正确，则启用追踪功能
- 如果 langfuse SDK 未安装，则静默跳过，不影响项目运行

使用方式:
    from utils.langfuse_adapter import LangfuseClient
    
    client = LangfuseClient.get_instance()
    client.init()
    
    with client.trace(trace_id="xxx", session_id="yyy") as trace:
        with trace.span(name="operation") as span:
            span.update(output={"result": "success"})
"""

import logging
from typing import Optional, Dict, Any, Union

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE: bool = True
except ImportError:
    LANGFUSE_AVAILABLE: bool = False
    Langfuse = None  # type: ignore
    logger.debug("langfuse 未安装，监控功能已禁用。安装: pip install langfuse")


def is_langfuse_available() -> bool:
    """检查 Langfuse SDK 是否可用
    
    Returns:
        bool: SDK 是否可用
    """
    return LANGFUSE_AVAILABLE


class NoOpTrace:
    """空操作 Trace - 当 langfuse 不可用时使用
    
    所有方法都是空操作，返回自身或对应的空操作对象
    """
    
    def span(self, **kwargs: Any) -> "NoOpSpan":
        """创建空操作 Span
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpSpan: 空操作 Span 实例
        """
        return NoOpSpan()
    
    def event(self, **kwargs: Any) -> "NoOpEvent":
        """创建空操作 Event
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpEvent: 空操作 Event 实例
        """
        return NoOpEvent()
    
    def update(self, **kwargs: Any) -> "NoOpTrace":
        """更新 Trace（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpTrace: 自身实例
        """
        return self
    
    def score(self, **kwargs: Any) -> "NoOpTrace":
        """记录评分（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpTrace: 自身实例
        """
        return self
    
    def __enter__(self) -> "NoOpTrace":
        """进入上下文管理器
        
        Returns:
            NoOpTrace: 自身实例
        """
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        pass


class NoOpSpan:
    """空操作 Span
    
    所有方法都是空操作，返回自身或对应的空操作对象
    """
    
    def event(self, **kwargs: Any) -> "NoOpEvent":
        """创建空操作 Event
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpEvent: 空操作 Event 实例
        """
        return NoOpEvent()
    
    def update(self, **kwargs: Any) -> "NoOpSpan":
        """更新 Span（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def score(self, **kwargs: Any) -> "NoOpSpan":
        """记录评分（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def end(self) -> "NoOpSpan":
        """结束 Span（空操作）
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def __enter__(self) -> "NoOpSpan":
        """进入上下文管理器
        
        Returns:
            NoOpSpan: 自身实例
        """
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        pass


class NoOpEvent:
    """空操作 Event
    
    所有方法都是空操作，返回自身
    """
    
    def update(self, **kwargs: Any) -> "NoOpEvent":
        """更新 Event（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpEvent: 自身实例
        """
        return self
    
    def __enter__(self) -> "NoOpEvent":
        """进入上下文管理器
        
        Returns:
            NoOpEvent: 自身实例
        """
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        pass


class LangfuseClient:
    """Langfuse 客户端包装器 - 单例模式
    
    如果 langfuse SDK 未安装，所有方法都是空操作
    
    使用方式:
        client = LangfuseClient.get_instance()
        client.init(config={
            "public_key": "xxx",
            "secret_key": "yyy",
            "host": "http://localhost:3000"
        })
        
        with client.trace(trace_id="xxx") as trace:
            with trace.span(name="operation") as span:
                span.update(output={"result": "success"})
    """
    
    _instance: Optional["LangfuseClient"] = None
    
    def __new__(cls) -> "LangfuseClient":
        """创建单例实例
        
        Returns:
            LangfuseClient: 单例实例
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
            cls._instance._enabled = False
            cls._instance._config: Dict[str, Any] = {}
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "LangfuseClient":
        """获取单例实例
        
        Returns:
            LangfuseClient: 单例实例
        """
        return cls()
    
    def init(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化 Langfuse 客户端
        
        Args:
            config: 配置字典，包含:
                - public_key: Langfuse 公钥
                - secret_key: Langfuse 密钥
                - host: Langfuse 服务器地址（默认 http://localhost:3000）
                - enabled: 是否启用（默认 True）
        """
        if not LANGFUSE_AVAILABLE:
            logger.info("langfuse SDK 未安装，监控功能已禁用")
            self._enabled = False
            return
        
        if config:
            self._config = config
        
        if not self._config.get('enabled', True):
            logger.info("Langfuse 监控已禁用")
            self._enabled = False
            return
        
        public_key = self._config.get('public_key')
        secret_key = self._config.get('secret_key')
        
        if not public_key or not secret_key:
            logger.warning("Langfuse 配置不完整（缺少 public_key 或 secret_key），监控功能已禁用")
            self._enabled = False
            return
        
        try:
            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=self._config.get('host', 'http://localhost:3000')
            )
            self._enabled = True
            logger.info(f"Langfuse 监控已启用: {self._config.get('host', 'http://localhost:3000')}")
        except Exception as e:
            logger.error(f"Langfuse 初始化失败: {e}")
            self._enabled = False
    
    @property
    def enabled(self) -> bool:
        """检查是否启用
        
        Returns:
            bool: 是否启用
        """
        return self._enabled and LANGFUSE_AVAILABLE
    
    def trace(self, trace_id: str, **kwargs: Any) -> Union["Trace", NoOpTrace]:
        """创建 Trace
        
        Args:
            trace_id: 追踪 ID（与现有 Trace 系统兼容）
            **kwargs: 其他参数（session_id, metadata 等）
        
        Returns:
            Union[Trace, NoOpTrace]: Langfuse Trace 或 NoOpTrace
        """
        if not self.enabled or not self._client:
            return NoOpTrace()
        
        try:
            return self._client.trace(id=trace_id, **kwargs)
        except Exception as e:
            logger.warning(f"创建 Langfuse Trace 失败: {e}")
            return NoOpTrace()
    
    def flush(self) -> None:
        """刷新数据到 Langfuse Server"""
        if self.enabled and self._client:
            try:
                self._client.flush()
            except Exception as e:
                logger.warning(f"刷新 Langfuse 数据失败: {e}")
