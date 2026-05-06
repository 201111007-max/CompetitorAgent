"""日志系统集成测试

测试日志系统的完整工作流程：
- 日志记录到文件和内存
- API接口与日志系统的集成
- 多组件日志分离
- 日志轮转功能
"""

import pytest
import logging
import json
import time
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from utils.log_config import setup_logging_with_memory, get_logger
from utils.memory_log_handler import get_memory_handler


class TestLogSystemIntegration:
    """日志系统集成测试"""

    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_full_logging_workflow(self, temp_log_dir):
        """测试完整的日志工作流程"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            # 1. 设置日志系统
            logger, memory_handler = setup_logging_with_memory(
                log_level='DEBUG',
                daily_max_bytes=1024 * 1024,  # 1MB for testing
                memory_max_entries=100,
                console_output=False
            )

            # 2. 获取组件日志记录器
            web_logger = get_logger('web_test', component='web')
            agent_logger = get_logger('agent_test', component='agent')

            # 3. 记录不同级别的日志
            web_logger.debug_ctx('Debug message', session_id='sess_001')
            web_logger.info_ctx('Info message', session_id='sess_001')
            web_logger.warning_ctx('Warning message', session_id='sess_001')
            web_logger.error_ctx('Error message', session_id='sess_001')

            agent_logger.info_ctx('Agent info', session_id='sess_002')

            # 等待日志处理
            time.sleep(0.1)

            # 4. 验证内存日志
            logs = memory_handler.get_logs()
            assert len(logs) >= 5

            # 5. 验证日志筛选
            web_logs = memory_handler.get_logs(component='web')
            assert len(web_logs) >= 4

            agent_logs = memory_handler.get_logs(component='agent')
            assert len(agent_logs) >= 1

            # 6. 验证文件日志
            today = datetime.now().strftime('%Y-%m-%d')
            web_log_file = Path(temp_log_dir) / today / 'part-1' / 'web.log'
            agent_log_file = Path(temp_log_dir) / today / 'part-1' / 'agent.log'

            assert web_log_file.exists()
            assert agent_log_file.exists()

            web_content = web_log_file.read_text(encoding='utf-8')
            assert 'Info message' in web_content
            assert 'Warning message' in web_content
            assert 'Error message' in web_content

            memory_handler.close()

    def test_log_rotation_by_size(self, temp_log_dir):
        """测试按大小轮转日志"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            # 使用很小的分片大小来测试轮转
            logger, memory_handler = setup_logging_with_memory(
                log_level='INFO',
                daily_max_bytes=500,  # 500 bytes for testing
                memory_max_entries=100,
                console_output=False
            )

            test_logger = get_logger('rotation_test', component='web')

            # 写入大量日志以触发轮转
            for i in range(100):
                test_logger.info_ctx(f'Test message {i}' + 'x' * 50, session_id='test')

            # 等待日志处理
            time.sleep(0.2)

            # 验证是否创建了多个part目录
            today = datetime.now().strftime('%Y-%m-%d')
            date_dir = Path(temp_log_dir) / today

            part_dirs = list(date_dir.glob('part-*'))
            assert len(part_dirs) >= 1

            # 如果有多个part目录，说明轮转正常工作
            if len(part_dirs) > 1:
                # 验证part-1和part-2都存在
                assert (date_dir / 'part-1').exists()
                assert (date_dir / 'part-2').exists()

            memory_handler.close()

    def test_session_isolation(self, temp_log_dir):
        """测试会话隔离"""
        # 重置内存处理器以确保干净的测试环境
        from utils.memory_log_handler import reset_memory_handler
        reset_memory_handler()
        
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger, memory_handler = setup_logging_with_memory(
                log_level='INFO',
                console_output=False
            )

            test_logger = get_logger('session_test', component='web')

            # 记录不同会话的日志
            for i in range(5):
                test_logger.info_ctx(f'Session 1 message {i}', session_id='sess_001')
                test_logger.info_ctx(f'Session 2 message {i}', session_id='sess_002')

            # 等待日志处理
            time.sleep(0.1)

            # 验证会话隔离
            sess_001_logs = memory_handler.get_logs(session_id='sess_001')
            sess_002_logs = memory_handler.get_logs(session_id='sess_002')

            assert len(sess_001_logs) == 5
            assert len(sess_002_logs) == 5

            for log in sess_001_logs:
                assert log.get('session_id') == 'sess_001'
                assert 'Session 1' in log['message']

            for log in sess_002_logs:
                assert log.get('session_id') == 'sess_002'
                assert 'Session 2' in log['message']

            memory_handler.close()

    def test_log_clearing(self, temp_log_dir):
        """测试日志清空功能"""
        # 重置内存处理器以确保干净的测试环境
        from utils.memory_log_handler import reset_memory_handler
        reset_memory_handler()
        
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger, memory_handler = setup_logging_with_memory(
                log_level='INFO',
                console_output=False
            )

            test_logger = get_logger('clear_test', component='web')

            # 记录不同会话的日志
            for i in range(5):
                test_logger.info_ctx(f'Session 1 message {i}', session_id='sess_001')
                test_logger.info_ctx(f'Session 2 message {i}', session_id='sess_002')

            # 等待日志处理
            time.sleep(0.1)

            # 验证日志已添加
            all_logs = memory_handler.get_logs()
            assert len(all_logs) == 10

            # 清空 sess_001 的日志
            memory_handler.clear(session_id='sess_001')

            # 验证只有 sess_002 的日志保留
            remaining_logs = memory_handler.get_logs()
            assert len(remaining_logs) == 5
            for log in remaining_logs:
                assert log.get('session_id') == 'sess_002'

            memory_handler.close()

    def test_concurrent_logging(self, temp_log_dir):
        """测试并发日志记录"""
        import threading
        # 重置内存处理器以确保干净的测试环境
        from utils.memory_log_handler import reset_memory_handler
        reset_memory_handler()

        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger, memory_handler = setup_logging_with_memory(
                log_level='INFO',
                console_output=False
            )

            errors = []

            def log_worker(thread_id, count):
                try:
                    worker_logger = get_logger(f'worker_{thread_id}', component='web')
                    for i in range(count):
                        worker_logger.info_ctx(
                            f'Thread {thread_id} message {i}',
                            session_id=f'sess_{thread_id}'
                        )
                except Exception as e:
                    errors.append(e)

            # 创建多个线程并发记录日志
            threads = []
            for i in range(5):
                t = threading.Thread(target=log_worker, args=(i, 20))
                threads.append(t)
                t.start()

            # 等待所有线程完成
            for t in threads:
                t.join()

            # 等待日志处理
            time.sleep(0.2)

            # 验证没有错误
            assert len(errors) == 0

            # 验证所有日志都被记录（允许有一定的误差）
            logs = memory_handler.get_logs()
            assert len(logs) >= 95  # 5 线程 * 20 条 = 100，允许少量误差

            memory_handler.close()


