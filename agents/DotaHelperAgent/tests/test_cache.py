"""DotaHelperAgent 缓存测试脚本"""

import sys
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from agents.DotaHelperAgent import DotaHelperAgent, OpenDotaClient


def test_cache_performance():
    """测试缓存性能"""
    print("\n" + "=" * 60)
    print("测试: 缓存性能对比")
    print("=" * 60)

    client = OpenDotaClient()

    # 清空缓存，确保第一次是冷启动
    client.clear_cache()

    # 第一次调用（无缓存）
    print("\n【第一次调用 - 无缓存】")
    start = time.time()
    heroes1 = client.get_heroes()
    elapsed1 = time.time() - start
    print(f"获取 {len(heroes1)} 个英雄，耗时: {elapsed1:.3f} 秒")

    # 第二次调用（有内存缓存）
    print("\n【第二次调用 - 内存缓存】")
    start = time.time()
    heroes2 = client.get_heroes()
    elapsed2 = time.time() - start
    print(f"获取 {len(heroes2)} 个英雄，耗时: {elapsed2:.3f} 秒")
    if elapsed2 > 0.001:
        print(f"缓存加速: {elapsed1/elapsed2:.1f}x")
    else:
        print("缓存命中！速度极快")

    # 创建新客户端（模拟重启），测试文件缓存
    print("\n【第三次调用 - 新客户端（文件缓存）】")
    client2 = OpenDotaClient()
    start = time.time()
    heroes3 = client2.get_heroes()
    elapsed3 = time.time() - start
    print(f"获取 {len(heroes3)} 个英雄，耗时: {elapsed3:.3f} 秒")

    # 显示缓存统计
    print("\n【缓存统计】")
    stats = client2.get_cache_stats()
    print(f"  内存缓存项: {stats['memory_cache_count']}")
    print(f"  文件缓存项: {stats['file_cache_count']}")
    print(f"  缓存总大小: {stats['total_size_mb']} MB")


def test_hero_matchup_cache():
    """测试英雄克制数据缓存"""
    print("\n" + "=" * 60)
    print("测试: 英雄克制数据缓存")
    print("=" * 60)

    client = OpenDotaClient()
    hero_id = 1  # Anti-Mage

    # 第一次调用
    print(f"\n【第一次获取英雄 {hero_id} 的克制数据】")
    start = time.time()
    matchups1 = client.get_hero_matchups(hero_id)
    elapsed1 = time.time() - start
    print(f"获取 {len(matchups1) if matchups1 else 0} 条数据，耗时: {elapsed1:.3f} 秒")

    # 第二次调用（应命中缓存）
    print(f"\n【第二次获取（应命中缓存）】")
    start = time.time()
    matchups2 = client.get_hero_matchups(hero_id)
    elapsed2 = time.time() - start
    print(f"获取 {len(matchups2) if matchups2 else 0} 条数据，耗时: {elapsed2:.3f} 秒")
    print(f"缓存加速: {elapsed1/elapsed2:.1f}x" if elapsed2 > 0 else "缓存命中！")

    # 显示缓存统计
    print("\n【缓存统计】")
    stats = client.get_cache_stats()
    print(f"  文件缓存项: {stats['file_cache_count']}")


def test_full_agent_with_cache():
    """测试完整 Agent 功能（带缓存）"""
    print("\n" + "=" * 60)
    print("测试: 完整 Agent 功能（带缓存）")
    print("=" * 60)

    agent = DotaHelperAgent()

    our_heroes = ["Anti-Mage"]
    enemy_heroes = ["Phantom Assassin", "Pudge"]

    print(f"\n己方英雄: {our_heroes}")
    print(f"对方英雄: {enemy_heroes}")

    # 第一次分析
    print("\n【第一次分析】")
    start = time.time()
    result = agent.recommend_heroes(
        our_heroes=our_heroes,
        enemy_heroes=enemy_heroes,
        top_n=2
    )
    elapsed1 = time.time() - start
    print(f"分析耗时: {elapsed1:.3f} 秒")
    print(agent.format_recommendation(result))

    # 第二次分析（应使用缓存）
    print("\n【第二次分析（使用缓存）】")
    start = time.time()
    result2 = agent.recommend_heroes(
        our_heroes=our_heroes,
        enemy_heroes=enemy_heroes,
        top_n=2
    )
    elapsed2 = time.time() - start
    print(f"分析耗时: {elapsed2:.3f} 秒")
    print(f"缓存加速: {elapsed1/elapsed2:.1f}x" if elapsed2 > 0 else "全部缓存命中！")

    # 显示最终缓存统计
    print("\n【最终缓存统计】")
    stats = agent.client.get_cache_stats()
    print(f"  内存缓存项: {stats['memory_cache_count']}")
    print(f"  文件缓存项: {stats['file_cache_count']}")
    print(f"  缓存总大小: {stats['total_size_mb']} MB")
    print(f"  缓存目录: {stats['cache_dir']}")
    print(f"  缓存过期: {stats['ttl_hours']} 小时")


def main():
    """主函数"""
    print("=" * 60)
    print("DotaHelperAgent 缓存测试")
    print("=" * 60)
    print("\n说明:")
    print("- 第一次调用会从 API 获取数据（较慢）")
    print("- 第二次调用会从内存缓存读取（极快）")
    print("- 新客户端会从文件缓存读取（快）")
    print("- 缓存每天自动过期更新")

    try:
        # 运行测试
        test_cache_performance()
        test_hero_matchup_cache()
        test_full_agent_with_cache()

        print("\n" + "=" * 60)
        print("所有测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
