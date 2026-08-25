"""集成测试 — 预算终止真实链路（设计文档 11 §3.1，49 收拢为 Lead ReAct 编排）

doc 49 预算语义（budget 为代码强制兜底，不进 LLM；doc 39 预算/成本控制暂缓）：
- Lead 已移除迭代次数限制（设计决策：max_steps=None 无限，靠 LLM 自然收敛 Final Answer，
  防失控由子 Agent max_steps 兜底 + 取消协作 + url_guard/超时护栏）
- 无美元成本核算（设计决策：项目仅保留 token 统计，token 记账在 LLMClient）
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
    def test_lead_not_bounded_by_max_iterations(self, fake_extractor, mock_llm) -> None:
        """Lead 移除迭代次数限制：即使 max_iterations 很小，Lead 仍完整收敛（不 partial）。"""
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            max_iterations=1,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "success"

    def test_iteration_accounting_recorded(self, fake_extractor, mock_llm) -> None:
        """迭代预算为末尾统一记账（doc 49）：不中途打断确定性 mock 流程，仅累计迭代数。"""
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            max_iterations=10,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "success"
        assert api._budget.iteration_count >= 1, "analyze 末尾应统一累计迭代数"
        assert api._budget.iteration_count <= api._budget.max_iterations

    def test_lead_plan_drives_dimension_coverage(self, mock_llm) -> None:
        """维度集合由 Lead 的 plan 决定（doc 49：无核心满足度启发，LLM 决策）。"""
        api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page=_PAGE),
            llm=mock_llm,
            use_llm=True,
            max_iterations=10,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor", mode="single")

        assert report.terminal_state == "success"
        dims = {d.dimension for d in report.dimension_results}
        assert {"pricing", "feature"} <= dims, "plan 声明维度应全部落地"
        assert api._budget.iteration_count >= 1
        assert api._budget.iteration_count <= api._budget.max_iterations
