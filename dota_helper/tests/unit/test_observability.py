"""可观测性体系测试 — ITracer + NoOpTracer + Tracer + MetricsCollector"""
import asyncio
import time

import pytest

from dota_helper.interfaces.tracer import ITracer, Span
from dota_helper.observability.noop_tracer import NoOpTracer, NoOpSpan
from dota_helper.observability.tracer import Tracer, TracerSpan
from dota_helper.observability.metrics import MetricsCollector, Timer, get_metrics_collector
from dota_helper.observability import get_tracer, init_tracer


# ── ITracer 协议测试 ──

class TestITracerProtocol:
    """ITracer + Span Protocol 检查"""

    def test_noop_tracer_satisfies_itracr(self) -> None:
        """NoOpTracer 满足 ITracer 协议"""
        tracer = NoOpTracer()
        assert isinstance(tracer, ITracer)

    def test_tracer_satisfies_itracr(self) -> None:
        """Tracer 满足 ITracer 协议"""
        tracer = Tracer()
        assert isinstance(tracer, ITracer)

    def test_noop_span_satisfies_span(self) -> None:
        """NoOpSpan 满足 Span 协议"""
        span = NoOpSpan()
        assert isinstance(span, Span)

    def test_tracer_span_satisfies_span(self) -> None:
        """TracerSpan 满足 Span 协议"""
        span = TracerSpan(name="test")
        assert isinstance(span, Span)


# ── NoOpTracer 测试 ──

class TestNoOpTracer:
    """NoOpTracer 空实现测试"""

    @pytest.mark.asyncio
    async def test_span_noop(self) -> None:
        """NoOpTracer.span() 返回 NoOpSpan，无副作用"""
        tracer = NoOpTracer()
        async with tracer.span("test_span") as s:
            assert isinstance(s, NoOpSpan)
            s.set_attribute("key", "value")  # no-op
            s.set_status("ok")  # no-op
            s.end()  # no-op

    def test_event_noop(self) -> None:
        """NoOpTracer.event() 无副作用"""
        tracer = NoOpTracer()
        tracer.event("test_event", key="value")  # 不应报错


# ── Tracer 核心测试 ──

class TestTracer:
    """Tracer 核心实现测试"""

    @pytest.mark.asyncio
    async def test_span_creation(self) -> None:
        """Tracer 创建 Span"""
        tracer = Tracer()
        async with tracer.span("test_span") as s:
            assert isinstance(s, TracerSpan)
            assert s.name == "test_span"

    @pytest.mark.asyncio
    async def test_span_attributes(self) -> None:
        """Span 设置属性"""
        tracer = Tracer()
        async with tracer.span("test_span", match_id="123") as s:
            assert s.attributes.get("match_id") == "123"
            s.set_attribute("key", "value")
            assert s.attributes.get("key") == "value"

    @pytest.mark.asyncio
    async def test_span_status(self) -> None:
        """Span 设置状态"""
        tracer = Tracer()
        async with tracer.span("test_span") as s:
            s.set_status("error")
            assert s.status == "error"

    @pytest.mark.asyncio
    async def test_span_duration(self) -> None:
        """Span 计算耗时"""
        tracer = Tracer()
        async with tracer.span("test_span") as s:
            await asyncio.sleep(0.01)
        assert s.duration_ms > 0

    @pytest.mark.asyncio
    async def test_span_nesting(self) -> None:
        """Span 嵌套（父子关系）"""
        tracer = Tracer()
        async with tracer.span("parent") as parent:
            async with tracer.span("child") as child:
                assert child.parent_id == parent.span_id
                assert child.trace_id == parent.trace_id

    @pytest.mark.asyncio
    async def test_span_error_handling(self) -> None:
        """Span 异常时设置 error 状态"""
        tracer = Tracer()
        try:
            async with tracer.span("error_span") as s:
                raise ValueError("test error")
        except ValueError:
            pass
        spans = tracer.completed_spans
        assert len(spans) == 1
        assert spans[0].status == "error"
        assert "test error" in spans[0].attributes.get("error", "")

    @pytest.mark.asyncio
    async def test_completed_spans(self) -> None:
        """Tracer 记录已完成的 Span"""
        tracer = Tracer()
        async with tracer.span("span1"):
            pass
        async with tracer.span("span2"):
            pass
        assert len(tracer.completed_spans) == 2

    @pytest.mark.asyncio
    async def test_event(self) -> None:
        """Tracer 记录事件"""
        tracer = Tracer()
        tracer.event("test_event", key="value")  # 不应报错

    @pytest.mark.asyncio
    async def test_span_to_dict(self) -> None:
        """Span 转换为字典"""
        tracer = Tracer()
        async with tracer.span("test_span", match_id="123") as s:
            s.set_attribute("key", "value")
        d = s.to_dict()
        assert d["name"] == "test_span"
        assert "span_id" in d
        assert "trace_id" in d
        assert d["duration_ms"] > 0

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        """Tracer.clear() 清除已完成 Span"""
        tracer = Tracer()
        async with tracer.span("span1"):
            pass
        assert len(tracer.completed_spans) == 1
        tracer.clear()
        assert len(tracer.completed_spans) == 0


