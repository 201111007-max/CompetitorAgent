"""设计文档 40 — MCP↔ReAct 工具打通：唯一工具源 / 同源生成 / 多工具 ReAct / 自恢复

全程 mock LLM（call_func），不触真实网络与 API Key；
MCP 同源测试依赖 mcp 包（importorskip），无 mcp 时跳过。
"""
from __future__ import annotations

import asyncio

import pytest
from competitor_agent.agent import ReactAgent, ToolArgumentError
from competitor_agent.agent.tool_registry import build_react_dispatcher
from competitor_agent.config.loader import AppConfig
from competitor_agent.llm.client import LLMClient
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

    def fake_llm(messages, model):
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        seen.append(user_msgs)
        return responses[min(len(seen) - 1, len(responses) - 1)]

    agent = ReactAgent(llm=LLMClient(call_func=fake_llm), dispatcher=dispatcher)
    answer = agent.run(agent.build_system_prompt(), "任务")
    observations = [m for msgs in seen for m in msgs]
    return answer, observations


class TestMultiToolReact:
    """集成：mock LLM 自主走 web_search → web_extract → Final Answer（工具结果回灌）"""

    def test_multi_tool_chain(self):
        calls = []

        def fake_extract(url):
            calls.append(url)
            return f"页面内容:{url}"

        d = build_react_dispatcher(config=_config(), web_extract=fake_extract)
        answer, observations = _run_react(
            [
                'Thought: 先搜索\n<action>web_search({"query": "Cursor 定价"})</action>',
                'Thought: 抓取官网\n<action>web_extract({"url": "https://cursor.com/pricing"})</action>',
                "Final Answer: 定价 $20/月",
            ],
            d,
        )
        assert answer == "定价 $20/月"
        assert calls == ["https://cursor.com/pricing"]
        # web_search 结果回灌（Observation 里含工具输出）
        assert any("搜索功能需要接入搜索引擎 API" in m for m in observations)

    def test_recovers_from_unknown_tool(self):
        d = build_react_dispatcher(config=_config())
        answer, observations = _run_react(
            [
                'Thought: 用不存在的工具\n<action>ghost_tool({})</action>',
                'Thought: 改用合法工具\n<action>web_search({"query": "cursor"})</action>',
                "Final Answer: 完成",
            ],
            d,
        )
        assert answer == "完成"
        assert any("工具不可用" in m for m in observations)
        # 自恢复后合法工具结果也回灌
        assert any("搜索功能需要接入搜索引擎 API" in m for m in observations)

    def test_system_prompt_lists_multi_tools(self):
        d = build_react_dispatcher(config=_config(), web_extract=lambda url: "")
        agent = ReactAgent(llm=LLMClient(call_func=lambda m, mo: "Final Answer: x"), dispatcher=d)
        prompt = agent.build_system_prompt()
        assert "web_search" in prompt
        assert "github_stars" in prompt
        assert "analyze_pricing" in prompt
