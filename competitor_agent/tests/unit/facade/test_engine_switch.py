"""引擎切换（设计文档 51 §3.3）：engine 路由 / 未装 langgraph 的 ImportError / 默认 react 回归"""
from __future__ import annotations

import sys

import pytest
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient
from competitor_agent.tests.conftest import FakeExtractor


def _api(engine: str = "react") -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(),
        llm=LLMClient(call_func=BenchmarkMockLLM().complete),
        use_llm=True,
        engine=engine,
    )


def test_default_engine_is_react():
    assert _api()._engine == "react"


def test_unknown_engine_rejected():
    with pytest.raises(ValueError, match="未知编排引擎"):
        _api(engine="crewai")


def test_langgraph_missing_dependency_import_error(monkeypatch):
    """未装 langgraph（sys.modules 屏蔽模拟）：构造期可读 ImportError，默认路径不受影响。"""
    monkeypatch.setitem(sys.modules, "langgraph", None)
    with pytest.raises(ImportError, match="langgraph"):
        _api(engine="langgraph")
    assert _api()._engine == "react"  # 默认 react 不受屏蔽影响


def test_engine_routing_langgraph():
    """engine="langgraph" 的 analyze() 走 LangGraph 引擎，报告出口与 react 路径一致。"""
    pytest.importorskip("langgraph", reason="langgraph 为 optional extra")
    report = _api(engine="langgraph").analyze("分析 Cursor")
    dims = {r.dimension for r in report.dimension_results}
    assert "pricing" in dims
    assert report.competitor.name
    assert report.terminal_state == "success"


def test_engine_routing_default_react_unchanged():
    """默认 engine="react" 行为回归：analyze() 仍走 Lead ReAct 编排。"""
    report = _api().analyze("分析 Cursor")
    dims = {r.dimension for r in report.dimension_results}
    assert "pricing" in dims
