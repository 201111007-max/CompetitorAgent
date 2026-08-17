"""集成测试 — 预算/满足度终止（BudgetController 四条件）真实链路

对齐设计文档 11 §3.1：
- 迭代预算耗尽：max_iterations=1 → terminal_state=partial，未闭环缺口随报告返回
- 成本上限触发：cost_limit=0.01（单次采集 0.01）→ 首个缺口后即停
- 核心满足度提前终止：mock LLM 关闭 pricing/feature（核心缺口）后即返回 success，
  不再执行剩余非核心缺口
"""

from __future__ import annotations

import pytest

from competitor_agent.evaluation.benchmark import BenchmarkExtractor
from competitor_agent.facade.api import CompetitorAnalysisAPI

pytestmark = pytest.mark.integration

_PAGE = (
    "Cursor is an AI code editor.\nPro $20/month\nTeam $40/month\n"
    "\nSupports MCP integration and agent mode.\n\nswe-bench: 45%"
)


class TestBudgetTermination:
    def test_iteration_budget_exhaustion_returns_partial(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=1, cost_limit=1.0)
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "partial"
        assert api._budget.iteration_count == 1
        assert report.gaps_pending, "预算耗尽后未闭环缺口应随报告返回"

    def test_cost_limit_terminates_after_single_source(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10, cost_limit=0.01
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "partial"
        assert api._budget.iteration_count == 1, "单次采集 0.01 成本后应触顶停止"
        assert len(report.dimension_results) == 1

    def test_core_satisfaction_terminates_early(self, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page=_PAGE),
            llm=mock_llm,
            use_llm=True,
            max_iterations=10,
            cost_limit=1.0,
        )
        report = api.analyze("分析 Cursor", mode="single")

        # 核心缺口 pricing/feature 关闭即返回成功，剩余非核心缺口不浪费预算
        assert report.terminal_state == "success"
        assert [d.dimension for d in report.dimension_results] == ["pricing", "feature"]
        assert api._budget.iteration_count == 2
