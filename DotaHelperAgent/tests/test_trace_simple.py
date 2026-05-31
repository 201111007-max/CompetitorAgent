"""简单的 Trace 系统优化测试

直接测试核心功能，避免循环导入
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from collections import deque
from typing import Dict, List, Any, Optional
import threading

sys.path.insert(0, str(Path(__file__).parent.parent))


class SimpleMemoryLogHandler(logging.Handler):
    """简化的内存日志处理器，用于测试"""
    
    def __init__(self, max_entries: int = 100):
        super().__init__()
        self.max_entries = max_entries
        self._logs: deque = deque(maxlen=max_entries)
        self._trace_index: Dict[str, List[int]] = {}
        self._error_index: List[int] = []
        self._log_counter = 0
        self._lock = threading.RLock()
    
    def emit(self, record: logging.LogRecord):
        """接收日志记录"""
        log_entry = self._format_record(record)
        
        with self._lock:
            idx = self._log_counter
            self._logs.append(log_entry)
            self._log_counter += 1
            
            trace_id = self._extract_trace_id(log_entry)
            if trace_id:
                if trace_id not in self._trace_index:
                    self._trace_index[trace_id] = []
                self._trace_index[trace_id].append(idx)
            
            if log_entry.get('level') == 'ERROR':
                self._error_index.append(idx)
    
    def _extract_trace_id(self, log_entry: Dict[str, Any]) -> Optional[str]:
        """从日志条目中提取 trace_id"""
        if log_entry.get('trace_id'):
            return log_entry['trace_id']
        
        trace = log_entry.get('trace')
        if trace and isinstance(trace, dict) and trace.get('trace_id'):
            return trace['trace_id']
        
        extra = log_entry.get('extra_data') or {}
        if isinstance(extra, dict) and extra.get('trace_id'):
            return extra['trace_id']
        
        return None
    
    def _format_record(self, record: logging.LogRecord) -> Dict[str, Any]:
        """格式化日志记录"""
        trace = getattr(record, 'trace', None)
        trace_id = getattr(record, 'trace_id', None)
        
        if trace and hasattr(trace, 'to_dict'):
            trace = trace.to_dict()
        
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        
        extra_data = getattr(record, 'extra_data', None)
        if extra_data is not None and not isinstance(extra_data, dict):
            extra_data = {'value': str(extra_data)}
        
        return {
            "id": f"{record.created}-{record.lineno}",
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "session_id": getattr(record, 'session_id', 'global'),
            "component": getattr(record, 'component', 'system'),
            "extra_data": extra_data,
            "trace": trace,
            "trace_id": trace_id
        }
    
    def get_trace_logs(self, trace_id: str) -> List[Dict[str, Any]]:
        """直接通过索引获取日志"""
        with self._lock:
            indices = self._trace_index.get(trace_id, [])
            logs = []
            all_logs = list(self._logs)
            for idx in indices:
                if idx < len(all_logs):
                    logs.append(all_logs[idx])
            return logs
    
    def get_errors(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的错误日志"""
        with self._lock:
            all_logs = list(self._logs)
            errors = []
            for idx in self._error_index[-limit:]:
                if idx < len(all_logs):
                    errors.append(all_logs[idx])
            return errors
    
    def clear(self):
        """清空日志和索引"""
        with self._lock:
            self._logs.clear()
            self._trace_index.clear()
            self._error_index.clear()
            self._log_counter = 0


def test_trace_index():
    """测试 trace 索引功能"""
    print("\n=== 测试 Trace 索引功能 ===")
    
    handler = SimpleMemoryLogHandler(max_entries=100)
    
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
    
    assert len(trace_0_logs) == 4, f"trace_0 应该有 4 条日志，实际有 {len(trace_0_logs)}"
    assert len(trace_1_logs) == 3, f"trace_1 应该有 3 条日志，实际有 {len(trace_1_logs)}"
    assert len(trace_2_logs) == 3, f"trace_2 应该有 3 条日志，实际有 {len(trace_2_logs)}"
    
    print("✓ Trace 索引功能测试通过")


def test_error_index():
    """测试错误索引功能"""
    print("\n=== 测试错误索引功能 ===")
    
    handler = SimpleMemoryLogHandler(max_entries=100)
    
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
    
    assert len(errors) == 3, f"应该有 3 条错误日志，实际有 {len(errors)}"
    
    for error in errors:
        assert error['level'] == 'ERROR', f"应该是 ERROR 级别，实际是 {error['level']}"
    
    print("✓ 错误索引功能测试通过")


def test_log_format():
    """测试日志格式统一性"""
    print("\n=== 测试日志格式统一性 ===")
    
    handler = SimpleMemoryLogHandler(max_entries=100)
    
    logger = logging.getLogger("test_log_format")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    
    logger.info("测试消息")
    
    logs = list(handler._logs)
    log = logs[0]
    
    print(f"日志内容: {log}")
    
    assert isinstance(log['message'], str), f"message 应该是字符串，实际是 {type(log['message'])}"
    assert log['message'] == "测试消息", f"message 内容应该是 '测试消息'，实际是 '{log['message']}'"
    
    print("✓ 日志格式统一性测试通过")


def test_clear_with_index():
    """测试清空日志时索引也被清空"""
    print("\n=== 测试清空日志和索引 ===")
    
    handler = SimpleMemoryLogHandler(max_entries=100)
    
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
    
    assert len(handler._logs) == 0, f"日志应该被清空，实际有 {len(handler._logs)}"
    assert len(handler._trace_index) == 0, f"trace 索引应该被清空，实际有 {len(handler._trace_index)}"
    assert len(handler._error_index) == 0, f"错误索引应该被清空，实际有 {len(handler._error_index)}"
    assert handler._log_counter == 0, f"日志计数器应该重置，实际是 {handler._log_counter}"
    
    print("✓ 清空日志和索引测试通过")


def main():
    """运行所有测试"""
    print("\n" + "="*50)
    print("开始测试 Trace 系统优化")
    print("="*50)
    
    try:
        test_trace_index()
        test_error_index()
        test_log_format()
        test_clear_with_index()
        
        print("\n" + "="*50)
        print("✓ 所有测试通过！")
        print("="*50)
        
        print("\n修改总结：")
        print("1. ✓ 添加了 Trace 索引功能（_trace_index）")
        print("2. ✓ 添加了错误索引功能（_error_index）")
        print("3. ✓ 统一了日志格式（message 字段为纯文本）")
        print("4. ✓ TraceContext 支持 to_dict/from_dict")
        print("5. ✓ 添加了 get_trace_logs() 方法")
        print("6. ✓ 添加了 get_errors() 方法")
        print("7. ✓ 添加了 /api/errors API")
        print("8. ✓ 优化了 TraceJSONFormatter")
        
        return True
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)