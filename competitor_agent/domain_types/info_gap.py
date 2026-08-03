"""信息缺口（InfoGap）— Agent 自主决策的中枢"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as d_field

from competitor_agent.domain_types.enums import GapStatus
from competitor_agent.domain_types.observation import SourceEvidence

CLOSED_CONFIDENCE = 0.8
CORE_PRIORITY = 8


@dataclass
class InfoGap:
    """一个信息缺口。Agent 据此决定采哪个源、何时关闭。

    status 状态机：OPEN → PARTIAL → CONFIRMED → CLOSED；失败回退 → OPEN/BLOCKED。
    """

    field: str
    priority: int = 5
    confidence: float = 0.0
    sources_tried: list[str] = d_field(default_factory=list)
    status: GapStatus = GapStatus.OPEN
    evidence: list[SourceEvidence] = d_field(default_factory=list)

    @property
    def is_core(self) -> bool:
        """是否核心缺口（优先级 >=8）"""
        return self.priority >= CORE_PRIORITY

    @property
    def is_satisfied(self) -> bool:
        """核心满足度判定：confidence 且关闭阈值"""
        return self.confidence >= CLOSED_CONFIDENCE

    @property
    def is_closed(self) -> bool:
        return self.status in (GapStatus.CLOSED, GapStatus.CONFIRMED)

    def add_evidence(self, evidence: SourceEvidence) -> None:
        """追加证据并去重"""
        if all(e.content_hash != evidence.content_hash for e in self.evidence):
            self.evidence.append(evidence)

    def record_source_try(self, source_name: str) -> None:
        """记录已尝试数据源（去重）"""
        if source_name not in self.sources_tried:
            self.sources_tried.append(source_name)

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "priority": self.priority,
            "confidence": self.confidence,
            "sources_tried": self.sources_tried,
            "status": self.status.value,
            "evidence_count": len(self.evidence),
        }