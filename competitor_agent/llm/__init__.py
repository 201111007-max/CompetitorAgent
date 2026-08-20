"""LLM 抽象层"""
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply

__all__ = ["LLMClient", "ToolCall", "ToolCallReply"]