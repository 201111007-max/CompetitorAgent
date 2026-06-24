"""推荐查询工具单元测试"""

import pytest
from unittest.mock import Mock, MagicMock
from tools.recommendation_tools import RecommendationQueryTool, RecommendationStatusTool, create_recommendation_tools


class TestRecommendationQueryTool:
    """推荐查询工具测试类"""

    def test_initialization(self):
        """测试推荐查询工具初始化"""
        decision_fusion = Mock()
        state_manager = Mock()
        event_queue = Mock()
        
        tool = RecommendationQueryTool(decision_fusion, state_manager, event_queue)
        
        assert tool.name == "get_recommendation"
        assert tool.decision_fusion == decision_fusion
        assert tool.state_manager == state_manager
        assert tool.event_queue == event_queue
        assert tool.category == "recommendation"

    def test_get_recommendation_success(self):
        """测试成功获取推荐"""
        # Mock 依赖
        decision_fusion = Mock()
        recommendation = Mock()
        recommendation.recommendation = "建议回城补给"
        recommendation.confidence = 0.8
        recommendation.sources = ["rule"]
        decision_fusion.generate_recommendation.return_value = recommendation
        
        state_manager = Mock()
        state = Mock()
        state.to_dict.return_value = {"health": 150, "max_health": 1000}
        state_manager.get_state.return_value = state
        
        event_queue = Mock()
        event = Mock()
        event.event_type = "low_health"
        event_queue.get_recent.return_value = [event]
        
        # 创建工具
        tool = RecommendationQueryTool(decision_fusion, state_manager, event_queue)
        
        # 调用工具
        result = tool._get_recommendation()
        
        # 验证结果
        assert result["available"] is True
        assert result["recommendation"] == "建议回城补给"
        assert result["confidence"] == 0.8
        assert result["sources"] == ["rule"]
        
        # 验证决策融合器被调用
        decision_fusion.generate_recommendation.assert_called_once()

    def test_get_recommendation_no_state(self):
        """测试无游戏状态时获取推荐"""
        decision_fusion = Mock()
        state_manager = Mock()
        state_manager.get_state.return_value = None
        
        event_queue = Mock()
        
        tool = RecommendationQueryTool(decision_fusion, state_manager, event_queue)
        
        result = tool._get_recommendation()
        
        assert result["available"] is False
        assert "不在游戏中" in result["message"]

    def test_get_recommendation_no_events(self):
        """测试无事件时获取推荐"""
        decision_fusion = Mock()
        state_manager = Mock()
        state = Mock()
        state.to_dict.return_value = {"health": 500, "max_health": 1000}
        state_manager.get_state.return_value = state
        
        event_queue = Mock()
        event_queue.get_recent.return_value = []
        
        tool = RecommendationQueryTool(decision_fusion, state_manager, event_queue)
        
        result = tool._get_recommendation()
        
        assert result["available"] is False
        assert "暂无游戏事件" in result["message"]

    def test_get_recommendation_no_result(self):
        """测试无推荐结果时获取推荐"""
        decision_fusion = Mock()
        decision_fusion.generate_recommendation.return_value = None
        
        state_manager = Mock()
        state = Mock()
        state.to_dict.return_value = {"health": 500, "max_health": 1000}
        state_manager.get_state.return_value = state
        
        event_queue = Mock()
        event = Mock()
        event.event_type = "general_query"
        event_queue.get_recent.return_value = [event]
        
        tool = RecommendationQueryTool(decision_fusion, state_manager, event_queue)
        
        result = tool._get_recommendation()
        
        assert result["available"] is False
        assert "暂无推荐建议" in result["message"]

    def test_get_recommendation_exception(self):
        """测试获取推荐时发生异常"""
        decision_fusion = Mock()
        decision_fusion.generate_recommendation.side_effect = Exception("测试异常")
        
        state_manager = Mock()
        state = Mock()
        state.to_dict.return_value = {"health": 500, "max_health": 1000}
        state_manager.get_state.return_value = state
        
        event_queue = Mock()
        event = Mock()
        event.event_type = "low_health"
        event_queue.get_recent.return_value = [event]
        
        tool = RecommendationQueryTool(decision_fusion, state_manager, event_queue)
        
        result = tool._get_recommendation()
        
        assert result["available"] is False
        assert "发生错误" in result["message"]
        assert "测试异常" in result["message"]


