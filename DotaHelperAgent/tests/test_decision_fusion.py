"""
决策融合器单元测试

测试覆盖：
- 融合器初始化
- 多引擎调用
- 加权平均融合
- 最高置信度融合
- 冲突检测
- 冲突解决
- 置信度过滤
"""

import pytest
from unittest.mock import Mock, MagicMock
from core.decision.decision_fusion import DecisionFusion, FusedRecommendation, ConflictResolution


class TestDecisionFusion:
    """决策融合器测试类"""
    
    def test_initialization(self):
        """测试融合器初始化"""
        config = {
            "conflict_resolution": "weighted_average",
            "min_confidence": 0.5
        }
        fusion = DecisionFusion(config)
        
        assert fusion is not None
        assert fusion.rule_engine is not None
        assert fusion.data_engine is not None
        assert fusion.llm_engine is not None
        assert fusion.conflict_resolution == ConflictResolution.WEIGHTED_AVERAGE
        assert fusion.min_confidence == 0.5
    
    def test_initialization_default_config(self):
        """测试默认配置初始化"""
        fusion = DecisionFusion()
        
        assert fusion.conflict_resolution == ConflictResolution.WEIGHTED_AVERAGE
        assert fusion.min_confidence == 0.5
    
    def test_set_data_engine_dependencies(self):
        """测试设置数据引擎依赖"""
        fusion = DecisionFusion()
        
        mock_api_client = Mock()
        mock_cache = Mock()
        
        fusion.set_data_engine_dependencies(mock_api_client, mock_cache)
        
        assert fusion.data_engine.api_client == mock_api_client
        assert fusion.data_engine.cache == mock_cache
    
    def test_set_llm_engine_dependencies(self):
        """测试设置 LLM 引擎依赖"""
        fusion = DecisionFusion()
        
        mock_llm_client = Mock()
        mock_knowledge = Mock()
        
        fusion.set_llm_engine_dependencies(mock_llm_client, mock_knowledge)
        
        assert fusion.llm_engine.llm_client == mock_llm_client
        assert fusion.llm_engine.knowledge_system == mock_knowledge
    
    def test_generate_recommendation_rule_only(self):
        """测试仅规则引擎产生推荐"""
        fusion = DecisionFusion()
        
        # Mock 规则引擎
        fusion.rule_engine.get_recommendations = Mock(return_value=[
            {
                "engine": "rule",
                "recommendation": "血量过低，建议回城",
                "confidence": 0.9
            }
        ])
        
        # Mock 数据引擎和 LLM 引擎返回 None
        fusion.data_engine.generate_recommendation = Mock(return_value=None)
        fusion.llm_engine.generate_recommendation = Mock(return_value=None)
        
        game_state = {"health": 200, "max_health": 1000}
        result = fusion.generate_recommendation("low_health", game_state)
        
        assert result is not None
        assert result.recommendation == "血量过低，建议回城"
        assert result.confidence >= 0.5
        assert "rule" in result.sources
    
    def test_generate_recommendation_multiple_engines(self):
        """测试多引擎产生推荐"""
        fusion = DecisionFusion()
        
        # Mock 规则引擎
        fusion.rule_engine.get_recommendations = Mock(return_value=[
            {
                "engine": "rule",
                "recommendation": "建议回城补给",
                "confidence": 0.9
            }
        ])
        
        # Mock 数据引擎
        mock_data_result = Mock()
        mock_data_result.to_dict.return_value = {
            "engine": "data",
            "recommendation": "根据数据，建议购买回复道具",
            "confidence": 0.8
        }
        fusion.data_engine.generate_recommendation = Mock(return_value=mock_data_result)
        
        # Mock LLM 引擎
        mock_llm_result = Mock()
        mock_llm_result.to_dict.return_value = {
            "engine": "llm",
            "recommendation": "综合分析，建议回城并购买装备",
            "confidence": 0.7
        }
        fusion.llm_engine.generate_recommendation = Mock(return_value=mock_llm_result)
        
        game_state = {"health": 200, "max_health": 1000}
        result = fusion.generate_recommendation("low_health", game_state)
        
        assert result is not None
        assert len(result.sources) == 3
        assert "rule" in result.sources
        assert "data" in result.sources
        assert "llm" in result.sources
    
    def test_generate_recommendation_no_results(self):
        """测试所有引擎均无推荐"""
        fusion = DecisionFusion()
        
        # 所有引擎返回空
        fusion.rule_engine.get_recommendations = Mock(return_value=[])
        fusion.data_engine.generate_recommendation = Mock(return_value=None)
        fusion.llm_engine.generate_recommendation = Mock(return_value=None)
        
        game_state = {"health": 800, "max_health": 1000}
        result = fusion.generate_recommendation("normal", game_state)
        
        assert result is None
    
    def test_generate_recommendation_below_min_confidence(self):
        """测试推荐置信度低于阈值"""
        fusion = DecisionFusion({"min_confidence": 0.8})
        
        # Mock 规则引擎返回低置信度推荐
        fusion.rule_engine.get_recommendations = Mock(return_value=[
            {
                "engine": "rule",
                "recommendation": "可能应该回城",
                "confidence": 0.3
            }
        ])
        
        fusion.data_engine.generate_recommendation = Mock(return_value=None)
        fusion.llm_engine.generate_recommendation = Mock(return_value=None)
        
        game_state = {"health": 200, "max_health": 1000}
        result = fusion.generate_recommendation("low_health", game_state)
        
        assert result is None
    
    def test_detect_conflict_no_conflict(self):
        """测试无冲突检测"""
        fusion = DecisionFusion()
        
        recommendations = [
            {"engine": "rule", "recommendation": "建议回城补给", "confidence": 0.9},
            {"engine": "data", "recommendation": "建议购买回复道具", "confidence": 0.8}
        ]
        
        conflict = fusion._detect_conflict(recommendations)
        
        assert conflict is False
    
    def test_detect_conflict_with_conflict(self):
        """测试冲突检测"""
        fusion = DecisionFusion()
        
        recommendations = [
            {"engine": "rule", "recommendation": "建议激进进攻", "confidence": 0.9},
            {"engine": "data", "recommendation": "建议保守撤退", "confidence": 0.8}
        ]
        
        conflict = fusion._detect_conflict(recommendations)
        
        assert conflict is True
    
    def test_resolve_conflict_max_confidence(self):
        """测试冲突解决（最高置信度）"""
        fusion = DecisionFusion()
        
        recommendations = [
            {"engine": "rule", "recommendation": "建议激进进攻", "confidence": 0.9},
            {"engine": "data", "recommendation": "建议保守撤退", "confidence": 0.6}
        ]
        
        result = fusion._resolve_conflict(recommendations)
        
        assert result.recommendation == "建议激进进攻"
        assert result.confidence == 0.9
        assert result.conflict_detected is True
    
    def test_fuse_by_max_confidence(self):
        """测试最高置信度融合"""
        fusion = DecisionFusion()
        
        recommendations = [
            {"engine": "rule", "recommendation": "建议1", "confidence": 0.7},
            {"engine": "data", "recommendation": "建议2", "confidence": 0.9},
            {"engine": "llm", "recommendation": "建议3", "confidence": 0.6}
        ]
        
        result = fusion._fuse_by_max_confidence(recommendations)
        
        assert result.recommendation == "建议2"
        assert result.confidence == 0.9
        assert result.sources == ["data"]
    
    def test_fuse_by_weighted_average(self):
        """测试加权平均融合"""
        fusion = DecisionFusion()
        
        recommendations = [
            {"engine": "rule", "recommendation": "建议1", "confidence": 0.7},
            {"engine": "data", "recommendation": "建议2", "confidence": 0.9},
            {"engine": "llm", "recommendation": "建议3", "confidence": 0.6}
        ]
        
        result = fusion._fuse_by_weighted_average(recommendations)
        
        # 加权平均置信度：(0.3*0.7 + 0.4*0.9 + 0.3*0.6) / (0.3+0.4+0.3)
        expected_confidence = (0.3*0.7 + 0.4*0.9 + 0.3*0.6) / 1.0
        assert abs(result.confidence - expected_confidence) < 0.01
        assert len(result.sources) == 3
        assert result.conflict_detected is False
    
    def test_fuse_by_weighted_average_single_engine(self):
        """测试单引擎加权平均融合"""
        fusion = DecisionFusion()
        
        recommendations = [
            {"engine": "rule", "recommendation": "建议1", "confidence": 0.8}
        ]
        
        result = fusion._fuse_by_weighted_average(recommendations)
        
        assert result.confidence == 0.8
        assert result.sources == ["rule"]
    
    def test_engine_call_exception_handling(self):
        """测试引擎调用异常处理"""
        fusion = DecisionFusion()
        
        # Mock 规则引擎抛出异常
        fusion.rule_engine.get_recommendations = Mock(side_effect=Exception("规则引擎错误"))
        
        # 其他引擎正常
        fusion.data_engine.generate_recommendation = Mock(return_value=None)
        fusion.llm_engine.generate_recommendation = Mock(return_value=None)
        
        game_state = {"health": 200, "max_health": 1000}
        
        # 不应该抛出异常
        result = fusion.generate_recommendation("low_health", game_state)
        
        assert result is None


class TestFusedRecommendation:
    """融合推荐结果测试类"""
    
    def test_creation(self):
        """测试推荐结果创建"""
        rec = FusedRecommendation(
            recommendation="建议回城",
            confidence=0.85,
            sources=["rule", "data"],
            all_recommendations=[],
            conflict_detected=False
        )
        
        assert rec.recommendation == "建议回城"
        assert rec.confidence == 0.85
        assert rec.sources == ["rule", "data"]
        assert rec.conflict_detected is False
    
    def test_to_dict(self):
        """测试转换为字典"""
        rec = FusedRecommendation(
            recommendation="建议进攻",
            confidence=0.9,
            sources=["rule"],
            all_recommendations=[{"engine": "rule", "confidence": 0.9}],
            conflict_detected=True
        )
        
        rec_dict = rec.to_dict()
        
        assert rec_dict["recommendation"] == "建议进攻"
        assert rec_dict["confidence"] == 0.9
        assert rec_dict["sources"] == ["rule"]
        assert rec_dict["conflict_detected"] is True
        assert len(rec_dict["all_recommendations"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
