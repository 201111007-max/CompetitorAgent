"""直接测试 API"""

import requests

# 直接调用 OpenDota API
url = "https://api.opendota.com/api/heroes"
response = requests.get(url)

print(f"状态码：{response.status_code}")

if response.status_code == 200:
    heroes = response.json()
    print(f"获取到 {len(heroes)} 个英雄")
    
    if heroes:
        print(f"\n前 3 个英雄:")
        for hero in heroes[:3]:
            print(f"  ID: {hero['id']}, Name: {hero['name']}, Localized: {hero['localized_name']}")
else:
    print(f"请求失败：{response.text}")
