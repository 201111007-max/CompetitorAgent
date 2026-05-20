"""Langfuse 适配器单元测试"""

import pytest


class TestNoOpClasses:
    """测试空操作类"""
    
    def test_noop_observation_span_returns_noop(self):
        from utils.langfuse_adapter import NoOpObservation
        
        obs = NoOpObservation()
        span = obs.span(name="test")
        
        assert span is not None
        assert hasattr(span, 'update')
        assert hasattr(span, 'score')
        assert hasattr(span, 'end')
    
    def test_noop_observation_context_manager(self):
        from utils.langfuse_adapter import NoOpObservation
        
        with NoOpObservation() as obs:
            assert obs is not None
            obs.update(metadata={"test": "value"})
            obs.score(name="test", value=0.9)
    
    def test_noop_observation_chain(self):
        from utils.langfuse_adapter import NoOpObservation
        
        obs = NoOpObservation()
        result = obs.update(output={"result": "success"}).score(name="quality", value=0.8).end()
        assert result is obs


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
    
    def test_observation_returns_noop_when_disabled(self):
        from utils.langfuse_adapter import LangfuseClient, NoOpObservation
        
        client = LangfuseClient.get_instance()
        obs = client.observation(name="test_obs")
        
        assert isinstance(obs, NoOpObservation)


class TestIsLangfuseAvailable:
    """测试 SDK 可用性检查"""
    
    def test_returns_boolean(self):
        from utils.langfuse_adapter import is_langfuse_available
        
        result = is_langfuse_available()
        assert isinstance(result, bool)


class TestBackwardCompatibility:
    """测试向后兼容性"""
    
    def test_noop_trace_alias(self):
        from utils.langfuse_adapter import NoOpTrace, NoOpObservation
        
        assert NoOpTrace is NoOpObservation
    
    def test_noop_span_alias(self):
        from utils.langfuse_adapter import NoOpSpan, NoOpObservation
        
        assert NoOpSpan is NoOpObservation
    
    def test_noop_event_alias(self):
        from utils.langfuse_adapter import NoOpEvent, NoOpObservation
        
        assert NoOpEvent is NoOpObservation
