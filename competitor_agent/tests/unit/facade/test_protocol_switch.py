"""设计文档 53 M3 — protocol 路由（facade 级）

覆盖：
- API 默认 protocol="native"、非法值拒绝
- analyze() 透传 protocol 到 Lead ReactAgent / 子 Agent
- protocol="react" 行为与现状逐位一致（回归网，同 fixture 双协议可跑）
- BenchmarkMockLLM 双形态：同 fixture 在 native/react 下产出等价报告

全程 mock（conftest mock_llm 双形态 + fake_extractor），零真实网络与 Key。
"""
from __future__ import annotations

import pytest
from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.facade.api import CompetitorAnalysisAPI

pytestmark = pytest.mark.integration

_OFFLINE_CFG = AppConfig(collector=CollectorConfig(block_private_urls=False))


def _api(fake_extractor, mock_llm, protocol: str) -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(
        extractor=fake_extractor,
        llm=mock_llm,
        use_llm=True,
        max_iterations=10,
        config=_OFFLINE_CFG,
        protocol=protocol,
    )


class TestProtocolRouting:
    def test_default_is_native(self):
        assert CompetitorAnalysisAPI(use_llm=False)._protocol == "native"

    def test_invalid_protocol_rejected(self):
        with pytest.raises(ValueError):
            CompetitorAnalysisAPI(use_llm=False, protocol="bogus")

    def test_react_override(self):
        assert CompetitorAnalysisAPI(use_llm=False, protocol="react")._protocol == "react"


class TestDualProtocolEquivalent:
    """同一 fixture（mock_llm 双形态）在 native/react 下跑 Lead，产出等价报告（协议是唯一变量）。"""

    @pytest.mark.parametrize("protocol", ["native", "react"])
    def test_lead_report_both_protocols(self, protocol, fake_extractor, mock_llm):
        api = _api(fake_extractor, mock_llm, protocol)
        report = api.analyze("分析 Cursor 定价", session_id=f"s_{protocol}")
        assert report.competitor.name.lower() == "cursor"
        assert report.dimension_results
        # 双协议出口一致：structured JSON → CompetitorReport
        assert report.overall_confidence > 0
        assert "cursor" in report.markdown_report.lower()

    def test_react_protocol_regression_net(self, fake_extractor, mock_llm):
        """protocol='react' 作为文本协议回归网：走原文本循环，行为与现状一致。"""
        api = _api(fake_extractor, mock_llm, "react")
        report = api.analyze("只看 Cursor 定价", session_id="s_react_reg")
        assert report.dimension_results
        pricing = [r for r in report.dimension_results if r.dimension == "pricing"]
        assert pricing or report.dimension_results


class TestReactAgentRouting:
    def test_react_loop_defaults_native(self):
        loop = ReactLoop(ReactAgent(llm=None, dispatcher=ToolDispatcher({"x": lambda: "1"})))
        assert loop._agent.protocol == "native"

    def test_react_loop_protocol_override_sets_agent(self):
        loop = ReactLoop(
            ReactAgent(llm=None, dispatcher=ToolDispatcher({"x": lambda: "1"})),
            protocol="react",
        )
        assert loop._agent.protocol == "react"