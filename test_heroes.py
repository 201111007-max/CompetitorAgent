"""检查英雄数据"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from agents.DotaHelperAgent.utils.api_client import OpenDotaClient

client = OpenDotaClient()
heroes = client.get_heroes()

print(f"获取到 {len(heroes)} 个英雄\n")

# 打印前 10 个英雄
for i, hero in enumerate(heroes[:10], 1):
    print(f"{i}. ID: {hero['id']}, Name: {hero['name']}, Localized: {hero['localized_name']}")

# 查找 axe
print("\n查找 Axe...")
for hero in heroes:
    if 'axe' in hero['name'].lower() or 'axe' in hero['localized_name'].lower():
        print(f"找到：ID: {hero['id']}, Name: {hero['name']}, Localized: {hero['localized_name']}")
        break

# 测试名称转换
print("\n测试名称转换...")
test_names = ["axe", "Axe", "AXE", "npc_dota_hero_axe"]
for name in test_names:
    hero_id = client.hero_name_to_id(name)
    print(f"{name} -> {hero_id}")
