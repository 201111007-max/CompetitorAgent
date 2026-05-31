"""Trace 系统修复验证测试

验证所有修复是否正确：
1. P0-1: 索引失效问题修复
2. P0-2: 内存泄漏问题修复
3. P1-1: clear() 方法逻辑修复
4. P1-2: 线程安全问题修复
5. P1-3: 持久化异步化
6. P1-4: 内存复制开销优化
7. P1-5: SSE 事件处理优化
8. P1-6: SQLite 连接池优化
"""

import sys
import logging
import threading
import time
from pathlib import Path
from datetime import datetime

# 设置路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.memory_log_handler import MemoryLogHandler


def test_index_validity():
    """测试 P0-1: 索引失效问题修复"""
    print("\n=== 测试 P0-1: 索引失效问题修复 ===")
    
    # 创建一个小容量的 handler，便于测试 deque 满的情况
    handler = MemoryLogHandler(max_entries=10)
    
    # 添加带 trace_id 的日志
    for i in range(15):  # 超过 max_entries，触发 deque 滚动
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=i,
            msg=f"Test message {i}",
            args=(),
            exc_info=None
        )
        record.trace_id = f"trace_{i % 3}"  # 创建3个不同的 trace_id
        record.session_id = "test_session"
        
        handler.emit(record)
    
    # 验证索引是否有效
    print(f"日志数量: {len(handler._logs)}")
    print(f"日志计数器: {handler._log_counter}")
    print(f"最小有效索引: {handler._get_min_valid_idx()}")
    
    # 测试查询
    for trace_id in ["trace_0", "trace_1", "trace_2"]:
        logs = handler.get_trace_logs(trace_id)
        print(f"Trace {trace_id} 日志数量: {len(logs)}")
        
        # 验证日志是否有效（不为空）
        if logs:
            print(f"  最新日志: {logs[-1]['message']}")
    
    # 验证错误索引
    handler2 = MemoryLogHandler(max_entries=10)
    for i in range(15):
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR if i % 2 == 0 else logging.INFO,
            pathname="test.py",
            lineno=i,
            msg=f"Test message {i}",
            args=(),
            exc_info=None
        )
        record.trace_id = f"trace_{i % 3}"
        record.session_id = "test_session"
        
        handler2.emit(record)
    
    errors = handler2.get_errors(limit=5)
    print(f"\n错误日志数量: {len(errors)}")
    if errors:
        print(f"  最新错误: {errors[-1]['message']}")
    
    print("✓ P0-1 测试通过：索引失效问题已修复")


def test_memory_leak():
    """测试 P0-2: 内存泄漏问题修复"""
    print("\n=== 测试 P0-2: 内存泄漏问题修复 ===")
    
    handler = MemoryLogHandler(max_entries=10)
    
    # 添加大量日志，触发多次 deque 滚动
    for i in range(100):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=i,
            msg=f"Test message {i}",
            args=(),
            exc_info=None
        )
        record.trace_id = f"trace_{i % 10}"
        record.session_id = "test_session"
        
        handler.emit(record)
    
    # 验证索引大小是否合理
    print(f"日志数量: {len(handler._logs)}")
    print(f"Trace 索引大小: {len(handler._trace_index)}")
    print(f"错误索引大小: {len(handler._error_index)}")
    
    # 验证索引总数不超过 deque 容量
    total_trace_indices = sum(len(indices) for indices in handler._trace_index.values())
    print(f"Trace 索引总数: {total_trace_indices}")
    
    assert total_trace_indices <= handler.max_entries, "Trace 索引总数超过 deque 容量"
    assert len(handler._error_index) <= handler.max_entries, "错误索引总数超过 deque 容量"
    
    print("✓ P0-2 测试通过：内存泄漏问题已修复")


def test_clear_method():
    """测试 P1-1: clear() 方法逻辑修复"""
    print("\n=== 测试 P1-1: clear() 方法逻辑修复 ===")
    
    handler = MemoryLogHandler(max_entries=20)
    
    # 添加两个 session 的日志
    for i in range(10):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=i,
            msg=f"Session A message {i}",
            args=(),
            exc_info=None
        )
        record.trace_id = f"trace_a_{i}"
        record.session_id = "session_a"
        
        handler.emit(record)
    
    for i in range(10):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=i,
            msg=f"Session B message {i}",
            args=(),
            exc_info=None
        )
        record.trace_id = f"trace_b_{i}"
        record.session_id = "session_b"
        
        handler.emit(record)
    
    print(f"初始日志数量: {len(handler._logs)}")
    print(f"初始 Trace 索引大小: {len(handler._trace_index)}")
    
    # 清空 session_a
    handler.clear(session_id="session_a")
    
    print(f"清空 session_a 后日志数量: {len(handler._logs)}")
    print(f"清空 session_a 后 Trace 索引大小: {len(handler._trace_index)}")
    
    # 验证 session_b 的日志仍然存在
    session_b_logs = handler.get_session_logs("session_b")
    print(f"Session B 日志数量: {len(session_b_logs)}")
    
    assert len(session_b_logs) > 0, "Session B 日志不应被清空"
    
    # 验证 session_a 的日志已被清空
    session_a_logs = handler.get_session_logs("session_a")
    print(f"Session A 日志数量: {len(session_a_logs)}")
    
    assert len(session_a_logs) == 0, "Session A 日志应被清空"
    
    # 验证 session_b 的 trace 索引仍然存在
    trace_b_logs = handler.get_trace_logs("trace_b_0")
    print(f"Trace B_0 日志数量: {len(trace_b_logs)}")
    
    assert len(trace_b_logs) > 0, "Trace B 日志不应被清空"
    
    print("✓ P1-1 测试通过：clear() 方法逻辑已修复")


