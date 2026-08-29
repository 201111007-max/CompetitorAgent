"""设计文档 62 §6 M3 — run() 单 Lead 统一 + comparison 组装单测。

覆盖：
- registry/compare/discovery 每次 run() 恰好构建一条单 Lead loop（无 resolution 分派 if-else），
  组装按 plan.resolution 分型（CompetitorReport / ComparisonReport）；
- 候选子 Agent 标准多维度 dimensions[] → 每候选最小 CompetitorReport → build_comparison 矩阵 +
  Lead Final Answer 市场格局核心结论段；
- delegate 候选数硬上限（max_discover_candidates）与结构化结果收集器；
- 候选子 Agent 系统提示要求输出 dimensions[]（对齐 REPORT_SCHEMA）。
"""
from __future__ import annotations

import json

from competitor_agent.agent.delegate_tool import (
    DelegateRunner,
    SubagentRuntime,
    make_delegate_tool,
)
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport
from competitor_agent.facade.api import CompetitorAnalysisAPI


class FakeExtractor:
    def fetch(self, gap, context):
        from competitor_agent.domain_types import Observation, SourceEvidence

        url = str(context.kwargs.get("url"))
        text = "Pro $20/month" if "pricing" in url else "is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _api(mock_llm, web_tool=None, **kwargs) -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(), llm=mock_llm, use_llm=True, web_tool=web_tool, **kwargs
    )


def _two_candidate_web_tool(task: str) -> list[dict]:
    return [
        {"name": "cursor", "home": "https://www.cursor.com", "pricing": "https://www.cursor.com/pricing"},
        {"name": "windsurf", "home": "https://windsurf.com", "pricing": "https://windsurf.com/pricing"},
    ]


class TestRunSingleLoopUnified:
    def test_run_builds_single_loop_all_resolutions(self, mock_llm, monkeypatch) -> None:
        """registry/compare/discovery 每次 run() 恰好一条单 Lead loop，组装按 plan.resolution 分型。"""
        api = _api(mock_llm, web_tool=_two_candidate_web_tool)
        calls: list[str] = []
        orig = api._run_react_loop

        def _wrapped(
            task: str,
            session_id: str | None = None,
            history_messages: list[dict[str, str]] | None = None,
        ):
            calls.append(task)
            return orig(task, session_id, history_messages)

        monkeypatch.setattr(api, "_run_react_loop", _wrapped)
        r1 = api.run("分析 Cursor")
        r2 = api.run("对比 Cursor 和 Windsurf")
        r3 = api.run("帮我找市场上所有 coding agent")
        assert isinstance(r1, CompetitorReport)  # registry
        assert isinstance(r2, ComparisonReport)  # compare
        assert isinstance(r3, ComparisonReport)  # discovery
        assert len(calls) == 3  # 每次 run 恰好一条单 Lead loop，无三分支各自构建循环

    def test_compare_report_has_per_candidate_multi_dimensions(self, mock_llm) -> None:
        """compare：候选子 Agent dimensions[] → 每候选多维度 CompetitorReport → 矩阵 + 结论段。"""
        result = _api(mock_llm).run("对比 Cursor 和 Windsurf")
        assert isinstance(result, ComparisonReport)
        assert [r.competitor.name for r in result.reports] == ["cursor", "windsurf"]
        # 每候选报告含标准多维度（候选子 Agent dimensions[] 逐维度填全）
        for report in result.reports:
            dims = {d.dimension for d in report.dimension_results}
            assert "pricing" in dims and "feature" in dims, f"{report.competitor.name} 缺维度条目"
        md = result.markdown_report
        assert "品类格局矩阵" in md
        assert "市场格局核心结论" in md  # Lead Final Answer 结论段拼入

    def test_discovery_report_matrix_and_conclusion(self, mock_llm) -> None:
        """discovery：web_search_candidates → delegate 候选 → 矩阵 + 结论段。"""
        result = _api(mock_llm, web_tool=_two_candidate_web_tool).run("帮我找市场上所有 coding agent")
        assert isinstance(result, ComparisonReport)
        assert len(result.reports) >= 2
        assert "品类格局矩阵" in result.markdown_report
        assert "市场格局核心结论" in result.markdown_report


