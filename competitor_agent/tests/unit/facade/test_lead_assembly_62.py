"""设计文档 62 M2/M4 — aggregate_report 接入 Lead 工具面 + 编排提示 + 候选子 Agent 记忆绑定。

覆盖：``_react_loop`` 组装的 Lead 工具面含 ``aggregate_report`` / ``delegate``；
Lead system prompt 含 DISCOVERY/COMPARE 编排引导；候选子 Agent 记忆/RAG 按候选竞品名绑定
（设计文档 62 §3.9）。
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


class TestCandidateMemoryBinding:
    """设计文档 62 §3.9：候选子 Agent 记忆/RAG 按候选竞品名绑定（维度子 Agent 绑 Lead 竞品）。"""

    def _api(self, mock_llm) -> CompetitorAnalysisAPI:
        cfg = load_config()
        cfg.subagents.enabled = True
        return CompetitorAnalysisAPI(
            llm=mock_llm,
            use_llm=True,
            enable_memory=True,
            enable_rag=False,
            config=cfg,
        )

    def test_candidate_subagent_memory_bound_to_candidate(self, mock_llm) -> None:
        api = self._api(mock_llm)
        seen: list[str] = []
        api._memory_ctx_for = lambda competitor, task: seen.append(competitor) or ""
        loop = api._react_loop("分析 Cursor", None)
        runner = loop._delegate_runner
        eid = runner.spawn("windsurf", "分析候选竞品 windsurf")
        runner.await_terminal(eid)
        runner.cleanup(eid)
        runner.shutdown()
        assert "windsurf" in seen  # 候选子 Agent 按候选自身名召回，而非误绑 Lead 竞品 cursor

    def test_dimension_subagent_memory_bound_to_lead_competitor(self, mock_llm) -> None:
        api = self._api(mock_llm)
        seen: list[str] = []
        api._memory_ctx_for = lambda competitor, task: seen.append(competitor) or ""
        loop = api._react_loop("分析 Cursor", None)
        runner = loop._delegate_runner
        eid = runner.spawn("pricing", "分析 Cursor 的定价")
        runner.await_terminal(eid)
        runner.cleanup(eid)
        runner.shutdown()
        assert "cursor" in seen  # 维度子 Agent 绑 Lead 竞品名
        assert "pricing" not in seen
