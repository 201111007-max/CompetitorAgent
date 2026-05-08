"""测试英雄名称到 ID 的转换"""
import sys
sys.path.insert(0, 'agents/DotaHelperAgent')

from utils.api_client import OpenDotaClient

client = OpenDotaClient()

# 测试 LLM 返回的英文名称格式
test_names = [
    "faceless_void",
    "pugna", 
    "sand_king",
    "anti-mage",
    "phantom_assassin",
    "shadow_fiend",
    "crystal_maiden",
]

print("测试英雄名称到 ID 的转换:")
print("=" * 50)
for name in test_names:
    hero_id = client.hero_name_to_id(name)
    if hero_id:
        hero_name = client.hero_id_to_name(hero_id)
        print(f"  {name:25} -> ID: {hero_id:4} -> {hero_name}")
    else:
        print(f"  {name:25} -> ID: None -> NOT FOUND")
