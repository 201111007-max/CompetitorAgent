"""设计文档 40 — MCP↔ReAct 工具打通：唯一工具源 / 同源生成 / 多工具 ReAct / 自恢复

全程 mock LLM（call_func），不触真实网络与 API Key；
MCP 同源测试依赖 mcp 包（importorskip），无 mcp 时跳过。
"""
from __future__ import annotations

import asyncio

import pytest
from competitor_agent.agent import ReactAgent, ToolArgumentError
from competitor_agent.agent.delegate_tool import (
    DelegateRunner,
    SubagentRuntime,
    make_delegate_tool,
)
from competitor_agent.agent.tool_registry import build_openai_tools, build_react_dispatcher
from competitor_agent.config.loader import AppConfig
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply
from competitor_agent.mcp_server.tools import TOOL_SPECS, TOOLS


def _config() -> AppConfig:
    return AppConfig()


class TestRegistryConsistency:
    """注册表一致：tool_count == len(TOOLS)，每个工具描述含参数类型与描述（schema 生效）"""

    def test_tool_count_matches_tools(self):
        d = build_react_dispatcher(config=_config())
        assert d.tool_count == len(TOOLS) == len(TOOL_SPECS) == 8

    def test_all_tool_names_registered(self):
        d = build_react_dispatcher(config=_config())
        desc = d.get_tool_descriptions()
        for name in TOOLS:
            assert name in desc

    def test_descriptions_include_param_types(self):
        d = build_react_dispatcher(config=_config())
        desc = d.get_tool_descriptions()
        assert "web_extract(url:string, selector?:string)" in desc
        assert "web_search(query:string, max_results?:integer)" in desc
        assert "github_stars(repo:string)" in desc
        assert "run_benchmark()" in desc

    def test_descriptions_include_spec_description(self):
        d = build_react_dispatcher(config=_config())
        desc = d.get_tool_descriptions()
        assert "采集指定 URL 的网页文本" in desc
        assert "综合分析一个竞品" in desc

    def test_schema_enforced(self):
        d = build_react_dispatcher(config=_config())
        with pytest.raises(ToolArgumentError, match="缺少必填字段 url"):
            d.dispatch("web_extract", {})

    def test_web_extract_override_keeps_schema(self):
        d = build_react_dispatcher(config=_config(), web_extract=lambda url: f"REACT:{url}")
        assert d.dispatch("web_extract", {"url": "https://x.com"}) == "REACT:https://x.com"
        with pytest.raises(ToolArgumentError, match="缺少必填字段 url"):
            d.dispatch("web_extract", {})

    def test_web_search_no_network(self):
        # web_search 为提示实现，不触网络；build_react_dispatcher 默认注册全部工具
        d = build_react_dispatcher(config=_config())
        out = d.dispatch("web_search", {"query": "cursor"})
        assert "搜索" in out


class TestMcpSameSource:
    """MCP 同源：create_server 工具名集 == TOOLS 键，描述与 TOOL_SPECS 一致（无重复文案）"""

    @pytest.fixture(autouse=True)
    def _ensure_mcp(self):
        pytest.importorskip("mcp")

    def test_tool_names_match_tools(self):
        from competitor_agent.mcp_server.server import create_server

        mcp = create_server()
        names = asyncio.run(mcp.list_tools())
        assert sorted(t.name for t in names) == sorted(TOOLS)

    def test_descriptions_match_specs(self):
        from competitor_agent.mcp_server.server import create_server

        mcp = create_server()
        tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
        for name, spec in TOOL_SPECS.items():
            assert tools[name].description == spec.description

    def test_input_schema_derived(self):
        from competitor_agent.mcp_server.server import create_server

        mcp = create_server()
        tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
        assert set(tools["web_extract"].inputSchema.get("properties", {})) == {"url", "selector"}


def _run_react(responses, dispatcher):
    seen = []

    def fake_llm(messages, model, **kwargs):
        seen.append([dict(m) for m in messages])
        return responses[min(len(seen) - 1, len(responses) - 1)]

    agent = ReactAgent(llm=LLMClient(call_func=fake_llm), dispatcher=dispatcher)
    answer = agent.run(agent.build_system_prompt(), "任务")
    tool_msgs = [str(m.get("content", "")) for msgs in seen for m in msgs if m["role"] == "tool"]
    return answer, tool_msgs


def _tool(name: str, args: dict) -> ToolCallReply:
    return ToolCallReply(tool_calls=[ToolCall(id="call_0", name=name, arguments=args)])


