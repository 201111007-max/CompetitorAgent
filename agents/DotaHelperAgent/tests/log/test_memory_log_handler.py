"""内存日志处理器测试

测试内存日志处理器相关功能：
- MemoryLogHandler 基本功能
- 日志缓存和检索
- 日志筛选（按级别、组件、会话）
- 日志订阅和推送
- 线程安全性
"""

import pytest
import logging
import json
import time
import threading
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock, call

# 添加项目根目录到路径
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from utils.memory_log_handler import MemoryLogHandler, get_memory_handler


class TestMemoryLogHandlerBasic:
    """内存日志处理器基本功能测试"""

    def test_handler_initialization(self):
        """测试处理器初始化"""
        handler = MemoryLogHandler(max_entries=100)
        assert handler.max_entries == 100
        assert handler._lock is not None
        handler.close()

    def test_handler_default_max_entries(self):
        """测试处理器默认最大条目数"""
        handler = MemoryLogHandler()
        assert handler.max_entries == 1000
        handler.close()

    def test_emit_stores_log(self):
        """测试emit方法存储日志"""
        handler = MemoryLogHandler(max_entries=10)

        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        record.created = time.time()

        handler.emit(record)
        handler.close()

        logs = handler.get_logs()
        assert len(logs) == 1
        assert logs[0]['message'] == 'test message'

    def test_emit_with_formatter(self):
        """测试emit方法使用格式化器"""
        handler = MemoryLogHandler(max_entries=10)
        formatter = logging.Formatter('%(name)s - %(message)s')
        handler.setFormatter(formatter)

        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='formatted message',
            args=(),
            exc_info=None
        )
        record.created = time.time()

        handler.emit(record)
        handler.close()

        logs = handler.get_logs()
        assert len(logs) == 1
        # 格式化器应该被使用
        assert 'test_logger' in logs[0].get('formatted', '')


class TestMemoryLogHandlerFiltering:
    """内存日志处理器筛选功能测试"""

    @pytest.fixture
    def populated_handler(self):
        """创建带有测试日志的处理器"""
        handler = MemoryLogHandler(max_entries=100)

        # 添加不同级别的日志
        for level, level_name in [(logging.DEBUG, 'DEBUG'),
                                  (logging.INFO, 'INFO'),
                                  (logging.WARNING, 'WARNING'),
                                  (logging.ERROR, 'ERROR')]:
            record = logging.LogRecord(
                name='test',
                level=level,
                pathname='test.py',
                lineno=1,
                msg=f'{level_name} message',
                args=(),
                exc_info=None
            )
            record.created = time.time()
            record.levelname = level_name
            handler.emit(record)

        # 添加不同组件的日志
        for component in ['web', 'agent', 'tool', 'cache']:
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=1,
                msg=f'{component} message',
                args=(),
                exc_info=None
            )
            record.created = time.time()
            record.component = component
            handler.emit(record)

        # 添加不同会话的日志
        for session_id in ['sess_001', 'sess_002', 'sess_003']:
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=1,
                msg=f'session {session_id} message',
                args=(),
                exc_info=None
            )
            record.created = time.time()
            record.session_id = session_id
            handler.emit(record)

        yield handler
        handler.close()

    def test_get_logs_all(self, populated_handler):
        """测试获取所有日志"""
        logs = populated_handler.get_logs()
        assert len(logs) > 0

    def test_get_logs_by_level(self, populated_handler):
        """测试按级别筛选日志"""
        logs = populated_handler.get_logs(level='INFO')
        for log in logs:
            assert log['level'] == 'INFO'

    def test_get_logs_by_component(self, populated_handler):
        """测试按组件筛选日志"""
        logs = populated_handler.get_logs(component='web')
        for log in logs:
            assert log.get('component') == 'web'

    def test_get_logs_by_session_id(self, populated_handler):
        """测试按会话ID筛选日志"""
        logs = populated_handler.get_logs(session_id='sess_001')
        for log in logs:
            assert log.get('session_id') == 'sess_001'

    def test_get_logs_with_limit(self, populated_handler):
        """测试限制返回日志数量"""
        logs = populated_handler.get_logs(limit=5)
        assert len(logs) <= 5

    def test_get_logs_combined_filters(self, populated_handler):
        """测试组合筛选条件"""
        logs = populated_handler.get_logs(
            level='INFO',
            component='web',
            session_id='sess_001',
            limit=10
        )
        for log in logs:
            assert log['level'] == 'INFO'
            assert log.get('component') == 'web'
            assert log.get('session_id') == 'sess_001'

    def test_get_logs_no_match(self, populated_handler):
        """测试没有匹配的日志"""
        logs = populated_handler.get_logs(level='CRITICAL')
        # 如果没有CRITICAL级别的日志，应该返回空列表
        assert isinstance(logs, list)


