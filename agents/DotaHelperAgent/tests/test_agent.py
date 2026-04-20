"""DotaHelperAgent 基础测试脚本"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from agents.DotaHelperAgent import DotaHelperAgent


def test_hero_recommendation():
    """测试英雄推荐功能"""
    print("\n" + "=" * 60)
    print("测试 1: 英雄推荐")
    print("=" * 60)

    agent = DotaHelperAgent()

    # 测试场景：己方有 Anti-Mage，对方有 Phantom Assassin
    our_heroes = ["Anti-Mage"]
    enemy_heroes = ["Phantom Assassin", "Pudge"]

    result = agent.recommend_heroes(
        our_heroes=our_heroes,
        enemy_heroes=enemy_heroes,
        top_n=3
    )

    print(agent.format_recommendation(result))


def test_item_recommendation():
    """测试物品推荐功能"""
    print("\n" + "=" * 60)
    print("测试 2: 物品推荐")
    print("=" * 60)

    agent = DotaHelperAgent()

    hero_name = "Anti-Mage"
    result = agent.recommend_build(
        hero_name=hero_name,
        role="core",
        game_stage="all"
    )

    print(agent.format_build(result))


def test_counter_heroes():
    """测试克制英雄查询"""
    print("\n" + "=" * 60)
    print("测试 3: 克制英雄查询")
    print("=" * 60)

    agent = DotaHelperAgent()

    target_hero = "Phantom Assassin"
    result = agent.get_counter_heroes(target_hero=target_hero, top_n=5)

    print(f"\n克制 {target_hero} 的英雄:")
    for counter in result.get("counters", []):
        print(f"  - {counter['hero_name']}: 胜率 {counter['win_rate']:.1%}")


def test_full_analysis():
    """测试完整分析"""
    print("\n" + "=" * 60)
    print("测试 4: 完整分析")
    print("=" * 60)

    agent = DotaHelperAgent()

    our_heroes = ["Anti-Mage", "Crystal Maiden"]
    enemy_heroes = ["Phantom Assassin", "Pudge", "Invoker"]

    result = agent.full_analysis(
        our_heroes=our_heroes,
        enemy_heroes=enemy_heroes,
        top_n=2
    )

    # 显示英雄推荐
    hero_rec = result.get("hero_recommendation", {})
    print(agent.format_recommendation(hero_rec))

    # 显示出装建议
    builds = result.get("builds", [])
    for build in builds:
        print(agent.format_build(build))


def main():
    """主函数"""
    print("=" * 60)
    print("DotaHelperAgent 测试")
    print("=" * 60)

    try:
        # 运行测试
        test_hero_recommendation()
        test_item_recommendation()
        test_counter_heroes()
        test_full_analysis()

        print("\n" + "=" * 60)
        print("所有测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
