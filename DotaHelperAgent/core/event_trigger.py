"""
事件触发器 - 订阅 GSI 事件队列，判断是否触发推荐

职责：
- 订阅 GSI 事件队列
- 根据配置过滤事件
- 实现冷却控制（避免频繁推荐）
- 检查阈值条件
- 调用决策融合器生成推荐
- 推送推荐结果到 SSE

配置项：
- enabled: 是否启用触发器
- cooldown: 冷却时间（秒）
- threshold: 阈值条件
"""

from typing import Dict, Any, Optional, List
import time
import queue
import threading
import logging

logger = logging.getLogger(__name__)


class EventTrigger:
    """事件触发器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化事件触发器
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        
        # 事件队列和订阅
        self.event_queue = None
        self._subscriber: Optional[queue.Queue] = None
        
        # 决策融合器
        self.decision_fusion = None
        
        # 状态管理器（用于获取游戏状态）
        self.state_manager = None
        
        # 冷却控制
        self._cooldowns: Dict[str, float] = {}
        
        # 推送回调
        self._push_callback = None
        
        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        logger.info(f"事件触发器初始化完成，启用状态: {self.enabled}")
    
    def set_event_queue(self, event_queue):
        """
        设置 GSI 事件队列
        
        Args:
            event_queue: GSI 事件队列实例
        """
        self.event_queue = event_queue
        logger.info("事件触发器设置事件队列")
    
    def set_decision_fusion(self, decision_fusion):
        """
        设置决策融合器
        
        Args:
            decision_fusion: 决策融合器实例
        """
        self.decision_fusion = decision_fusion
        logger.info("事件触发器设置决策融合器")
    
    def set_state_manager(self, state_manager):
        """
        设置状态管理器
        
        Args:
            state_manager: GSI 状态管理器实例
        """
        self.state_manager = state_manager
        logger.info("事件触发器设置状态管理器")
    
    def set_push_callback(self, callback):
        """
        设置推送回调
        
        Args:
            callback: 推送回调函数
        """
        self._push_callback = callback
        logger.info("事件触发器设置推送回调")
    
    def start(self):
        """启动事件监听"""
        if not self.enabled:
            logger.info("事件触发器未启用，跳过启动")
            return
        
        if not self.event_queue:
            logger.error("事件队列未设置，无法启动")
            return
        
        if not self.decision_fusion:
            logger.error("决策融合器未设置，无法启动")
            return
        
        if self._running:
            logger.warning("事件触发器已在运行")
            return
        
        # 订阅事件队列
        self._subscriber = self.event_queue.subscribe()
        
        # 启动监听线程
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        
        logger.info("事件触发器启动成功")
    
    def stop(self):
        """停止事件监听"""
        if not self._running:
            return
        
        self._running = False
        
        # 取消订阅
        if self._subscriber and self.event_queue:
            self.event_queue.unsubscribe(self._subscriber)
            self._subscriber = None
        
        # 等待线程结束
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        
        logger.info("事件触发器已停止")
    
    def _listen_loop(self):
        """事件监听循环"""
        logger.info("事件监听循环启动")
        
        while self._running:
            try:
                # 从队列获取事件（带超时）
                event = self._subscriber.get(timeout=1.0)
                
                if event and self._should_trigger(event):
                    self._trigger_recommendation(event)
            
            except queue.Empty:
                # 超时无事件，继续循环
                continue
            
            except Exception as e:
                logger.error(f"事件监听循环异常: {e}")
                time.sleep(1.0)
        
        logger.info("事件监听循环结束")
    
    def _should_trigger(self, event) -> bool:
        """
        判断是否应该触发推荐
        
        Args:
            event: GSI 事件
        
        Returns:
            是否应该触发
        """
        event_type = event.event_type
        
        # 1. 检查事件类型是否在配置中启用
        triggers_config = self.config.get("triggers", {})
        trigger_config = triggers_config.get(event_type, {})
        
        if not trigger_config.get("enabled", True):
            logger.debug(f"事件类型 {event_type} 未启用")
            return False
        
        # 2. 检查冷却时间
        cooldown = trigger_config.get("cooldown", 60)
        last_trigger = self._cooldowns.get(event_type, 0)
        current_time = time.time()
        
        if current_time - last_trigger < cooldown:
            logger.debug(f"事件类型 {event_type} 在冷却期内")
            return False
        
        # 3. 检查阈值条件
        threshold = trigger_config.get("threshold")
        if threshold is not None:
            if not self._check_threshold(event, threshold):
                logger.debug(f"事件类型 {event_type} 未满足阈值条件")
                return False
        
        return True
    
    def _check_threshold(self, event, threshold: Any) -> bool:
        """
        检查阈值条件
        
        Args:
            event: GSI 事件
            threshold: 阈值
        
        Returns:
            是否满足阈值
        """
        # 根据事件类型检查不同的阈值
        event_type = event.event_type
        
        if event_type == "low_health":
            # 血量阈值
            if self.state_manager:
                state = self.state_manager.get_state()
                if state:
                    health = state.health if hasattr(state, 'health') else state.get("health", 0)
                    max_health = state.max_health if hasattr(state, 'max_health') else state.get("max_health", 1)
                    health_percent = health / max_health if max_health > 0 else 0
                    return health_percent < threshold
        
        elif event_type == "low_mana":
            # 魔法阈值
            if self.state_manager:
                state = self.state_manager.get_state()
                if state:
                    mana = state.mana if hasattr(state, 'mana') else state.get("mana", 0)
                    max_mana = state.max_mana if hasattr(state, 'max_mana') else state.get("max_mana", 1)
                    mana_percent = mana / max_mana if max_mana > 0 else 0
                    return mana_percent < threshold
        
        # 默认返回 True
        return True
    
    def _trigger_recommendation(self, event):
        """
        触发推荐
        
        Args:
            event: GSI 事件对象
        """
        event_type = event.event_type
        
        # 更新冷却时间
        self._cooldowns[event_type] = time.time()
        
        # 获取当前游戏状态
        game_state = None
        if self.state_manager:
            game_state = self.state_manager.get_state()
        
        # 调用决策融合器生成推荐（传入完整事件对象）
        try:
            recommendation = self.decision_fusion.generate_recommendation(
                event=event,
                game_state=game_state
            )
            
            if recommendation:
                logger.info(f"生成推荐: {recommendation.recommendation[:50]}...")
                
                # 推送推荐结果
                self._push_recommendation(recommendation, event)
            else:
                logger.debug(f"事件 {event_type} 未生成推荐")
        
        except Exception as e:
            logger.error(f"生成推荐失败: {e}")
    
    def _push_recommendation(self, recommendation, event):
        """
        推送推荐结果
        
        Args:
            recommendation: 推荐结果
            event: 触发事件
        """
        if not self._push_callback:
            logger.debug("未设置推送回调，跳过推送")
            return
        
        try:
            # 构建推送数据
            push_data = {
                "type": "recommendation",
                "event_type": event.event_type,
                "event_message": event.message,
                "recommendation": recommendation.to_dict(),
                "timestamp": time.time()
            }
            
            # 调用推送回调
            self._push_callback(push_data)
            
            logger.info(f"推送推荐结果: {event.event_type}")
        
        except Exception as e:
            logger.error(f"推送推荐结果失败: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取触发器状态
        
        Returns:
            状态字典
        """
        return {
            "enabled": self.enabled,
            "running": self._running,
            "event_queue_set": self.event_queue is not None,
            "decision_fusion_set": self.decision_fusion is not None,
            "state_manager_set": self.state_manager is not None,
            "push_callback_set": self._push_callback is not None,
            "cooldowns": self._cooldowns.copy()
        }
