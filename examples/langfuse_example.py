"""Langfuse 使用示例"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from langfuse import Langfuse, observe
from config.settings import Config

langfuse = Config.init_langfuse()


@observe(name="greeting_function")
def create_greeting(name: str, tone: str = "friendly") -> str:
    if tone == "friendly":
        return f"Hello, {name}! Nice to meet you!"
    elif tone == "formal":
        return f"Good day, {name}. It is a pleasure to make your acquaintance."
    else:
        return f"Hi {name}!"


@observe(name="data_processing")
def process_data(data: dict) -> dict:
    result = {k: v.upper() if isinstance(v, str) else v for k, v in data.items()}
    return result


@observe(name="full_workflow")
def full_workflow(user_name: str) -> dict:
    greeting = create_greeting(user_name, "friendly")
    data = process_data({"name": user_name, "status": "active"})
    return {
        "greeting": greeting,
        "processed_data": data
    }


if __name__ == "__main__":
    result = full_workflow("Alice")
    print(f"Result: {result}")
    print(f"\n查看追踪数据请访问：{Config.LANGFUSE_HOST}")
    print("确保 Langfuse 服务已启动：docker run -d -p 3000:3000 langfuse/langfuse")
