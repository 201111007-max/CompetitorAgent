"""Token 计数器：估算文本和消息列表的 Token 数"""
from typing import List, Dict

from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.llm.token_counter")


class TokenCounter:
    """Token 计数器

    支持基于字符数的粗略估算，可选集成 tiktoken 进行精确计数。
    """

    def __init__(self, use_tiktoken: bool = True) -> None:
        """初始化计数器

        Args:
            use_tiktoken: 是否尝试使用 tiktoken，缺失时自动降级为字符估算
        """
        self._use_tiktoken = use_tiktoken
        self._tiktoken_available = False

        # 尝试导入 tiktoken
        if use_tiktoken:
            try:
                import tiktoken  # type: ignore
                self._tiktoken_available = True
                logger.info("TokenCounter: tiktoken 可用，使用精确计数")
            except ImportError:
                logger.warning("TokenCounter: tiktoken 不可用，降级为字符估算")

    def count_text(self, text: str, model: str = "gpt-4o") -> int:
        """估算文本 Token 数

        Args:
            text: 待计数文本
            model: 模型名称（用于选择 tiktoken 编码）

        Returns:
            int: 估算的 Token 数
        """
        if not text:
            return 0

        if self._tiktoken_available:
            return self._count_with_tiktoken(text, model)
        else:
            return self._count_with_estimation(text)

    def count_messages(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o",
    ) -> int:
        """估算消息列表 Token 数

        Args:
            messages: OpenAI 风格消息列表
            model: 模型名称

        Returns:
            int: 估算的总 Token 数
        """
        total_tokens = 0

        for msg in messages:
            # 每条消息有固定开销（role + 分隔符）
            total_tokens += 4  # role 和格式开销

            # 计算 content
            content = msg.get("content", "")
            if content:
                total_tokens += self.count_text(content, model)

            # 计算 name（如果有）
            name = msg.get("name", "")
            if name:
                total_tokens += self.count_text(name, model)

        # 每次请求的固定开销
        total_tokens += 2  # 起始和结束标记

        logger.debug("消息列表 Token 计数: %d 条消息, %d tokens", len(messages), total_tokens)
        return total_tokens

    def _count_with_tiktoken(self, text: str, model: str) -> int:
        """使用 tiktoken 精确计数

        Args:
            text: 待计数文本
            model: 模型名称

        Returns:
            int: 精确 Token 数
        """
        try:
            import tiktoken  # type: ignore

            # 根据模型选择编码
            if "gpt-4" in model or "gpt-3.5" in model:
                encoding = tiktoken.encoding_for_model(model)
            else:
                # 默认使用 cl100k_base（适用于大多数现代模型）
                encoding = tiktoken.get_encoding("cl100k_base")

            return len(encoding.encode(text))
        except Exception as e:
            logger.warning("tiktoken 计数失败，降级为字符估算: %s", str(e))
            return self._count_with_estimation(text)

    def _count_with_estimation(self, text: str) -> int:
        """基于字符数的粗略估算

        使用 1 token ≈ 4 字符的经验公式（英文为主）。
        中文文本 1 token ≈ 1.5-2 字符，但此处简化处理。

        Args:
            text: 待计数文本

        Returns:
            int: 估算的 Token 数
        """
        # 经验公式：1 token ≈ 4 字符
        estimated_tokens = len(text) // 4
        return max(1, estimated_tokens)  # 至少 1 个 token
