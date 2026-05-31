"""测试 Trace 系统优化

验证以下修改：
1. Trace 索引功能
2. TraceContext to_dict/from_dict 方法
3. 日志格式统一
4. 错误索引功能
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.memory_log_handler import MemoryLogHandler
from utils.trace_context import TraceContext, set_current_trace
from utils.log_config import TraceJSONFormatter


def test_trace_index():
    """测试 trace 索引功能"""
    print("\n=== 测试 Trace 索引功能 ===")
    
    handler = MemoryLogHandler(max_entries=100)
    
    logger = logging.getLogger("test_trace_index")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    
    for i in range(10):
        record = logger.makeRecord(
            "test_trace_index", logging.INFO, "test.py", i,
            f"Test message {i}", (), None
        )
        record.trace_id = f"trace_{i % 3}"
        handler.handle(record)
    
    trace_0_logs = handler.get_trace_logs("trace_0")
    print(f"trace_0 日志数量: {len(trace_0_logs)}")
    
    trace_1_logs = handler.get_trace_logs("trace_1")
    print(f"trace_1 日志数量: {len(trace_1_logs)}")
    
    trace_2_logs = handler.get_trace_logs("trace_2")
    print(f"trace_2 日志数量: {len(trace_2_logs)}")
    
    assert len(trace_0_logs) == 4, "trace_0 应该有 4 条日志"
    assert len(trace_1_logs) == 3, "trace_1 应该有 3 条日志"
    assert len(trace_2_logs) == 3, "trace_2 应该有 3 条日志"
    
    print("✓ Trace 索引功能测试通过")


def test_error_index():
    """测试错误索引功能"""
    print("\n=== 测试错误索引功能 ===")
    
    handler = MemoryLogHandler(max_entries=100)
    
    logger = logging.getLogger("test_error_index")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    
    for i in range(10):
        logger.info(f"Info message {i}")
    
    for i in range(3):
        logger.error(f"Error message {i}")
    
    logger.warning("Warning message")
    
    errors = handler.get_errors(limit=10)
    print(f"错误日志数量: {len(errors)}")
    
    assert len(errors) == 3, "应该有 3 条错误日志"
    
    for error in errors:
        assert error['level'] == 'ERROR', "应该是 ERROR 级别"
    
    print("✓ 错误索引功能测试通过")


def test_trace_context_to_dict():
    """测试 TraceContext to_dict/from_dict 方法"""
    print("\n=== 测试 TraceContext 序列化 ===")
    
    trace_ctx = TraceContext(
        trace_id="test_trace_123",
        span_id="span_456",
        session_id="session_789",
        operation="test_operation",
        metadata={"key": "value"}
    )
    
    trace_dict = trace_ctx.to_dict()
    print(f"Trace 字典: {trace_dict}")
    
    assert trace_dict['trace_id'] == "test_trace_123", "trace_id 应该正确"
    assert trace_dict['span_id'] == "span_456", "span_id 应该正确"
    assert trace_dict['session_id'] == "session_789", "session_id 应该正确"
    assert trace_dict['operation'] == "test_operation", "operation 应该正确"
    assert trace_dict['metadata']['key'] == "value", "metadata 应该正确"
    
    restored_ctx = TraceContext.from_dict(trace_dict)
    print(f"恢复的 TraceContext: {restored_ctx}")
    
    assert restored_ctx.trace_id == "test_trace_123", "恢复的 trace_id 应该正确"
    assert restored_ctx.span_id == "span_456", "恢复的 span_id 应该正确"
    assert restored_ctx.session_id == "session_789", "恢复的 session_id 应该正确"
    assert restored_ctx.operation == "test_operation", "恢复的 operation 应该正确"
    assert restored_ctx.metadata['key'] == "value", "恢复的 metadata 应该正确"
    
    print("✓ TraceContext 序列化测试通过")


def test_log_format():
    """测试日志格式统一性"""
    print("\n=== 测试日志格式统一性 ===")
    
    handler = MemoryLogHandler(max_entries=100)
    formatter = TraceJSONFormatter()
    handler.setFormatter(formatter)
    
    logger = logging.getLogger("test_log_format")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    
    trace_ctx = TraceContext(
        trace_id="test_trace_format",
        span_id="span_format",
        session_id="session_format",
        operation="format_test"
    )
    set_current_trace(trace_ctx)
    
    logger.info("测试消息", extra={"key": "value"})
    
    logs = handler.get_logs(limit=1)
    log = logs[0]
    
    print(f"日志内容: {log}")
    
    assert isinstance(log['message'], str), "message 应该是字符串"
    assert log['trace'] is not None, "trace 应该存在"
    assert isinstance(log['trace'], dict), "trace 应该是字典"
    assert log['trace']['trace_id'] == "test_trace_format", "trace_id 应该正确"
    
    set_current_trace(None)
    
    print("✓ 日志格式统一性测试通过")


def test_clear_with_index():
    """测试清空日志时索引也被清空"""
    print("\n=== 测试清空日志和索引 ===")
    
    handler = MemoryLogHandler(max_entries=100)
    
    logger = logging.getLogger("test_clear")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    
    for i in range(10):
        record = logger.makeRecord(
            "test_clear", logging.INFO, "test.py", i,
            f"Test message {i}", (), None
        )
        record.trace_id = f"trace_{i % 3}"
        handler.handle(record)
    
    handler.clear()
    
    assert len(handler._logs) == 0, "日志应该被清空"
    assert len(handler._trace_index) == 0, "trace 索引应该被清空"
    assert len(handler._error_index) == 0, "错误索引应该被清空"
    assert handler._log_counter == 0, "日志计数器应该重置"
    
    print("✓ 清空日志和索引测试通过")


def main():
    """运行所有测试"""
    print("\n" + "="*50)
    print("开始测试 Trace 系统优化")
    print("="*50)
    
    try:
        test_trace_index()
        test_error_index()
        test_trace_context_to_dict()
        test_log_format()
        test_clear_with_index()
        
        print("\n" + "="*50)
        print("✓ 所有测试通过！")
        print("="*50)
        
        return True
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)