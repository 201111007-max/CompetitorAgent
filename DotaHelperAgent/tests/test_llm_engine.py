"""
LLM 增强引擎单元测试

测试覆盖：
- 引擎初始化
- 知识库查询
- Prompt 构建
- LLM 调用
- 推荐生成
- 异常处理
"""

import pytest
from unittest.mock import Mock, MagicMock
from core.decision.llm_engine import LLMEngine, LLMRecommendation


class TestLLMEngine:
    """LLM 增强引擎测试类"""
    
    def test_initialization(self):
        """测试引擎初始化"""
        engine = LLMEngine()
        assert engine is not None
        assert engine.llm_client is None
        assert engine.knowledge_system is None
    
    def test_set_llm_client(self):
        """测试设置 LLM 客户端"""
        engine = LLMEngine()
        mock_client = Mock()
        engine.set_llm_client(mock_client)
        assert engine.llm_client == mock_client
    
    def test_set_knowledge_system(self):
        """测试设置知识库系统"""
        engine = LLMEngine()
        mock_knowledge = Mock()
        engine.set_knowledge_system(mock_knowledge)
        assert engine.knowledge_system == mock_knowledge
    
    def test_generate_recommendation_success(self):
        """测试成功生成推荐"""
        engine = LLMEngine()
        
        # Mock LLM 客户端
        mock_llm = Mock()
        mock_llm.chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "建议购买黑皇杖防止被控制"
                    }
                }
            ]
        }
        engine.set_llm_client(mock_llm)
        
        # Mock 知识库系统
        mock_knowledge = Mock()
        mock_knowledge.query.return_value = [
            {
                "title": "PA 出装攻略",
                "content": "相位鞋、狂战斧、黑皇杖是核心装备"
            }
        ]
        engine.set_knowledge_system(mock_knowledge)
        
        # 测试数据
        event_type = "item_purchase"
        game_state = {
            "hero_name": "幻影刺客",
            "health": 800,
            "max_health": 1000,
            "mana": 200,
            "max_mana": 300,
            "gold": 2500,
            "game_time": 1200,
            "kills": 5,
            "deaths": 2,
            "assists": 8
        }
        
        result = engine.generate_recommendation(event_type, game_state)
        
        assert result is not None
        assert result.engine == "llm"
        assert result.recommendation == "建议购买黑皇杖防止被控制"
        assert result.confidence == 0.6
        assert "PA 出装攻略" in result.knowledge_sources
    
    def test_generate_recommendation_no_client(self):
        """测试无 LLM 客户端时返回 None"""
        engine = LLMEngine()
        mock_knowledge = Mock()
        engine.set_knowledge_system(mock_knowledge)
        
        result = engine.generate_recommendation("test", {})
        
        assert result is None
    
    def test_generate_recommendation_no_knowledge(self):
        """测试无知识库时返回 None"""
        engine = LLMEngine()
        mock_llm = Mock()
        engine.set_llm_client(mock_llm)
        
        result = engine.generate_recommendation("test", {})
        
        assert result is None
    
    def test_query_knowledge_success(self):
        """测试知识库查询成功"""
        engine = LLMEngine()
        
        mock_knowledge = Mock()
        mock_knowledge.query.return_value = [
            {"title": "攻略1", "content": "内容1"},
            {"title": "攻略2", "content": "内容2"}
        ]
        engine.set_knowledge_system(mock_knowledge)
        
        results = engine._query_knowledge("幻影刺客", "item_purchase")
        
        assert len(results) == 2
        mock_knowledge.query.assert_called_once()
    
    def test_query_knowledge_no_system(self):
        """测试无知识库系统时返回空列表"""
        engine = LLMEngine()
        
        results = engine._query_knowledge("幻影刺客", "test")
        
        assert results == []
    
    def test_query_knowledge_exception(self):
        """测试知识库查询异常"""
        engine = LLMEngine()
        
        mock_knowledge = Mock()
        mock_knowledge.query.side_effect = Exception("查询失败")
        engine.set_knowledge_system(mock_knowledge)
        
        results = engine._query_knowledge("幻影刺客", "test")
        
        assert results == []
    
    def test_build_prompt(self):
        """测试 Prompt 构建"""
        engine = LLMEngine()
        
        event_type = "low_health"
        game_state = {
            "hero_name": "幻影刺客",
            "health": 200,
            "max_health": 1000,
            "mana": 100,
            "max_mana": 300,
            "gold": 1500,
            "game_time": 900,
            "kills": 3,
            "deaths": 5,
            "assists": 2
        }
        knowledge = [
            {"title": "PA 生存攻略", "content": "低血量时应该回城补给"}
        ]
        
        prompt = engine._build_prompt(event_type, game_state, knowledge)
        
        assert "幻影刺客" in prompt
        assert "200/1000" in prompt
        assert "1500" in prompt
        assert "PA 生存攻略" in prompt
        assert "低血量" in event_type
    
    def test_format_knowledge_with_content(self):
        """测试格式化有内容的知识"""
        engine = LLMEngine()
        
        knowledge = [
            {"title": "攻略1", "content": "内容1"},
            {"title": "攻略2", "content": "内容2"}
        ]
        
        result = engine._format_knowledge(knowledge)
        
        assert "攻略1" in result
        assert "内容1" in result
        assert "攻略2" in result
        assert "内容2" in result
    
    def test_format_knowledge_empty(self):
        """测试格式化空知识"""
        engine = LLMEngine()
        
        result = engine._format_knowledge([])
        
        assert result == "暂无相关攻略知识"
    
    def test_format_knowledge_long_content(self):
        """测试格式化长内容（截断）"""
        engine = LLMEngine()
        
        long_content = "A" * 300
        knowledge = [
            {"title": "长攻略", "content": long_content}
        ]
        
        result = engine._format_knowledge(knowledge)
        
        assert "..." in result
        assert len(result) < 300
    
    def test_call_llm_success(self):
        """测试 LLM 调用成功"""
        engine = LLMEngine()
        
        mock_llm = Mock()
        mock_llm.chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "建议回城补给"
                    }
                }
            ]
        }
        engine.set_llm_client(mock_llm)
        
        result = engine._call_llm("测试 Prompt")
        
        assert result == "建议回城补给"
        mock_llm.chat_completion.assert_called_once()
    
    def test_call_llm_no_client(self):
        """测试无 LLM 客户端时返回 None"""
        engine = LLMEngine()
        
        result = engine._call_llm("测试 Prompt")
        
        assert result is None
    
    def test_call_llm_exception(self):
        """测试 LLM 调用异常"""
        engine = LLMEngine()
        
        mock_llm = Mock()
        mock_llm.chat_completion.side_effect = Exception("API 调用失败")
        engine.set_llm_client(mock_llm)
        
        result = engine._call_llm("测试 Prompt")
        
        assert result is None
    
    def test_call_llm_invalid_response(self):
        """测试 LLM 返回无效响应"""
        engine = LLMEngine()
        
        mock_llm = Mock()
        mock_llm.chat_completion.return_value = {}  # 无效响应
        engine.set_llm_client(mock_llm)
        
        result = engine._call_llm("测试 Prompt")
        
        assert result is None


