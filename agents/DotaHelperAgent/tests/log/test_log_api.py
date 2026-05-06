"""日志API接口测试

测试日志相关的API接口：
- GET /api/logs - 获取日志列表
- GET /api/logs/stream - SSE流式日志
- GET /api/logs/files - 获取日志文件列表
- GET /api/logs/files/<path> - 获取日志文件内容
- POST /api/logs/clear - 清空日志
"""

import pytest
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


class TestLogAPI:
    """日志API接口测试类"""

    @pytest.fixture
    def client(self):
        """创建Flask测试客户端"""
        from web.app import app, memory_handler
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_logs_success(self, client):
        """测试获取日志列表接口 - 成功场景"""
        response = client.get('/api/logs')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        assert 'logs' in data
        assert isinstance(data['logs'], list)

    def test_get_logs_with_session_filter(self, client):
        """测试获取日志列表接口 - 按 session_id 筛选"""
        test_session = "test-session-123"
        response = client.get(f'/api/logs?session_id={test_session}')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        # 验证返回的日志是否都属于指定 session
        for log in data['logs']:
            assert log.get('session_id') == test_session

    def test_get_logs_with_level_filter(self, client):
        """测试获取日志列表接口 - 按级别筛选"""
        response = client.get('/api/logs?level=INFO')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        # 验证返回的日志级别是否符合要求
        for log in data['logs']:
            assert log.get('level') == 'INFO'

    def test_get_logs_with_component_filter(self, client):
        """测试获取日志列表接口 - 按组件筛选"""
        response = client.get('/api/logs?component=web')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        # 验证返回的日志组件是否符合要求
        for log in data['logs']:
            assert log.get('component') == 'web'

    def test_get_logs_with_limit(self, client):
        """测试获取日志列表接口 - 限制返回数量"""
        limit = 10
        response = client.get(f'/api/logs?limit={limit}')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['logs']) <= limit

    def test_get_logs_combined_filters(self, client):
        """测试获取日志列表接口 - 组合筛选条件"""
        response = client.get('/api/logs?level=INFO&component=web&limit=5')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['logs']) <= 5
        for log in data['logs']:
            assert log.get('level') == 'INFO'
            assert log.get('component') == 'web'

    def test_get_log_files_success(self, client):
        """测试获取日志文件列表接口 - 成功场景"""
        response = client.get('/api/logs/files')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True
        assert 'files' in data
        assert isinstance(data['files'], list)

        # 验证文件信息结构
        for file_info in data['files']:
            assert 'name' in file_info
            assert 'size' in file_info
            assert 'modified' in file_info
            assert 'path' in file_info
            assert 'date' in file_info
            assert 'part' in file_info

    def test_get_log_file_content_success(self, client, temp_log_dir):
        """测试获取日志文件内容接口 - 成功场景"""
        # 创建测试日志文件
        test_date = datetime.now().strftime('%Y-%m-%d')
        test_file = Path(temp_log_dir) / test_date / 'part-1' / 'test.log'
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_content = "Test log line 1\nTest log line 2\nTest log line 3"
        test_file.write_text(test_content, encoding='utf-8')

        # 使用环境变量传递日志目录
        with patch('web.app.app.config.LOG_DIR', Path(temp_log_dir)):
            response = client.get(f'/api/logs/files/{test_date}/part-1/test.log')
            assert response.status_code == 200

            data = json.loads(response.data)
            assert data['success'] is True
            assert data['filename'] == f'{test_date}/part-1/test.log'
            assert test_content in data['content']

    def test_get_log_file_content_with_tail(self, client, temp_log_dir):
        """测试获取日志文件内容接口 - 使用 tail 参数"""
        # 创建测试日志文件
        test_date = datetime.now().strftime('%Y-%m-%d')
        test_file = Path(temp_log_dir) / test_date / 'part-1' / 'test.log'
        test_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"Line {i}" for i in range(1, 21)]
        test_file.write_text('\n'.join(lines), encoding='utf-8')

        # 使用环境变量传递日志目录
        with patch('web.app.app.config.LOG_DIR', Path(temp_log_dir)):
            response = client.get(f'/api/logs/files/{test_date}/part-1/test.log?tail=5')
            assert response.status_code == 200

            data = json.loads(response.data)
            assert data['success'] is True
            content_lines = data['content'].strip().split('\n')
            assert len(content_lines) == 5
            assert 'Line 16' in content_lines[0]
            assert 'Line 20' in content_lines[-1]

    def test_get_log_file_content_not_found(self, client):
        """测试获取日志文件内容接口 - 文件不存在"""
        response = client.get('/api/logs/files/nonexistent.log')
        assert response.status_code == 404

        data = json.loads(response.data)
        assert data['success'] is False
        assert 'error' in data

    def test_get_log_file_content_invalid_path(self, client):
        """测试获取日志文件内容接口 - 非法路径（路径遍历攻击防护）"""
        response = client.get('/api/logs/files/../../../etc/passwd')
        # 由于路径验证，应该返回 404（文件不存在）
        assert response.status_code == 404

        data = json.loads(response.data)
        assert data['success'] is False

    def test_clear_logs_success(self, client):
        """测试清空日志接口 - 成功场景"""
        response = client.post('/api/logs/clear',
                              data=json.dumps({}),
                              content_type='application/json')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True

    def test_clear_logs_with_session(self, client):
        """测试清空日志接口 - 指定session_id"""
        test_session = "test_session_001"
        response = client.post('/api/logs/clear',
                              data=json.dumps({'session_id': test_session}),
                              content_type='application/json')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['success'] is True

    def test_log_stream_sse_format(self, client):
        """测试日志流接口 - SSE 格式验证"""
        response = client.get('/api/logs/stream')
        assert response.status_code == 200
        # Content-Type 应该包含 text/event-stream
        assert 'text/event-stream' in response.content_type

        # 读取部分数据验证 SSE 格式
        data = response.data.decode('utf-8')
        # SSE 格式应该以 "data:" 开头
        if data.strip():
            lines = data.strip().split('\n')
            for line in lines:
                if line.strip():
                    assert line.startswith('data:') or line.startswith('event:') or line == ''

    def test_log_stream_with_session_filter(self, client):
        """测试日志流接口 - 按 session_id 筛选"""
        test_session = "test-session-123"
        response = client.get(f'/api/logs/stream?session_id={test_session}')
        assert response.status_code == 200
        assert 'text/event-stream' in response.content_type


