"""RagPlugin 单元测试"""
from typing import Any, Dict, List

import pytest

from dota_helper.agent.rag_plugin import RagPlugin
from dota_helper.agent.rag_engine import RagEngine


class TestRagPlugin:
    """RagPlugin 基本功能测试"""

    @pytest.fixture
    def engine(self) -> RagEngine:
        """创建 RagEngine 实例"""
        return RagEngine()

    @pytest.fixture
    def plugin(self, engine: RagEngine) -> RagPlugin:
        """创建 RagPlugin 实例"""
        return RagPlugin(engine=engine, threshold=0.4, top_k=2)

    def test_plugin_name(self, plugin: RagPlugin) -> None:
        """插件名称正确"""
        assert plugin.name == "RagPlugin"

    def test_get_last_user_message(self, plugin: RagPlugin) -> None:
        """提取最后一条 user 消息"""
        messages = [
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "幽鬼怎么玩"},
            {"role": "assistant", "content": "让我想想"},
            {"role": "user", "content": "帕吉呢"},
        ]
        result = plugin._get_last_user_message(messages)
        assert result == "帕吉呢"

    def test_get_last_user_message_no_user(self, plugin: RagPlugin) -> None:
        """无 user 消息返回空字符串"""
        messages = [
            {"role": "system", "content": "You are a helper"},
            {"role": "assistant", "content": "Hello"},
        ]
        result = plugin._get_last_user_message(messages)
        assert result == ""

    def test_get_last_user_message_empty(self, plugin: RagPlugin) -> None:
        """空消息列表返回空字符串"""
        result = plugin._get_last_user_message([])
        assert result == ""

    def test_inject_context_appends_to_last_system(self, plugin: RagPlugin) -> None:
        """注入到最后一条 system 消息末尾"""
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "幽鬼怎么玩"},
        ]
        result = plugin._inject_context(messages, "## 相关知识\n幽鬼攻略")
        assert len(result) == 2
        assert "## 相关知识" in result[0]["content"]
        assert result[0]["role"] == "system"

    def test_inject_context_no_system(self, plugin: RagPlugin) -> None:
        """无 system 消息时在开头插入"""
        messages: List[Dict[str, str]] = [
            {"role": "user", "content": "幽鬼怎么玩"},
        ]
        result = plugin._inject_context(messages, "## 相关知识\n幽鬼攻略")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "## 相关知识" in result[0]["content"]

    def test_inject_context_multiple_system(self, plugin: RagPlugin) -> None:
        """多个 system 消息时追加到最后一条"""
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "System prompt 1"},
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "System prompt 2"},
        ]
        result = plugin._inject_context(messages, "## 相关知识\n幽鬼攻略")
        assert len(result) == 3
        assert "System prompt 2" in result[2]["content"]
        assert "## 相关知识" in result[2]["content"]

    def test_reset_clears_cache(self, plugin: RagPlugin) -> None:
        """reset 清除去重缓存"""
        plugin._last_query = "幽鬼怎么玩"
        plugin._last_injected = "## 相关知识\n幽鬼攻略"
        plugin.reset()
        assert plugin._last_query == ""
        assert plugin._last_injected == ""

    @pytest.mark.asyncio
    async def test_before_llm_call_empty_message(self, plugin: RagPlugin) -> None:
        """空消息不检索"""
        messages: List[Dict[str, str]] = []
        result = await plugin.before_llm_call(messages)
        assert result == []

    @pytest.mark.asyncio
    async def test_before_llm_call_no_user(self, plugin: RagPlugin) -> None:
        """无 user 消息不检索"""
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helper"},
        ]
        result = await plugin.before_llm_call(messages)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_before_llm_call_dedup(self, plugin: RagPlugin) -> None:
        """同一 query 不重复检索"""
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "幽鬼怎么玩"},
        ]
        # 第一次调用
        result1 = await plugin.before_llm_call(messages)
        # 第二次调用（相同 query）
        result2 = await plugin.before_llm_call(result1)
        # 第二次不应再注入
        assert len(result2) == len(result1)
