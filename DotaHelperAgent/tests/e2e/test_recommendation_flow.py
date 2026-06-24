"""
推荐系统完整流程测试脚本
模拟 GSI 事件触发推荐系统的完整流程
"""

import sys
import time
import json
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from gsi.models import GSIEvent, GameState
from gsi.event_queue import GSIEventQueue
from core.decision.rule_engine import RuleEngine
from core.decision.data_engine import DataEngine
from core.decision.llm_engine import LLMEngine
from core.decision.decision_fusion import DecisionFusion
from core.event_trigger import EventTrigger
from utils.log_config import setup_logging


def create_mock_game_state() -> GameState:
    """创建模拟游戏状态"""
    return GameState(
        hero_name="幻影刺客",
        hero_id=44,
        level=9,
        alive=True,
        health=250,
        max_health=1200,
        mana=80,
        max_mana=400,
        gold=1800,
        game_time=720,
        kills=3,
        deaths=2,
        assists=5
    )


def create_mock_events():
    """创建一系列模拟 GSI 事件"""
    events = [
        GSIEvent(
            event_type="low_health",
            message="血量过低，需要回复",
            priority="warning",
            data={"health_percent": 0.21}
        ),
        GSIEvent(
            event_type="low_mana",
            message="魔法不足",
            priority="info",
            data={"mana_percent": 0.20}
        ),
        GSIEvent(
            event_type="stack_neutral",
            message="堆野时机到了",
            priority="info",
            data={"game_time": 53}
        ),
        GSIEvent(
            event_type="rune_spawn",
            message="符文即将刷新",
            priority="info",
            data={"game_time": 180}
        ),
        GSIEvent(
            event_type="item_purchase",
            message="购买了新物品",
            priority="info",
            data={"item": "phase_boots"}
        ),
        GSIEvent(
            event_type="stack",
            message="堆野时间到了！（游戏 0:53）",
            priority="info",
            data={"game_time": 53}
        ),
        GSIEvent(
            event_type="rune",
            message="财神符刷新了！",
            priority="info",
            data={"game_time": 180}
        )
    ]
    return events


def test_recommendation_flow():
    """测试推荐系统完整流程"""
    print("=" * 70)
    print("推荐系统完整流程测试")
    print("=" * 70)
    
    # 初始化日志
    setup_logging(log_level="INFO")
    
    # 1. 初始化事件队列
    print("\n[1/6] 初始化事件队列...")
    event_queue = GSIEventQueue(max_history=100)
    print("✓ 事件队列初始化完成")
    
    # 2. 初始化三个决策引擎
    print("\n[2/6] 初始化决策引擎...")
    config = {
        "conflict_resolution": "weighted_average",
        "min_confidence": 0.5,
        "rule_engine": {},
        "data_engine": {},
        "llm_engine": {}
    }
    
    rule_engine = RuleEngine(config.get("rule_engine", {}))
    data_engine = DataEngine(config.get("data_engine", {}))
    llm_engine = LLMEngine(config.get("llm_engine", {}))
    print("✓ 规则引擎初始化完成")
    print("✓ 数据引擎初始化完成")
    print("✓ LLM 引擎初始化完成")
    
    # 3. 初始化决策融合器
    print("\n[3/6] 初始化决策融合器...")
    decision_fusion = DecisionFusion(config)
    decision_fusion.rule_engine = rule_engine
    decision_fusion.data_engine = data_engine
    decision_fusion.llm_engine = llm_engine
    print("✓ 决策融合器初始化完成")
    
    # 4. 初始化事件触发器
    print("\n[4/6] 初始化事件触发器...")
    trigger_config = {
        "enabled": True,
        "triggers": {
            "low_health": {"enabled": True, "cooldown": 10, "threshold": 0.3},
            "low_mana": {"enabled": True, "cooldown": 10, "threshold": 0.2},
            "stack_neutral": {"enabled": True, "cooldown": 60},
            "rune_spawn": {"enabled": True, "cooldown": 30},
            "item_purchase": {"enabled": True, "cooldown": 30},
            "stack": {"enabled": True, "cooldown": 60},
            "rune": {"enabled": True, "cooldown": 30}
        }
    }
    
    event_trigger = EventTrigger(trigger_config)
    event_trigger.set_event_queue(event_queue)
    event_trigger.set_decision_fusion(decision_fusion)
    
    # 创建模拟状态管理器
    class MockStateManager:
        def __init__(self):
            self.state = create_mock_game_state()
        
        def get_state(self):
            return self.state
    
    state_manager = MockStateManager()
    event_trigger.set_state_manager(state_manager)
    
    # 设置推送回调
    def push_callback(recommendation_data):
        print("\n" + "=" * 70)
        print("📢 推荐推送")
        print("=" * 70)
        print(f"事件类型: {recommendation_data['event_type']}")
        print(f"事件消息: {recommendation_data['event_message']}")
        print(f"推荐内容: {recommendation_data['recommendation']['recommendation']}")
        print(f"置信度: {recommendation_data['recommendation']['confidence']:.2f}")
        print(f"来源: {', '.join(recommendation_data['recommendation']['sources'])}")
        print(f"冲突检测: {recommendation_data['recommendation']['conflict_detected']}")
        print("=" * 70)
    
    event_trigger.set_push_callback(push_callback)
    print("✓ 事件触发器初始化完成")
    
    # 5. 启动事件触发器
    print("\n[5/6] 启动事件触发器...")
    event_trigger.start()
    print("✓ 事件触发器已启动")
    
    # 6. 模拟 GSI 事件
    print("\n[6/6] 模拟 GSI 事件...")
    mock_events = create_mock_events()
    
    for i, event in enumerate(mock_events, 1):
        print(f"\n--- 事件 {i}/{len(mock_events)}: {event.event_type} ---")
        print(f"消息: {event.message}")
        
        # 将事件放入队列
        event_queue.put(event)
        
        # 等待事件处理
        time.sleep(1.5)
    
    # 停止事件触发器
    print("\n" + "=" * 70)
    print("停止事件触发器...")
    event_trigger.stop()
    print("✓ 事件触发器已停止")
    
    # 输出测试总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    status = event_trigger.get_status()
    print(f"触发器状态: {'运行中' if status['running'] else '已停止'}")
    print(f"冷却记录: {len(status['cooldowns'])} 个事件类型")
    for event_type, last_time in status['cooldowns'].items():
        print(f"  - {event_type}: 上次触发于 {time.strftime('%H:%M:%S', time.localtime(last_time))}")
    print("=" * 70)
    
    print("\n✓ 完整流程测试完成")


if __name__ == "__main__":
    try:
        test_recommendation_flow()
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
