"""测试英雄推荐 API - E2E 集成测试

测试完整的 HTTP API 调用流程
"""

import requests
import json


def test_hero_recommendation():
    """测试英雄推荐功能"""
    url = "http://localhost:5000/api/chat"
    data = {
        "query": "我方英雄有敌法师,祈求者,圣堂刺客，敌方英雄有混沌骑士,裂魂人，推荐我选什么英雄，并简要给出理由",
        "session_id": "test-session-001"
    }

    print("发送请求...")
    response = requests.post(url, json=data)

    if response.status_code == 200:
        result = response.json()
        print("\n=== 测试结果 ===")
        print(f"成功: {result.get('success')}")
        print(f"耗时: {result.get('duration', 'N/A')} 秒")
        print(f"轮次: {result.get('turn_count', 'N/A')}")
        print(f"\n最终答案:\n{result.get('final_answer', 'N/A')}")
    else:
        print(f"请求失败: {response.status_code}")
        print(response.text)


def test_counter_recommendation():
    """测试克制英雄推荐"""
    url = "http://localhost:5000/api/chat"
    data = {
        "query": "我方英雄有虚空假面,帕格纳,沙王，推荐我选什么英雄"
    }

    print("发送克制推荐请求...")
    response = requests.post(url, json=data)

    if response.status_code == 200:
        result = response.json()
        print("\n=== 克制推荐测试结果 ===")
        print(f"成功: {result.get('success')}")
        print(f"耗时: {result.get('duration', 'N/A')} 秒")
        print(f"\n最终答案:\n{result.get('final_answer', 'N/A')}")
    else:
        print(f"请求失败: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("E2E API 测试 - 英雄推荐")
    print("="*60)
    
    try:
        test_hero_recommendation()
        print("\n" + "-"*60)
        test_counter_recommendation()
        print("\n" + "="*60)
        print("测试完成！")
        print("="*60)
    except requests.exceptions.ConnectionError:
        print("\n[错误] 无法连接到服务器，请确保服务已启动: http://localhost:5000")
    except Exception as e:
        print(f"\n[错误] 测试失败: {e}")
        import traceback
        traceback.print_exc()
