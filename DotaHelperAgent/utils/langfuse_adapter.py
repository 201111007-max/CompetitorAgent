"""Langfuse 适配器模块

将 Langfuse SDK 包装为可选组件：
- 如果 langfuse SDK 已安装且配置正确，则启用追踪功能
- 如果 langfuse SDK 未安装，则静默跳过，不影响项目运行

使用方式:
    from utils.langfuse_adapter import LangfuseClient
    
    client = LangfuseClient.get_instance()
    client.init()
    
    with client.observation(name="operation") as obs:
        obs.update(output={"result": "success"})
"""

import logging
from typing import Optional, Dict, Any

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


class NoOpObservation:
    """空操作 Observation - 当 langfuse 不可用时使用
    
    所有方法都是空操作，返回自身或对应的空操作对象
    """
    
    def span(self, **kwargs: Any) -> "NoOpObservation":
        """创建空操作 Span
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpObservation: 空操作 Observation 实例
        """
        return NoOpObservation()
    
    def update(self, **kwargs: Any) -> "NoOpObservation":
        """更新 Observation（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpObservation: 自身实例
        """
        return self
    
    def score(self, **kwargs: Any) -> "NoOpObservation":
        """记录评分（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpObservation: 自身实例
        """
        return self
    
    def end(self, **kwargs: Any) -> "NoOpObservation":
        """结束 Observation（空操作）
        
        Args:
            **kwargs: 任意参数（忽略）
        
        Returns:
            NoOpObservation: 自身实例
        """
        return self
    
    def __enter__(self) -> "NoOpObservation":
        """进入上下文管理器
        
        Returns:
            NoOpObservation: 自身实例
        """
        return self
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """退出上下文管理器"""
        pass


class LangfuseClient:
    """Langfuse 客户端单例
    
    确保全局只有一个 Langfuse 客户端实例
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
                - host: Langfuse 服务器地址
                - enabled: 是否启用
        """
        if not LANGFUSE_AVAILABLE:
            logger.info("langfuse SDK 未安装，监控功能已禁用")
            self._enabled = False
            return
        
        import os
        
        self._config = config or {}
        
        public_key = self._config.get('public_key') or os.getenv('LANGFUSE_PUBLIC_KEY')
        secret_key = self._config.get('secret_key') or os.getenv('LANGFUSE_SECRET_KEY')
        host = self._config.get('host') or os.getenv('LANGFUSE_HOST', 'http://localhost:3000')
        
        if not public_key or not secret_key:
            logger.warning("Langfuse 密钥未配置，监控功能已禁用")
            self._enabled = False
            return
        
        try:
            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host
            )
            
            if self._config.get('enabled', True):
                if self._client.auth_check():
                    self._enabled = True
                    logger.info(f"Langfuse 客户端初始化成功，连接到 {host}")
                else:
                    logger.warning("Langfuse 认证失败，监控功能已禁用")
                    self._enabled = False
            else:
                self._enabled = False
                logger.info("Langfuse 监控已被配置禁用")
        except Exception as e:
            logger.warning(f"Langfuse 初始化失败: {e}")
            self._enabled = False
    
    @property
    def enabled(self) -> bool:
        """检查客户端是否启用
        
        Returns:
            bool: 是否启用
        """
        return self._enabled
    
    @property
    def client(self) -> Optional[Any]:
        """获取底层 Langfuse 客户端
        
        Returns:
            Optional[Any]: Langfuse 客户端实例或 None
        """
        return self._client
    
    def observation(
        self, 
        name: str, 
        as_type: str = "span",
        input: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Any:
        """创建 Observation
        
        Args:
            name: Observation 名称
            as_type: 类型 (span, chain, agent, tool, generation 等)
            input: 输入数据
            metadata: 元数据
        
        Returns:
            Observation 实例或 NoOpObservation
        """
        if not self.enabled or not self._client:
            return NoOpObservation()
        
        try:
            return self._client.start_observation(
                name=name,
                as_type=as_type,
                input=input,
                metadata=metadata
            )
        except Exception as e:
            logger.warning(f"创建 Langfuse observation 失败: {e}")
            return NoOpObservation()
    
    def event(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Any:
        """创建 Event
        
        Args:
            name: Event 名称
            metadata: 元数据
        
        Returns:
            Event 实例
        """
        if not self.enabled or not self._client:
            return None
        
        try:
            return self._client.create_event(name=name, metadata=metadata)
        except Exception as e:
            logger.warning(f"创建 Langfuse event 失败: {e}")
            return None
    
    def score(
        self,
        name: str,
        value: float,
        comment: Optional[str] = None
    ) -> None:
        """创建评分
        
        Args:
            name: 评分名称
            value: 评分值
            comment: 评论文
        """
        if not self.enabled or not self._client:
            return
        
        try:
            self._client.create_score(name=name, value=value, comment=comment)
        except Exception as e:
            logger.warning(f"创建 Langfuse score 失败: {e}")
    
    def flush(self) -> None:
        """刷新数据到 Langfuse 服务器"""
        if self._client:
            try:
                self._client.flush()
            except Exception as e:
                logger.warning(f"刷新 Langfuse 数据失败: {e}")
    
    def shutdown(self) -> None:
        """关闭客户端"""
        if self._client:
            try:
                self._client.shutdown()
            except Exception as e:
                logger.warning(f"关闭 Langfuse 客户端失败: {e}")


# 兼容旧 API 的别名
NoOpTrace = NoOpObservation
NoOpSpan = NoOpObservation
NoOpEvent = NoOpObservation
