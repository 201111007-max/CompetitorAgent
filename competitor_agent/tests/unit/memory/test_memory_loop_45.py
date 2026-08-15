"""设计文档 45：L4 记忆回路消费（规划提权/降权 + 源选择降级）+ team 路径 memory_context 注入

- L4 契约新增：retrieve_patterns_with_outcome（带 outcome 供判定）/ failure_patterns_for（失败源提取）
- StrategicPlanner：成功模式提权 / 失败反例降权（与 L3 _apply_memory_boost 并列）
- SourceSelector.set_failure_penalties：失败反例命中源排后（降级优先于成功率）
- AnalyzerAgent：team 路径注入 memory_context（与 single 的 GapExecutor 同口径 recent_context）
"""
from __future__ import annotations

from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types import Competitor, InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.memory import FourLayerMemory
from competitor_agent.memory.evolution_memory import EvolutionMemory
from competitor_agent.team.analyzer_agent import AnalyzerAgent
from competitor_agent.team.message_bus import MessageBus


class TestL4Contract:
    def test_retrieve_patterns_with_outcome(self, tmp_path):
        evo = EvolutionMemory(tmp_path / "evo")
        evo.note_pattern("cursor", "performance", "命中 SWE-bench 榜单", outcome="success")
        evo.note_pattern("cursor", "performance", "榜单源缺失 → 回退页面", outcome="degraded")
        got = evo.retrieve_patterns_with_outcome("cursor", "performance")
        assert ("命中 SWE-bench 榜单", "success") in got
        assert ("榜单源缺失 → 回退页面", "degraded") in got
        assert evo.retrieve_patterns_with_outcome("cursor", "pricing") == []

    def test_failure_patterns_for_extracts_failed_sources(self, tmp_path):
        evo = EvolutionMemory(tmp_path / "evo")
        evo.note_pattern("cursor", "pricing", "失败: 源 official_pricing 无数据", outcome="failure")
        evo.note_pattern("cursor", "pricing", "由源 docs 有效", outcome="success")
        evo.note_pattern("cursor", "performance", "由源 github 降级命中", outcome="degraded")
        evo.note_pattern("cursor", "roadmap", "无具体源的反例", outcome="failure")
        assert evo.failure_patterns_for("cursor") == ["github", "official_pricing"]

    def test_four_layer_memory_delegates(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "m")
        mem.note_pattern("cursor", "pricing", "失败: 源 docs 无数据", outcome="failure")
        assert mem.failure_patterns_for("cursor") == ["docs"]
        assert mem.retrieve_patterns_with_outcome("cursor", "pricing") == [
            ("失败: 源 docs 无数据", "failure")
        ]


class TestPlannerPatternBoost:
    def _plans(self, memory):
        strategy = StrategicPlanner().plan("cursor", memory=memory)
        return {g.field: g for g in strategy.gaps}

    def test_success_pattern_boosts_confidence(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "m")
        mem.note_pattern("cursor", "pricing", "由源 docs 有效", outcome="success")
        by_field = self._plans(mem)
        assert by_field["pricing"].confidence == 0.1

    def test_failure_pattern_downgrades_priority(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "m")
        mem.note_pattern("cursor", "pricing", "失败: 源 docs 无数据", outcome="failure")
        by_field = self._plans(mem)
        assert by_field["pricing"].confidence == 0.0
        assert by_field["pricing"].priority == 8  # 默认 9 → 降权

    def test_no_pattern_no_change(self):
        by_field = self._plans(None)
        assert by_field["pricing"].confidence == 0.0
        assert by_field["pricing"].priority == 9

    def test_success_boost_respects_cap(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "m")
        for i in range(10):
            mem.note_pattern("cursor", "pricing", f"由源 docs 有效 {i}", outcome="success")
        by_field = self._plans(mem)
        assert by_field["pricing"].confidence == 0.9  # 封顶


class TestSelectorFailurePenalty:
    def _pricing_cands(self, sel):
        gap = InfoGap(field="pricing")
        competitor = Competitor(
            name="cursor",
            official_links={"pricing": "https://c.com/pricing", "home": "https://c.com"},
        )
        return sel.candidates(gap, competitor)

    def test_failed_source_ranked_last(self):
        sel = SourceSelector()
        sel.set_failure_penalties(["official_pricing"])
        cands = self._pricing_cands(sel)
        assert cands[0].source_name == "official_home"

    def test_penalty_overrides_high_success_rate(self):
        sel = SourceSelector()
        sel.set_success_rates({"official_pricing": 0.95})
        sel.set_failure_penalties(["official_pricing"])
        cands = self._pricing_cands(sel)
        assert cands[0].source_name == "official_home"

    def test_no_penalty_keeps_order(self):
        sel = SourceSelector()
        cands = self._pricing_cands(sel)
        assert cands[0].source_name == "official_pricing"


class _SpyMemory:
    """仅实现 AnalyzerAgent 用到的 recent_context（其余调用不会触发）"""

    def __init__(self, lines):
        self._lines = lines

    def recent_context(self, competitor, top_k=5, query=""):
        return list(self._lines)


class _CaptureAnalyzer:
    dimension = "pricing"

    def __init__(self):
        self.captured = None

    def analyze(self, observation, gap, context):
        self.captured = context
        return DimensionResult(dimension="pricing", summary="ok", confidence=0.9)


class _FakeRegistry:
    def __init__(self, analyzer):
        self._analyzer = analyzer

    def get(self, field):
        return self._analyzer


def _make_agent(memory):
    cap = _CaptureAnalyzer()
    agent = AnalyzerAgent(MessageBus(), AnalyzerRegistry(use_llm=False), memory=memory)
    agent._registry = _FakeRegistry(cap)
    return agent, cap


class TestTeamMemoryInjection:
    def test_analyzer_agent_injects_memory_context(self):
        agent, cap = _make_agent(_SpyMemory(["历史结论: 官网源有效"]))
        obs = Observation(gap_field="pricing", source="web", raw_text="Pro plan $20")
        agent.analyze_observation("cursor", obs)
        assert cap.captured is not None
        assert "历史结论: 官网源有效" in cap.captured.memory_context

    def test_analyzer_agent_no_memory_no_context(self):
        agent, cap = _make_agent(None)
        obs = Observation(gap_field="pricing", source="web", raw_text="Pro plan $20")
        agent.analyze_observation("cursor", obs)
        assert cap.captured.memory_context == ""

    def test_team_injection_consistent_with_single(self):
        """路径一致性：team（AnalyzerAgent）与 single（GapExecutor _memory_context_fn）同口径。"""
        lines = ["结论: 官网定价页最准"]
        mem = _SpyMemory(lines)
        single_ctx = "\n".join(mem.recent_context("cursor", top_k=3, query="pricing"))
        assert single_ctx == "结论: 官网定价页最准"
        agent, _ = _make_agent(mem)
        assert agent._retrieve_memory("cursor", "pricing") == single_ctx

    def test_real_archive_reaches_team_context(self, tmp_path):
        from competitor_agent.interfaces.context import AnalysisSession

        mem = FourLayerMemory(tmp_path / "m")
        mem.archive_session(
            AnalysisSession(
                task="分析 cursor 定价",
                competitor_name="cursor",
                session_id="s1",
                raw={
                    "dimensions": [{"dimension": "pricing", "summary": "Pro $20/mo", "confidence": 0.9}],
                    "pending_gaps": [],
                },
            )
        )
        agent, cap = _make_agent(mem)
        obs = Observation(gap_field="pricing", source="web", raw_text="Pro plan")
        agent.analyze_observation("cursor", obs)
        assert "Pro $20/mo" in cap.captured.memory_context