class TestMemoryLogHandlerLimits:
    """内存日志处理器限制测试"""

    def test_max_entries_limit(self):
        """测试最大条目数限制"""
        handler = MemoryLogHandler(max_entries=5)

        # 添加超过限制的日志
        for i in range(10):
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=i,
                msg=f'message {i}',
                args=(),
                exc_info=None
            )
            record.created = time.time()
            handler.emit(record)

        logs = handler.get_logs()
        assert len(logs) <= 5
        handler.close()

    def test_fifo_behavior(self):
        """测试FIFO行为（先进先出）"""
        handler = MemoryLogHandler(max_entries=3)

        # 添加3条日志
        for i in range(3):
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=i,
                msg=f'message {i}',
                args=(),
                exc_info=None
            )
            record.created = time.time()
            handler.emit(record)

        # 再添加一条，应该移除最早的一条
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=3,
            msg='message 3',
            args=(),
            exc_info=None
        )
        record.created = time.time()
        handler.emit(record)

        logs = handler.get_logs()
        assert len(logs) == 3
        # 最早的message 0应该被移除
        messages = [log['message'] for log in logs]
        assert 'message 0' not in messages
        assert 'message 3' in messages
        handler.close()


class TestMemoryLogHandlerClear:
    """内存日志处理器清空功能测试"""

    def test_clear_all_logs(self):
        """测试清空所有日志"""
        handler = MemoryLogHandler(max_entries=10)

        # 添加一些日志
        for i in range(5):
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=i,
                msg=f'message {i}',
                args=(),
                exc_info=None
            )
            record.created = time.time()
            handler.emit(record)

        # 验证日志已添加
        assert len(handler.get_logs()) == 5

        # 清空日志
        handler.clear()

        # 验证日志已清空
        assert len(handler.get_logs()) == 0
        handler.close()

    def test_clear_by_session_id(self):
        """测试按会话ID清空日志"""
        handler = MemoryLogHandler(max_entries=10)

        # 添加不同会话的日志
        for session_id in ['sess_001', 'sess_002']:
            for i in range(3):
                record = logging.LogRecord(
                    name='test',
                    level=logging.INFO,
                    pathname='test.py',
                    lineno=i,
                    msg=f'{session_id} message {i}',
                    args=(),
                    exc_info=None
                )
                record.created = time.time()
                record.session_id = session_id
                handler.emit(record)

        # 验证日志已添加
        assert len(handler.get_logs()) == 6

        # 清空特定会话的日志
        handler.clear(session_id='sess_001')

        # 验证只有sess_001的日志被清空
        logs = handler.get_logs()
        assert len(logs) == 3
        for log in logs:
            assert log.get('session_id') == 'sess_002'
        handler.close()


