"""
测试推荐系统 SSE 推送
模拟 GSI 事件触发推荐
"""

import requests
import time
import json

# 后端 API 地址
API_BASE = "http://localhost:5000"

def test_recommendation_status():
    """测试推荐系统状态"""
    print("=" * 60)
    print("测试推荐系统状态")
    print("=" * 60)
    
    try:
        response = requests.get(f"{API_BASE}/api/gsi/recommendation/status")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 推荐系统状态: {json.dumps(data, indent=2, ensure_ascii=False)}")
            return data.get("available", False)
        else:
            print(f"✗ 请求失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ 请求异常: {e}")
        return False


def test_gsi_state():
    """测试 GSI 状态"""
    print("\n" + "=" * 60)
    print("测试 GSI 状态")
    print("=" * 60)
    
    try:
        response = requests.get(f"{API_BASE}/api/gsi/state")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ GSI 状态: {json.dumps(data, indent=2, ensure_ascii=False)}")
            return data.get("available", False)
        else:
            print(f"✗ 请求失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ 请求异常: {e}")
        return False


def simulate_gsi_event():
    """模拟 GSI 事件推送到后端"""
    print("\n" + "=" * 60)
    print("模拟 GSI 事件推送")
    print("=" * 60)
    
    # 模拟低血量事件
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
        # 发送 GSI 数据到后端
        response = requests.post(
            f"{API_BASE}/api/gsi/data",
            json=gsi_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            print(f"✓ GSI 数据推送成功")
            print(f"  响应: {response.json()}")
            return True
        else:
            print(f"✗ GSI 数据推送失败: {response.status_code}")
            print(f"  响应: {response.text}")
            return False
    except Exception as e:
        print(f"✗ 请求异常: {e}")
        return False


def test_recommendation_query():
    """测试主动查询推荐"""
    print("\n" + "=" * 60)
    print("测试主动查询推荐")
    print("=" * 60)
    
    try:
        response = requests.get(f"{API_BASE}/api/gsi/recommendation/query")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 推荐查询结果: {json.dumps(data, indent=2, ensure_ascii=False)}")
            return True
        else:
            print(f"✗ 请求失败: {response.status_code}")
            print(f"  响应: {response.text}")
            return False
    except Exception as e:
        print(f"✗ 请求异常: {e}")
        return False


def main():
    """主测试流程"""
    print("\n" + "=" * 60)
    print("推荐系统 SSE 推送测试")
    print("=" * 60)
    print(f"后端 API: {API_BASE}")
    print()
    
    # 1. 测试推荐系统状态
    rec_available = test_recommendation_status()
    
    # 2. 测试 GSI 状态
    gsi_available = test_gsi_state()
    
    # 3. 模拟 GSI 事件
    if gsi_available:
        simulate_gsi_event()
        time.sleep(2)  # 等待事件处理
    
    # 4. 测试推荐查询
    if rec_available:
        test_recommendation_query()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    print("\n提示: 请在浏览器中打开 http://localhost:3000")
    print("查看 GSI 状态面板中的'主动推荐'区域")
    print("如果看到推荐信息，说明 SSE 推送正常工作")


if __name__ == "__main__":
    main()
