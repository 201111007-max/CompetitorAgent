import requests
import json

url = "http://localhost:5000/api/chat"
data = {
    "query": "我方英雄有虚空假面,帕格纳,沙王，推荐我选什么英雄"
}

response = requests.post(url, json=data)
print(json.dumps(response.json(), indent=2, ensure_ascii=False))