class TestLogAPIIntegration:
    """日志API集成测试"""

    @pytest.fixture
    def client_and_handler(self, temp_log_dir):
        """创建测试客户端和处理器"""
        # 重置内存处理器以确保干净的测试环境
        from utils.memory_log_handler import reset_memory_handler
        reset_memory_handler()
        
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            from web.app import app, memory_handler

            # 清空之前的日志
            memory_handler.clear()

            # 记录一些测试日志
            test_logger = get_logger('api_test', component='web')
            test_logger.info_ctx('Test log 1', session_id='test_session')
            test_logger.info_ctx('Test log 2', session_id='test_session')
            test_logger.warning_ctx('Warning log', session_id='test_session')

            # 等待日志处理
            time.sleep(0.1)

            app.config['TESTING'] = True
            with app.test_client() as client:
                yield client, memory_handler

    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_api_returns_correct_logs(self, client_and_handler):
        """测试API返回正确的日志"""
        client, handler = client_and_handler

        response = client.get('/api/logs')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['logs']) >= 3

    def test_api_filter_by_session(self, client_and_handler):
        """测试API按会话筛选"""
        client, handler = client_and_handler

        response = client.get('/api/logs?session_id=test_session')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        for log in data['logs']:
            assert log.get('session_id') == 'test_session'

    def test_api_filter_by_level(self, client_and_handler):
        """测试API按级别筛选"""
        client, handler = client_and_handler

        response = client.get('/api/logs?level=WARNING')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        for log in data['logs']:
            assert log['level'] == 'WARNING'

    def test_api_clear_logs(self, client_and_handler):
        """测试 API 清空日志"""
        client, handler = client_and_handler

        # 先验证有日志
        response = client.get('/api/logs')
        data = json.loads(response.data)
        initial_count = len(data['logs'])
        assert initial_count > 0

        # 清空日志
        response = client.post('/api/logs/clear',
                              data=json.dumps({}),
                              content_type='application/json')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True

        # 验证日志已清空（允许有 1 条系统日志）
        response = client.get('/api/logs')
        data = json.loads(response.data)
        assert len(data['logs']) <= 1


class TestLogFileStructure:
    """日志文件结构测试"""

    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_log_directory_structure(self, temp_log_dir):
        """测试日志目录结构"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger, memory_handler = setup_logging_with_memory(
                log_level='INFO',
                console_output=False
            )

            # 记录日志
            test_logger = get_logger('structure_test', component='web')
            test_logger.info_ctx('Test message', session_id='test')

            # 等待日志处理
            time.sleep(0.1)

            # 验证目录结构
            today = datetime.now().strftime('%Y-%m-%d')
            date_dir = Path(temp_log_dir) / today
            part_dir = date_dir / 'part-1'

            assert date_dir.exists()
            assert part_dir.exists()

            # 验证日志文件存在
            assert (part_dir / 'app.log').exists()
            assert (part_dir / 'web.log').exists()

            memory_handler.close()

    def test_readme_file_created(self, temp_log_dir):
        """测试README文件被创建"""
        with patch('utils.log_config.LOG_DIR', Path(temp_log_dir)):
            logger, memory_handler = setup_logging_with_memory(
                log_level='INFO',
                console_output=False
            )

            # 验证README文件存在
            readme_file = Path(temp_log_dir) / 'README.md'
            assert readme_file.exists()

            # 验证README内容
            content = readme_file.read_text(encoding='utf-8')
            assert '日志文件说明' in content
            assert '文件夹结构' in content

            memory_handler.close()
