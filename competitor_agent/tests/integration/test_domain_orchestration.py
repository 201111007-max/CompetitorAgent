"""领域差异化编排集成测试（设计文档 49）

- 对抗式评审（③）：reviewer 开 + mock 零缺陷 → 零回灌，LLM 调用次数不变；
  命中低置信 COMPLETE → 有界回灌修订（≤1 轮）→ [REVIEWED] 标注。
- 新鲜度驱动委派（②）：新鲜维度跳过采集复用归档；过期维度照常采集。
- 跨维度冲突检测（①）：同源同键异值 → 报告"## 跨维度冲突备注"。
"""
from __future__ import annotations

import pytest

from competitor_agent.config.loader import AppConfig, OrchestrationConfig
from competitor_agent.core.freshness_gate import FreshnessGate
from competitor_agent.core.source_dedup import SourceDedup
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import DimensionType, GapStatus, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient
from competitor_agent.team.base_agent import AgentResult, AgentStatus
from competitor_agent.team.orchestrator import TeamOrchestrator

pytestmark = pytest.mark.integration

CURSOR = Competitor(
    name="cursor",
    official_links={
        "pricing": "https://cursor.com/pricing",
        "home": "https://cursor.com",
    },
)


def _pricing_strategy() -> CompetitorStrategy:
    return CompetitorStrategy(
        competitor=CURSOR,
        gaps=[InfoGap(field="pricing", priority=9, confidence=0.0, status=GapStatus.OPEN)],
        budget_allocation={DimensionType.PRICING: 1},
        terminal_thresholds={"confidence": 0.8},
    )


class _CountingExtractor:
    """统计抓取次数的采集器（验证新鲜度跳过 / 去重命中）。"""

    source_name = "web_extractor"

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, gap: object, context: object) -> Observation:
        self.calls += 1
        url = str(getattr(context, "kwargs", {}).get("url"))
        return Observation(
            gap_field=str(getattr(gap, "field", "")),
            source=self.source_name,
            raw_text="Pro costs $20 per month",
            evidence=SourceEvidence(
                source_name=self.source_name, url=url, content_hash="hash-pricing", trust_level=0.9
            ),
        )


class _StubAnalyzer:
    """按脚本序列返回 DimensionResult 列表的桩分析器（确定性驱动评审回灌）。"""

    name = "analyzer"

    def __init__(self, *scripts: list[DimensionResult]) -> None:
        self._scripts = list(scripts)
        self.calls = 0
        self._last_ctx_observations: list = []

    def run(self, ctx: object) -> AgentResult:
        self.calls += 1
        self._last_ctx_observations = list(getattr(ctx, "extra", {}).get("observations", []))
        payload = self._scripts[min(self.calls, len(self._scripts)) - 1]
        return AgentResult(status=AgentStatus.SUCCESS, payload=list(payload))


class TestReviewerZeroDefectInvariant:
    """③ 评审开启且 mock 零缺陷 → 零回灌，LLM 调用次数与关闭时一致。"""

    @staticmethod
    def _counting_llm(mock_llm) -> tuple[LLMClient, list[int]]:
        calls = [0]
        base = mock_llm._call

        def wrapped(messages, model):
            calls[0] += 1
            return base(messages, model)

        return LLMClient(call_func=wrapped), calls

    def test_zero_defect_no_review_notes(self, fake_extractor, mock_llm):
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            config=AppConfig(orchestration=OrchestrationConfig(reviewer_enabled=True)),
        )
        report = api.analyze_team("分析 Cursor")
        assert report.terminal_state == "success"
        assert report.dimension_results
        assert "对抗式评审备注" not in report.markdown_report

    def test_llm_call_count_unchanged_with_reviewer(self, fake_extractor, mock_llm):
        on_llm, on_calls = self._counting_llm(mock_llm)
        off_llm, off_calls = self._counting_llm(mock_llm)

        api_off = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=off_llm,
            use_llm=True,
            config=AppConfig(orchestration=OrchestrationConfig(reviewer_enabled=False)),
        )
        api_off.analyze_team("分析 Cursor")

        api_on = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=on_llm,
            use_llm=True,
            config=AppConfig(orchestration=OrchestrationConfig(reviewer_enabled=True)),
        )
        api_on.analyze_team("分析 Cursor")

        assert on_calls[0] == off_calls[0], "零缺陷评审不应增加 LLM 调用次数"


