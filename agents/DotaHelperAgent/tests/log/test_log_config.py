"""日志配置模块测试

测试日志配置相关功能：
- setup_logging 函数
- setup_logging_with_memory 函数
- get_logger 函数
- JSONFormatter 格式化器
- SessionFilter 过滤器
- 日志文件结构生成
"""

import pytest
import logging
import json
import tempfile
import shutil
import time
import threading
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from utils.log_config import (
    setup_logging,
    setup_logging_with_memory,
    get_logger,
    JSONFormatter,
    SessionFilter,
    DailyTimedRotatingHandler,
    DailyPartitionRotatingHandler,
    LOG_DIR,
    LOG_FORMAT,
    DAILY_PART_MAX_BYTES,
    get_latest_log_files,
    get_log_files_by_date
)


class TestSessionFilter:
    """会话过滤器测试"""

    def test_session_filter_adds_session_id(self):
        """测试过滤器添加session_id属性"""
        filter_obj = SessionFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )

        result = filter_obj.filter(record)
        assert result is True
        assert hasattr(record, 'session_id')
        assert record.session_id == 'global'

    def test_session_filter_preserves_existing_session_id(self):
        """测试过滤器保留已存在的session_id"""
        filter_obj = SessionFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )
        record.session_id = 'custom_session'

        result = filter_obj.filter(record)
        assert result is True
        assert record.session_id == 'custom_session'

    def test_session_filter_adds_component(self):
        """测试过滤器添加component属性"""
        filter_obj = SessionFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None
        )

        filter_obj.filter(record)
        assert hasattr(record, 'component')
        assert record.component == 'system'


