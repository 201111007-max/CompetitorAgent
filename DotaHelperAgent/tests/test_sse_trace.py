"""测试 SSE 流式响应的 Trace 传递"""

import requests
import json
import time

def test_sse_stream():
    """测试 SSE 流式响应"""
    print("\n=== 测试 SSE 流式响应 ===")
    
    url = "http://localhost:5000/api/chat/stream"
    
    # 测试数据
    data = {
        "query": "谁是当前最强的英雄",
        "session_id": "test_session_001",
        "context": {}
    }
    
    print(f"发送请求: {url}")
    print(f"查询: {data['query']}")
    print(f"Session ID: {data['session_id']}")
    
    try:
        # 发送 POST 请求，接收 SSE 流
        response = requests.post(
            url,
            json=data,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=30
        )
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        
        # 检查响应头中的 Trace ID
        trace_id_header = response.headers.get('X-Trace-Id')
        print(f"\n响应头中的 Trace ID: {trace_id_header}")
        
        # 读取 SSE 事件
        events = []
        trace_ids_found = []
        
        for line in response.iter_lines(decode_unicode=True):
            if line:
                print(f"收到: {line}")
                
                # 解析 SSE 事件
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    event_data_str = line[6:]
                    try:
                        event_data = json.loads(event_data_str)
                        events.append({
                            "type": event_type,
                            "data": event_data
                        })
                        
                        # 检查 Trace 信息
                        if "trace" in event_data:
                            trace_info = event_data["trace"]
                            trace_id = trace_info.get("trace_id")
                            if trace_id and trace_id not in trace_ids_found:
                                trace_ids_found.append(trace_id)
                                print(f"  发现 Trace ID: {trace_id}")
                                print(f"  Trace 信息: {json.dumps(trace_info, indent=2)}")
                        
                        # 检查 trace_id 字段
                        if "trace_id" in event_data:
                            trace_id = event_data["trace_id"]
                            if trace_id and trace_id not in trace_ids_found:
                                trace_ids_found.append(trace_id)
                                print(f"  发现 Trace ID (字段): {trace_id}")
                        
                    except json.JSONDecodeError as e:
                        print(f"  JSON 解析失败: {e}")
        
        print(f"\n总共收到 {len(events)} 个事件")
        print(f"发现的 Trace ID: {trace_ids_found}")
        
        # 检查 Trace 信息是否正确传递
        if trace_ids_found:
            print("✓ Trace 信息已正确传递")
            
            # 检查 Trace ID 是否一致
            if len(trace_ids_found) == 1:
                print("✓ Trace ID 一致")
            else:
                print("⚠ Trace ID 不一致，可能有多个 Trace")
        else:
            print("✗ 未发现 Trace 信息")
        
        # 检查响应头中的 Trace ID 是否与事件中的一致
        if trace_id_header and trace_ids_found:
            if trace_id_header in trace_ids_found:
                print("✓ 响应头 Trace ID 与事件 Trace ID 一致")
            else:
                print("⚠ 响应头 Trace ID 与事件 Trace ID 不一致")
        
        return events, trace_ids_found
        
    except requests.exceptions.Timeout:
        print("✗ 请求超时")
        return [], []
    except requests.exceptions.RequestException as e:
        print(f"✗ 请求失败: {e}")
        return [], []


def test_trace_query():
    """测试 Trace 查询 API"""
    print("\n=== 测试 Trace 查询 API ===")
    
    # 先执行一个 SSE 请求，获取 Trace ID
    events, trace_ids = test_sse_stream()
    
    if not trace_ids:
        print("没有 Trace ID，无法测试查询")
        return
    
    trace_id = trace_ids[0]
    print(f"\n使用 Trace ID: {trace_id}")
    
    # 测试 Trace 查询 API
    url = f"http://localhost:5000/api/trace/{trace_id}"
    
    try:
        response = requests.get(url, timeout=10)
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            trace_data = response.json()
            print(f"Trace 数据: {json.dumps(trace_data, indent=2)}")
            print("✓ Trace 查询成功")
        else:
            print(f"✗ Trace 查询失败: {response.text}")
        
    except requests.exceptions.RequestException as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试 Trace 日志查询 API
    url = f"http://localhost:5000/api/trace/{trace_id}/logs"
    
    try:
        response = requests.get(url, timeout=10)
        print(f"\nTrace 日志查询响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            logs_data = response.json()
            print(f"Trace 日志数量: {len(logs_data.get('logs', []))}")
            if logs_data.get('logs'):
                print(f"第一条日志: {json.dumps(logs_data['logs'][0], indent=2)}")
            print("✓ Trace 日志查询成功")
        else:
            print(f"✗ Trace 日志查询失败: {response.text}")
        
    except requests.exceptions.RequestException as e:
        print(f"✗ 请求失败: {e}")


if __name__ == "__main__":
    test_trace_query()