class TestFreshnessDelegation:
    """② 新鲜度驱动委派：新鲜跳过采集复用归档 / 过期照常采集。"""

    def _orch(self, extractor, llm, archive_results, archive_freshness, freshness_enabled):
        return TeamOrchestrator(
            extractor=extractor,
            llm=llm,
            use_llm=True,
            orchestration=OrchestrationConfig(freshness_delegation_enabled=freshness_enabled),
            freshness_gate=FreshnessGate(),
            archive_results=archive_results,
            archive_freshness=archive_freshness,
        )

    @staticmethod
    def _archived_pricing() -> DimensionResult:
        return DimensionResult(
            dimension="pricing",
            summary="归档定价",
            details={"monthly_price_usd": 20},
            confidence=0.9,
            status=ResultStatus.COMPLETE,
            evidence=[SourceEvidence(source_name="archive", trust_level=0.9)],
        )

    def test_fresh_dimension_skips_collection_and_reuses_archive(self, mock_llm):
        extractor = _CountingExtractor()
        archived = self._archived_pricing()
        orch = self._orch(
            extractor,
            mock_llm,
            archive_results=[archived],
            archive_freshness={"pricing": 1},  # 1 天 ≤ 7 天 TTL → 新鲜
            freshness_enabled=True,
        )
        report = orch.run("分析 Cursor", strategy=_pricing_strategy())
        assert extractor.calls == 0  # 新鲜维度未采集
        pricing = next(r for r in report.dimension_results if r.dimension == "pricing")
        assert pricing.summary == "归档定价"  # 复用归档结论

    def test_stale_dimension_still_collected(self, fake_extractor, mock_llm):
        orch = self._orch(
            fake_extractor,
            mock_llm,
            archive_results=[],
            archive_freshness={"pricing": 100},  # 100 天 > 7 天 TTL → 过期
            freshness_enabled=True,
        )
        report = orch.run("分析 Cursor", strategy=_pricing_strategy())
        pricing = next(r for r in report.dimension_results if r.dimension == "pricing")
        assert pricing.details  # 重新采集分析产出

    def test_gate_disabled_ignores_archive(self, fake_extractor, mock_llm):
        """未启用 → 编排器原行为：忽略归档，照常采集。"""
        extractor = _CountingExtractor()
        orch = self._orch(
            extractor,
            mock_llm,
            archive_results=[self._archived_pricing()],
            archive_freshness={"pricing": 1},
            freshness_enabled=False,
        )
        report = orch.run("分析 Cursor", strategy=_pricing_strategy())
        assert extractor.calls == 1  # 照常采集
        assert report.dimension_results


class TestReviewerRevisionLoop:
    """③ 评审回灌：低置信 COMPLETE → 命中维度重入分析器修订（≤1 轮）。"""

    @staticmethod
    def _orch_with_stub(mock_llm, analyzer, reviewer_enabled: bool, extractor):
        orch = TeamOrchestrator(
            extractor=extractor,
            llm=mock_llm,
            use_llm=True,
            orchestration=OrchestrationConfig(reviewer_enabled=reviewer_enabled),
            dedup=SourceDedup(),
        )
        orch._analyzer = analyzer
        return orch

    @staticmethod
    def _ev() -> SourceEvidence:
        return SourceEvidence(source_name="official_pricing", trust_level=0.9)

    @staticmethod
    def _low_confidence() -> DimensionResult:
        return DimensionResult(
            dimension="pricing",
            summary="低价",
            details={"monthly_price_usd": 20},
            confidence=0.1,  # COMPLETE 却低置信 → 评审必命中
            status=ResultStatus.COMPLETE,
            evidence=[TestReviewerRevisionLoop._ev()],
        )

    @staticmethod
    def _fixed() -> DimensionResult:
        return DimensionResult(
            dimension="pricing",
            summary="修正定价",
            details={"monthly_price_usd": 20},
            confidence=0.9,
            status=ResultStatus.COMPLETE,
            evidence=[TestReviewerRevisionLoop._ev()],
        )

    def test_revision_loop_fixes_and_marks_revised(self, fake_extractor, mock_llm):
        analyzer = _StubAnalyzer([self._low_confidence()], [self._fixed()])
        orch = self._orch_with_stub(mock_llm, analyzer, reviewer_enabled=True, extractor=fake_extractor)
        report = orch.run("分析 Cursor", strategy=_pricing_strategy())
        assert analyzer.calls == 2  # 首轮 + 1 轮回灌修订
        pricing = next(r for r in report.dimension_results if r.dimension == "pricing")
        assert pricing.confidence == 0.9  # 修订结果汇总进报告
        assert "对抗式评审备注" not in report.markdown_report  # 修订通过，无 issue 标注

    def test_unresolved_revision_marks_reviewed(self, fake_extractor, mock_llm):
        analyzer = _StubAnalyzer([self._low_confidence()], [self._low_confidence()])
        orch = self._orch_with_stub(mock_llm, analyzer, reviewer_enabled=True, extractor=fake_extractor)
        report = orch.run("分析 Cursor", strategy=_pricing_strategy())
        assert analyzer.calls == 2  # ≤1 轮封顶
        assert "## 对抗式评审备注" in report.markdown_report
        assert "[REVIEWED]" in report.markdown_report

    def test_reviewer_disabled_no_revision(self, fake_extractor, mock_llm):
        analyzer = _StubAnalyzer([self._fixed()])
        orch = self._orch_with_stub(mock_llm, analyzer, reviewer_enabled=False, extractor=fake_extractor)
        report = orch.run("分析 Cursor", strategy=_pricing_strategy())
        assert analyzer.calls == 1  # 无回灌
        assert report.terminal_state == "success"


