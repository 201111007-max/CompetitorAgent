"""设计文档 48：skill 注入点测试 + BenchmarkMockLLM 门禁回归

- 分析器 _base_messages：注入 <skill name="{dim}_analysis"> + fact_verification + confidence_disclosure，
  messages[0]（维度抽取指令）与末条 user（观察文本）保持不变
- 规划 prompt：注入 <skill name="planning">，messages[0] 仍含"战略规划器"与"用户任务"
- skill 缺失 → 注入点静默跳过（零依赖降级）
- mock 确定性：注入后 BenchmarkMockLLM 仍按维度返回正确 JSON（messages[0] 原样 → 分支不变）
"""
from __future__ import annotations

import json

from competitor_agent.analyzers import (
    EcosystemAnalyzer,
    FeatureAnalyzer,
    PerformanceAnalyzer,
    PricingAnalyzer,
    RoadmapAnalyzer,
    SentimentAnalyzer,
)
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types import InfoGap, Observation, SourceEvidence
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.llm.client import LLMClient
from competitor_agent.skills import SkillLoader

ANALYZERS = [
    PricingAnalyzer,
    FeatureAnalyzer,
    PerformanceAnalyzer,
    EcosystemAnalyzer,
    SentimentAnalyzer,
    RoadmapAnalyzer,
]


def _obs(dimension: str, raw_text: str) -> Observation:
    return Observation(
        gap_field=dimension,
        source="web_extractor",
        raw_text=raw_text,
        evidence=SourceEvidence(source_name="web_extractor", content_hash="h1"),
    )


def _analyzer_messages(analyzer, raw_text: str = "Pro $20/month") -> list[dict[str, str]]:
    dim = analyzer.dimension.value
    return analyzer._base_messages(
        _obs(dim, raw_text), InfoGap(field=dim), AnalysisContext(competitor_name="cursor")
    )


class TestAnalyzerInjection:
    def test_injects_three_skill_blocks(self):
        messages = _analyzer_messages(PricingAnalyzer())
        joined = "\n".join(m["content"] for m in messages)
        assert '<skill name="pricing_analysis">' in joined
        assert '<skill name="fact_verification">' in joined
        assert '<skill name="confidence_disclosure">' in joined

    def test_first_system_message_preserved(self):
        """messages[0]（维度抽取指令）原样保留 → mock 维度分支不变。"""
        messages = _analyzer_messages(PricingAnalyzer())
        assert messages[0]["role"] == "system"
        assert "你是竞品定价分析师" in messages[0]["content"]
        # skill 块在独立 system 消息中，未混入首条指令
        assert "<skill name=" not in messages[0]["content"]

    def test_last_user_observation_preserved(self):
        """末条 user（观察文本）原样保留 → mock 观察抽取不变。"""
        messages = _analyzer_messages(PricingAnalyzer(), raw_text="Pro $20/month")
        assert messages[-1]["role"] == "user"
        assert "Pro $20/month" in messages[-1]["content"]
        assert "<skill name=" not in messages[-1]["content"]

    def test_all_six_dimensions_inject_own_skill(self):
        for cls in ANALYZERS:
            analyzer = cls()
            dim = analyzer.dimension.value
            messages = _analyzer_messages(analyzer)
            joined = "\n".join(m["content"] for m in messages)
            assert f'<skill name="{dim}_analysis">' in joined, dim


class TestPlannerInjection:
    def _planner(self):
        return StrategicPlanner(llm=LLMClient(call_func=lambda messages, model: "{}"), use_llm=True)

    def test_injects_planning_skill(self):
        messages = self._planner()._plan_messages("分析 Cursor", None)
        joined = "\n".join(m["content"] for m in messages)
        assert '<skill name="planning">' in joined

    def test_first_message_preserves_plan_prompt_and_task(self):
        """messages[0]（含"战略规划器"与"用户任务：<task>"）保持不变 → mock 规划分支/竞品推断不变。"""
        messages = self._planner()._plan_messages("分析 Cursor", None)
        assert messages[0]["role"] == "user"
        assert "战略规划器" in messages[0]["content"]
        assert "用户任务：分析 Cursor" in messages[0]["content"]
        assert "<skill name=" not in messages[0]["content"]


class TestMissingSkillNoInjection:
    def test_analyzer_skips_when_no_skill_dir(self, tmp_path, monkeypatch):
        import competitor_agent.analyzers.base as base_mod

        empty = SkillLoader(tmp_path / "empty")
        monkeypatch.setattr(base_mod, "get_skill_loader", lambda: empty)
        messages = _analyzer_messages(PricingAnalyzer())
        assert not any("<skill name=" in m["content"] for m in messages)
        assert messages[0]["content"] == PricingAnalyzer()._build_prompt(
            _obs("pricing", "Pro $20/month"), InfoGap(field="pricing")
        )[0]["content"]

    def test_planner_skips_when_no_skill_dir(self, tmp_path, monkeypatch):
        import competitor_agent.core.strategic_loop as sl_mod

        empty = SkillLoader(tmp_path / "empty")
        monkeypatch.setattr(sl_mod, "get_skill_loader", lambda: empty)
        messages = StrategicPlanner(
            llm=LLMClient(call_func=lambda messages, model: "{}"), use_llm=True
        )._plan_messages("分析 Cursor", None)
        assert not any("<skill name=" in m["content"] for m in messages)


class TestMockGateUnchanged:
    """注入后 BenchmarkMockLLM 仍按维度返回正确 JSON（mock 全量门禁不回归）。"""

    def test_mock_branch_per_dimension(self):
        raw = {
            "pricing": "Pro $20/month\nTeams $40/month",
            "feature": "support cli agent terminal mcp",
            "performance": "swe-bench verified: 62.0",
            "ecosystem": "vscode plugin marketplace 12 plugins",
            "sentiment": "Developers love it, great and recommend it.",
            "roadmap": "roadmap 2026: background agents",
        }
        for cls in ANALYZERS:
            dim = cls().dimension.value
            messages = _analyzer_messages(cls(), raw_text=raw[dim])
            out = json.loads(BenchmarkMockLLM().complete(messages))
            assert out["details"] is not None, dim
            # 各维度 mock 返回的关键键存在（证明维度分支未被 skill 注入破坏）
            keys = {
                "pricing": "plans",
                "feature": "features",
                "performance": "benchmarks",
                "ecosystem": "plugins",
                "sentiment": "verdict",
                "roadmap": "upcoming",
            }
            assert keys[dim] in out["details"], dim

    def test_user_text_unpolluted_by_skill(self):
        """_user_text 取末条 user 观察文本，skill 块（独立 system）不污染观察抽取。"""
        messages = _analyzer_messages(PricingAnalyzer(), raw_text="Pro $20/month")
        user = BenchmarkMockLLM._user_text(messages)
        assert "Pro $20/month" in user
        assert "skill" not in user

    def test_full_analyze_with_mock_still_produces_dimensions(self, mock_llm, fake_extractor):
        """mock_llm fixture 下跑通 analyze 全链路（单竞品），报告维度齐全。"""
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=30)
        report = api.analyze("Cursor")
        assert report.competitor.name == "cursor"
        assert report.dimension_results, "注入 skill 后仍应产出维度结果"
