"""LangChain 示例 - 使用 LM Studio 本地模型调用工具 + Langfuse 监控"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langfuse import Langfuse
from config.settings import Config


langfuse = Langfuse(
    public_key=Config.LANGFUSE_PUBLIC_KEY,
    secret_key=Config.LANGFUSE_SECRET_KEY,
    host=Config.LANGFUSE_HOST,
)


@tool
def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"


llm = ChatOpenAI(
    model="qwen3.5-9b", base_url="http://localhost:1234/v1", api_key="lmstudio", temperature=0
)

llm_with_tools = llm.bind_tools([get_weather])

user_input = "what is the weather in San Francisco?"

trace = langfuse.trace(name="weather-query", input=user_input)

result = llm_with_tools.invoke([HumanMessage(content=user_input)])

trace.generation(
    model=result.response_metadata.get("model_name", "qwen3.5-9b")
    if hasattr(result, "response_metadata")
    else "qwen3.5-9b",
    input=[{"role": "user", "content": user_input}],
    output=str(result.tool_calls) if result.tool_calls else result.content,
)

print("=" * 50)
print("Model Response:")
print(result)
print("=" * 50)

if hasattr(result, "tool_calls") and result.tool_calls:
    print("\nTool Calls:")
    for tool_call in result.tool_calls:
        print(f"  - {tool_call}")

        if tool_call["name"] == "get_weather":
            args = tool_call["args"]
            tool_result = get_weather.invoke(args)
            print(f"  Tool Result: {tool_result}")

            trace.tool(name="get_weather", input=args, output=str(tool_result))

langfuse.flush()