class TestJSONFormatter:
    """JSON格式化器测试"""

    def test_json_formatter_basic(self):
        """测试JSON格式化器基本功能"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=10,
            msg='test message',
            args=(),
            exc_info=None
        )
        record.created = time.time()

        output = formatter.format(record)
        data = json.loads(output)

        assert data['level'] == 'INFO'
        assert data['logger'] == 'test_logger'
        assert data['message'] == 'test message'
        assert data['module'] == 'test'
        assert data['line'] == 10
        assert 'timestamp' in data

    def test_json_formatter_with_session(self):
        """测试JSON格式化器带session信息"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test',
            args=(),
            exc_info=None
        )
        record.created = time.time()
        record.session_id = 'test_session_001'
        record.component = 'web'

        output = formatter.format(record)
        data = json.loads(output)

        assert data['session_id'] == 'test_session_001'
        assert data['component'] == 'web'

    def test_json_formatter_with_extra_data(self):
        """测试JSON格式化器带额外数据"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='test',
            args=(),
            exc_info=None
        )
        record.created = time.time()
        record.extra_data = {'key1': 'value1', 'key2': 123}

        output = formatter.format(record)
        data = json.loads(output)

        assert 'extra' in data
        assert data['extra']['key1'] == 'value1'
        assert data['extra']['key2'] == 123


class TestGetLogger:
    """获取日志记录器测试"""

    def test_get_logger_returns_logger(self):
        """测试获取日志记录器返回正确的logger对象"""
        logger = get_logger('test_name', component='web')
        assert isinstance(logger, logging.Logger)
        assert logger.name == 'test_name'

    def test_get_logger_has_context_methods(self):
        """测试获取的logger有上下文方法"""
        logger = get_logger('test', component='agent')

        assert hasattr(logger, 'debug_ctx')
        assert hasattr(logger, 'info_ctx')
        assert hasattr(logger, 'warning_ctx')
        assert hasattr(logger, 'error_ctx')

    def test_get_logger_context_methods_callable(self):
        """测试上下文方法可调用"""
        logger = get_logger('test', component='web')

        # 这些方法不应该抛出异常
        try:
            logger.debug_ctx('debug message', session_id='sess_001')
            logger.info_ctx('info message', session_id='sess_001')
            logger.warning_ctx('warning message', session_id='sess_001')
            logger.error_ctx('error message', session_id='sess_001')
        except Exception as e:
            pytest.fail(f"Context methods should not raise exception: {e}")


class TestSetupLogging:
    """日志设置测试"""

    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_setup_logging_returns_root_logger(self, temp_log_dir):
        """测试setup_logging返回根日志记录器"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger = setup_logging(log_level='INFO', console_output=False)
            assert isinstance(logger, logging.Logger)
            assert logger.name == 'root'

    def test_setup_logging_creates_handlers(self, temp_log_dir):
        """测试setup_logging创建处理器"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger = setup_logging(log_level='INFO', console_output=False)
            assert len(logger.handlers) > 0

    def test_setup_logging_with_console_output(self, temp_log_dir):
        """测试setup_logging带控制台输出"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger = setup_logging(log_level='INFO', console_output=True)
            # 检查是否有StreamHandler
            has_stream_handler = any(
                isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                for h in logger.handlers
            )
            assert has_stream_handler

    def test_setup_logging_log_level(self, temp_log_dir):
        """测试setup_logging设置日志级别"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger = setup_logging(log_level='DEBUG', console_output=False)
            assert logger.level == logging.DEBUG

            logger = setup_logging(log_level='ERROR', console_output=False)
            assert logger.level == logging.ERROR


class TestDailyTimedRotatingHandler:
    """按日期轮转处理器测试"""

    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_handler_creates_date_directory(self, temp_log_dir):
        """测试处理器创建日期目录"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            handler = DailyTimedRotatingHandler('test.log', maxBytes=1024)
            handler.close()

            today = datetime.now().strftime('%Y-%m-%d')
            date_dir = Path(temp_log_dir) / today
            assert date_dir.exists()

    def test_handler_creates_part_directory(self, temp_log_dir):
        """测试处理器创建part目录"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            handler = DailyTimedRotatingHandler('test.log', maxBytes=1024)
            handler.close()

            today = datetime.now().strftime('%Y-%m-%d')
            part_dir = Path(temp_log_dir) / today / 'part-1'
            assert part_dir.exists()

    def test_handler_creates_log_file(self, temp_log_dir):
        """测试处理器创建日志文件"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            handler = DailyTimedRotatingHandler('test.log', maxBytes=1024)
            handler.close()

            today = datetime.now().strftime('%Y-%m-%d')
            log_file = Path(temp_log_dir) / today / 'part-1' / 'test.log'
            assert log_file.exists()

    def test_handler_writes_log(self, temp_log_dir):
        """测试处理器写入日志"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            handler = DailyTimedRotatingHandler('test.log', maxBytes=1024)

            formatter = logging.Formatter(LOG_FORMAT)
            handler.setFormatter(formatter)

            logger = logging.getLogger('test_write')
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)

            test_message = "Test log message"
            logger.info(test_message)

            handler.close()

            today = datetime.now().strftime('%Y-%m-%d')
            log_file = Path(temp_log_dir) / today / 'part-1' / 'test.log'
            assert log_file.exists()
            content = log_file.read_text(encoding='utf-8')
            assert test_message in content


class TestLogFileHelpers:
    """日志文件辅助函数测试"""

    @pytest.fixture
    def temp_log_dir_with_files(self):
        """创建带日志文件的临时目录"""
        temp_dir = tempfile.mkdtemp()

        # 创建日期文件夹结构
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now().replace(day=datetime.now().day - 1)).strftime('%Y-%m-%d')

        # 今天的日志
        today_part1 = Path(temp_dir) / today / 'part-1'
        today_part1.mkdir(parents=True)
        (today_part1 / 'app.log').write_text('today app log')
        (today_part1 / 'web.log').write_text('today web log')

        today_part2 = Path(temp_dir) / today / 'part-2'
        today_part2.mkdir(parents=True)
        (today_part2 / 'app.log').write_text('today app log part 2')

        # 昨天的日志
        yesterday_part1 = Path(temp_dir) / yesterday / 'part-1'
        yesterday_part1.mkdir(parents=True)
        (yesterday_part1 / 'app.log').write_text('yesterday app log')

        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_latest_log_files(self, temp_log_dir_with_files):
        """测试获取最新日志文件"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir_with_files)):
            latest_files = get_latest_log_files()

            # 应该返回最新的日期和part
            today = datetime.now().strftime('%Y-%m-%d')
            assert 'app' in latest_files
            assert today in latest_files['app']
            assert 'part-2' in latest_files['app']

    def test_get_log_files_by_date(self, temp_log_dir_with_files):
        """测试按日期获取日志文件"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir_with_files)):
            today = datetime.now().strftime('%Y-%m-%d')
            files = get_log_files_by_date(today)

            assert 'part-1' in files
            assert 'part-2' in files
            assert 'app' in files['part-1']
            assert 'web' in files['part-1']

    def test_get_log_files_by_date_nonexistent(self, temp_log_dir_with_files):
        """测试获取不存在的日期的日志文件"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir_with_files)):
            files = get_log_files_by_date('2099-01-01')
            assert files == {}


class TestLogConstants:
    """日志常量测试"""

    def test_log_dir_is_path(self):
        """测试LOG_DIR是Path对象"""
        assert isinstance(LOG_DIR, Path)

    def test_log_format_is_string(self):
        """测试LOG_FORMAT是字符串"""
        assert isinstance(LOG_FORMAT, str)
        assert '%(asctime)s' in LOG_FORMAT

    def test_daily_part_max_bytes(self):
        """测试每日分片大小常量"""
        assert DAILY_PART_MAX_BYTES == 300 * 1024 * 1024  # 300MB
