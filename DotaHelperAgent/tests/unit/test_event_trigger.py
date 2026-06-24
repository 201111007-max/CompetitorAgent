"""事件触发器单元测试"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from core.event_trigger import EventTrigger
from gsi.event_queue import GSIEventQueue


class TestEventTrigger:
    """事件触发器测试类"""

    def test_initialization(self):
        """测试事件触发器初始化"""
        config = {
            "enabled": True,
            "triggers": {
                "low_health": {"enabled": True, "cooldown": 60, "threshold": 0.2}
            }
        }
        trigger = EventTrigger(config)
        
        assert trigger.enabled is True
        assert trigger.event_queue is None
        assert trigger.decision_fusion is None
        assert trigger.state_manager is None
        assert trigger._push_callback is None
        assert trigger._running is False

    def test_set_event_queue(self):
        """测试设置事件队列"""
        trigger = EventTrigger()
        event_queue = Mock(spec=GSIEventQueue)
        trigger.set_event_queue(event_queue)
        
        assert trigger.event_queue == event_queue

    def test_set_decision_fusion(self):
        """测试设置决策融合器"""
        trigger = EventTrigger()
        decision_fusion = Mock()
        trigger.set_decision_fusion(decision_fusion)
        
        assert trigger.decision_fusion == decision_fusion

    def test_set_state_manager(self):
        """测试设置状态管理器"""
        trigger = EventTrigger()
        state_manager = Mock()
        trigger.set_state_manager(state_manager)
        
        assert trigger.state_manager == state_manager

    def test_set_push_callback(self):
        """测试设置推送回调"""
        trigger = EventTrigger()
        callback = Mock()
        trigger.set_push_callback(callback)
        
        assert trigger._push_callback == callback

    def test_should_trigger_disabled_event(self):
        """测试禁用事件的触发判断"""
        config = {
            "triggers": {
                "low_health": {"enabled": False}
            }
        }
        trigger = EventTrigger(config)
        
        event = Mock()
        event.event_type = "low_health"
        
        assert trigger._should_trigger(event) is False

    def test_should_trigger_cooldown(self):
        """测试冷却时间判断"""
        config = {
            "triggers": {
                "low_health": {"enabled": True, "cooldown": 60}
            }
        }
        trigger = EventTrigger(config)
        
        event = Mock()
        event.event_type = "low_health"
        
        # 第一次应该触发
        assert trigger._should_trigger(event) is True
        
        # 更新冷却时间
        trigger._cooldowns["low_health"] = time.time()
        
        # 第二次不应该触发（在冷却期内）
        assert trigger._should_trigger(event) is False

    def test_should_trigger_after_cooldown(self):
        """测试冷却时间后触发"""
        config = {
            "triggers": {
                "low_health": {"enabled": True, "cooldown": 1}  # 1秒冷却
            }
        }
        trigger = EventTrigger(config)
        
        event = Mock()
        event.event_type = "low_health"
        
        # 第一次触发
        assert trigger._should_trigger(event) is True
        trigger._cooldowns["low_health"] = time.time()
        
        # 等待冷却时间结束
        time.sleep(1.1)
        
        # 应该可以再次触发
        assert trigger._should_trigger(event) is True

    def test_check_threshold_low_health(self):
        """测试低血量阈值检查"""
        config = {
            "triggers": {
                "low_health": {"threshold": 0.2}
            }
        }
        trigger = EventTrigger(config)
        
        # Mock 状态管理器
        state_manager = Mock()
        state = Mock()
        state.health = 150
        state.max_health = 1000
        state.to_dict.return_value = {"health": 150, "max_health": 1000}
        state_manager.get_state.return_value = state
        trigger.set_state_manager(state_manager)
        
        event = Mock()
        event.event_type = "low_health"
        
        # 血量低于阈值，应该触发
        assert trigger._check_threshold(event, 0.2) is True
        
        # 血量高于阈值，不应该触发
        state.health = 300
        assert trigger._check_threshold(event, 0.2) is False

    def test_check_threshold_low_mana(self):
        """测试低魔法阈值检查"""
        config = {
            "triggers": {
                "low_mana": {"threshold": 0.1}
            }
        }
        trigger = EventTrigger(config)
        
        # Mock 状态管理器
        state_manager = Mock()
        state = Mock()
        state.mana = 50
        state.max_mana = 1000
        state.to_dict.return_value = {"mana": 50, "max_mana": 1000}
        state_manager.get_state.return_value = state
        trigger.set_state_manager(state_manager)
        
        event = Mock()
        event.event_type = "low_mana"
        
        # 魔法低于阈值，应该触发
        assert trigger._check_threshold(event, 0.1) is True
        
        # 魔法高于阈值，不应该触发
        state.mana = 200
        assert trigger._check_threshold(event, 0.1) is False

    def test_trigger_recommendation(self):
        """测试触发推荐"""
        trigger = EventTrigger()
        
        # Mock 依赖
        state_manager = Mock()
        state = Mock()
        state.to_dict.return_value = {"health": 150, "max_health": 1000}
        state_manager.get_state.return_value = state
        trigger.set_state_manager(state_manager)
        
        decision_fusion = Mock()
        recommendation = Mock()
        recommendation.recommendation = "建议回城补给"
        recommendation.confidence = 0.8
        recommendation.sources = ["rule"]
        recommendation.conflict_detected = False
        recommendation.to_dict.return_value = {
            "recommendation": "建议回城补给",
            "confidence": 0.8,
            "sources": ["rule"],
            "conflict_detected": False
        }
        decision_fusion.generate_recommendation.return_value = recommendation
        trigger.set_decision_fusion(decision_fusion)
        
        push_callback = Mock()
        trigger.set_push_callback(push_callback)
        
        # 触发推荐
        event = Mock()
        event.event_type = "low_health"
        event.message = "血量过低"
        
        trigger._trigger_recommendation(event)
        
        # 验证决策融合器被调用
        decision_fusion.generate_recommendation.assert_called_once()
        
        # 验证推送回调被调用
        push_callback.assert_called_once()
        call_args = push_callback.call_args[0][0]
        assert call_args["type"] == "recommendation"
        assert call_args["event_type"] == "low_health"
        assert call_args["recommendation"]["recommendation"] == "建议回城补给"

    def test_trigger_recommendation_no_result(self):
        """测试触发推荐但无结果"""
        trigger = EventTrigger()
        
        # Mock 依赖
        state_manager = Mock()
        state_manager.get_state.return_value = None
        trigger.set_state_manager(state_manager)
        
        decision_fusion = Mock()
        decision_fusion.generate_recommendation.return_value = None
        trigger.set_decision_fusion(decision_fusion)
        
        push_callback = Mock()
        trigger.set_push_callback(push_callback)
        
        # 触发推荐
        event = Mock()
        event.event_type = "general_query"
        event.message = "一般查询"
        
        trigger._trigger_recommendation(event)
        
        # 验证推送回调未被调用
        push_callback.assert_not_called()

    def test_get_status(self):
        """测试获取状态"""
        trigger = EventTrigger()
        
        # Mock 依赖
        trigger.event_queue = Mock()
        trigger.decision_fusion = Mock()
        trigger.state_manager = Mock()
        trigger._push_callback = Mock()
        trigger._cooldowns = {"low_health": time.time()}
        
        status = trigger.get_status()
        
        assert status["enabled"] is True
        assert status["running"] is False
        assert status["event_queue_set"] is True
        assert status["decision_fusion_set"] is True
        assert status["state_manager_set"] is True
        assert status["push_callback_set"] is True
        assert "low_health" in status["cooldowns"]

    def test_start_without_event_queue(self):
        """测试未设置事件队列时启动"""
        trigger = EventTrigger()
        
        # 不应该抛出异常
        trigger.start()
        
        assert trigger._running is False

    def test_start_without_decision_fusion(self):
        """测试未设置决策融合器时启动"""
        trigger = EventTrigger()
        trigger.event_queue = Mock()
        
        # 不应该抛出异常
        trigger.start()
        
        assert trigger._running is False

    def test_start_success(self):
        """测试成功启动"""
        trigger = EventTrigger()
        
        # Mock 依赖
        event_queue = Mock()
        subscriber = Mock()
        event_queue.subscribe.return_value = subscriber
        trigger.set_event_queue(event_queue)
        
        decision_fusion = Mock()
        trigger.set_decision_fusion(decision_fusion)
        
        # 启动
        trigger.start()
        
        # 验证状态
        assert trigger._running is True
        assert trigger._thread is not None
        assert trigger._subscriber == subscriber
        
        # 停止
        trigger.stop()

    def test_stop(self):
        """测试停止"""
        trigger = EventTrigger()
        
        # Mock 依赖
        event_queue = Mock()
        subscriber = Mock()
        event_queue.subscribe.return_value = subscriber
        trigger.set_event_queue(event_queue)
        
        decision_fusion = Mock()
        trigger.set_decision_fusion(decision_fusion)
        
        # 启动
        trigger.start()
        assert trigger._running is True
        
        # 停止
        trigger.stop()
        
        # 验证状态
        assert trigger._running is False
        assert trigger._thread is None
        assert trigger._subscriber is None
        
        # 验证取消订阅
        event_queue.unsubscribe.assert_called_once_with(subscriber)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