class TestComparisonAssembler:
    def _payload(self) -> tuple[dict, dict]:
        plan = {"resolution": "compare", "competitors": ["cursor", "windsurf"]}
        candidate_results = {
            "cursor": {
                "competitor": "cursor",
                "dimensions": [
                    {"dimension": "pricing", "summary": "Pro $20", "details": {"plans": ["Pro"]},
                     "confidence": 0.8, "evidence_urls": ["https://cursor.com/pricing"]},
                    {"dimension": "feature", "summary": "AI 编辑器", "details": {"features": ["agent"]},
                     "confidence": 0.7, "evidence_urls": ["https://cursor.com"]},
                ],
                "official_links": {"home": "https://cursor.com"},
            },
            "windsurf": {
                "competitor": "windsurf",
                "dimensions": [
                    {"dimension": "pricing", "summary": "$15", "details": {"plans": ["Free"]},
                     "confidence": 0.7, "evidence_urls": ["https://windsurf.com/pricing"]},
                ],
                "official_links": {"home": "https://windsurf.com"},
            },
        }
        return plan, candidate_results

    def test_assemble_builds_matrix_and_conclusion(self) -> None:
        from competitor_agent.facade.comparison_report import assemble_comparison

        plan, cands = self._payload()
        lead_answer = json.dumps(
            {"competitors": ["cursor", "windsurf"], "kind": "compare",
             "conclusion": "Cursor 综合领先（定价 Cursor 更贵但功能更全）"}, ensure_ascii=False
        )
        comparison = assemble_comparison(lead_answer, plan, cands)
        assert [r.competitor.name for r in comparison.reports] == ["cursor", "windsurf"]
        assert comparison.reports[0].dimension_results[0].dimension == "pricing"
        assert comparison.reports[0].dimension_results[0].confidence == 0.8
        assert "品类格局矩阵" in comparison.markdown_report
        assert "## 市场格局核心结论" in comparison.markdown_report
        assert "Cursor 综合领先" in comparison.markdown_report

    def test_assemble_empty_candidates_graceful(self) -> None:
        """无候选结果 → 空矩阵 + 结论段兜底，不报错（设计文档 62 §5）。"""
        from competitor_agent.facade.comparison_report import assemble_comparison

        comparison = assemble_comparison("Final Answer: {\"conclusion\": \"无候选\"}", {"resolution": "discovery"}, {})
        assert isinstance(comparison, ComparisonReport)
        assert comparison.reports == []
        assert "无候选" in comparison.markdown_report

    def test_extract_conclusion_json_and_marker(self) -> None:
        from competitor_agent.facade.comparison_report import _extract_conclusion

        assert _extract_conclusion('{"conclusion": "X 领先"}') == "X 领先"
        assert _extract_conclusion("Final Answer: 【市场格局核心结论】Cursor 最佳") == "Cursor 最佳"
        assert _extract_conclusion("Cursor 整体领先") == "Cursor 整体领先"
        assert _extract_conclusion('{"kind": "compare"}') == ""  # JSON 无 conclusion → 空结论段


