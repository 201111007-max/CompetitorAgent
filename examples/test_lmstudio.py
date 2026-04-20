"""测试 LM Studio 模型调用"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_anthropic import ChatAnthropic
from config.settings import Config


def test_llm():
    print("=" * 50)
    print("测试 LM Studio 模型调用")
    print("=" * 50)

    print(f"\n配置信息:")
    print(f"  ANTHROPIC_BASE_URL: {Config.ANTHROPIC_BASE_URL}")
    print(f"  ANTHROPIC_AUTH_TOKEN: {Config.ANTHROPIC_AUTH_TOKEN}")

    client = ChatAnthropic(
        base_url=Config.ANTHROPIC_BASE_URL, api_key=Config.ANTHROPIC_AUTH_TOKEN, model="qwen3.5-9b"
    )

    print(f"\n发送测试请求到模型: qwen3.5-9b")
    print("...")

    response = client.invoke("你好，请用一句话介绍自己")

    print(f"\n[OK] 模型响应成功!")
    print(f"响应内容: {response.content}")
    print("=" * 50)


if __name__ == "__main__":
    test_llm()