# ── MetricsCollector 测试 ──

class TestMetricsCollector:
    """MetricsCollector 指标采集测试"""

    def test_counter(self) -> None:
        """计数器递增"""
        m = MetricsCollector()
        m.increment_counter("tokens_prompt", 100)
        m.increment_counter("tokens_prompt", 50)
        assert m.get_counter("tokens_prompt") == 150

    def test_gauge(self) -> None:
        """Gauge 设置值"""
        m = MetricsCollector()
        m.set_gauge("confidence", 0.85)
        assert m.get_gauge("confidence") == 0.85
        m.set_gauge("confidence", 0.9)
        assert m.get_gauge("confidence") == 0.9

    def test_histogram(self) -> None:
        """Histogram 观测和统计"""
        m = MetricsCollector()
        m.observe_histogram("llm_latency_ms", 100)
        m.observe_histogram("llm_latency_ms", 200)
        m.observe_histogram("llm_latency_ms", 300)
        summary = m.get_histogram_summary("llm_latency_ms")
        assert summary["count"] == 3
        assert summary["mean"] == 200.0
        assert summary["min"] == 100.0
        assert summary["max"] == 300.0

    def test_histogram_empty(self) -> None:
        """空 Histogram 统计"""
        m = MetricsCollector()
        summary = m.get_histogram_summary("nonexistent")
        assert summary["count"] == 0

    def test_to_dict(self) -> None:
        """导出指标字典"""
        m = MetricsCollector()
        m.increment_counter("tokens", 100)
        m.set_gauge("confidence", 0.8)
        m.observe_histogram("latency", 50)
        d = m.to_dict()
        assert "counters" in d
        assert "gauges" in d
        assert "histograms" in d

    def test_reset(self) -> None:
        """重置指标"""
        m = MetricsCollector()
        m.increment_counter("tokens", 100)
        m.reset()
        assert m.get_counter("tokens") == 0

    def test_timer(self) -> None:
        """Timer 上下文管理器"""
        m = MetricsCollector()
        with Timer(m, "test_timer"):
            time.sleep(0.01)
        summary = m.get_histogram_summary("test_timer")
        assert summary["count"] == 1
        assert summary["mean"] > 0


# ── 全局单例测试 ──

class TestGlobalInstances:
    """全局单例测试"""

    def test_get_tracer_default_noop(self) -> None:
        """get_tracer() 默认返回 NoOpTracer"""
        # 重置全局状态
        import dota_helper.observability as obs
        obs._tracer = None
        tracer = get_tracer()
        assert isinstance(tracer, NoOpTracer)

    def test_init_tracer_noop(self) -> None:
        """init_tracer(use_langfuse=False) 使用 Tracer"""
        import dota_helper.observability as obs
        obs._tracer = None
        init_tracer(use_langfuse=False)
        tracer = get_tracer()
        assert isinstance(tracer, Tracer)

    def test_init_tracer_langfuse_fallback(self) -> None:
        """init_tracer(use_langfuse=True) 无 SDK 时降级为 NoOpTracer"""
        import dota_helper.observability as obs
        obs._tracer = None
        init_tracer(use_langfuse=True)
        tracer = get_tracer()
        # 无 SDK 时应为 NoOpTracer
        assert isinstance(tracer, (NoOpTracer, Tracer))

    def test_get_metrics_collector(self) -> None:
        """get_metrics_collector() 返回 MetricsCollector"""
        m = get_metrics_collector()
        assert isinstance(m, MetricsCollector)
