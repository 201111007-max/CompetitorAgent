"""插件系统单元测试"""
import pytest

from dota_helper.agent.plugin import Plugin, PluginRegistry


class TestPlugin(Plugin):
    """测试用插件：记录所有钩子调用"""
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.block_action: bool = False
        self.modify_messages: bool = False
        self.modify_llm_output: bool = False

    async def on_start(self, context: dict) -> None:
        self.calls.append(f"on_start:{context.get('session_id', '')}")

    async def on_end(self, context: dict) -> None:
        self.calls.append(f"on_end:{context.get('session_id', '')}")

    async def before_llm_call(self, messages: list) -> list:
        self.calls.append("before_llm_call")
        if self.modify_messages:
            messages.append({"role": "system", "content": "plugin injected"})
        return messages

    async def after_llm_call(self, llm_output: str) -> str:
        self.calls.append("after_llm_call")
        if self.modify_llm_output:
            return llm_output + " [plugin modified]"
        return llm_output

    async def before_action(self, tool_name: str, args: dict) -> dict | None:
        self.calls.append(f"before_action:{tool_name}")
        if self.block_action:
            return None
        return args

    async def after_action(self, tool_name: str, args: dict, result: str) -> str:
        self.calls.append(f"after_action:{tool_name}")
        return result + " [plugin enriched]"

    async def on_error(self, error: Exception, context: str = "") -> None:
        self.calls.append(f"on_error:{type(error).__name__}:{context}")


class TestPluginRegistry:
    """测试 PluginRegistry 的注册和事件分发"""

    @pytest.mark.asyncio
    async def test_register_and_unregister(self) -> None:
        """注册和卸载插件"""
        registry = PluginRegistry()
        plugin = TestPlugin()

        name = registry.register(plugin)
        assert name == "TestPlugin"
        assert registry.count == 1
        assert registry.get_plugin("TestPlugin") is plugin

        result = registry.unregister("TestPlugin")
        assert result is True
        assert registry.count == 0

    @pytest.mark.asyncio
    async def test_register_duplicate_raises(self) -> None:
        """重复注册同名插件抛出 ValueError"""
        registry = PluginRegistry()
        registry.register(TestPlugin(), name="my_plugin")

        with pytest.raises(ValueError, match="已注册"):
            registry.register(TestPlugin(), name="my_plugin")

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_returns_false(self) -> None:
        """卸载不存在的插件返回 False"""
        registry = PluginRegistry()
        result = registry.unregister("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_on_start_and_on_end(self) -> None:
        """on_start 和 on_end 事件分发"""
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)

        await registry.dispatch_on_start({"session_id": "sess_123"})
        await registry.dispatch_on_end({"session_id": "sess_123"})

        assert plugin.calls == ["on_start:sess_123", "on_end:sess_123"]

    @pytest.mark.asyncio
    async def test_before_and_after_llm_call(self) -> None:
        """before_llm_call 和 after_llm_call 事件分发"""
        registry = PluginRegistry()
        plugin = TestPlugin()
        plugin.modify_messages = True
        plugin.modify_llm_output = True
        registry.register(plugin)

        messages = [{"role": "user", "content": "hello"}]
        result_messages = await registry.dispatch_before_llm_call(messages)
        assert len(result_messages) == 2
        assert result_messages[-1]["content"] == "plugin injected"

        result_output = await registry.dispatch_after_llm_call("original output")
        assert result_output == "original output [plugin modified]"

        assert "before_llm_call" in plugin.calls
        assert "after_llm_call" in plugin.calls

    @pytest.mark.asyncio
    async def test_before_action_normal(self) -> None:
        """before_action 正常返回参数"""
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)

        result = await registry.dispatch_before_action("get_match_details", {"match_id": 123})
        assert result == {"match_id": 123}
        assert "before_action:get_match_details" in plugin.calls

    @pytest.mark.asyncio
    async def test_before_action_blocked(self) -> None:
        """before_action 返回 None 阻止调用"""
        registry = PluginRegistry()
        plugin = TestPlugin()
        plugin.block_action = True
        registry.register(plugin)

        result = await registry.dispatch_before_action("get_match_details", {"match_id": 123})
        assert result is None

    @pytest.mark.asyncio
    async def test_after_action(self) -> None:
        """after_action 事件分发"""
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)

        result = await registry.dispatch_after_action(
            "get_match_details", {"match_id": 123}, "original result"
        )
        assert result == "original result [plugin enriched]"
        assert "after_action:get_match_details" in plugin.calls

    @pytest.mark.asyncio
    async def test_on_error(self) -> None:
        """on_error 事件分发"""
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)

        await registry.dispatch_on_error(ValueError("bad value"), context="tool:test")
        assert "on_error:ValueError:tool:test" in plugin.calls

    @pytest.mark.asyncio
    async def test_multiple_plugins_pipeline(self) -> None:
        """多个插件按注册顺序管道执行"""
        registry = PluginRegistry()

        class PrefixPlugin(Plugin):
            async def after_llm_call(self, llm_output: str) -> str:
                return f"[P1]{llm_output}"

        class SuffixPlugin(Plugin):
            async def after_llm_call(self, llm_output: str) -> str:
                return f"{llm_output}[P2]"

        registry.register(PrefixPlugin(), name="p1")
        registry.register(SuffixPlugin(), name="p2")

        result = await registry.dispatch_after_llm_call("hello")
        assert result == "[P1]hello[P2]"

    @pytest.mark.asyncio
    async def test_plugin_error_does_not_break_chain(self) -> None:
        """单个插件异常不影响其他插件"""
        registry = PluginRegistry()

        class BrokenPlugin(Plugin):
            async def after_llm_call(self, llm_output: str) -> str:
                raise RuntimeError("broken")

        class GoodPlugin(Plugin):
            async def after_llm_call(self, llm_output: str) -> str:
                return llm_output + " [ok]"

        registry.register(BrokenPlugin(), name="broken")
        registry.register(GoodPlugin(), name="good")

        result = await registry.dispatch_after_llm_call("hello")
        assert result == "hello [ok]"

    @pytest.mark.asyncio
    async def test_plugin_registry_properties(self) -> None:
        """PluginRegistry 属性"""
        registry = PluginRegistry()
        assert registry.count == 0
        assert registry.plugins == {}

        p1 = TestPlugin()
        p2 = TestPlugin()
        registry.register(p1, name="p1")
        registry.register(p2, name="p2")

        assert registry.count == 2
        assert len(registry.plugins) == 2
        assert registry.plugins["p1"] is p1
        assert registry.plugins["p2"] is p2
