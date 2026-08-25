"""设计文档 62 M2 — aggregate_report 接入 Lead 工具面 + 编排提示装配单测。

覆盖：``_react_loop`` 组装的 Lead 工具面含 ``aggregate_report`` / ``delegate``；
Lead system prompt 含 DISCOVERY/COMPARE 编排引导（web_search→delegate→aggregate_report、
parallel/reason 决策、市场格局核心结论）。
"""
from __future__ import annotations

from competitor_agent.config.loader import load_config
from competitor_agent.facade.api import CompetitorAnalysisAPI


def _api() -> CompetitorAnalysisAPI:
    cfg = load_config()
    cfg.subagents.enabled = True
    return CompetitorAnalysisAPI(
        llm=None,
        use_llm=False,
        enable_memory=False,
        enable_rag=False,
        config=cfg,
    )


class TestLeadToolFace:
    def test_aggregate_report_registered(self) -> None:
        api = _api()
        loop = api._react_loop("分析 Cursor", None)
        specs = loop._agent._dispatcher.specs
        assert "aggregate_report" in specs
        assert "delegate" in specs
        assert "make_plan" in specs

    def test_lead_prompt_has_orchestration_guidance(self) -> None:
        api = _api()
        loop = api._react_loop("分析 Cursor", None)
        prompt = loop._system_prompt_override or ""
        assert "aggregate_report" in prompt
        assert "市场格局" in prompt
        assert "parallel" in prompt
        assert "web_search" in prompt


class TestLeadPromptGuidance:
    def test_prompt_mentions_candidate_delegate(self) -> None:
        from competitor_agent.agent.prompts.react_system import build_lead_system_prompt

        prompt = build_lead_system_prompt()
        assert "候选竞品名" in prompt
        assert "kind=" in prompt  # aggregate_report 的 compare/position 口径
