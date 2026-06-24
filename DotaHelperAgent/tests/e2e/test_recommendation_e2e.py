"""
推荐系统端到端测试脚本

模拟 GSI 事件触发 → 决策融合 → 推荐输出的完整流程
"""

import sys
import time
import json
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from gsi.models import GameState, GSIEvent, parse_gsi_data
from gsi.event_queue import GSIEventQueue
from gsi.state_manager import GSIStateManager
from gsi.event_handler import GSIEventHandler
from core.decision.decision_fusion import DecisionFusion
from core.event_trigger import EventTrigger
from utils.log_config import setup_logging


def create_mock_gsi_data() -> dict:
    """创建模拟 GSI 原始数据（符合 Dota 2 GSI 格式）"""
    return {
        "provider": {
            "name": "Dota 2",
            "appid": 570,
            "version": 1
        },
        "map": {
            "matchid": "1234567890",
            "game_time": 720,  # 12分钟
            "clock_time": 720,
            "daytime": True,
            "radiant_score": 15,
            "dire_score": 12,
            "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
            "paused": False,
            "win_team": ""
        },
        "player": {
            "steamid": "76561198000000000",
            "name": "TestPlayer",
            "kills": 3,
            "deaths": 2,
            "assists": 5,
            "last_hits": 120,
            "denies": 15,
            "gold": 1800,
            "gold_reliable": 1200,
            "gpm": 450,
            "xpm": 520
        },
        "hero": {
            "id": 44,  # 幻影刺客
            "name": "npc_dota_hero_phantom_assassin",
            "level": 9,
            "alive": True,
            "respawn_seconds": 0,
            "buyback_cost": 285,
            "health": 250,
            "max_health": 1200,
            "mana": 80,
            "max_mana": 400,
            "abilities": {
                "0": {
                    "name": "phantom_assassin_stifling_dagger",
                    "level": 3,
                    "can_cast": True,
                    "passive": False,
                    "cooldown": 0,
                    "ultimate": False
                },
                "1": {
                    "name": "phantom_assassin_phantom_strike",
                    "level": 2,
                    "can_cast": True,
                    "passive": False,
                    "cooldown": 0,
                    "ultimate": False
                },
                "2": {
                    "name": "phantom_assassin_blur",
                    "level": 1,
                    "can_cast": False,
                    "passive": True,
                    "cooldown": 0,
                    "ultimate": False
                },
                "3": {
                    "name": "phantom_assassin_coup_de_grace",
                    "level": 1,
                    "can_cast": False,
                    "passive": True,
                    "cooldown": 0,
                    "ultimate": True
                }
            },
            "items": {
                "slot0": {"name": "item_phase_boots", "can_cast": False, "cooldown": 0, "charges": 0},
                "slot1": {"name": "item_battle_fury", "can_cast": False, "cooldown": 0, "charges": 0},
                "slot2": {"name": "item_empty", "can_cast": False, "cooldown": 0, "charges": 0},
                "slot3": {"name": "item_empty", "can_cast": False, "cooldown": 0, "charges": 0},
                "slot4": {"name": "item_empty", "can_cast": False, "cooldown": 0, "charges": 0},
                "slot5": {"name": "item_empty", "can_cast": False, "cooldown": 0, "charges": 0}
            }
        }
    }


def create_mock_event(event_type: str, message: str) -> GSIEvent:
    """创建模拟 GSI 事件"""
    return GSIEvent(
        event_type=event_type,
        message=message,
        priority="info",
        data={},
        timestamp=time.time()
    )


