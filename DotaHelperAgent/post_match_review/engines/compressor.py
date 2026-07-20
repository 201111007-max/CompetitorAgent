"""上下文压缩器：修剪 + 保护 + LLM 摘要"""
from typing import List, Dict, Any

from post_match_review.interfaces.compressor import IContextCompressor
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.llm.token_counter import TokenCounter
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.engines.compressor")


class ContextCompressor:
    """上下文压缩器（修剪 + 保护 + LLM 摘要）

    三阶段压缩策略：
    1. 修剪过长的工具结果
    2. 保护头部（系统提示）和尾部（最近上下文）
    3. 使用 LLM 摘要中间区域
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        head_protect_count: int = 2,
        tail_token_budget: int = 20000,
        target_max_tokens: int = 15250,
        summary_token_budget: int = 750,
        token_counter: TokenCounter | None = None,
    ) -> None:
        """初始化压缩器

        Args:
            llm_client: LLM 客户端（用于生成摘要）
            head_protect_count: 头部保护的消息数量
            tail_token_budget: 尾部保护的 Token 预算
            target_max_tokens: 目标最大 Token 数（超过则触发压缩）
            summary_token_budget: 摘要 Token 预算
            token_counter: Token 计数器（可选，默认创建新实例）
        """
        self._llm_client = llm_client
        self._head_protect_count = head_protect_count
        self._tail_token_budget = tail_token_budget
        self._target_max_tokens = target_max_tokens
        self._summary_token_budget = summary_token_budget
        self._token_counter = token_counter or TokenCounter()

        logger.info(
            "上下文压缩器初始化: head_protect=%d, tail_budget=%d, target_max=%d",
            head_protect_count,
            tail_token_budget,
            target_max_tokens,
        )

    def should_compress(self, current_tokens: int) -> bool:
        """判断是否需要压缩

        Args:
            current_tokens: 当前 Token 数

        Returns:
            bool: 是否超过目标阈值
        """
        return current_tokens > self._target_max_tokens

    async def compress(
        self,
        messages: List[Dict[str, str]],
        current_tokens: int,
    ) -> List[Dict[str, str]]:
        """执行三阶段压缩

        Args:
            messages: 当前消息列表
            current_tokens: 当前 Token 数

        Returns:
            List[Dict[str, str]]: 压缩后的消息列表
        """
        logger.info(
            "[压缩器] 开始压缩检查: messages_count=%d, current_tokens=%d, target_max_tokens=%d",
            len(messages),
            current_tokens,
            self._target_max_tokens,
        )

        if not self.should_compress(current_tokens):
            logger.info(
                "[压缩器] 无需压缩: current_tokens=%d <= target_max_tokens=%d",
                current_tokens,
                self._target_max_tokens,
            )
            return messages

        logger.info(
            "[压缩器] 需要压缩: current_tokens=%d > target_max_tokens=%d",
            current_tokens,
            self._target_max_tokens,
        )

        # 阶段 1：修剪工具结果
        logger.info("[压缩器] 阶段 1: 修剪工具结果")
        messages = self._prune_tool_results(messages)
        logger.info("[压缩器] 修剪完成: messages_count=%d", len(messages))

        # 阶段 2：划分保护区域
        logger.info(
            "[压缩器] 阶段 2: 划分保护区域: head_protect_count=%d, tail_token_budget=%d",
            self._head_protect_count,
            self._tail_token_budget,
        )
        head = messages[: self._head_protect_count]
        tail = self._protect_tail(messages[self._head_protect_count :], self._tail_token_budget)
        middle_start = self._head_protect_count
        middle_end = len(messages) - len(tail)
        middle = messages[middle_start:middle_end]

        logger.info(
            "[压缩器] 区域划分完成: head=%d messages, middle=%d messages, tail=%d messages",
            len(head),
            len(middle),
            len(tail),
        )

        # 阶段 3：摘要中间区域
        logger.info("[压缩器] 阶段 3: 处理中间区域")
        if middle:
            logger.info(
                "[压缩器] 开始摘要中间区域: messages_count=%d, summary_token_budget=%d",
                len(middle),
                self._summary_token_budget,
            )
            summary = await self._summarize_middle(middle)
            summary_msg = {
                "role": "system",
                "content": f"[上下文摘要] {summary}",
            }
            compressed = head + [summary_msg] + tail
            logger.info(
                "[压缩器] 摘要完成: summary_length=%d characters",
                len(summary),
            )
        else:
            logger.info("[压缩器] 中间区域为空，跳过摘要")
            compressed = head + tail

        # 验证压缩结果
        new_tokens = self._token_counter.count_messages(compressed)
        compression_ratio = (1 - new_tokens / current_tokens) * 100 if current_tokens > 0 else 0
        logger.info(
            "[压缩器] 压缩完成: before_tokens=%d, after_tokens=%d, compression_ratio=%.1f%%, messages_count=%d",
            current_tokens,
            new_tokens,
            compression_ratio,
            len(compressed),
        )

        return compressed

    def _prune_tool_results(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """修剪过长的工具结果

        将超过 500 字符的工具结果截断，保留前 200 字符和摘要。

        Args:
            messages: 消息列表

        Returns:
            List[Dict[str, str]]: 修剪后的消息列表
        """
        pruned = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # 工具结果通常是 function 或 tool 角色
            if role in ("function", "tool") and len(content) > 500:
                truncated = content[:200] + "\n...[已截断]..."
                pruned.append({"role": role, "content": truncated})
                logger.debug("修剪工具结果: %d -> %d 字符", len(content), len(truncated))
            else:
                pruned.append(msg)

        return pruned

    def _protect_tail(
        self,
        messages: List[Dict[str, str]],
        token_budget: int,
    ) -> List[Dict[str, str]]:
        """保护尾部消息

        从尾部向前累积，直到达到 Token 预算。

        Args:
            messages: 消息列表（不含头部）
            token_budget: 尾部 Token 预算

        Returns:
            List[Dict[str, str]]: 受保护的尾部消息
        """
        if not messages:
            return []

        tail: List[Dict[str, str]] = []
        tail_tokens = 0

        for msg in reversed(messages):
            msg_tokens = self._token_counter.count_text(msg.get("content", ""))
            if tail_tokens + msg_tokens > token_budget:
                break
            tail.insert(0, msg)
            tail_tokens += msg_tokens

        logger.debug("尾部保护: %d 条消息, %d tokens", len(tail), tail_tokens)
        return tail

    async def _summarize_middle(self, middle: List[Dict[str, str]]) -> str:
        """使用 LLM 摘要中间内容

        Args:
            middle: 中间区域消息列表

        Returns:
            str: 摘要文本
        """
        if not middle:
            return ""

        # 构建待摘要内容
        content_parts = []
        for msg in middle:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            content_parts.append(f"[{role}]: {content}")

        full_content = "\n".join(content_parts)

        # 构建摘要请求
        summary_prompt = (
            "请将以下对话内容压缩为简洁的摘要，保留关键信息和结论。"
            f"摘要长度控制在 {self._summary_token_budget} tokens 以内。\n\n"
            f"{full_content}"
        )

        try:
            summary = await self._llm_client.chat(
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.3,
            )
            logger.info("LLM 摘要生成成功: %d 字符", len(summary))
            return summary.strip()
        except Exception as e:
            logger.warning("LLM 摘要失败，降级为截断: %s", str(e))
            # 降级策略：直接截断中间内容
            max_chars = self._summary_token_budget * 4  # 粗略估算
            return full_content[:max_chars] + "\n...[已截断]..."
