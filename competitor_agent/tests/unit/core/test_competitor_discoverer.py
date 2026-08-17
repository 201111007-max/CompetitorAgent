"""core/competitor_discoverer.py 单测（设计文档 20 / 47：无内置兜底清单）"""
import json

import pytest

from competitor_agent.core.competitor_discoverer import (
    CompetitorDiscoverer,
    json_loads_array,
)
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient


def _echo_llm() -> LLMClient:
    """去重 mock：原样回显候选（确定性 oracle）。"""

    def call(messages, model):
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "[]")
        try:
            data = json.loads(user)
        except json.JSONDecodeError:
            data = []
        return json.dumps(data, ensure_ascii=False) if isinstance(data, list) else "[]"

    return LLMClient(call_func=call)


class TestDiscoverer:
    def test_registry_hit_first(self):
        d = CompetitorDiscoverer(use_llm=False)
        comps = d.discover("帮我对比市场上 Cursor 和 Windsurf")
        names = [c.name for c in comps]
        assert "cursor" in names
        assert "windsurf" in names

    def test_no_web_tool_returns_empty(self):
        """设计文档 47：缺 web_tool / 无候选 → 返回空（不编造内置清单）。"""
        d = CompetitorDiscoverer(use_llm=False)
        comps = d.discover("帮我寻找市场上所有 AI coding agent")
        assert comps == []

    def test_web_tool_results_used(self):
        def web_tool(task: str) -> list[dict]:
            return [
                {"name": "super-agent", "home": "https://super-agent.dev"},
                {"name": "Cursor", "home": "https://www.cursor.com"},
            ]

        d = CompetitorDiscoverer(use_llm=True, llm=_echo_llm(), web_tool=web_tool)
        comps = d.discover("市场上所有 coding agent")
        names = [c.name for c in comps]
        assert "super-agent" in names
        assert "cursor" in names
        # 注册表命中的 cursor 带 official_links
        cursor = next(c for c in comps if c.name == "cursor")
        assert cursor.official_links.get("home") == "https://www.cursor.com"

    def test_llm_dedup_with_mock(self):
        calls = []

        def llm_call(messages, model):
            calls.append(messages)
            return json_dumps(
                [{"name": "alpha", "home": "https://alpha.dev"}, {"name": "beta", "home": "https://beta.dev"}]
            )

        llm = LLMClient(call_func=llm_call)
        d = CompetitorDiscoverer(llm=llm, use_llm=True, web_tool=lambda task: [{"name": "alpha"}, {"name": "alpha"}])
        comps = d.discover("all agents")
        names = [c.name for c in comps]
        assert "alpha" in names
        assert "beta" in names
        assert len(calls) == 1

    def test_llm_garbage_raises_llm_unavailable(self):
        llm = LLMClient(call_func=lambda messages, model: "不是 JSON")
        d = CompetitorDiscoverer(llm=llm, use_llm=True, web_tool=lambda task: [{"name": "alpha"}])
        with pytest.raises(LLMUnavailableError):
            d.discover("all agents")

    def test_no_llm_for_dedup_raises(self):
        d = CompetitorDiscoverer(use_llm=False, web_tool=lambda task: [{"name": "alpha"}])
        with pytest.raises(LLMUnavailableError):
            d.discover("all agents")

    def test_dedupe_by_canonical_name(self):
        d = CompetitorDiscoverer(
            use_llm=True, llm=_echo_llm(), web_tool=lambda task: [{"name": "Alpha"}, {"name": "alpha"}]
        )
        comps = d.discover("x")
        assert len(comps) == 1

    def test_on_candidate_callback_per_candidate(self):
        """每发现一个候选即回调一次（供 Web SSE 实时推送）。"""
        d = CompetitorDiscoverer(
            use_llm=True,
            llm=_echo_llm(),
            web_tool=lambda task: [
                {"name": "alpha", "home": "https://alpha.dev"},
                {"name": "beta", "home": "https://beta.dev"},
            ],
        )
        pushed: list[str] = []
        comps = d.discover("all agents", on_candidate=pushed.append)
        assert pushed == ["alpha", "beta"]
        assert [c.name for c in comps] == ["alpha", "beta"]


class TestJsonLoadsArray:
    def test_plain_array(self):
        assert json_loads_array('[{"name": "a"}]') == [{"name": "a"}]

    def test_object_wrapped(self):
        assert json_loads_array('{"competitors": [{"name": "a"}]}') == [{"name": "a"}]

    def test_fenced_code_block(self):
        assert json_loads_array("```json\n[{\"name\": \"a\"}]\n```") == [{"name": "a"}]


def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)