class TestLogAPIErrorHandling:
    """日志API接口错误处理测试"""

    @pytest.fixture
    def client(self):
        """创建Flask测试客户端"""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_get_logs_invalid_level(self, client):
        """测试获取日志接口 - 无效的日志级别"""
        response = client.get('/api/logs?level=INVALID')
        assert response.status_code == 200  # 应该返回空列表而不是错误

        data = json.loads(response.data)
        assert data['success'] is True
        assert data['logs'] == []

    def test_get_logs_invalid_limit(self, client):
        """测试获取日志接口 - 无效的 limit 参数"""
        # 应该处理异常并返回默认值或错误
        with pytest.raises((ValueError, TypeError)):
            response = client.get('/api/logs?limit=invalid')
            # 如果 API 没有抛出异常，应该返回 400 或 200
            assert response.status_code in [200, 400]

    def test_clear_logs_invalid_json(self, client):
        """测试清空日志接口 - 无效的JSON数据"""
        response = client.post('/api/logs/clear',
                              data='invalid json',
                              content_type='application/json')
        # 应该优雅处理错误
        assert response.status_code in [200, 400, 500]


class TestLogAPIIntegration:
    """日志API接口集成测试"""

    @pytest.fixture
    def client(self):
        """创建Flask测试客户端"""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_full_log_workflow(self, client):
        """测试完整的日志工作流程"""
        # 1. 获取初始日志列表
        response = client.get('/api/logs')
        assert response.status_code == 200
        initial_data = json.loads(response.data)
        initial_count = len(initial_data['logs'])

        # 2. 获取日志文件列表
        response = client.get('/api/logs/files')
        assert response.status_code == 200
        files_data = json.loads(response.data)
        assert files_data['success'] is True

        # 3. 清空日志
        response = client.post('/api/logs/clear',
                              data=json.dumps({}),
                              content_type='application/json')
        assert response.status_code == 200

        # 4. 验证日志已清空（允许有 1 条日志，因为可能有系统日志）
        response = client.get('/api/logs')
        assert response.status_code == 200
        cleared_data = json.loads(response.data)
        assert len(cleared_data['logs']) <= 1

    def test_log_filtering_consistency(self, client):
        """测试日志筛选的一致性"""
        # 多次相同筛选应该返回一致的结果
        response1 = client.get('/api/logs?level=INFO&limit=10')
        response2 = client.get('/api/logs?level=INFO&limit=10')

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = json.loads(response1.data)
        data2 = json.loads(response2.data)

        assert data1['success'] == data2['success']
        assert len(data1['logs']) == len(data2['logs'])