class TestCrossDimensionConflictInReport:
    """① 跨维度冲突：同源同键异值 → 报告含"## 跨维度冲突备注"。"""

    def test_conflict_rendered_in_report(self, fake_extractor, mock_llm):
        pricing = DimensionResult(
            dimension="pricing",
            summary="定价",
            details={"monthly_price_usd": 20},
            confidence=0.9,
            status=ResultStatus.COMPLETE,
            evidence_hashes=["shared-hash"],
        )
        feature = DimensionResult(
            dimension="feature",
            summary="功能",
            details={"monthly_price_usd": 40},  # 同源同键异值
            confidence=0.8,
            status=ResultStatus.COMPLETE,
            evidence_hashes=["shared-hash"],
        )
        analyzer = _StubAnalyzer([pricing, feature])

        orch = TeamOrchestrator(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            orchestration=OrchestrationConfig(),  # 冲突检测默认开
            dedup=SourceDedup(),
        )
        orch._analyzer = analyzer
        strategy = CompetitorStrategy(
            competitor=CURSOR,
            gaps=[
                InfoGap(field="pricing", priority=9, confidence=0.0, status=GapStatus.OPEN),
                InfoGap(field="feature", priority=8, confidence=0.0, status=GapStatus.OPEN),
            ],
            budget_allocation={DimensionType.PRICING: 1, DimensionType.FEATURE: 1},
            terminal_thresholds={"confidence": 0.8},
        )
        report = orch.run("分析 Cursor", strategy=strategy)
        assert "## 跨维度冲突备注" in report.markdown_report
        assert "monthly_price_usd" in report.markdown_report

    def test_conflict_detection_disabled(self, fake_extractor, mock_llm):
        pricing = DimensionResult(
            dimension="pricing",
            summary="定价",
            details={"monthly_price_usd": 20},
            confidence=0.9,
            status=ResultStatus.COMPLETE,
            evidence_hashes=["shared-hash"],
        )
        feature = DimensionResult(
            dimension="feature",
            summary="功能",
            details={"monthly_price_usd": 40},
            confidence=0.8,
            status=ResultStatus.COMPLETE,
            evidence_hashes=["shared-hash"],
        )
        orch = TeamOrchestrator(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            orchestration=OrchestrationConfig(cross_dimension_conflict_enabled=False),
            dedup=SourceDedup(),
        )
        orch._analyzer = _StubAnalyzer([pricing, feature])
        strategy = CompetitorStrategy(
            competitor=CURSOR,
            gaps=[
                InfoGap(field="pricing", priority=9, confidence=0.0, status=GapStatus.OPEN),
                InfoGap(field="feature", priority=8, confidence=0.0, status=GapStatus.OPEN),
            ],
            budget_allocation={DimensionType.PRICING: 1, DimensionType.FEATURE: 1},
            terminal_thresholds={"confidence": 0.8},
        )
        report = orch.run("分析 Cursor", strategy=strategy)
        assert "## 跨维度冲突备注" not in report.markdown_report
