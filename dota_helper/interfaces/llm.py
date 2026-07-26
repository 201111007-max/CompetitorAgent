"""LLM 客户端接口契约"""
from typing import Protocol, List, Dict, Any


class ILLMClient(Protocol):
    """LLM 客户端接口"""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        """调用 LLM 生成回复

        Args:
            messages: OpenAI 风格消息列表
            model: 模型名称
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            str: 模型回复文本
        """
        ...
