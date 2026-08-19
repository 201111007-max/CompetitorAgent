"""集成测试 — 预算终止真实链路（设计文档 11 §3.1，49 收拢为 Lead ReAct 编排）

doc 49 预算语义（budget 为代码强制兜底，不进 LLM；doc 39 预算/成本控制暂缓）：
- ``max_iterations`` 为 Lead 步数上限（迭代预算耗尽 → partial；plan 声明未产出维度
  随 gaps_pending 返回，供 resume/预算判定）
- ``cost_limit`` 为末尾统一记账（非中途打断），成本随 ``record_iteration(cost=0.01×步数)``
  落账，防止确定性 mock 流程被误停
- 无"核心满足度"启发 —— 维度集合由 Lead 的 plan 决定（LLM 决策），非规则
"""

from __future__ import annotations

import pytest

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.evaluation.benchmark import BenchmarkExtractor
from competitor_agent.facade.api import CompetitorAnalysisAPI

pytestmark = pytest.mark.integration

_PAGE = (
    "Cursor is an AI code editor.\nPro $20/month\nTeam $40/month\n"
    "\nSupports MCP integration and agent mode.\n\nswe-bench: 45%"
)

# 离线环境 URL 守卫（DNS 解析）会拦截 before 采集器运行：关闭守卫让采集器真被命中
_OFFLINE_CFG = AppConfig(collector=CollectorConfig(block_private_urls=False))


class TestBudgetTermination:
    def test_iteration_budget_exhaustion_returns_partial(self, fake_extractor, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            max_iterations=1,
            cost_limit=1.0,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "partial"
        assert api._budget.iteration_count == 1
        assert report.gaps_pending, "预算耗尽后未闭环缺口应随报告返回"

    def test_cost_limit_is_post_hoc_accounting(self, fake_extractor, mock_llm) -> None:
        """成本上限为末尾记账（doc 49），不中途打断确定性 mock 流程。"""
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            max_iterations=10,
            cost_limit=0.01,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "success"
        assert api._budget.total_cost > 0, "analyze 末尾应统一记账（cost=0.01×步数）"
        assert api._budget.iteration_count <= api._budget.max_iterations

    def test_lead_plan_drives_dimension_coverage(self, mock_llm) -> None:
        """维度集合由 Lead 的 plan 决定（doc 49：无核心满足度启发，LLM 决策）。"""
        api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page=_PAGE),
            llm=mock_llm,
            use_llm=True,
            max_iterations=10,
            cost_limit=1.0,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "success"
        dims = {d.dimension for d in report.dimension_results}
        assert {"pricing", "feature"} <= dims, "plan 声明维度应全部落地"
        assert api._budget.iteration_count >= 1
        assert api._budget.iteration_count <= api._budget.max_iterations
