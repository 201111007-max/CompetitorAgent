"""上下文压缩器接口契约"""
from typing import List, Dict, Protocol


class IContextCompressor(Protocol):
    """上下文压缩器接口"""

    async def compress(
        self,
        messages: List[Dict[str, str]],
        current_tokens: int,
    ) -> List[Dict[str, str]]:
        """执行有损压缩

        Args:
            messages: 当前消息列表
            current_tokens: 当前 Token 数

        Returns:
            List[Dict[str, str]]: 压缩后的消息列表
        """
        ...

    def should_compress(self, current_tokens: int) -> bool:
        """判断是否需要压缩

        Args:
            current_tokens: 当前 Token 数

        Returns:
            bool: 是否需要压缩
        """
        ...
