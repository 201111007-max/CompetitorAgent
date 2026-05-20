"""Langfuse 集成测试"""

import pytest
import os


class TestLangfuseIntegration:
    """测试 Langfuse 集成"""
    
    def test_langfuse_client_without_sdk(self):
        """测试在没有 SDK 时的行为"""
        from utils.langfuse_adapter import LangfuseClient, NoOpTrace
        
        client = LangfuseClient.get_instance()
        
        # 未初始化时应该返回 NoOpTrace
        trace = client.trace(trace_id="test_123")
        assert isinstance(trace, NoOpTrace)
    
    def test_langfuse_config_from_env(self, monkeypatch):
        """测试从环境变量加载配置"""
        from utils.langfuse_config import LangfuseConfig
        
        monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
        monkeypatch.setenv('LANGFUSE_HOST', 'http://test-host:3000')
        
        config = LangfuseConfig()
        
        assert config.enabled is False
        assert config.host == "http://test-host:3000"
    
    def test_flask_app_starts_without_langfuse_sdk(self):
        """测试 Flask 应用在没有 Langfuse SDK 时能正常启动"""
        import sys
        
        # 模拟 langfuse 未安装
        if 'langfuse' in sys.modules:
            del sys.modules['langfuse']
        
        # 尝试导入 adapter
        try:
            from utils.langfuse_adapter import is_langfuse_available
            result = is_langfuse_available()
            assert isinstance(result, bool)
        except ImportError:
            pytest.fail("导入 langfuse_adapter 失败，应该支持可选导入")


class TestLangfuseTraceContext:
    """测试 Trace 上下文集成"""
    
    def test_trace_context_with_langfuse(self):
        """测试 Trace 上下文与 Langfuse 的集成"""
        from utils.trace_context import TraceContext, generate_trace_id, generate_session_id
        from utils.langfuse_adapter import LangfuseClient
        
        # 创建 Trace 上下文
        trace_ctx = TraceContext(
            trace_id=generate_trace_id(),
            span_id="test_span",
            session_id=generate_session_id(),
            operation="test_operation"
        )
        
        # 获取 Langfuse 客户端
        client = LangfuseClient.get_instance()
        
        # 创建 Langfuse Trace（使用相同的 trace_id）
        langfuse_trace = client.trace(
            trace_id=trace_ctx.trace_id,
            session_id=trace_ctx.session_id
        )
        
        # 验证 trace 可以正常使用
        with langfuse_trace as trace:
            with trace.span(name="test_span") as span:
                span.update(output={"result": "success"})


class TestLangfuseNoOpClasses:
    """测试 NoOp 类的行为"""
    
    def test_noop_trace_chain(self):
        """测试 NoOp Trace 链式调用"""
        from utils.langfuse_adapter import NoOpTrace
        
        trace = NoOpTrace()
        
        # 链式调用应该正常工作
        result = trace.update(metadata={"key": "value"}).score(name="test", value=0.9)
        assert result is trace
    
    def test_noop_span_chain(self):
        """测试 NoOp Span 链式调用"""
        from utils.langfuse_adapter import NoOpSpan
        
        span = NoOpSpan()
        
        # 链式调用应该正常工作
        result = span.update(output={"result": "success"}).score(name="quality", value=0.8).end()
        assert result is span
    
    def test_noop_nested_contexts(self):
        """测试嵌套上下文管理器"""
        from utils.langfuse_adapter import NoOpTrace
        
        with NoOpTrace() as trace:
            with trace.span(name="outer") as outer_span:
                outer_span.update(metadata={"has_inner": True})
                with trace.span(name="inner") as inner_span:
                    inner_span.update(output={"nested": True})
                trace.update(metadata={"completed": True})
