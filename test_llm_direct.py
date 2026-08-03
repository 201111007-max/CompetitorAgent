"""测试 LLM 调用是否正常工作（带代理）"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test():
    from dota_helper.llm.client import LLMClient

    # 设置代理
    os.environ["HTTP_PROXY"] = "http://proxynj.huawei.com:8080"
    os.environ["HTTPS_PROXY"] = "http://proxynj.huawei.com:8080"

    client = LLMClient(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        timeout=30,
    )

    print("Testing LLM call with proxy...", flush=True)
    try:
        result = await asyncio.wait_for(
            client.chat([{"role": "user", "content": "Say hello in one word."}]),
            timeout=25,
        )
        print(f"SUCCESS: {result}", flush=True)
    except asyncio.TimeoutError:
        print("TIMEOUT: LLM call timed out after 25s", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test())
