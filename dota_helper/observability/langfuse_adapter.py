"""LangfuseTracer — Langfuse SDK 适配器

当 Langfuse SDK 可用时，桥接到 Langfuse 远程追踪。
SDK 缺失时自动降级为 NoOpTracer，项目正常运行。
"""
import os
from typing import Any, Optional

from dota_helper.observability.logger import get_logger
from dota_helper.observability.noop_tracer import NoOpTracer
from dota_helper.secret_vault import vault

logger = get_logger("observability.langfuse_adapter")

# 检测 Langfuse SDK 是否可用
try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False


def create_tracer() -> Any:
    """创建追踪器实例

    Langfuse SDK 可用时返回 LangfuseTracer，否则返回 NoOpTracer。

    Returns:
        ITracer: 追踪器实例
    """
    if not LANGFUSE_AVAILABLE:
        logger.info("Langfuse SDK 不可用，使用 NoOpTracer 降级")
        return NoOpTracer()

    public_key = vault.get("LANGFUSE_PUBLIC_KEY", owner="langfuse_adapter")
    secret_key = vault.get("LANGFUSE_SECRET_KEY", owner="langfuse_adapter")
    host = os.getenv("LANGFUSE_HOST", "http://localhost:3001")

    if not public_key or not secret_key:
        logger.warning("Langfuse 环境变量未配置，使用 NoOpTracer 降级")
        return NoOpTracer()

    try:
        langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        logger.info("LangfuseTracer 初始化成功: host=%s", host)
        return _LangfuseTracer(langfuse_client)
    except Exception as e:
        logger.warning("Langfuse 初始化失败，降级为 NoOpTracer: %s", str(e))
        return NoOpTracer()


class _LangfuseSpan:
    """Langfuse Span 适配器"""

    def __init__(self, langfuse_span: Any) -> None:
        """初始化 Langfuse Span 适配器

        Args:
            langfuse_span: Langfuse SDK Span 对象
        """
        self._span = langfuse_span

    def set_attribute(self, key: str, value: Any) -> None:
        """设置 Span 属性

        Args:
            key: 属性键
            value: 属性值
        """
        try:
            self._span.update(metadata={key: value})
        except Exception as e:
            logger.debug("Langfuse span.set_attribute 失败: %s", str(e))

    def set_status(self, status: str) -> None:
        """设置 Span 状态

        Args:
            status: 状态值
        """
        try:
            if status == "error":
                self._span.update(level="ERROR")
            else:
                self._span.update(level="DEBUG")
        except Exception as e:
            logger.debug("Langfuse span.set_status 失败: %s", str(e))

    def end(self) -> None:
        """结束 Span"""
        try:
            self._span.end()
        except Exception as e:
            logger.debug("Langfuse span.end 失败: %s", str(e))


class _LangfuseTracer:
    """Langfuse 追踪器实现

    桥接到 Langfuse SDK，支持 Span 创建和事件记录。
    """

    def __init__(self, langfuse_client: Any) -> None:
        """初始化 Langfuse 追踪器

        Args:
            langfuse_client: Langfuse SDK 客户端实例
        """
        self._client = langfuse_client

    async def span(self, name: str, **kwargs: Any) -> Any:
        """创建 Langfuse Span

        Args:
            name: Span 名称
            **kwargs: Span 属性

        Returns:
            _LangfuseSpan: Langfuse Span 适配器
        """
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _span_ctx():
            trace = self._client.trace(name=name, metadata=kwargs)
            span_obj = trace.span(name=name)
            adapted = _LangfuseSpan(span_obj)
            try:
                yield adapted
            finally:
                adapted.end()

        return _span_ctx()

    def event(self, name: str, **kwargs: Any) -> None:
        """记录 Langfuse 事件

        Args:
            name: 事件名称
            **kwargs: 事件属性
        """
        try:
            self._client.event(name=name, metadata=kwargs)
        except Exception as e:
            logger.debug("Langfuse event 失败: %s", str(e))
