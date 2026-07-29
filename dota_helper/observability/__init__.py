"""可观测性模块 — Logger + Tracer + Metrics

渐进式六层架构：
L0: Logger（已实现）— Python 标准 logging 封装
L1: ITracer 协议 — 追踪接口定义
L2: Tracer 核心 — Span 创建/管理/嵌套
L3: NoOpTracer — 空实现降级
L4: LangfuseTracer — Langfuse SDK 适配
L5: MetricsCollector — 指标采集
"""
from dota_helper.observability.noop_tracer import NoOpTracer
from dota_helper.observability.tracer import Tracer, TracerSpan
from dota_helper.observability.metrics import MetricsCollector, get_metrics_collector

# 全局追踪器单例
_tracer = None


def get_tracer():
    """获取全局追踪器实例

    默认返回 NoOpTracer（零开销）。
    调用 init_tracer() 可初始化为 Tracer 或 LangfuseTracer。

    Returns:
        ITracer: 追踪器实例
    """
    global _tracer
    if _tracer is None:
        _tracer = NoOpTracer()
    return _tracer


def init_tracer(use_langfuse: bool = False) -> None:
    """初始化全局追踪器

    Args:
        use_langfuse: 是否启用 Langfuse 追踪（默认 False，使用 NoOpTracer）
    """
    global _tracer
    if use_langfuse:
        from dota_helper.observability.langfuse_adapter import create_tracer
        _tracer = create_tracer()
    else:
        _tracer = Tracer()


__all__ = [
    "NoOpTracer",
    "Tracer",
    "TracerSpan",
    "MetricsCollector",
    "get_tracer",
    "init_tracer",
    "get_metrics_collector",
]
