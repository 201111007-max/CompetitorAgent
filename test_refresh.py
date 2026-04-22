"""测试缓存加载"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from agents.DotaHelperAgent.utils.api_client import OpenDotaClient

client = OpenDotaClient()

# 不使用缓存
print("不使用缓存获取英雄...")
heroes = client.get_heroes(use_cache=False)
print(f"获取到 {len(heroes) if heroes else 0} 个英雄")

if heroes and len(heroes) > 1:
    print(f"第二个英雄：{heroes[1]}")
    
    # 测试名称转换
    hero_id = client.hero_name_to_id("axe")
    print(f"Axe 的 ID: {hero_id}")
    
    if hero_id:
        # 测试物品数据
        print("\n获取物品数据...")
        item_data = client.get_hero_item_popularity(hero_id)
        print(f"物品数据键：{list(item_data.keys()) if item_data else 'None'}")
