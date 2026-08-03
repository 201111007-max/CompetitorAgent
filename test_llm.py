"""测试 LLM 调用"""
import asyncio
import os
from dotenv import load_dotenv

# 加载 .env
_env_path = os.path.join(os.path.dirname(__file__), "dota_helper", ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=False)
    print(f"Loaded .env from {_env_path}")
    print(f"DEEPSEEK_API_KEY set: {bool(os.getenv('DEEPSEEK_API_KEY'))}")
    print(f"OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")
    print(f"HTTPS_PROXY: {os.getenv('HTTPS_PROXY')}")
else:
    print(f".env not found at {_env_path}")

from dota_helper.llm.client import LLMClient

async def main():
    client = LLMClient()
    try:
        result = await client.chat(
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        print(f"LLM result: {result}")
    except Exception as e:
        print(f"LLM error: {type(e).__name__}: {e}")

asyncio.run(main())