class TestRecommendationStatusTool:
    """推荐状态工具测试类"""

    def test_initialization(self):
        """测试推荐状态工具初始化"""
        event_trigger = Mock()
        
        tool = RecommendationStatusTool(event_trigger)
        
        assert tool.name == "get_recommendation_status"
        assert tool.event_trigger == event_trigger
        assert tool.category == "recommendation"

    def test_get_status_success(self):
        """测试成功获取状态"""
        event_trigger = Mock()
        event_trigger.get_status.return_value = {
            "enabled": True,
            "running": True,
            "event_queue_set": True,
            "decision_fusion_set": True,
            "state_manager_set": True,
            "push_callback_set": True,
            "cooldowns": {"low_health": 1234567890}
        }
        
        tool = RecommendationStatusTool(event_trigger)
        
        result = tool._get_status()
        
        assert result["available"] is True
        assert result["status"]["enabled"] is True
        assert result["status"]["running"] is True

    def test_get_status_no_trigger(self):
        """测试无事件触发器时获取状态"""
        tool = RecommendationStatusTool(None)
        
        result = tool._get_status()
        
        assert result["available"] is False
        assert "未初始化" in result["message"]

    def test_get_status_exception(self):
        """测试获取状态时发生异常"""
        event_trigger = Mock()
        event_trigger.get_status.side_effect = Exception("测试异常")
        
        tool = RecommendationStatusTool(event_trigger)
        
        result = tool._get_status()
        
        assert result["available"] is False
        assert "发生错误" in result["message"]
        assert "测试异常" in result["message"]


class TestCreateRecommendationTools:
    """创建推荐工具函数测试类"""

    def test_create_with_all_dependencies(self):
        """测试使用所有依赖创建工具"""
        decision_fusion = Mock()
        state_manager = Mock()
        event_trigger = Mock()
        
        tools = create_recommendation_tools(decision_fusion, state_manager, event_trigger)
        
        assert len(tools) == 2
        assert isinstance(tools[0], RecommendationQueryTool)
        assert isinstance(tools[1], RecommendationStatusTool)

    def test_create_without_state_manager(self):
        """测试无状态管理器时创建工具"""
        decision_fusion = Mock()
        event_trigger = Mock()
        
        tools = create_recommendation_tools(decision_fusion, state_manager=None, event_trigger=event_trigger)
        
        assert len(tools) == 2
        assert isinstance(tools[0], RecommendationQueryTool)
        assert isinstance(tools[1], RecommendationStatusTool)

    def test_create_without_event_trigger(self):
        """测试无事件触发器时创建工具"""
        decision_fusion = Mock()
        state_manager = Mock()
        
        tools = create_recommendation_tools(decision_fusion, state_manager, event_trigger=None)
        
        assert len(tools) == 1
        assert isinstance(tools[0], RecommendationQueryTool)

    def test_create_without_decision_fusion(self):
        """测试无决策融合器时创建工具"""
        state_manager = Mock()
        event_trigger = Mock()
        
        tools = create_recommendation_tools(None, state_manager, event_trigger)
        
        assert len(tools) == 1
        assert isinstance(tools[0], RecommendationStatusTool)

    def test_create_minimal(self):
        """测试最小化创建工具"""
        decision_fusion = Mock()
        
        tools = create_recommendation_tools(decision_fusion, state_manager=None, event_trigger=None)
        
        assert len(tools) == 1
        assert isinstance(tools[0], RecommendationQueryTool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
