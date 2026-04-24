"""Web API 集成测试

测试 Flask 后端 API 端点的完整功能
包括：健康检查、聊天接口、英雄解析、物品解析等
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from web.app import app, parse_heroes_with_llm, parse_heroes_with_rules, parse_items_with_llm


@pytest.fixture
def client():
    """测试客户端 fixture"""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_agent_controller():
    """模拟 Agent Controller"""
    with patch('web.app.agent_controller') as mock_controller:
        yield mock_controller


class TestHealthEndpoints:
    """测试健康检查端点"""
    
    def test_health_check(self, client):
        """测试健康检查接口"""
        response = client.get('/api/health')
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['status'] == 'ok'
        assert data['service'] == 'DotaHelperAgent'
        assert 'llm_enabled' in data
        assert 'agent_controller_ready' in data
        assert 'memory' in data
    
    def test_test_tools_endpoint(self, client):
        """测试工具测试接口"""
        response = client.get('/api/test_tools')
        
        # 如果 Agent Controller 未初始化，应该返回错误
        if app.config.get('agent_controller') is None:
            assert response.status_code == 200
            data = response.get_json()
            assert 'error' in data or 'test_result' in data


class TestChatEndpoint:
    """测试聊天接口"""
    
    def test_chat_empty_query(self, client):
        """测试空查询"""
        response = client.post('/api/chat', json={'query': ''})
        
        assert response.status_code == 200
        data = response.get_json()
        # 空查询可能返回成功（有错误提示）或失败
        assert 'success' in data
        assert 'error' in data or 'final_answer' in data or data.get('success') == False
    
    def test_chat_with_query(self, client, mock_agent_controller):
        """测试正常查询"""
        # 设置模拟响应
        mock_agent_controller.solve.return_value = {
            'success': True,
            'state': 'completed',
            'turn_count': 2,
            'duration': 1.5,
            'reasoning': ['分析用户查询', '调用工具'],
            'actions': ['analyze_counter_picks'],
            'answer': {
                'recommendations': [
                    {'hero_name': 'Axe', 'score': 0.85, 'reasons': ['控制能力强']}
                ],
                'answer': '推荐 Axe'
            }
        }
        
        response = client.post('/api/chat', json={
            'query': '对面有敌法，我们选什么英雄克制？'
        })
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] == True
        assert 'final_answer' in data
        assert 'reasoning' in data
        assert 'actions' in data
    
    def test_chat_with_session_id(self, client, mock_agent_controller):
        """测试带 session_id 的查询"""
        mock_agent_controller.solve.return_value = {
            'success': True,
            'state': 'completed',
            'turn_count': 1,
            'duration': 0.5,
            'reasoning': [],
            'actions': [],
            'answer': {'answer': '测试响应'}
        }
        
        response = client.post('/api/chat', json={
            'query': '推荐出装',
            'session_id': 'test-session-123'
        })
        
        data = response.get_json()
        assert response.status_code == 200
        assert data['session_id'] == 'test-session-123'
    
    def test_chat_with_context(self, client, mock_agent_controller):
        """测试带上下文的查询"""
        mock_agent_controller.solve.return_value = {
            'success': True,
            'state': 'completed',
            'turn_count': 1,
            'duration': 0.5,
            'reasoning': [],
            'actions': [],
            'answer': {'answer': '基于上下文的响应'}
        }
        
        response = client.post('/api/chat', json={
            'query': '怎么打？',
            'context': {
                'our_heroes': ['anti-mage'],
                'enemy_heroes': ['legion_commander']
            }
        })
        
        data = response.get_json()
        assert response.status_code == 200
        assert data['success'] == True


class TestHeroParsing:
    """测试英雄解析功能"""
    
    def test_parse_heroes_with_rules_simple(self):
        """测试规则解析 - 简单情况"""
        query = "我们有敌法，黑鸟，小鹿，对面有军团，小鱼，兽"
        result = parse_heroes_with_rules(query)
        
        assert 'our_heroes' in result
        assert 'enemy_heroes' in result
        assert isinstance(result['our_heroes'], list)
        assert isinstance(result['enemy_heroes'], list)
    
    def test_parse_heroes_with_rules_english(self):
        """测试规则解析 - 英文名"""
        query = "our: anti-mage, invoker; enemy: pudge, axe"
        result = parse_heroes_with_rules(query)
        
        assert 'our_heroes' in result
        assert 'enemy_heroes' in result
    
    def test_parse_heroes_with_rules_mixed(self):
        """测试规则解析 - 混合情况"""
        query = "对面有 PA、小黑，我们选了斧王、祈求者"
        result = parse_heroes_with_rules(query)
        
        assert 'our_heroes' in result
        assert 'enemy_heroes' in result
        print(f"[DEBUG] our={result['our_heroes']}, enemy={result['enemy_heroes']}")
    
    def test_parse_heroes_with_llm_mock(self):
        """测试 LLM 解析（模拟）"""
        with patch('web.app.get_llm_client') as mock_get_client:
            mock_client = Mock()
            mock_client.chat.return_value = {
                'choices': [{
                    'message': {
                        'content': '{"our_heroes": ["anti-mage"], "enemy_heroes": ["pudge"]}'
                    }
                }]
            }
            mock_get_client.return_value = mock_client
            
            # 这里需要实际调用 parse_heroes_with_llm
            # 但由于 LLM 客户端可能未配置，使用规则解析作为备选
            query = "我们有敌法，对面有帕吉"
            result = parse_heroes_with_llm(query)
            
            assert 'our_heroes' in result
            assert 'enemy_heroes' in result


class TestItemParsing:
    """测试物品解析功能"""
    
    def test_parse_items_with_llm_mock(self):
        """测试物品解析（模拟）"""
        with patch('web.app.get_llm_client') as mock_get_client:
            mock_client = Mock()
            mock_client.chat.return_value = {
                'choices': [{
                    'message': {
                        'content': '{"items": ["bfury", "bkb", "blink"]}'
                    }
                }]
            }
            mock_get_client.return_value = mock_client
            
            query = "敌法应该出狂战、黑皇、跳刀"
            result = parse_items_with_llm(query)
            
            assert 'items' in result
            assert isinstance(result['items'], list)
    
    def test_parse_items_no_llm(self):
        """测试无 LLM 时的物品解析"""
        with patch('web.app.get_llm_client') as mock_get_client:
            mock_get_client.return_value = None
            
            query = "出装备"
            result = parse_items_with_llm(query)
            
            assert result == {'items': []}


class TestFormatAnswer:
    """测试答案格式化"""
    
    def test_format_recommendations(self):
        """测试推荐结果格式化"""
        from web.app import _format_answer
        
        answer_data = {
            'recommendations': [
                {'hero_name': 'Axe', 'score': 0.92, 'reasons': ['控制强', '伤害高']},
                {'hero_name': 'Legion', 'score': 0.88, 'reasons': ['对决优势']}
            ],
            'answer': '推荐 Axe 和 Legion'
        }
        
        formatted = _format_answer(answer_data)
        
        assert '推荐结果' in formatted
        assert 'Axe' in formatted
        assert 'Legion' in formatted
        assert '答案' in formatted
    
    def test_format_empty(self):
        """测试空数据格式化"""
        from web.app import _format_answer
        
        answer_data = {}
        formatted = _format_answer(answer_data)
        
        assert formatted == '{}'


class TestMockRecommendations:
    """测试模拟推荐数据"""
    
    def test_get_mock_recommendations(self):
        """测试模拟推荐函数"""
        from web.app import _get_mock_recommendations
        
        result = _get_mock_recommendations(['anti-mage'])
        
        assert isinstance(result, str)
        assert len(result) > 0
        assert '克制' in result or '推荐' in result
    
    def test_get_mock_recommendations_empty(self):
        """测试空英雄列表"""
        from web.app import _get_mock_recommendations
        
        result = _get_mock_recommendations([])
        
        assert isinstance(result, str)
        assert len(result) > 0


class TestStaticFiles:
    """测试静态文件服务"""
    
    def test_index_page(self, client):
        """测试首页"""
        response = client.get('/')
        
        # 应该返回 index.html 文件
        assert response.status_code == 200
        assert 'text/html' in response.content_type
    
    def test_web_static_files(self, client):
        """测试 Web 静态文件"""
        # 测试 CSS/JS 文件访问
        response = client.get('/web/index.html')
        
        assert response.status_code == 200


class TestEdgeCases:
    """测试边界情况"""
    
    def test_chat_very_long_query(self, client, mock_agent_controller):
        """测试超长查询"""
        mock_agent_controller.solve.return_value = {
            'success': True,
            'state': 'completed',
            'turn_count': 1,
            'duration': 0.5,
            'reasoning': [],
            'actions': [],
            'answer': {'answer': '响应'}
        }
        
        long_query = "推荐英雄 " * 100
        response = client.post('/api/chat', json={'query': long_query})
        
        assert response.status_code == 200
    
    def test_chat_special_characters(self, client, mock_agent_controller):
        """测试特殊字符"""
        mock_agent_controller.solve.return_value = {
            'success': True,
            'state': 'completed',
            'turn_count': 1,
            'duration': 0.5,
            'reasoning': [],
            'actions': [],
            'answer': {'answer': '响应'}
        }
        
        response = client.post('/api/chat', json={
            'query': '推荐英雄！@#$%^&*() 对面有 <script>alert(1)</script>'
        })
        
        assert response.status_code == 200
    
    def test_chat_missing_json(self, client):
        """测试缺失 JSON"""
        response = client.post('/api/chat', data='not json')
        
        # Flask 可能返回 400 (Bad Request) 或 415 (Unsupported Media Type)
        assert response.status_code in [200, 400, 415]
    
    def test_hero_parsing_typos(self):
        """测试拼写错误处理"""
        # "地方" 是 "敌方" 的 typo
        query = "地方有敌法、小黑"
        result = parse_heroes_with_rules(query)
        
        assert 'enemy_heroes' in result
        # 应该识别为敌方英雄


class TestIntegration:
    """集成测试 - 模拟完整流程"""
    
    def test_full_chat_workflow(self, client, mock_agent_controller):
        """完整聊天工作流测试"""
        # 1. 设置 Agent Controller 的模拟行为
        mock_agent_controller.solve.side_effect = [
            # 第一次调用 - 英雄克制查询
            {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.2,
                'reasoning': [
                    '用户询问克制英雄',
                    '需要分析敌方阵容'
                ],
                'actions': [
                    {'tool': 'analyze_counter_picks', 'params': {'enemy_heroes': ['legion_commander']}},
                    {'tool': 'format_recommendations', 'params': {}}
                ],
                'reflections': [],
                'answer': {
                    'recommendations': [
                        {'hero_name': 'Axe', 'score': 0.90, 'reasons': ['控制能力强']},
                        {'hero_name': 'Legion Commander', 'score': 0.85, 'reasons': ['对决优势']}
                    ],
                    'answer': '推荐使用 Axe 或 Legion Commander'
                }
            }
        ]
        
        # 2. 发送查询
        response = client.post('/api/chat', json={
            'query': '对面有军团，我们选什么英雄克制？',
            'context': {}
        })
        
        # 3. 验证响应
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['agent_mode'] == True
        assert 'final_answer' in data
        assert 'reasoning' in data
        assert 'actions' in data
        assert 'session_id' in data
        
        # 4. 验证 Agent Controller 被调用
        assert mock_agent_controller.solve.called
        
        print(f"[OK] 完整工作流测试通过")
        print(f"   - Query: {data['query']}")
        print(f"   - Turns: {data.get('turn_count', 'N/A')}")
        print(f"   - Duration: {data.get('duration', 'N/A')}s")
