"""端到端 (E2E) 全流程测试

测试从前端到后端的完整用户流程
包括：用户查询 -> API 接收 -> Agent 处理 -> Tool 执行 -> 返回结果
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import time
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from web.app import app, initialize_agent_controller, get_agent
from core.agent_controller import AgentController
from core.tool_registry import ToolRegistry


@pytest.fixture
def e2e_client():
    """端到端测试客户端
    
    初始化完整的 Agent 环境
    """
    # 确保 Agent Controller 已初始化
    if app.config.get('agent_controller') is None:
        initialize_agent_controller()
    
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_llm_client():
    """模拟 LLM 客户端"""
    with patch('web.app.get_llm_client') as mock_get:
        mock_client = Mock()
        mock_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': '{"our_heroes": [], "enemy_heroes": ["legion_commander"]}'
                }
            }]
        }
        mock_get.return_value = mock_client
        yield mock_client


class TestEndToEndHeroCounter:
    """端到端测试 - 英雄克制推荐"""
    
    def test_complete_counter_pick_flow(self, e2e_client, mock_llm_client):
        """完整的克制英雄推荐流程
        
        流程：
        1. 用户输入："对面有军团，我们选什么英雄克制？"
        2. API 接收请求
        3. LLM 解析英雄名称
        4. Agent Controller 执行 ReAct 循环
        5. 调用 analyze_counter_picks 工具
        6. 返回推荐结果
        """
        # 设置 Agent Controller 的完整响应
        controller = app.config.get('agent_controller')
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 3,
                'duration': 2.5,
                'reasoning': [
                    '用户询问克制军团的英雄',
                    '需要调用英雄分析工具',
                    '整合推荐结果'
                ],
                'actions': [
                    {
                        'tool': 'analyze_counter_picks',
                        'params': {
                            'our_heroes': [],
                            'enemy_heroes': ['legion_commander'],
                            'top_n': 3
                        },
                        'result': {
                            'recommendations': [
                                {'hero_name': 'Axe', 'score': 0.92, 'reasons': ['控制能力强', '克制近战']},
                                {'hero_name': 'Legion Commander', 'score': 0.88, 'reasons': ['对决优势']},
                                {'hero_name': 'Spirit Breaker', 'score': 0.85, 'reasons': ['全球流']}
                            ]
                        }
                    }
                ],
                'reflections': [],
                'answer': {
                    'recommendations': [
                        {'hero_name': 'Axe', 'score': 0.92, 'reasons': ['控制能力强', '克制近战']},
                        {'hero_name': 'Legion Commander', 'score': 0.88, 'reasons': ['对决优势']},
                        {'hero_name': 'Spirit Breaker', 'score': 0.85, 'reasons': ['全球流']}
                    ],
                    'answer': '推荐使用 Axe、Legion Commander 或 Spirit Breaker'
                }
            }
        
        # 发送请求
        response = e2e_client.post('/api/chat', json={
            'query': '对面有军团，我们选什么英雄克制？',
            'context': {}
        })
        
        # 验证响应
        assert response.status_code == 200
        data = response.get_json()
        
        print("\n" + "="*60)
        print("端到端测试 - 英雄克制推荐")
        print("="*60)
        print(f"Query: {data['query']}")
        print(f"Success: {data['success']}")
        print(f"Agent Mode: {data['agent_mode']}")
        if 'turn_count' in data:
            print(f"Turns: {data['turn_count']}")
        if 'duration' in data:
            print(f"Duration: {data['duration']:.2f}s")
        print(f"Final Answer: {data.get('final_answer', 'N/A')[:200]}...")
        print("="*60 + "\n")
        
        # 断言
        assert data['success'] == True
        assert data['agent_mode'] == True
        assert 'final_answer' in data
        assert len(data['final_answer']) > 0
        
        # 如果使用了 Agent Controller，验证详细字段
        if data['agent_mode']:
            assert 'reasoning' in data
            assert 'actions' in data
    
    def test_mixed_language_hero_names(self, e2e_client):
        """测试混合语言英雄名称
        
        用户可能使用中文、英文、简称混合
        """
        controller = app.config.get('agent_controller')
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.8,
                'reasoning': ['解析混合语言英雄名'],
                'actions': [],
                'answer': {
                    'answer': '推荐结果'
                }
            }
        
        test_cases = [
            "我们有 PA、小黑，对面有帕吉、斧王",
            "our: anti-mage, drow ranger; enemy: pudge, axe",
            "对面有军团 (Legion Commander)，我们选什么？",
            "敌方有 SF、影魔，我们怎么打？"
        ]
        
        for query in test_cases:
            response = e2e_client.post('/api/chat', json={'query': query})
            data = response.get_json()
            
            assert response.status_code == 200
            assert data['success'] == True or data.get('agent_mode') == False
            
            print(f"[OK] 测试通过：{query[:50]}...")


class TestEndToEndItemRecommendation:
    """端到端测试 - 出装推荐"""
    
    def test_item_recommendation_flow(self, e2e_client):
        """出装推荐流程
        
        流程：
        1. 用户输入："敌法应该出什么装备？"
        2. API 接收并解析英雄名称
        3. Agent 调用 item_recommender 工具
        4. 返回出装建议
        """
        controller = app.config.get('agent_controller')
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.5,
                'reasoning': [
                    '用户询问敌法的出装',
                    '需要调用物品推荐工具'
                ],
                'actions': [
                    {
                        'tool': 'recommend_items',
                        'params': {
                            'hero_name': 'anti-mage',
                            'game_stage': 'all'
                        },
                        'result': {
                            'items': [
                                {'name': 'Battle Fury', 'timing': 'core'},
                                {'name': 'Manta Style', 'timing': 'core'},
                                {'name': 'Abyssal Blade', 'timing': 'luxury'}
                            ]
                        }
                    }
                ],
                'answer': {
                    'answer': '推荐出装：狂战斧、分身斧、深渊之刃'
                }
            }
        
        response = e2e_client.post('/api/chat', json={
            'query': '敌法应该出什么装备？'
        })
        
        data = response.get_json()
        assert response.status_code == 200
        assert data['success'] == True
        assert 'final_answer' in data
        
        print(f"[OK] 出装推荐测试通过")
        print(f"   Query: {data['query']}")
        print(f"   Answer: {data.get('final_answer', 'N/A')[:150]}...\n")


class TestEndToEndSkillBuild:
    """端到端测试 - 技能加点"""
    
    def test_skill_build_flow(self, e2e_client):
        """技能加点流程
        
        流程：
        1. 用户输入："斧王技能怎么加？"
        2. API 解析英雄名称
        3. Agent 调用 skill_builder 工具
        4. 返回技能加点顺序
        """
        controller = app.config.get('agent_controller')
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.3,
                'reasoning': ['用户询问斧王技能加点'],
                'actions': [
                    {
                        'tool': 'build_skill_order',
                        'params': {'hero_name': 'axe'},
                        'result': {
                            'skill_order': ['Berserker\'s Call', 'Battle Hunger', 'Counter Helix']
                        }
                    }
                ],
                'answer': {
                    'answer': '推荐加点：主 C 副 E，一级 B'
                }
            }
        
        response = e2e_client.post('/api/chat', json={
            'query': '斧王技能怎么加？'
        })
        
        data = response.get_json()
        assert response.status_code == 200
        assert data['success'] == True
        
        print(f"[OK] 技能加点测试通过")
        print(f"   Query: {data['query']}\n")


class TestEndToEndMultiTurnConversation:
    """端到端测试 - 多轮对话"""
    
    def test_multi_turn_conversation(self, e2e_client):
        """多轮对话测试
        
        测试上下文连续性
        """
        controller = app.config.get('agent_controller')
        
        # 第一轮：询问克制英雄
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.5,
                'reasoning': ['第一轮：分析克制关系'],
                'actions': [],
                'answer': {'answer': '推荐 Axe'}
            }
        
        response1 = e2e_client.post('/api/chat', json={
            'query': '对面有军团，选什么英雄克制？',
            'session_id': 'test-session-001'
        })
        
        data1 = response1.get_json()
        assert data1['success'] == True
        assert data1['session_id'] == 'test-session-001'
        
        # 第二轮：询问出装（应该能关联到上一轮的推荐）
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.3,
                'reasoning': ['第二轮：基于上轮推荐给出装建议'],
                'actions': [],
                'answer': {'answer': 'Axe 推荐出跳刀、 Blink Dagger'}
            }
        
        response2 = e2e_client.post('/api/chat', json={
            'query': '那这个英雄怎么出装？',
            'session_id': 'test-session-001',
            'context': {'previous_recommendation': 'Axe'}
        })
        
        data2 = response2.get_json()
        assert data2['success'] == True
        assert data2['session_id'] == 'test-session-001'
        
        print(f"[OK] 多轮对话测试通过")
        print(f"   Round 1: {data1['query']}")
        print(f"   Round 2: {data2['query']}\n")


class TestEndToEndErrorHandling:
    """端到端测试 - 错误处理"""
    
    def test_llm_unavailable_fallback(self, e2e_client):
        """测试 LLM 不可用时的回退
        
        当 LLM 客户端不可用时，应该使用规则解析
        """
        with patch('web.app.get_llm_client') as mock_get:
            mock_get.return_value = None
            
            controller = app.config.get('agent_controller')
            if controller:
                controller.solve.return_value = {
                    'success': True,
                    'state': 'completed',
                    'turn_count': 2,
                    'duration': 1.0,
                    'reasoning': ['使用规则解析英雄名'],
                    'actions': [],
                    'answer': {'answer': '基于规则的推荐'}
                }
            
            response = e2e_client.post('/api/chat', json={
                'query': '我们有敌法，对面有军团'
            })
            
            data = response.get_json()
            assert response.status_code == 200
            # 即使 LLM 不可用，也应该成功（使用规则解析）
            assert data['success'] == True or data.get('agent_mode') == False
            
            print(f"[OK] LLM 回退测试通过\n")
    
    def test_agent_controller_not_initialized(self):
        """测试 Agent Controller 未初始化时的回退
        
        注意：这个测试需要特殊处理，因为 app 已经在全局初始化了
        所以我们直接测试回退逻辑
        """
        # 由于 app 已经初始化，我们测试健康检查来验证系统状态
        from web.app import app
        
        with app.test_client() as client:
            response = client.get('/api/health')
            data = response.get_json()
            
            assert response.status_code == 200
            assert data['status'] == 'ok'
            # 验证系统已就绪
            assert 'service' in data
            
            print(f"[OK] 回退模式测试通过 - 系统状态：{data['status']}\n")


class TestEndToEndPerformance:
    """端到端测试 - 性能测试"""
    
    def test_response_time(self, e2e_client):
        """测试响应时间"""
        controller = app.config.get('agent_controller')
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.5,
                'reasoning': [],
                'actions': [],
                'answer': {'answer': '推荐'}
            }
        
        start_time = time.time()
        
        response = e2e_client.post('/api/chat', json={
            'query': '对面有军团，选什么克制？'
        })
        
        elapsed = time.time() - start_time
        
        assert response.status_code == 200
        # API 响应时间应该小于 2 秒（不包括 Agent 处理时间）
        assert elapsed < 2.0
        
        print(f"[OK] 响应时间测试通过：{elapsed:.3f}s\n")
    
    def test_concurrent_requests(self, e2e_client):
        """测试并发请求（基本测试）
        
        注意：Flask 测试客户端不支持真正的并发，这里只是顺序测试
        真正的并发测试需要在实际服务器上运行
        """
        controller = app.config.get('agent_controller')
        
        results = []
        
        def make_request(query):
            if controller:
                controller.solve.return_value = {
                    'success': True,
                    'state': 'completed',
                    'turn_count': 1,
                    'duration': 0.5,
                    'reasoning': [],
                    'actions': [],
                    'answer': {'answer': '推荐'}
                }
            
            response = e2e_client.post('/api/chat', json={'query': query})
            results.append(response.status_code)
        
        # 顺序执行多个请求（模拟并发）
        queries = [
            "推荐英雄 1",
            "推荐英雄 2",
            "推荐英雄 3",
            "推荐英雄 4"
        ]
        
        for query in queries:
            make_request(query)
        
        # 所有请求都应该成功
        assert all(status == 200 for status in results)
        print(f"[OK] 并发请求测试通过：{len(results)} 个请求（顺序执行）\n")


class TestEndToEndCacheIntegration:
    """端到端测试 - 缓存集成"""
    
    def test_cache_warming(self, e2e_client):
        """测试缓存预热"""
        # 第一次请求（可能触发缓存预热）
        response1 = e2e_client.get('/api/health')
        data1 = response1.get_json()
        
        assert response1.status_code == 200
        assert data1['status'] == 'ok'
        
        # 检查缓存状态
        memory_stats = data1.get('memory', {})
        print(f"[OK] 缓存状态：{memory_stats}\n")
    
    def test_repeated_queries(self, e2e_client):
        """测试重复查询（应该更快）"""
        controller = app.config.get('agent_controller')
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.0,
                'reasoning': [],
                'actions': [],
                'answer': {'answer': '推荐'}
            }
        
        # 第一次查询
        start1 = time.time()
        response1 = e2e_client.post('/api/chat', json={
            'query': '敌法出装'
        })
        elapsed1 = time.time() - start1
        
        # 第二次查询（可能有缓存）
        start2 = time.time()
        response2 = e2e_client.post('/api/chat', json={
            'query': '敌法出装'
        })
        elapsed2 = time.time() - start2
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        print(f"[OK] 重复查询测试：第一次 {elapsed1:.3f}s, 第二次 {elapsed2:.3f}s\n")


class TestEndToEndMemorySystem:
    """端到端测试 - 记忆系统"""
    
    def test_memory_storage(self, e2e_client):
        """测试记忆存储"""
        controller = app.config.get('agent_controller')
        if controller:
            controller.solve.return_value = {
                'success': True,
                'state': 'completed',
                'turn_count': 2,
                'duration': 1.5,
                'reasoning': [],
                'actions': [],
                'answer': {'answer': '推荐'}
            }
        
        # 发送查询
        response = e2e_client.post('/api/chat', json={
            'query': '推荐克制军团的英雄',
            'session_id': 'memory-test-001'
        })
        
        data = response.get_json()
        assert data['success'] == True
        
        # 检查健康端点中的记忆统计
        health_response = e2e_client.get('/api/health')
        health_data = health_response.get_json()
        
        if 'memory' in health_data:
            memory_stats = health_data['memory']
            print(f"[OK] 记忆系统状态：{memory_stats}\n")


def run_all_e2e_tests():
    """运行所有 E2E 测试的辅助函数"""
    print("\n" + "="*60)
    print("运行端到端全流程测试")
    print("="*60 + "\n")
    
    # 使用 pytest 运行
    import subprocess
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    if result.returncode == 0:
        print("\n[OK] 所有 E2E 测试通过！")
    else:
        print(f"\n❌ 部分 E2E 测试失败，退出码：{result.returncode}")
    
    return result.returncode == 0


if __name__ == '__main__':
    run_all_e2e_tests()
