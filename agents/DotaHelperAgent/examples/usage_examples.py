"""DotaHelperAgent 配置使用示例"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.DotaHelperAgent import (
    DotaHelperAgent,
    AgentConfig,
    MatchupConfig,
    CacheConfig,
    WinRateStrategy,
    PopularityStrategy,
)


def example_basic_usage():
    """基础使用示例"""
    print("=" * 60)
    print("示例 1: 基础使用")
    print("=" * 60)
    
    # 使用默认配置
    agent = DotaHelperAgent()
    
    result = agent.recommend_heroes(
        our_heroes=["Anti-Mage"],
        enemy_heroes=["Phantom Assassin", "Pudge"],
        top_n=3
    )
    
    print(agent.format_recommendation(result))


def example_custom_config():
    """自定义配置示例"""
    print("\n" + "=" * 60)
    print("示例 2: 自定义配置")
    print("=" * 60)
    
    # 创建自定义配置
    config = AgentConfig(
        # 分析配置
        matchup=MatchupConfig(
            min_games_threshold=50,      # 降低样本要求
            min_winrate_threshold=0.50,  # 降低胜率要求
            score_weight=100.0,
        ),
        # 缓存配置
        cache=CacheConfig(
            enabled=True,
            ttl_hours=48,          # 缓存 48 小时
            max_size_mb=200,       # 最大 200MB
            max_items=2000,        # 最多 2000 个缓存项
        ),
    )
    
    # 使用配置创建 Agent
    agent = DotaHelperAgent(config=config)
    
    result = agent.recommend_heroes(
        our_heroes=["Anti-Mage"],
        enemy_heroes=["Phantom Assassin"],
        top_n=2
    )
    
    print(agent.format_recommendation(result))


def example_custom_strategies():
    """自定义评分策略示例"""
    print("\n" + "=" * 60)
    print("示例 3: 自定义评分策略")
    print("=" * 60)
    
    agent = DotaHelperAgent()
    
    # 添加多个评分策略
    agent.hero_analyzer.add_strategy(WinRateStrategy())
    agent.hero_analyzer.add_strategy(PopularityStrategy())
    
    result = agent.recommend_heroes(
        our_heroes=["Crystal Maiden"],
        enemy_heroes=["Pudge"],
        top_n=3
    )
    
    print(agent.format_recommendation(result))


def example_cache_warmup():
    """缓存预热示例"""
    print("\n" + "=" * 60)
    print("示例 4: 缓存预热")
    print("=" * 60)
    
    agent = DotaHelperAgent()
    
    # 预热缓存
    agent.warm_up_cache()
    
    # 使用缓存
    result = agent.recommend_heroes(
        our_heroes=["Anti-Mage"],
        enemy_heroes=["Phantom Assassin"],
        top_n=2
    )
    
    print(agent.format_recommendation(result))
    
    # 显示缓存统计
    agent.print_cache_stats()


def example_cache_stats():
    """查看缓存统计示例"""
    print("\n" + "=" * 60)
    print("示例 5: 查看缓存统计")
    print("=" * 60)
    
    agent = DotaHelperAgent()
    
    # 第一次调用（无缓存）
    agent.recommend_heroes(
        our_heroes=["Anti-Mage"],
        enemy_heroes=["Phantom Assassin"],
        top_n=2
    )
    
    # 第二次调用（有缓存）
    agent.recommend_heroes(
        our_heroes=["Anti-Mage"],
        enemy_heroes=["Phantom Assassin"],
        top_n=2
    )
    
    # 显示统计
    stats = agent.get_cache_stats()
    print(f"\n缓存命中率：{stats['hit_rate']}%")
    print(f"命中次数：{stats['hits']}")
    print(f"未命中次数：{stats['misses']}")
    print(f"缓存大小：{stats['total_size_mb']} MB")


def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("DotaHelperAgent 配置使用示例")
    print("=" * 60)
    print("\n说明:")
    print("- 示例 1: 最基础的使用方式")
    print("- 示例 2: 自定义配置参数")
    print("- 示例 3: 使用多种评分策略")
    print("- 示例 4: 缓存预热优化性能")
    print("- 示例 5: 查看缓存统计信息")
    print("=" * 60)
    
    try:
        # 运行示例（可以注释掉不需要的）
        example_basic_usage()
        # example_custom_config()
        # example_custom_strategies()
        # example_cache_warmup()
        # example_cache_stats()
        
        print("\n" + "=" * 60)
        print("所有示例运行完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n示例运行出错：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
