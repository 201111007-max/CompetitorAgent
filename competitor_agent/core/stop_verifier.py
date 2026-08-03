"""StopVerifier — 停止验证器（Hook 仲裁能否终止）

对照 config/review_config.yaml stop_verifier 段：
- required_dimensions: 必须关闭的核心维度（缺则不许停）
- min_confidence: 核心维度最低置信度
- min_evidence_ratio: 已关闭缺口中有证据支撑的比例下限

验证器作为 BudgetController 的最终仲裁 Hook：
四条件可能判定停，但若核心维度未达标，验证器否决（veto）。
"""
from __future__ import annotations

from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.interfaces.context import BudgetState, StopDecision


class StopVerifier:
    """基于维度/置信度/证据率的停止验证器"""

    def __init__(
        self,
        required_dimensions: list[str] | None = None,
        min_confidence: float = 0.6,
        min_evidence_ratio: float = 0.7,
    ) -> None:
        self._required_dimensions = required_dimensions or ["pricing", "feature"]
        self._min_confidence = min_confidence
        self._min_evidence_ratio = min_evidence_ratio

    def verify(self, gaps: list[InfoGap], budget_state: BudgetState) -> StopDecision:
        """决定可否终止。可停 → should_stop=True + reason；不可停 → 列出缺口原因。"""
        # 核心维度必须存在且达到置信度
        missing = [d for d in self._required_dimensions if not any(g.field == d for g in gaps)]
        low_conf = [
            g.field
            for g in gaps
            if g.field in self._required_dimensions and g.confidence < self._min_confidence
        ]

        if missing:
            return StopDecision(
                should_stop=False,
                reason="required_dimension_missing",
                details=f"缺少必需维度: {missing}",
            )
        if low_conf:
            return StopDecision(
                should_stop=False,
                reason="core_confidence_low",
                details=f"核心维度置信度不足: {low_conf}",
            )

        # 证据率：已收集证据的缺口占比
        closed_gaps = [g for g in gaps if g.is_closed]
        if closed_gaps:
            with_evidence = [g for g in closed_gaps if g.evidence]
            ratio = len(with_evidence) / len(closed_gaps)
            if ratio < self._min_evidence_ratio:
                return StopDecision(
                    should_stop=False,
                    reason="evidence_ratio_low",
                    details=f"证据率 {ratio:.2f} < {self._min_evidence_ratio}",
                )

        return StopDecision(
            should_stop=True,
            reason="verifier_approved",
            details=f"核心维度全部达标，证据率满足下限 {self._min_evidence_ratio}",
        )