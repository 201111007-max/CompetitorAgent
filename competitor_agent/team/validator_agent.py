"""ValidatorAgent — 校验 Agent（事实校验 + 冲突检测）

职责（3.2）：
1. 证据引用校验：每个结论必须有 >=1 条 SourceEvidence 支持，否则拦截。
2. 冲突检测：与历史结论（memory L2 笔记 / 传入的历史结果）冲突时
   标记冲突，交由 ReporterAgent 决定打回或降置信度。
3. 校验通过才发布到 T_VALIDATED。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus, BaseAgent
from competitor_agent.team.message_bus import T_VALIDATED, MessageBus

logger = logging.getLogger("competitor_agent.team.validator_agent")


@dataclass
class ValidationIssue:
    """一条校验问题"""
    dimension: str
    kind: str  # missing_evidence / conflict / low_confidence
    message: str
    severity: str = "error"  # error / warning


@dataclass
class ValidationResult:
    """校验汇总"""
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


class FactValidator:
    """纯校验逻辑（可单测，不依赖总线）"""

    def __init__(self, min_confidence: float = 0.3) -> None:
        self._min_confidence = min_confidence

    def validate(
        self,
        results: list[DimensionResult],
        history: list[DimensionResult] | None = None,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        for result in results:
            self._check_evidence(result, issues)
            self._check_confidence(result, issues)
            if history:
                self._check_conflict(result, history, issues)
        return ValidationResult(passed=not issues, issues=issues)

    def _check_evidence(self, result: DimensionResult, issues: list[ValidationIssue]) -> None:
        if not result.evidence:
            issues.append(
                ValidationIssue(
                    dimension=result.dimension,
                    kind="missing_evidence",
                    message="结论缺少证据链，无法溯源",
                )
            )
        elif result.confidence > 0.5 and not any(e.trust_level >= 0.7 for e in result.evidence):
            issues.append(
                ValidationIssue(
                    dimension=result.dimension,
                    kind="missing_evidence",
                    message="高置信结论缺少高可信证据",
                    severity="warning",
                )
            )

    def _check_confidence(self, result: DimensionResult, issues: list[ValidationIssue]) -> None:
        if result.confidence < self._min_confidence and result.status.value != "unavailable":
            issues.append(
                ValidationIssue(
                    dimension=result.dimension,
                    kind="low_confidence",
                    message=f"置信度 {result.confidence:.2f} 低于阈值 {self._min_confidence:.2f}",
                    severity="warning",
                )
            )

    def _check_conflict(
        self,
        result: DimensionResult,
        history: list[DimensionResult],
        issues: list[ValidationIssue],
    ) -> None:
        """与历史结论同维度对比：置信度翻转或结论方向相反视为冲突"""
        for past in history:
            if past.dimension != result.dimension:
                continue
            if past.confidence >= 0.7 and result.confidence <= 0.3:
                issues.append(
                    ValidationIssue(
                        dimension=result.dimension,
                        kind="conflict",
                        message=f"与历史冲突：历史置信 {past.confidence:.2f} vs 当前 {result.confidence:.2f}",
                    )
                )
                return

    def arbitrate(self, results: list[DimensionResult]) -> dict[str, DimensionResult]:
        """同维度多来源仲裁：按 置信度 > 证据源 trust > 时间新鲜度 取优（设计文档 33 §3.3）。

        被丢弃的候选保留为最优结果的 conflict_evidence（不静默丢弃，供报告标注）。
        每个维度只有一个结果时原样返回（与既有串行行为一致）。
        """
        by_dim: dict[str, list[DimensionResult]] = {}
        for result in results:
            by_dim.setdefault(result.dimension, []).append(result)

        arbitrated: dict[str, DimensionResult] = {}
        for dim, candidates in by_dim.items():
            if len(candidates) == 1:
                arbitrated[dim] = candidates[0]
                continue
            best = max(candidates, key=self._candidate_rank)
            conflicts = [c for c in candidates if c is not best]
            if conflicts:
                best.conflict_evidence = [
                    self._describe_conflict(c) for c in conflicts
                ]
            arbitrated[dim] = best
        return arbitrated

    @staticmethod
    def _candidate_rank(result: DimensionResult) -> tuple[float, float, str]:
        """仲裁排序键：置信度 > 平均证据 trust > 时间新鲜度（ISO 时间戳字典序）。"""
        trust = (
            sum(e.trust_level for e in result.evidence) / len(result.evidence)
            if result.evidence
            else 0.0
        )
        return (result.confidence, trust, result.timestamp)

    @staticmethod
    def _describe_conflict(result: DimensionResult) -> str:
        sources = ", ".join(e.source_name for e in result.evidence) or "无证据"
        return f"{result.dimension}: {result.summary[:120]}（来源 {sources}，置信 {result.confidence:.2f}）"


class ValidatorAgent(BaseAgent):
    """校验 Agent：包装 FactValidator，发布校验结果"""

    def __init__(
        self,
        bus: MessageBus,
        validator: FactValidator | None = None,
        memory: IFourLayerMemory | None = None,
    ) -> None:
        super().__init__("validator", bus, memory)
        self._validator = validator or FactValidator()

    def run(self, ctx: AgentContext) -> AgentResult:
        """决策入口：校验维度结论，产出 ValidationResult。"""
        results = ctx.extra.get("results", [])
        if not results:
            return AgentResult(
                status=AgentStatus.DEGRADED,
                payload=None,
                reason="无维度结论可校验",
            )
        outcome = self.validate(ctx.strategy.competitor.name, results)
        return AgentResult(
            status=AgentStatus.SUCCESS if outcome.passed else AgentStatus.DEGRADED,
            payload=outcome,
            reason="校验通过" if outcome.passed else f"{len(outcome.errors)} 项校验错误",
        )

    def validate(
        self,
        competitor_name: str,
        results: list[DimensionResult],
        history: list[DimensionResult] | None = None,
    ) -> ValidationResult:
        outcome = self._validator.validate(results, history)
        self._bus.publish(
            T_VALIDATED,
            {
                "competitor": competitor_name,
                "results": results,
                "validation": outcome,
            },
        )
        return outcome

    def arbitrate(self, results: list[DimensionResult]) -> dict[str, DimensionResult]:
        """同维度多来源仲裁（委托 FactValidator，设计文档 33 §3.3）"""
        return self._validator.arbitrate(results)