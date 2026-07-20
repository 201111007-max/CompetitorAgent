"""上下文压缩器单元测试"""
from unittest.mock import MagicMock, AsyncMock

import pytest

from post_match_review.engines.compressor import ContextCompressor
from post_match_review.llm.token_counter import TokenCounter
from post_match_review.interfaces.llm import ILLMClient


class MockLLMClient:
    """模拟 LLM 客户端"""

    def __init__(self, response: str = "摘要内容") -> None:
        self._response = response

    async def chat(
        self,
        messages: list,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        **kwargs,
    ) -> str:
        return self._response


def create_test_messages(count: int = 10) -> list:
    """创建测试消息列表"""
    messages = []
    for i in range(count):
        messages.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"这是第 {i} 条消息的内容，包含一些测试文本。" * 10,
        })
    return messages


def test_should_compress_below_threshold() -> None:
    """测试：Token 数低于阈值时不应压缩"""
    llm_client = MockLLMClient()
    compressor = ContextCompressor(
        llm_client=llm_client,
        target_max_tokens=10000,
    )

    # 1000 tokens < 10000 阈值
    assert compressor.should_compress(1000) is False


def test_should_compress_above_threshold() -> None:
    """测试：Token 数超过阈值时应压缩"""
    llm_client = MockLLMClient()
    compressor = ContextCompressor(
        llm_client=llm_client,
        target_max_tokens=10000,
    )

    # 15000 tokens > 10000 阈值
    assert compressor.should_compress(15000) is True


@pytest.mark.asyncio
async def test_compress_skips_when_below_threshold() -> None:
    """测试：低于阈值时直接返回原消息"""
    llm_client = MockLLMClient()
    compressor = ContextCompressor(
        llm_client=llm_client,
        target_max_tokens=10000,
    )

    messages = create_test_messages(5)
    result = await compressor.compress(messages, current_tokens=5000)

    assert result == messages


def test_prune_tool_results() -> None:
    """测试：修剪过长的工具结果"""
    llm_client = MockLLMClient()
    compressor = ContextCompressor(llm_client=llm_client)

    messages = [
        {"role": "user", "content": "短消息"},
        {"role": "function", "content": "x" * 600},  # 超过 500 字符
        {"role": "assistant", "content": "正常消息"},
    ]

    pruned = compressor._prune_tool_results(messages)

    assert len(pruned) == 3
    assert len(pruned[1]["content"]) < 600
    assert "已截断" in pruned[1]["content"]


def test_protect_tail() -> None:
    """测试：保护尾部消息"""
    llm_client = MockLLMClient()
    compressor = ContextCompressor(
        llm_client=llm_client,
        tail_token_budget=100,
    )

    messages = [
        {"role": "user", "content": "消息1" * 50},  # ~250 tokens
        {"role": "assistant", "content": "消息2" * 10},  # ~50 tokens
        {"role": "user", "content": "消息3" * 10},  # ~50 tokens
    ]

    tail = compressor._protect_tail(messages, token_budget=100)

    # 应该只包含最后 2 条消息（约 100 tokens）
    assert len(tail) <= 2


@pytest.mark.asyncio
async def test_summarize_middle_with_llm() -> None:
    """测试：使用 LLM 摘要中间内容"""
    llm_client = MockLLMClient(response="这是摘要内容")
    compressor = ContextCompressor(llm_client=llm_client)

    middle = [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": "助手回答"},
    ]

    summary = await compressor._summarize_middle(middle)

    assert summary == "这是摘要内容"


@pytest.mark.asyncio
async def test_summarize_middle_fallback_on_error() -> None:
    """测试：LLM 失败时降级为截断"""

    class FailingLLMClient:
        async def chat(self, messages, **kwargs):
            raise Exception("LLM 调用失败")

    compressor = ContextCompressor(llm_client=FailingLLMClient())

    middle = [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": "助手回答"},
    ]

    summary = await compressor._summarize_middle(middle)

    assert "已截断" in summary or len(summary) > 0


@pytest.mark.asyncio
async def test_compress_three_phase_strategy() -> None:
    """测试：三阶段压缩策略"""
    llm_client = MockLLMClient(response="压缩摘要")
    compressor = ContextCompressor(
        llm_client=llm_client,
        head_protect_count=2,
        tail_token_budget=200,
        target_max_tokens=100,
    )

    # 创建大量消息
    messages = create_test_messages(20)

    # 计算当前 tokens（模拟超过阈值）
    token_counter = TokenCounter()
    current_tokens = token_counter.count_messages(messages)

    # 执行压缩
    compressed = await compressor.compress(messages, current_tokens)

    # 验证压缩结果
    assert len(compressed) < len(messages)
    # 验证头部保护（前 2 条消息）
    assert compressed[0] == messages[0]
    assert compressed[1] == messages[1]
    # 验证包含摘要
    assert any("摘要" in msg.get("content", "") for msg in compressed)


@pytest.mark.asyncio
async def test_compress_preserves_head() -> None:
    """测试：压缩保留头部消息"""
    llm_client = MockLLMClient()
    compressor = ContextCompressor(
        llm_client=llm_client,
        head_protect_count=3,
        target_max_tokens=100,
    )

    messages = create_test_messages(15)
    current_tokens = 5000  # 超过阈值

    compressed = await compressor.compress(messages, current_tokens)

    # 前 3 条消息应该被保留
    assert compressed[0] == messages[0]
    assert compressed[1] == messages[1]
    assert compressed[2] == messages[2]
