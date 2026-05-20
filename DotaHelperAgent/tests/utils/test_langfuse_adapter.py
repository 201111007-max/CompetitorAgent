"""Langfuse 适配器单元测试"""

import pytest


class TestNoOpClasses:
    """测试空操作类"""
    
    def test_noop_trace_span_returns_noop_span(self):
        from utils.langfuse_adapter import NoOpTrace
        
        trace = NoOpTrace()
        span = trace.span(name="test")
        
        assert span is not None
        assert hasattr(span, 'update')
        assert hasattr(span, 'event')
        assert hasattr(span, 'score')
    
    def test_noop_trace_event_returns_noop_event(self):
        from utils.langfuse_adapter import NoOpTrace
        
        trace = NoOpTrace()
        event = trace.event(name="test")
        
        assert event is not None
        assert hasattr(event, 'update')
    
    def test_noop_trace_context_manager(self):
        from utils.langfuse_adapter import NoOpTrace
        
        with NoOpTrace() as trace:
            assert trace is not None
            trace.update(metadata={"test": "value"})
            trace.score(name="test", value=0.9)
    
    def test_noop_span_context_manager(self):
        from utils.langfuse_adapter import NoOpSpan
        
        with NoOpSpan() as span:
            assert span is not None
            span.update(output={"result": "success"})
            span.score(name="quality", value=0.8)
    
    def test_noop_event_context_manager(self):
        from utils.langfuse_adapter import NoOpEvent
        
        with NoOpEvent() as event:
            assert event is not None
            event.update(metadata={"key": "value"})


class TestLangfuseClient:
    """测试 Langfuse 客户端"""
    
    def test_singleton_pattern(self):
        from utils.langfuse_adapter import LangfuseClient
        
        client1 = LangfuseClient.get_instance()
        client2 = LangfuseClient.get_instance()
        
        assert client1 is client2
    
    def test_disabled_when_no_sdk(self):
        from utils.langfuse_adapter import LangfuseClient
        
        client = LangfuseClient.get_instance()
        assert client.enabled is False
    
    def test_trace_returns_noop_when_disabled(self):
        from utils.langfuse_adapter import LangfuseClient, NoOpTrace
        
        client = LangfuseClient.get_instance()
        trace = client.trace(trace_id="test_123")
        
        assert isinstance(trace, NoOpTrace)


class TestIsLangfuseAvailable:
    """测试 SDK 可用性检查"""
    
    def test_returns_boolean(self):
        from utils.langfuse_adapter import is_langfuse_available
        
        result = is_langfuse_available()
        assert isinstance(result, bool)