class TestCandidatePromptAndDelegate:
    def test_candidate_subagent_prompt_has_dimensions_schema(self) -> None:
        from competitor_agent.agent.prompts.react_system import build_subagent_system_prompt

        prompt = build_subagent_system_prompt("windsurf")
        assert "分析候选竞品「windsurf」" in prompt
        assert "dimensions" in prompt  # 标准多维度数组
        assert "official_links" in prompt
        assert "维度子 Agent" not in prompt  # 候选子 Agent 不走单维度 schema

    def test_delegate_candidate_cap(self) -> None:
        """max_discover_candidates 硬上限：候选超限只保留前 N（注册维度不裁剪）。"""
        runner = DelegateRunner(
            lambda name: SubagentRuntime(name=name, run=lambda task: f"<result {name}>"),
            max_concurrent=2,
        )
        try:
            tool = make_delegate_tool(runner, registry=_FakeRegistry(), max_candidates=1)
            text = tool(dimensions=["cursor", "cline", "pricing"], task="分析候选")
            assert "<result cursor>" in text
            assert "<result cline>" not in text
            assert "<result pricing>" in text  # 注册维度不裁
            assert "候选数超过硬上限" in text
        finally:
            runner.shutdown()

    def test_delegate_collector_captures_candidate_dimensions(self) -> None:
        """collector 只收候选子 Agent 的标准多维度结果（维度子 Agent 单维度不收集）。"""

        def rt(name: str) -> SubagentRuntime:
            def _run(task: str) -> str:
                if _FakeRegistry().get(name) is not None:
                    # 维度子 Agent：单维度结果（无 dimensions 键，collector 不收集）
                    return json.dumps(
                        {"dimension": name, "summary": "x", "details": {}, "confidence": 0.8},
                        ensure_ascii=False,
                    )
                # 候选子 Agent：标准多维度 REPORT_SCHEMA（collector 收集）
                return json.dumps(
                    {"competitor": name, "dimensions": [
                        {"dimension": "pricing", "summary": "x", "details": {}, "confidence": 0.8}]
                    }, ensure_ascii=False,
                )
            return SubagentRuntime(name=name, run=_run)

        runner = DelegateRunner(rt, max_concurrent=2)
        try:
            collector: dict[str, dict] = {}
            tool = make_delegate_tool(runner, registry=_FakeRegistry(), collector=collector)
            tool(dimensions=["cursor", "pricing"], task="分析")
            assert "cursor" in collector
            assert collector["cursor"]["competitor"] == "cursor"
            assert "pricing" not in collector
        finally:
            runner.shutdown()


class _FakeMemory:
    """最小记忆替身：记录 recent_context 调用（品类级 competitor=\"\" vs 单竞品）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def recent_context(self, competitor: str, top_k: int = 5, query: str = "") -> list[str]:
        self.calls.append((competitor, top_k, query))
        return ["品类经验：pricing 建议用官网源"]


class TestM4MemoryCompressionWiring:
    """设计文档 62 §6 M4：Lead 压缩/记忆装配（lead.max_history_steps 透传 + 品类级召回）。"""

    def test_lead_loop_wires_lead_max_history_steps_and_pinned(self, mock_llm) -> None:
        api = _api(mock_llm, web_tool=_two_candidate_web_tool)
        loop = api._react_loop("对比 Cursor 和 Windsurf", None)
        try:
            assert loop._max_history_steps == api._config.lead.max_history_steps  # 压缩保留步数透传
            assert loop._pinned_facts == []  # 已核验事实 pinned 收集装配
            assert loop._on_step is not None
            assert loop._memory_context_fn.__self__ is api  # 记忆召回装配到本 api
        finally:
            loop._delegate_runner.shutdown()

    def test_lead_category_recall_for_discovery(self, mock_llm) -> None:
        """无具体竞品（discovery 编排）：Lead 走品类级 recent_context(competitor=\"\", query=task)。"""
        mem = _FakeMemory()
        api = _api(mock_llm, memory=mem)
        ctx = api._react_memory_context("帮我找市场上所有 coding agent")
        assert ctx == "品类经验：pricing 建议用官网源"
        assert mem.calls and mem.calls[0][0] == ""  # 品类级召回
        assert "coding agent" in mem.calls[0][2]

    def test_lead_per_competitor_recall_for_registry(self, mock_llm) -> None:
        """单竞品（registry）：Lead 按竞品名召回既有经验（行为不变）。"""
        mem = _FakeMemory()
        api = _api(mock_llm, memory=mem)
        api._react_memory_context("分析 Cursor")
        assert mem.calls and mem.calls[0][0] == "cursor"


class _FakeRegistry:
    """最小 registry 替身：维度可委派 + competitor 命名空间兜底。"""

    _COMPETITOR = object()

    def __init__(self) -> None:
        self._dims = {"pricing": object(), "feature": object(), "performance": object()}

    def get(self, name: str) -> object:
        return self._dims.get(name)

    def resolve(self, name: str) -> object:
        return self._dims.get(name) or self._COMPETITOR

    def names(self) -> list[str]:
        return list(self._dims)
