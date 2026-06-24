"""
测试 SSE 实时推送推荐数据到前端
"""

import requests
import time
import json

API_BASE = "http://localhost:5000"

def test_sse_recommendation():
    """测试 SSE 推荐推送"""
    print("=" * 60)
    print("测试 SSE 实时推荐推送")
    print("=" * 60)
    
    # 1. 检查推荐系统状态
    print("\n[1/4] 检查推荐系统状态...")
    try:
        response = requests.get(f"{API_BASE}/api/gsi/recommendation/status")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 推荐系统状态: {data}")
        else:
            print(f"✗ 推荐系统不可用: {response.status_code}")
            return
    except Exception as e:
        print(f"✗ 请求失败: {e}")
        return
    
    # 2. 检查 GSI 状态
    print("\n[2/4] 检查 GSI 状态...")
    try:
        response = requests.get(f"{API_BASE}/api/gsi/state")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ GSI 状态: {data}")
        else:
            print(f"✗ GSI 不可用: {response.status_code}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 3. 模拟 GSI 数据推送
    print("\n[3/4] 模拟 GSI 数据推送...")
    gsi_data = {
        "map": {
            "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
            "game_time": 720
        },
        "hero": {
            "id": 44,
            "name": "npc_dota_hero_phantom_assassin",
            "level": 9,
            "alive": True,
            "health": 250,
            "max_health": 1200,
            "mana": 80,
            "max_mana": 400
        },
        "player": {
            "steamid": "76561198000000000",
            "name": "TestPlayer",
            "kills": 3,
            "deaths": 2,
            "assists": 5,
            "gold": 1800
        }
    }
    
    try:
        response = requests.post(
            f"{API_BASE}/api/gsi/data",
            json=gsi_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            print(f"✓ GSI 数据推送成功")
            print(f"  响应: {response.json()}")
        else:
            print(f"✗ GSI 数据推送失败: {response.status_code}")
            print(f"  响应: {response.text}")
    except Exception as e:
        print(f"✗ 请求异常: {e}")
    
    # 4. 主动查询推荐
    print("\n[4/4] 主动查询推荐...")
    try:
        response = requests.get(f"{API_BASE}/api/gsi/recommendation/query")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 推荐查询成功:")
            print(f"  可用: {data.get('available')}")
            if data.get('available'):
                print(f"  推荐内容: {data.get('recommendation')}")
                print(f"  置信度: {data.get('confidence')}")
                print(f"  来源: {data.get('sources')}")
            else:
                print(f"  消息: {data.get('message')}")
        else:
            print(f"✗ 推荐查询失败: {response.status_code}")
            print(f"  响应: {response.text}")
    except Exception as e:
        print(f"✗ 请求异常: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    print("\n提示：")
    print("1. 打开浏览器访问: http://localhost:3001")
    print("2. 进入 GSI 状态面板")
    print("3. 观察是否能实时显示推荐数据")
    print("4. 可以通过 POST /api/gsi/data 持续推送 GSI 数据来触发推荐")


if __name__ == "__main__":
    test_sse_recommendation()
