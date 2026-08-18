"""ReviewerAgent — 对抗式评审 Agent（第 5 角色，设计文档 49 §3.3）

Reporter 之前插入独立评审角色，对草稿维度结论**主动证伪**（区别于分析器内部自检
``_needs_verification``——那是"自己核对自己"，这里是独立角色的反方核对）：
1. **关键数值复查**：复用 ``_count_numeric_conflicts`` 语义做反方核对——details 声称
   的实体数值应能回溯到对应观测原文，不能回溯 → ``needs_revision``；
2. **跨维度矛盾**：消费编排层 ``CrossDimensionConflict``（同源同键异值）；
3. **置信度/证据不足**：``COMPLETE`` 结论置信度低于阈值（过度自信）→ 需修订
   （``PARTIAL`` 低置信是诚实标注，不视为缺陷，保证 mock 无缺陷零回灌）。

评审回灌为**有界循环**（编排器 ``_MAX_REVISION_ROUNDS=1``）：命中维度重入分析器修订，
强制复查；超限未过 → 报告标注 ``[REVIEWED]`` + issue 摘要，不降级为失败。

确定性：Reviewer 纯代码校验，无 LLM 调用；mock 下无缺陷 → ``ok=True`` 零回灌，
LLM 调用次数不变（设计文档 47/48 不变量）。``reviewer.enabled`` 默认关（零行为变化）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from competitor_agent.analyzers.base import _count_numeric_conflicts
from competitor_agent.domain_types.conflict import CrossDimensionConflict
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.team.base_agent import AgentContext, AgentResult, AgentStatus, BaseAgent
from competitor_agent.team.message_bus import MessageBus

logger = logging.getLogger("competitor_agent.team.reviewer_agent")


@dataclass
class ReviewIssue:
    """一条评审问题（维度 + 类型 + 可读信息 + 期望动作）"""

    dimension: str
    kind: str  # numeric_conflict / cross_dimension_conflict / low_confidence
    message: str
    action: str = "reanalyze"


@dataclass
class ReviewVerdict:
    """评审结论：ok=True 通过；否则携带问题清单。"""

    ok: bool
    issues: list[ReviewIssue] = field(default_factory=list)

    @property
    def needs_revision(self) -> bool:
        return not self.ok


@dataclass
class ReviewResult:
    """编排层评审+修订的最终结果（供报告标注 [REVIEWED]）。"""

    ok: bool
    issues: list[ReviewIssue] = field(default_factory=list)
    revised: bool = False  # 是否发生过回灌修订
    rounds: int = 0  # 实际修订轮数


class ReviewerAgent(BaseAgent):
    """对抗式评审 Agent：对草稿维度结论主动证伪（纯代码校验，无 LLM 调用）。"""

    def __init__(
        self,
        bus: MessageBus,
        memory: IFourLayerMemory | None = None,
        min_confidence: float = 0.3,
        tool_dispatcher: Any = None,
    ) -> None:
        super().__init__("reviewer", bus, memory)
        self._min_confidence = min_confidence
        self._tool_dispatcher = tool_dispatcher  # 预留：后续可经工具独立重查来源

    # ── BaseAgent 契约（决策入口，供同步编排 _run_with_retry 复用）──

    def run(self, ctx: AgentContext) -> AgentResult:
        """决策入口：评审草稿维度结论，产出 ReviewVerdict。"""
        results = ctx.extra.get("results", [])
        observations = ctx.extra.get("observations", [])
        conflicts = ctx.extra.get("cross_dimension_conflicts", [])
        if not results:
            return AgentResult(
                status=AgentStatus.DEGRADED,
                payload=None,
                reason="无维度结论可评审",
            )
        verdict = self.review(ctx, results, observations, conflicts)
        return AgentResult(
            status=AgentStatus.SUCCESS if verdict.ok else AgentStatus.DEGRADED,
            payload=verdict,
            reason="评审通过" if verdict.ok else f"{len(verdict.issues)} 项评审问题",
        )

    # ── 对抗式证伪（纯逻辑，可单测）──────────────────────────────

    def review(
        self,
        ctx: AgentContext,
        results: list[DimensionResult],
        observations: list[Any] | None = None,
        cross_dim_conflicts: list[CrossDimensionConflict] | None = None,
    ) -> ReviewVerdict:
        issues: list[ReviewIssue] = []
        for result in results:
            self._check_numeric(result, observations, issues)
            self._check_confidence(result, issues)
        for conflict in cross_dim_conflicts or []:
            issues.append(
                ReviewIssue(
                    dimension=conflict.dimension_a,
                    kind="cross_dimension_conflict",
                    message=(
                        f"跨维度矛盾: {conflict.dimension_a}.{conflict.claim_key}="
                        f"{conflict.value_a} vs {conflict.dimension_b}.{conflict.claim_key}="
                        f"{conflict.value_b}（同源 {', '.join(conflict.evidence_hashes)}）"
                    ),
                )
            )
        return ReviewVerdict(ok=not issues, issues=issues)

    def _check_numeric(
        self,
        result: DimensionResult,
        observations: list[Any] | None,
        issues: list[ReviewIssue],
    ) -> None:
        """反方核对：details 声称的实体数值应回溯到该维度观测原文。"""
        obs = self._observation_for(observations, result.dimension)
        if obs is None:
            return
        conflicts = _count_numeric_conflicts(result.details, obs.raw_text)
        if conflicts:
            issues.append(
                ReviewIssue(
                    dimension=result.dimension,
                    kind="numeric_conflict",
                    message=f"{conflicts} 处关键数值无法回溯到原文证据（反方核对）",
                )
            )

    def _check_confidence(self, result: DimensionResult, issues: list[ReviewIssue]) -> None:
        """置信度核对：COMPLETE 结论却低于阈值 = 过度自信 → 需修订。

        PARTIAL/UNAVAILABLE 低置信是诚实标注（分析器已按设计文档 47 标 PARTIAL），
        不视为缺陷——保证 mock（口碑信号不足 → 0.1 PARTIAL）无缺陷零回灌。
        """
        if (
            result.status == ResultStatus.COMPLETE
            and result.confidence < self._min_confidence
        ):
            issues.append(
                ReviewIssue(
                    dimension=result.dimension,
                    kind="low_confidence",
                    message=(
                        f"COMPLETE 结论置信度 {result.confidence:.2f} "
                        f"低于评审阈值 {self._min_confidence:.2f}"
                    ),
                )
            )

    @staticmethod
    def _observation_for(observations: list[Any] | None, dimension: str) -> Any:
        """找对应维度的观测（duck-type gap_field），无则返回 None。"""
        for obs in observations or []:
            if getattr(obs, "gap_field", None) == dimension:
                return obs
        return None


__all__ = ["ReviewIssue", "ReviewResult", "ReviewVerdict", "ReviewerAgent"]
