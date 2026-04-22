"""简单测试混合模式"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from agents.DotaHelperAgent.utils.api_client import OpenDotaClient
from agents.DotaHelperAgent.analyzers.item_recommender import ItemRecommender

# 测试 API 调用
client = OpenDotaClient()

print("测试 API 调用...")
heroes = client.get_heroes()
print(f"获取到 {len(heroes) if heroes else 0} 个英雄")

if heroes:
    print(f"第一个英雄：{heroes[0]}")
    
    # 测试英雄 ID 转换
    hero_id = client.hero_name_to_id("axe")
    print(f"Axe 的 ID: {hero_id}")
    
    if hero_id:
        # 测试物品数据
        item_data = client.get_hero_item_popularity(hero_id)
        print(f"物品数据：{item_data}")

# 测试物品推荐器
print("\n测试物品推荐器...")
recommender = ItemRecommender(client)
result = recommender.recommend_items(hero_name="axe", game_stage="all")
print(f"推荐结果：{result}")
