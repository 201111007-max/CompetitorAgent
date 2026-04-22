"""测试混合模式架构"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from agents.DotaHelperAgent.utils.api_client import OpenDotaClient
from agents.DotaHelperAgent.analyzers.item_recommender import HybridItemRecommender
from agents.DotaHelperAgent.analyzers.skill_builder import HybridSkillBuilder
from agents.DotaHelperAgent.analyzers.hero_analyzer import HeroAnalyzer


def test_item_recommender():
    """测试物品推荐器"""
    print("\n" + "="*60)
    print("测试混合模式物品推荐器")
    print("="*60)
    
    client = OpenDotaClient()
    recommender = HybridItemRecommender(client, llm_enabled=False)
    
    # 测试数据驱动模式
    result = recommender.recommend_items(
        hero_name="axe",
        game_stage="all"
    )
    
    print(f"\n英雄：{result.get('hero')}")
    print(f"来源：{result.get('source_detail', 'unknown')}")
    print(f"物品数量：{len(result.get('items', []))}")
    
    if result.get('items'):
        print("\n前 3 件物品:")
        for i, item in enumerate(result['items'][:3], 1):
            print(f"  {i}. {item.get('name', 'Unknown')}")
    
    print("\n[OK] 物品推荐器测试完成")


def test_skill_builder():
    """测试技能加点建议器"""
    print("\n" + "="*60)
    print("测试混合模式技能加点建议器")
    print("="*60)
    
    client = OpenDotaClient()
    builder = HybridSkillBuilder(client, llm_enabled=False)
    
    # 测试数据驱动模式
    result = builder.recommend_skill_build(
        hero_name="axe",
        role="core"
    )
    
    print(f"\n英雄：{result.get('hero')}")
    print(f"来源：{result.get('source_detail', 'unknown')}")
    print(f"定位：{result.get('role')}")
    
    if 'early_game' in result:
        print(f"\n前期加点：{result['early_game'].get('notes', '')}")
    
    print("\n[OK] 技能加点建议器测试完成")


def test_hero_analyzer():
    """测试英雄分析器"""
    print("\n" + "="*60)
    print("测试混合模式英雄分析器")
    print("="*60)
    
    client = OpenDotaClient()
    analyzer = HeroAnalyzer(client)
    
    # 测试阵容分析
    result = analyzer.analyze_team_composition(
        our_heroes=["axe", "crystal_maiden"],
        enemy_heroes=["anti-mage", "invoker"]
    )
    
    print(f"\n己方优势对数：{len(result.get('our_advantages', []))}")
    print(f"敌方优势对数：{len(result.get('enemy_advantages', []))}")
    print(f"总体优势：{result.get('overall_advantage', 0)}")
    print(f"结论：{result.get('conclusion', '')}")
    
    print("\n[OK] 英雄分析器测试完成")


def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("混合模式架构测试")
    print("="*60)
    
    try:
        test_item_recommender()
        test_skill_builder()
        test_hero_analyzer()
        
        print("\n" + "="*60)
        print("所有测试完成！")
        print("="*60)
        
    except Exception as e:
        print(f"\n[FAIL] 测试失败：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
