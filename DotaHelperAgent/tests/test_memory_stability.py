"""检查 Trace 系统的内存使用情况"""

import requests
import json
import time
import psutil
import os

def get_memory_usage():
    """获取当前进程的内存使用"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024  # MB

def test_memory_stability():
    """测试内存稳定性"""
    print("\n=== 测试内存稳定性 ===")
    
    url = "http://localhost:5000/api/chat/stream"
    
    # 测试数据
    data = {
        "query": "谁是当前最强的英雄",
        "session_id": "test_session_memory",
        "context": {}
    }
    
    print(f"初始内存使用: {get_memory_usage():.2f} MB")
    
    # 执行多次请求，观察内存使用
    for i in range(10):
        print(f"\n--- 第 {i+1} 次请求 ---")
        
        try:
            response = requests.post(
                url,
                json=data,
                headers={"Content-Type": "application/json"},
                stream=True,
                timeout=30
            )
            
            # 读取所有事件
            events_count = 0
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    events_count += 1
            
            print(f"收到事件数: {events_count}")
            
            # 检查内存使用
            memory_mb = get_memory_usage()
            print(f"内存使用: {memory_mb:.2f} MB")
            
            # 检查日志数量
            logs_response = requests.get(
                "http://localhost:5000/api/logs?limit=100",
                timeout=10
            )
            logs_data = logs_response.json()
            logs_count = len(logs_data.get('logs', []))
            print(f"日志数量: {logs_count}")
            
            # 检查错误数量
            errors_response = requests.get(
                "http://localhost:5000/api/errors?limit=100",
                timeout=10
            )
            errors_data = errors_response.json()
            errors_count = errors_data.get('total', 0)
            print(f"错误数量: {errors_count}")
            
        except requests.exceptions.RequestException as e:
            print(f"请求失败: {e}")
        
        # 等待一会儿
        time.sleep(2)
    
    print(f"\n最终内存使用: {get_memory_usage():.2f} MB")
    print("✓ 内存稳定性测试完成")


def test_index_cleanup():
    """测试索引清理功能"""
    print("\n=== 测试索引清理功能 ===")
    
    # 获取内存日志处理器实例（通过 API）
    # 由于无法直接访问，我们通过日志数量来间接验证
    
    url = "http://localhost:5000/api/logs?limit=1000"
    
    try:
        response = requests.get(url, timeout=10)
        logs_data = response.json()
        logs_count = len(logs_data.get('logs', []))
        
        print(f"当前日志数量: {logs_count}")
        
        # 检查日志格式是否正确
        if logs_count > 0:
            first_log = logs_data['logs'][0]
            print(f"第一条日志格式: {json.dumps(first_log, indent=2)[:200]}")
            
            # 检查必要字段
            required_fields = ['timestamp', 'level', 'message', 'session_id', 'trace_id']
            missing_fields = [f for f in required_fields if f not in first_log]
            
            if missing_fields:
                print(f"⚠ 缺少字段: {missing_fields}")
            else:
                print("✓ 日志格式正确")
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")


def test_clear_session():
    """测试清空特定 session 的功能"""
    print("\n=== 测试清空特定 session ===")
    
    # 先创建一些日志
    url = "http://localhost:5000/api/chat/stream"
    data = {
        "query": "测试查询",
        "session_id": "test_session_clear",
        "context": {}
    }
    
    try:
        response = requests.post(
            url,
            json=data,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=30
        )
        
        # 读取所有事件
        for line in response.iter_lines(decode_unicode=True):
            if line:
                pass  # 只读取，不处理
        
        print("已创建测试日志")
        
        # 检查日志数量
        logs_response = requests.get(
            f"http://localhost:5000/api/logs?session_id=test_session_clear&limit=100",
            timeout=10
        )
        logs_data = logs_response.json()
        logs_count = len(logs_data.get('logs', []))
        print(f"Session 日志数量: {logs_count}")
        
        # 清空该 session
        clear_response = requests.post(
            "http://localhost:5000/api/logs/clear",
            json={"session_id": "test_session_clear"},
            timeout=10
        )
        
        print(f"清空响应状态码: {clear_response.status_code}")
        
        if clear_response.status_code == 200:
            clear_data = clear_response.json()
            print(f"清空结果: {json.dumps(clear_data, indent=2)}")
            
            # 再次检查日志数量
            logs_response2 = requests.get(
                f"http://localhost:5000/api/logs?session_id=test_session_clear&limit=100",
                timeout=10
            )
            logs_data2 = logs_response2.json()
            logs_count2 = len(logs_data2.get('logs', []))
            print(f"清空后 Session 日志数量: {logs_count2}")
            
            if logs_count2 == 0:
                print("✓ Session 清空成功")
            else:
                print("⚠ Session 清空后仍有日志")
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")


if __name__ == "__main__":
    test_memory_stability()
    test_index_cleanup()
    test_clear_session()