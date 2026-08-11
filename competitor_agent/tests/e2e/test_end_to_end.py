"""端到端测试 — 完整 analyze("Cursor") 链路（确定性采集 + mock/真实 LLM）

对齐设计文档 11 §3.2 / §5：
- mock LLM + 固定网页内容跑完整链路（CI 无网络、无 Key 可复现）
- 断言：报告结构完整、功能/定价维度结论、证据带 source_url、可渲染 Markdown
- real LLM smoke：本地有 API Key 时真实调用（无 Key 自动跳过，不影响 CI）
"""

from __future__ import annotations

import os

import pytest

from competitor_agent.evaluation.benchmark import (
    BenchmarkExtractor,
    BenchmarkMockLLM,
    extract_prediction,
)
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient

pytestmark = pytest.mark.e2e

_PAGE = (
    "Cursor is an AI code editor by Anysphere.\n"
    "Pro $20/month\nTeam $40/month\n\n"
    "Supports MCP integration and agent mode.\n\n"
    "swe-bench: 45%"
)

_LLM_KEY_ENVS = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY")


def _has_llm_key() -> bool:
    return any(os.getenv(key) for key in _LLM_KEY_ENVS)


class TestEndToEndMockLLM:
    def test_mock_llm_full_chain_single(self) -> None:
        api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page=_PAGE),
            llm=LLMClient(call_func=BenchmarkMockLLM().complete),
            use_llm=True,
            max_iterations=10,
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert "# cursor 竞品分析报告" in report.markdown_report
        assert "## 维度结论" in report.markdown_report
        assert "### [OK] pricing" in report.markdown_report
        assert "### [OK] feature" in report.markdown_report
        assert "证据:" in report.markdown_report

    def test_mock_llm_full_chain_team(self, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page=_PAGE),
            llm=mock_llm,
            use_llm=True,
            max_iterations=10,
        )
        report = api.analyze("分析 Cursor", mode="team")

        assert report.terminal_state == "success"
        assert report.dimension_results
        assert all(any(ev.url for ev in r.evidence) for r in report.dimension_results)
        assert "# cursor 竞品分析报告" in report.markdown_report

    def test_mock_llm_report_is_evaluable(self) -> None:
        api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page=_PAGE),
            llm=LLMClient(call_func=BenchmarkMockLLM().complete),
            use_llm=True,
            max_iterations=10,
        )
        report = api.analyze("只分析 cursor 的定价", mode="single")

        prediction = extract_prediction(report, "pricing", {"pro": "$20/month", "team": "$40/month"})
        assert prediction.get("pro") == "$20/month"
        assert prediction.get("team") == "$40/month"


@pytest.mark.skipif(not _has_llm_key(), reason=f"需要 LLM API Key（{' / '.join(_LLM_KEY_ENVS)}）")
class TestEndToEndRealLLM:
    def test_real_llm_full_chain(self, fake_extractor) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=LLMClient(), use_llm=True)
        report = api.analyze("分析 Cursor", mode="single")

        assert report.dimension_results
        assert "# cursor 竞品分析报告" in report.markdown_report
        assert all(any(ev.url for ev in r.evidence) for r in report.dimension_results)
