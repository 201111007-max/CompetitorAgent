"""采集观察与证据链定义（防幻觉核心）"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from competitor_agent.domain_types.enums import ObservationStatus


@dataclass(frozen=True)
class SourceEvidence:
    """证据链：任何写入报告的事实必须能回溯到 >=1 条证据"""

    source_name: str
    url: str = ""
    access_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_hash: str = ""
    trust_level: float = 0.5

    @staticmethod
    def compute_hash(raw: str) -> str:
        """内容去重/变更检测"""
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Observation:
    """单次采集的观察结果"""

    gap_field: str
    source: str
    raw_text: str
    extracted: dict[str, Any] = field(default_factory=dict)
    evidence: SourceEvidence = field(default_factory=lambda: SourceEvidence(source_name=""))
    status: ObservationStatus = ObservationStatus.OK

    def to_dict(self) -> dict[str, Any]:
        """序列化（用于归档/日志）"""
        return {
            "gap_field": self.gap_field,
            "source": self.source,
            "raw_text": self.raw_text[:500],
            "extracted": self.extracted,
            "evidence": {
                "source_name": self.evidence.source_name,
                "url": self.evidence.url,
                "access_time": self.evidence.access_time,
                "content_hash": self.evidence.content_hash,
                "trust_level": self.evidence.trust_level,
            },
            "status": self.status.value,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> Observation:
        """反序列化"""
        return Observation(
            gap_field=data["gap_field"],
            source=data["source"],
            raw_text=data["raw_text"],
            extracted=data.get("extracted", {}),
            evidence=SourceEvidence(
                source_name=data["evidence"]["source_name"],
                url=data["evidence"].get("url", ""),
                access_time=data["evidence"].get("access_time", ""),
                content_hash=data["evidence"].get("content_hash", ""),
                trust_level=data["evidence"].get("trust_level", 0.5),
            ),
            status=ObservationStatus(data.get("status", "ok")),
        )
