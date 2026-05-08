"""测试英雄推荐 API"""

import requests
import json

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