def test_recommendation_flow():
    """测试推荐系统完整流程"""
    
    print("=" * 60)
    print("推荐系统端到端测试")
    print("=" * 60)
    
    # 1. 初始化日志
    setup_logging(log_level="INFO")
    
    # 2. 初始化事件队列
    print("\n[1/6] 初始化事件队列...")
    event_queue = GSIEventQueue(max_history=100)
    print("✓ 事件队列初始化完成")
    
    # 3. 初始化状态管理器
    print("\n[2/6] 初始化状态管理器...")
    event_handler = GSIEventHandler(event_queue)
    state_manager = GSIStateManager(event_handler=event_handler)
    print("✓ 状态管理器初始化完成")
    
    # 4. 初始化决策融合引擎
    print("\n[3/6] 初始化决策融合引擎...")
    config = {
        "conflict_resolution": "weighted_average",
        "min_confidence": 0.5,
        "rule_engine": {},
        "data_engine": {},
        "llm_engine": {}
    }
    decision_fusion = DecisionFusion(config)
    print("✓ 决策融合引擎初始化完成")
    
    # 5. 初始化事件触发器
    print("\n[4/6] 初始化事件触发器...")
    trigger_config = {
        "enabled": True,
        "triggers": {
            "low_health": {"enabled": True, "cooldown": 10, "threshold": 0.3},
            "low_mana": {"enabled": True, "cooldown": 10, "threshold": 0.2},
            "stack_neutral": {"enabled": True, "cooldown": 60},
            "rune_spawn": {"enabled": True, "cooldown": 30},
            "item_purchase": {"enabled": True, "cooldown": 30},
        }
    }
    
    event_trigger = EventTrigger(trigger_config)
    event_trigger.set_event_queue(event_queue)
    event_trigger.set_decision_fusion(decision_fusion)
    
    # 设置推送回调（打印到控制台）
    def push_callback(recommendation_data):
        print("\n" + "=" * 60)
        print("📢 推荐推送")
        print("=" * 60)
        print(f"事件类型: {recommendation_data['event_type']}")
        print(f"事件消息: {recommendation_data['event_message']}")
        print(f"推荐内容: {recommendation_data['recommendation']['recommendation']}")
        print(f"置信度: {recommendation_data['recommendation']['confidence']:.2f}")
        print(f"来源: {', '.join(recommendation_data['recommendation']['sources'])}")
        print(f"冲突检测: {recommendation_data['recommendation']['conflict_detected']}")
        print("=" * 60 + "\n")
    
    event_trigger.set_push_callback(push_callback)
    event_trigger.set_state_manager(state_manager)
    print("✓ 事件触发器初始化完成")
    
    # 6. 启动事件触发器
    print("\n[5/6] 启动事件触发器...")
    event_trigger.start()
    print("✓ 事件触发器已启动")
    
    # 7. 模拟游戏状态和事件
    print("\n[6/6] 模拟游戏场景...")
    
    # 设置游戏状态
    gsi_data = create_mock_gsi_data()
    game_state = parse_gsi_data(gsi_data)
    state_manager.update_state(gsi_data)
    
    print(f"\n游戏状态:")
    print(f"  英雄: {game_state.hero_name}")
    print(f"  血量: {game_state.health}/{game_state.max_health} ({game_state.health/game_state.max_health*100:.1f}%)")
    print(f"  魔法: {game_state.mana}/{game_state.max_mana} ({game_state.mana/game_state.max_mana*100:.1f}%)")
    print(f"  金钱: {game_state.gold}")
    print(f"  游戏时间: {game_state.game_time//60}分{game_state.game_time%60}秒")
    
    # 测试场景1: 低血量事件
    print("\n" + "-" * 60)
    print("测试场景 1: 低血量事件")
    print("-" * 60)
    event1 = create_mock_event("low_health", "血量过低，需要回复")
    event_queue.put(event1)
    time.sleep(1)  # 等待事件处理
    
    # 测试场景2: 低魔法事件
    print("\n" + "-" * 60)
    print("测试场景 2: 低魔法事件")
    print("-" * 60)
    event2 = create_mock_event("low_mana", "魔法不足")
    event_queue.put(event2)
    time.sleep(1)
    
    # 测试场景3: 堆野时机
    print("\n" + "-" * 60)
    print("测试场景 3: 堆野时机")
    print("-" * 60)
    # 更新游戏时间到堆野时机（第53秒）
    gsi_data["map"]["game_time"] = 53
    state_manager.update_state(gsi_data)
    event3 = create_mock_event("stack_neutral", "堆野时机到了")
    event_queue.put(event3)
    time.sleep(1)
    
    # 测试场景4: 符文刷新
    print("\n" + "-" * 60)
    print("测试场景 4: 符文刷新")
    print("-" * 60)
    # 更新游戏时间到符文刷新（第180秒）
    gsi_data["map"]["game_time"] = 180
    state_manager.update_state(gsi_data)
    event4 = create_mock_event("rune_spawn", "符文即将刷新")
    event_queue.put(event4)
    time.sleep(1)
    
    # 测试场景5: 物品购买
    print("\n" + "-" * 60)
    print("测试场景 5: 物品购买")
    print("-" * 60)
    event5 = create_mock_event("item_purchase", "购买了新物品")
    event_queue.put(event5)
    time.sleep(1)
    
    # 8. 停止事件触发器
    print("\n" + "-" * 60)
    print("停止事件触发器...")
    print("-" * 60)
    event_trigger.stop()
    print("✓ 事件触发器已停止")
    
    # 9. 输出测试总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    status = event_trigger.get_status()
    print(f"触发器状态: {'运行中' if status['running'] else '已停止'}")
    print(f"冷却记录: {len(status['cooldowns'])} 个事件类型")
    for event_type, last_time in status['cooldowns'].items():
        print(f"  - {event_type}: 上次触发于 {time.strftime('%H:%M:%S', time.localtime(last_time))}")
    print("=" * 60)
    
    print("\n✓ 端到端测试完成")


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