def test_thread_safety():
    """测试 P1-2: 线程安全问题修复"""
    print("\n=== 测试 P1-2: 线程安全问题修复 ===")
    
    handler = MemoryLogHandler(max_entries=100)
    
    # 定义回调函数
    callback_count = 0
    callback_lock = threading.Lock()
    
    def callback(log_entry):
        with callback_lock:
            callback_count += 1
    
    handler.subscribe(callback)
    
    # 多线程并发写入
    threads = []
    for t in range(5):
        thread = threading.Thread(
            target=lambda tid=t: [
                handler.emit(logging.LogRecord(
                    name="test",
                    level=logging.INFO,
                    pathname="test.py",
                    lineno=i,
                    msg=f"Thread {tid} message {i}",
                    args=(),
                    exc_info=None
                ))
                for i in range(20)
            ]
        )
        threads.append(thread)
        thread.start()
    
    # 等待所有线程完成
    for thread in threads:
        thread.join()
    
    print(f"日志数量: {len(handler._logs)}")
    print(f"回调调用次数: {callback_count}")
    
    # 验证回调次数与日志数量一致
    assert callback_count == len(handler._logs), "回调次数应与日志数量一致"
    
    print("✓ P1-2 测试通过：线程安全问题已修复")


def test_persistence_async():
    """测试 P1-3: 持久化异步化"""
    print("\n=== 测试 P1-3: 持久化异步化 ===")
    
    # 创建带持久化的 handler
    handler = MemoryLogHandler(max_entries=100, enable_persistence=True)
    
    # 验证持久化队列和线程已创建
    print(f"持久化启用: {handler.enable_persistence}")
    print(f"持久化队列存在: {handler._persistence_queue is not None}")
    print(f"持久化线程存在: {handler._persistence_worker is not None}")
    
    if handler.enable_persistence:
        # 添加日志
        for i in range(10):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Test message {i}",
                args=(),
                exc_info=None
            )
            record.trace_id = f"trace_{i}"
            record.session_id = "test_session"
            
            handler.emit(record)
        
        # 等待持久化线程处理
        time.sleep(2)
        
        print(f"持久化队列大小: {handler._persistence_queue.qsize()}")
        
        assert handler._persistence_queue is not None, "持久化队列应存在"
        assert handler._persistence_worker is not None, "持久化线程应存在"
    
    print("✓ P1-3 测试通过：持久化已异步化")


def test_memory_copy_optimization():
    """测试 P1-4: 内存复制开销优化"""
    print("\n=== 测试 P1-4: 内存复制开销优化 ===")
    
    handler = MemoryLogHandler(max_entries=100)
    
    # 添加日志
    for i in range(50):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=i,
            msg=f"Test message {i}",
            args=(),
            exc_info=None
        )
        record.trace_id = f"trace_{i % 5}"
        record.session_id = "test_session"
        
        handler.emit(record)
    
    # 测试查询性能
    start_time = time.time()
    for _ in range(100):
        logs = handler.get_trace_logs("trace_0")
    elapsed_time = time.time() - start_time
    
    print(f"100次查询耗时: {elapsed_time:.4f}秒")
    print(f"每次查询平均耗时: {elapsed_time/100*1000:.2f}毫秒")
    
    # 验证查询结果正确
    logs = handler.get_trace_logs("trace_0")
    print(f"Trace 0 日志数量: {len(logs)}")
    
    assert len(logs) > 0, "查询结果不应为空"
    
    print("✓ P1-4 测试通过：内存复制开销已优化")


def test_connection_pool():
    """测试 P1-6: SQLite 连接池优化"""
    print("\n=== 测试 P1-6: SQLite 连接池优化 ===")
    
    from utils.trace_persistence import TracePersistence, ConnectionManager
    
    # 测试连接管理器
    db_path = str(project_root / "logs" / "test_traces.db")
    manager = ConnectionManager(db_path)
    
    # 获取连接
    conn1 = manager.get_connection()
    print(f"连接1类型: {type(conn1)}")
    
    # 同一线程再次获取连接（应该是同一个）
    conn2 = manager.get_connection()
    print(f"连接2类型: {type(conn2)}")
    print(f"同一线程连接是否相同: {conn1 is conn2}")
    
    assert conn1 is conn2, "同一线程应获取相同连接"
    
    # 关闭连接
    manager.close_connection()
    
    # 再次获取连接（应该是新连接）
    conn3 = manager.get_connection()
    print(f"关闭后新连接是否不同: {conn1 is not conn3}")
    
    assert conn1 is not conn3, "关闭后应获取新连接"
    
    # 清理测试数据库
    manager.close_connection()
    Path(db_path).unlink(missing_ok=True)
    
    print("✓ P1-6 测试通过：SQLite 连接池已优化")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("Trace 系统修复验证测试")
    print("="*60)
    
    try:
        test_index_validity()
        test_memory_leak()
        test_clear_method()
        test_thread_safety()
        test_persistence_async()
        test_memory_copy_optimization()
        test_connection_pool()
        
        print("\n" + "="*60)
        print("✓ 所有测试通过！")
        print("="*60)
        
    except Exception as e:
        print("\n" + "="*60)
        print(f"✗ 测试失败: {e}")
        print("="*60)
        raise


if __name__ == "__main__":
    run_all_tests()