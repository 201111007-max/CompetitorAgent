"""设计文档 66 §3.1/§3.2 — Tavily 装配层零入口注入 + 报告路径对齐集成测试。

覆盖：
① 主开关关（默认 enable_external_sources=False）→ 不注入 web_tool（降级不编造）；
② 显式注入 web_tool 优先，不被装配层覆盖；
③ enable_external_sources=True + 可用 provider → 自动注入候选枚举 web_tool，
   端到端经 LLM 归纳出候选；
④ 无 Key / provider 不可用 → 保持 None（与现状一致）。
"""
from __future__ import annotations

from competitor_agent.collector.search import SearchHit
from competitor_agent.config.loader import AppConfig
from competitor_agent.facade.api import CompetitorAnalysisAPI


class FakeProvider:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, max_results=8):
        return self._hits


class ScriptedLLM:
    """候选归纳/去重都返回规范候选 JSON（不触网络）。"""

    def complete(self, messages, **kwargs):
        return '[{"name": "cursor", "home": "https://cursor.com"}]'


def _cfg(**collector) -> AppConfig:
    cfg = AppConfig()
    for k, v in collector.items():
        setattr(cfg.collector, k, v)
    return cfg


def _api(monkeypatch, cfg, llm, **kwargs) -> CompetitorAnalysisAPI:
    from competitor_agent.collector import search as search_mod

    monkeypatch.setattr(
        search_mod,
        "build_search_router",
        lambda c: FakeProvider([SearchHit("Cursor", "https://cursor.com", "AI editor")]),
    )
    return CompetitorAnalysisAPI(
        llm=llm, use_llm=True, config=cfg, web_tool=None,
        enable_rag=False, enable_memory=False, **kwargs,
    )


def test_no_injection_when_external_sources_disabled(monkeypatch, mock_llm):
    """主开关关（默认）→ 不注入 web_tool，discoverer.web_tool 为 None（降级不编造）。"""
    cfg = _cfg(enable_external_sources=False)
    api = _api(monkeypatch, cfg, mock_llm)
    assert api._discoverer._web_tool is None


def test_router_unavailable_keeps_none(monkeypatch, mock_llm):
    """enable_external_sources=True 但搜索路由不可用 → 保持 None（不注入、不编造）。

    设计文档 71 §2.2：注入依赖 build_search_router（DDG 主力恒可用，但主开关关 →
    None）；router 为 None 时 DISCOVERY 走空候选降级。
    """
    from competitor_agent.collector import search as search_mod

    cfg = _cfg(enable_external_sources=True)
    monkeypatch.setattr(search_mod, "build_search_router", lambda c: None)
    api = CompetitorAnalysisAPI(
        llm=mock_llm, use_llm=True, config=cfg, web_tool=None,
        enable_rag=False, enable_memory=False,
    )
    assert api._discoverer._web_tool is None


def test_explicit_web_tool_still_prioritized(monkeypatch, mock_llm):
    """显式注入 web_tool 优先，不被装配层覆盖。"""
    def web_tool(task):
        return [{"name": "cursor"}]

    cfg = _cfg(enable_external_sources=True)
    api = CompetitorAnalysisAPI(
        llm=mock_llm, use_llm=True, config=cfg, web_tool=web_tool,
        enable_rag=False, enable_memory=False,
    )
    assert api._discoverer._web_tool is web_tool


def test_auto_injection_builds_candidate_web_tool(monkeypatch):
    """enable_external_sources=True + 可用 provider → 自动注入候选枚举 web_tool。"""
    cfg = _cfg(enable_external_sources=True)
    api = _api(monkeypatch, cfg, ScriptedLLM())
    assert api._discoverer._web_tool is not None
    # 端到端：候选枚举（provider hits → LLM 归纳 → 去重）产出规范候选
    candidates = api._discoverer.candidates("coding agents")
    assert candidates == [{"name": "cursor", "home": "https://cursor.com"}]


def test_auto_injection_discovers_competitors(monkeypatch):
    """装配层注入的候选 web_tool 转成 Competitor 列表（注册表命中用官方链接）。"""
    cfg = _cfg(enable_external_sources=True)
    api = _api(monkeypatch, cfg, ScriptedLLM())
    competitors = api._discoverer.discover("coding agents")
    assert len(competitors) == 1
    assert competitors[0].name == "cursor"
    # cursor 为注册表竞品：官方链接来自注册表（非候选字段）
    assert competitors[0].official_links.get("home") == "https://www.cursor.com"
