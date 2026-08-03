import requests, json

url = 'http://localhost:8000/api/chat'
payload = {'message': '复盘比赛 8909780728', 'session_id': 'test-500'}
try:
    resp = requests.post(url, json=payload, stream=True, timeout=60)
    print(f'Status: {resp.status_code}')
    events = []
    for line in resp.iter_lines(decode_unicode=True):
        if line:
            if line.startswith('data: '):
                data = json.loads(line[6:])
                events.append(data['type'])
                if data['type'] == 'final':
                    print(f'Final content (first 200): {data["content"][:200]}')
                elif data['type'] == 'error':
                    print(f'Error: {data.get("content", "")}')
    print(f'Event types: {events}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}')
