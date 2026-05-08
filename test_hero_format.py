"""检查 OpenDota API 返回的英雄名称格式"""
import sys
sys.path.insert(0, 'agents/DotaHelperAgent')

from utils.api_client import OpenDotaClient

client = OpenDotaClient()
heroes = client.get_heroes()

# 查找一些特定英雄
search_names = ["faceless", "pugna", "sand", "phantom", "shadow", "crystal"]

print("OpenDota API 英雄名称格式示例:")
print("=" * 80)

# 打印前10个英雄的格式
print("\n前10个英雄:")
for hero in heroes[:10]:
    print(f"  ID: {hero['id']:3} | name: {hero['name']:35} | localized_name: {hero.get('localized_name', 'N/A')}")

# 搜索目标英雄
print("\n搜索目标英雄:")
for hero in heroes:
    for search in search_names:
        if search in hero.get("name", "").lower() or search in hero.get("localized_name", "").lower():
            print(f"  ID: {hero['id']:3} | name: {hero['name']:35} | localized_name: {hero.get('localized_name', 'N/A')}")
            break
