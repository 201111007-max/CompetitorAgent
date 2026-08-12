"""core/competitor_discoverer.py 单测（设计文档 20）"""
from competitor_agent.core.competitor_discoverer import (
    CompetitorDiscoverer,
    _FALLBACK_CANDIDATES,
    json_loads_array,
)
from competitor_agent.llm.client import LLMClient


class TestDiscoverer:
    def test_registry_hit_first(self):
        d = CompetitorDiscoverer(use_llm=False)
        comps = d.discover("帮我对比市场上 Cursor 和 Windsurf")
        names = [c.name for c in comps]
        assert "cursor" in names
        assert "windsurf" in names

    def test_no_web_tool_uses_fallback_list(self):
        """无 web_tool / 无 LLM：内置兜底清单，保证不 0 维度"""
        d = CompetitorDiscoverer(use_llm=False)
        comps = d.discover("帮我寻找市场上所有 AI coding agent")
        assert len(comps) >= 2
        names = [c.name for c in comps]
        assert any(name in _FALLBACK_CANDIDATES_NAMES() for name in names)
        # 兜底竞品都带 official_links（否则采集 0 候选 → 0 维度）
        assert all(c.official_links for c in comps)

    def test_web_tool_results_used(self):
        def web_tool(task: str) -> list[dict]:
            return [
                {"name": "super-agent", "home": "https://super-agent.dev"},
                {"name": "Cursor", "home": "https://www.cursor.com"},
            ]

        d = CompetitorDiscoverer(use_llm=False, web_tool=web_tool)
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

    def test_llm_garbage_falls_back_to_raw(self):
        llm = LLMClient(call_func=lambda messages, model: "不是 JSON")
        d = CompetitorDiscoverer(llm=llm, use_llm=True, web_tool=lambda task: [{"name": "alpha"}])
        comps = d.discover("all agents")
        assert "alpha" in [c.name for c in comps]

    def test_dedupe_by_canonical_name(self):
        d = CompetitorDiscoverer(use_llm=False, web_tool=lambda task: [{"name": "Alpha"}, {"name": "alpha"}])
        comps = d.discover("x")
        assert len(comps) == 1


class TestJsonLoadsArray:
    def test_plain_array(self):
        assert json_loads_array('[{"name": "a"}]') == [{"name": "a"}]

    def test_object_wrapped(self):
        assert json_loads_array('{"competitors": [{"name": "a"}]}') == [{"name": "a"}]

    def test_fenced_code_block(self):
        assert json_loads_array("```json\n[{\"name\": \"a\"}]\n```") == [{"name": "a"}]


def _FALLBACK_CANDIDATES_NAMES() -> set[str]:
    return {c["name"] for c in _FALLBACK_CANDIDATES}


def json_dumps(data) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)
