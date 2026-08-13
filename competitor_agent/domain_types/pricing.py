"""定价结构与成本估算模型（设计文档 27 §3.1）

``PricingProfile`` 刻画竞品真实成本结构：
- ``PricingPlan``：免费/付费档位（月付/年付价格、限额、需询价标注）
- ``UsageBilling``：按量计费（单位、单价、档内包含量、模型档位表）
- ``cost_scenarios``：典型用量（light/medium/heavy）的月成本估算

随 ``AnalysisResult.details["pricing"]`` 落入报告，供渲染、导出与
时间线 price_change diff 读取。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# 典型用量场景（每日请求数）→ 月请求数按 30 天折算
DAILY_SCENARIOS: dict[str, int] = {"light": 30, "medium": 100, "heavy": 1000}


@dataclass
class PricingPlan:
    """单个定价档位：免费/付费计划的价格与限额"""

    tier: str = "plan"
    name: str = ""
    monthly_price_usd: float | None = None
    annual_price_usd: float | None = None
    limits: dict[str, str] = field(default_factory=dict)
    requires_quote: bool = False  # 隐藏定价（enterprise）需联系销售询价

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PricingPlan:
        return cls(
            tier=str(data.get("tier", "plan")),
            name=str(data.get("name") or ""),
            monthly_price_usd=_to_maybe_float(data.get("monthly_price_usd")),
            annual_price_usd=_to_maybe_float(data.get("annual_price_usd")),
            limits=dict(data.get("limits") or {}),
            requires_quote=bool(data.get("requires_quote", False)),
        )


@dataclass
class UsageBilling:
    """按量计费结构：单位/单价/模型档位表/档内包含量"""

    unit: str = "request"
    per_unit_usd: float | None = None
    model_tiers: dict[str, float] = field(default_factory=dict)
    included_units: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UsageBilling | None:
        if not data:
            return None
        return cls(
            unit=str(data.get("unit", "request")),
            per_unit_usd=_to_maybe_float(data.get("per_unit_usd")),
            model_tiers={
                str(k): v for k, v in (data.get("model_tiers") or {}).items() if _to_maybe_float(v) is not None
            },
            included_units=_to_maybe_int(data.get("included_units")),
        )


@dataclass
class PricingProfile:
    """竞品完整定价画像：档位 + 按量 + 典型场景成本估算"""

    plans: list[PricingPlan] = field(default_factory=list)
    usage: UsageBilling | None = None
    cost_scenarios: dict[str, float | None] = field(default_factory=dict)
    as_of: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_urls: list[str] = field(default_factory=list)

    @property
    def has_pricing_data(self) -> bool:
        return bool(self.plans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plans": [p.to_dict() for p in self.plans],
            "usage": self.usage.to_dict() if self.usage else None,
            "cost_scenarios": dict(self.cost_scenarios),
            "as_of": self.as_of,
            "source_urls": list(self.source_urls),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PricingProfile | None:
        if not data:
            return None
        return cls(
            plans=[PricingPlan.from_dict(p) for p in (data.get("plans") or [])],
            usage=UsageBilling.from_dict(data.get("usage")),
            cost_scenarios={
                str(k): None if v is None else _to_maybe_float(v)
                for k, v in (data.get("cost_scenarios") or {}).items()
            },
            as_of=str(data.get("as_of") or ""),
            source_urls=list(data.get("source_urls") or []),
        )


def _to_maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


__all__ = ["DAILY_SCENARIOS", "PricingPlan", "PricingProfile", "UsageBilling"]