class TestMultiToolReact:
    """集成：mock LLM 自主走 web_search → web_extract → Final Answer（工具结果回灌）"""

    def test_multi_tool_chain(self):
        calls = []

        def fake_extract(url):
            calls.append(url)
            return f"页面内容:{url}"

        d = build_react_dispatcher(config=_config(), web_extract=fake_extract)
        answer, tool_msgs = _run_react(
            [
                _tool("web_search", {"query": "Cursor 定价"}),
                _tool("web_extract", {"url": "https://cursor.com/pricing"}),
                ToolCallReply(content="定价 $20/月"),
            ],
            d,
        )
        assert answer == "定价 $20/月"
        assert calls == ["https://cursor.com/pricing"]
        # web_search 结果回灌（tool 消息含工具输出——未配 Key 时返回可读提示）
        assert any("搜索功能未启用" in m for m in tool_msgs)

    def test_recovers_from_unknown_tool(self):
        d = build_react_dispatcher(config=_config())
        answer, tool_msgs = _run_react(
            [
                _tool("ghost_tool", {}),
                _tool("web_search", {"query": "cursor"}),
                ToolCallReply(content="完成"),
            ],
            d,
        )
        assert answer == "完成"
        assert any("工具不可用" in m for m in tool_msgs)
        # 自恢复后合法工具结果也回灌
        assert any("搜索功能未启用" in m for m in tool_msgs)

    def test_openai_tools_cover_dispatcher(self):
        """native 单协议：工具经 build_openai_tools 下发，system prompt 不含工具描述。"""
        d = build_react_dispatcher(config=_config(), web_extract=lambda url: "")
        agent = ReactAgent(llm=LLMClient(call_func=lambda m, mo, **k: ToolCallReply(content="x")), dispatcher=d)
        prompt = agent.build_system_prompt()
        assert "web_search" not in prompt and "github_stars" not in prompt
        names = {t["function"]["name"] for t in build_openai_tools(d)}
        assert {"web_search", "github_stars", "analyze_pricing"} <= names


class TestWebSearchRealProvider:
    """设计文档 66 §3.1 — web_search 工具接真实 Tavily provider 的契约测试。

    schema/描述零改动（TOOL_SPECS 不动）；实现替换后 mock provider 返回固定 hits →
    工具输出「标题/URL/摘要」文本；无 provider → 可读提示；provider 抛异常 → 返回错误
    文案不冒泡（MCP 工具契约 str→str 保持）。
    """

    def test_spec_description_and_schema_unchanged(self):
        spec = TOOL_SPECS["web_search"]
        assert spec.description  # 描述仍在
        assert set(spec.params_schema["properties"]) == {"query", "max_results"}
        assert "query" in spec.params_schema["required"]

    def test_provider_hits_formatted_as_text(self, monkeypatch):
        from competitor_agent.collector.search import SearchHit
        from competitor_agent.mcp_server.tools import web_tools

        class FakeProvider:
            def search(self, query, max_results=5):
                return [
                    SearchHit("Cursor", "https://cursor.com", "AI code editor"),
                    SearchHit("Windsurf", "https://windsurf.com", "agentic IDE"),
                ]

        monkeypatch.setattr(web_tools, "build_search_provider", lambda cfg: FakeProvider())
        out = web_tools.web_search("coding agent", max_results=3)
        assert "Cursor" in out and "https://cursor.com" in out and "AI code editor" in out
        assert "Windsurf" in out

    def test_no_provider_returns_readable_hint(self, monkeypatch):
        from competitor_agent.mcp_server.tools import web_tools

        monkeypatch.setattr(web_tools, "build_search_provider", lambda cfg: None)
        out = web_tools.web_search("coding agent")
        assert "未启用" in out

    def test_provider_error_returns_error_text_not_raise(self, monkeypatch):
        from competitor_agent.collector.search import SearchError
        from competitor_agent.mcp_server.tools import web_tools

        class Boom:
            def search(self, query, max_results=5):
                raise SearchError("boom")

        monkeypatch.setattr(web_tools, "build_search_provider", lambda cfg: Boom())
        out = web_tools.web_search("coding agent")
        assert "搜索失败" in out and "boom" in out


class TestDelegateSchemaDerivation:
    """设计文档 62 — delegate 的 dimensions: list[str] 注解应派生为 array（而非 string）。

    修复前 ``_derive_params_schema`` 把 ``list[str]`` 降级为 ``"string"``，LLM 据此把
    候选名单当成字符串逐字符传入 → 产生单字符子 Agent。此处验证 schema 契约已纠正。
    """

    def _delegate_tool(self):
        """构造一个真实 delegate 工具（其 dimensions 注解为 list[str]），注册进 dispatcher。"""
        runner = DelegateRunner(lambda name: SubagentRuntime(name=name, run=lambda t: "ok"), max_concurrent=2)
        d = build_react_dispatcher(
            config=_config(),
            web_extract=lambda url: "",
            extra_tools={"delegate": make_delegate_tool(runner, registry=None)},
        )
        return d

    def test_delegate_dimensions_derived_as_array(self) -> None:
        """dimensions: list[str] 应派生为 {"type": "array", "items": {"type": "string"}}。"""
        d = self._delegate_tool()
        tools = {t["function"]["name"]: t["function"] for t in build_openai_tools(d)}
        dims_schema = tools["delegate"]["parameters"]["properties"]["dimensions"]
        assert dims_schema["type"] == "array"
        assert dims_schema["items"] == {"type": "string"}

    def test_delegate_required_includes_dimensions(self) -> None:
        d = self._delegate_tool()
        tools = {t["function"]["name"]: t["function"] for t in build_openai_tools(d)}
        assert "dimensions" in tools["delegate"]["parameters"]["required"]