class TestLLMRecommendation:
    """LLM 推荐结果测试类"""
    
    def test_creation(self):
        """测试推荐结果创建"""
        rec = LLMRecommendation(
            engine="llm",
            recommendation="建议购买 BKB",
            confidence=0.6,
            knowledge_sources=["PA 攻略"]
        )
        
        assert rec.engine == "llm"
        assert rec.recommendation == "建议购买 BKB"
        assert rec.confidence == 0.6
        assert rec.knowledge_sources == ["PA 攻略"]
    
    def test_to_dict(self):
        """测试转换为字典"""
        rec = LLMRecommendation(
            engine="llm",
            recommendation="建议回城",
            confidence=0.7,
            knowledge_sources=["攻略1", "攻略2"]
        )
        
        rec_dict = rec.to_dict()
        
        assert rec_dict["engine"] == "llm"
        assert rec_dict["recommendation"] == "建议回城"
        assert rec_dict["confidence"] == 0.7
        assert rec_dict["knowledge_sources"] == ["攻略1", "攻略2"]
    
    def test_default_knowledge_sources(self):
        """测试默认 knowledge_sources 字段"""
        rec = LLMRecommendation(
            engine="llm",
            recommendation="测试",
            confidence=0.5
        )
        
        assert rec.knowledge_sources == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