class TestMemoryLogHandlerThreading:
    """内存日志处理器线程安全测试"""

    def test_thread_safe_emit(self):
        """测试emit方法的线程安全性"""
        handler = MemoryLogHandler(max_entries=1000)
        errors = []

        def emit_logs(thread_id, count):
            try:
                for i in range(count):
                    record = logging.LogRecord(
                        name='test',
                        level=logging.INFO,
                        pathname='test.py',
                        lineno=i,
                        msg=f'thread {thread_id} message {i}',
                        args=(),
                        exc_info=None
                    )
                    record.created = time.time()
                    handler.emit(record)
            except Exception as e:
                errors.append(e)

        # 创建多个线程同时写入日志
        threads = []
        for i in range(5):
            t = threading.Thread(target=emit_logs, args=(i, 20))
            threads.append(t)
            t.start()

        # 等待所有线程完成
        for t in threads:
            t.join()

        # 验证没有错误
        assert len(errors) == 0

        # 验证所有日志都被记录
        logs = handler.get_logs()
        assert len(logs) == 100  # 5线程 * 20条
        handler.close()

    def test_thread_safe_get_logs(self):
        """测试get_logs方法的线程安全性"""
        handler = MemoryLogHandler(max_entries=100)

        # 先添加一些日志
        for i in range(50):
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=i,
                msg=f'message {i}',
                args=(),
                exc_info=None
            )
            record.created = time.time()
            handler.emit(record)

        results = []
        errors = []

        def get_logs_thread():
            try:
                logs = handler.get_logs()
                results.append(len(logs))
            except Exception as e:
                errors.append(e)

        # 创建多个线程同时读取日志
        threads = []
        for i in range(10):
            t = threading.Thread(target=get_logs_thread)
            threads.append(t)
            t.start()

        # 等待所有线程完成
        for t in threads:
            t.join()

        # 验证没有错误
        assert len(errors) == 0

        # 验证所有读取都成功
        assert len(results) == 10
        handler.close()


class TestMemoryLogHandlerSubscriber:
    """内存日志处理器订阅功能测试"""

    def test_subscribe_to_logs(self):
        """测试订阅日志功能"""
        handler = MemoryLogHandler(max_entries=10)

        received_logs = []

        def callback(log_data):
            received_logs.append(log_data)

        # 订阅日志
        handler.subscribe(callback)

        # 添加日志
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        record.created = time.time()
        handler.emit(record)

        # 等待异步处理
        time.sleep(0.1)

        # 验证回调被调用
        assert len(received_logs) == 1
        assert received_logs[0]['message'] == 'test message'
        handler.close()

    def test_unsubscribe_from_logs(self):
        """测试取消订阅日志功能"""
        handler = MemoryLogHandler(max_entries=10)

        received_logs = []

        def callback(log_data):
            received_logs.append(log_data)

        # 订阅日志
        handler.subscribe(callback)

        # 取消订阅
        handler.unsubscribe(callback)

        # 添加日志
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        record.created = time.time()
        handler.emit(record)

        # 等待异步处理
        time.sleep(0.1)

        # 验证回调没有被调用
        assert len(received_logs) == 0
        handler.close()


class TestGetMemoryHandler:
    """获取内存处理器单例测试"""

    def test_singleton_behavior(self):
        """测试单例行为"""
        handler1 = get_memory_handler(max_entries=100)
        handler2 = get_memory_handler(max_entries=200)

        # 应该是同一个实例
        assert handler1 is handler2

        # 使用第一次创建的参数
        assert handler1.max_entries == 100

        handler1.close()

    def test_get_memory_handler_returns_handler(self):
        """测试返回正确的处理器类型"""
        handler = get_memory_handler()
        assert isinstance(handler, MemoryLogHandler)
        handler.close()


class TestMemoryLogHandlerSessionLogs:
    """内存日志处理器会话日志测试"""

    def test_get_session_logs(self):
        """测试获取特定会话的日志"""
        handler = MemoryLogHandler(max_entries=10)

        # 添加不同会话的日志
        for session_id in ['sess_001', 'sess_002']:
            for i in range(3):
                record = logging.LogRecord(
                    name='test',
                    level=logging.INFO,
                    pathname='test.py',
                    lineno=i,
                    msg=f'{session_id} message {i}',
                    args=(),
                    exc_info=None
                )
                record.created = time.time()
                record.session_id = session_id
                handler.emit(record)

        # 获取特定会话的日志
        session_logs = handler.get_session_logs('sess_001')
        assert len(session_logs) == 3
        for log in session_logs:
            assert log.get('session_id') == 'sess_001'

        handler.close()

    def test_get_session_logs_nonexistent(self):
        """测试获取不存在会话的日志"""
        handler = MemoryLogHandler(max_entries=10)

        # 添加一些日志
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        record.created = time.time()
        record.session_id = 'sess_001'
        handler.emit(record)

        # 获取不存在会话的日志
        session_logs = handler.get_session_logs('nonexistent')
        assert len(session_logs) == 0

        handler.close()
