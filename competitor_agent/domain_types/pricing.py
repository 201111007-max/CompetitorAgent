"""定价结构与成本估算模型（设计文档 27 §3.1）

``PricingProfile`` 刻画竞品真实成本结构：
- ``PricingPlan``：免费/付费档位（月付/年付价格、限额、需询价标注）
- ``UsageBilling``：按量计费（单位、单价、档内包含量、模型档位表）
- ``cost_scenarios``：典型用量（light/medium/heavy）的月成本估算

随 ``AnalysisResult.details["pricing"]`` 落入报告，供渲染、导出与
时间线 price_change diff 读取。
"""
from __future__ import annotations

import re
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


# ── 结构抽取 + 成本估算（设计文档 27 §2，49 工具化迁入）──────────────
# 原实现位于 analyzers/pricing_analyzer.py（随 49 删除），逻辑与行为不变。

_TIER_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("enterprise", ("enterprise", "ent ", "contact sales")),
    ("business", ("business", "team", "teams")),
    ("pro", ("pro", "plus", "standard", "start")),
    ("free", ("free",)),
)


def _detect_tier(name: str) -> str:
    low = name.lower()
    for tier, keywords in _TIER_KEYWORDS:
        if any(keyword in low for keyword in keywords):
            return tier
    return "plan"


def parse_plan(data: Any) -> PricingPlan | None:
    """plan dict（LLM 两种键形态）→ PricingPlan。"""
    if not isinstance(data, dict):
        return None
    name = str(data.get("name") or "")
    tier = str(data.get("tier") or "") or _detect_tier(name)
    monthly = _to_maybe_float(data.get("monthly_price_usd"))
    if monthly is None:
        monthly = _to_maybe_float(data.get("monthly_price"))
    annual = _to_maybe_float(data.get("annual_price_usd"))
    if annual is None:
        annual = _to_maybe_float(data.get("annual_price"))
    if monthly is None and annual is None:
        price = _to_maybe_float(data.get("price"))
        period = str(data.get("period") or "").lower()
        if price is not None and period in ("year", "yr", "annual", "yearly"):
            annual = price
        elif price is not None:
            monthly = price
    limits = dict(data.get("limits") or {})
    requires_quote = bool(data.get("requires_quote", False))
    if not requires_quote and tier == "enterprise" and monthly is None and annual is None:
        requires_quote = True
    return PricingPlan(
        tier=tier,
        name=name,
        monthly_price_usd=monthly,
        annual_price_usd=annual,
        limits=limits,
        requires_quote=requires_quote,
    )


def parse_usage(data: Any) -> UsageBilling | None:
    if not isinstance(data, dict):
        return None
    unit = str(data.get("unit") or "request")
    per = _to_maybe_float(data.get("per_unit_usd", data.get("per_unit_price")))
    included = _to_maybe_int(data.get("included_units", data.get("quantity")))
    tiers: dict[str, float] = {}
    raw = data.get("model_tiers") or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            fv = _to_maybe_float(v)
            if fv is not None:
                tiers[str(k).lower()] = fv
    if per is None and not tiers and included is None:
        return None
    return UsageBilling(unit=unit, per_unit_usd=per, model_tiers=tiers, included_units=included)


def extract_profile(details: dict[str, Any], evidence: list[Any] | None = None) -> PricingProfile:
    """details（LLM 产物）→ PricingProfile（结构抽取，设计文档 27 §2.1）。

    plans 非 list（LLM 产物可能畸形）时按空档位处理，不抛错。
    """
    raw_plans = details.get("plans") or []
    raw_plans = raw_plans if isinstance(raw_plans, list) else []
    plans = [p for p in (parse_plan(d) for d in raw_plans) if p is not None]
    usage = parse_usage(details.get("usage"))
    urls = [str(getattr(e, "url", "")) for e in (evidence or []) if getattr(e, "url", "")]
    return PricingProfile(
        plans=plans,
        usage=usage,
        as_of=datetime.now(timezone.utc).isoformat(),
        source_urls=urls,
    )


def _limit_requests(limits: dict[str, str]) -> int | None:
    """计划限额里按请求/消息计的数值上限（用于无按量单价时判定超限）。"""
    for value in limits.values():
        m = re.search(r"(\d+)\s*(requests?|messages?|conversations?|runs?)\b", str(value), re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def plan_cost(plan: PricingPlan, usage: UsageBilling | None, monthly_requests: int) -> float | None:
    """单档月成本：档价 + 超限额按量追加；无法定价时 None（不编造）。"""
    if plan.requires_quote and plan.monthly_price_usd is None:
        return None  # 企业档需询价：不猜数字
    per = usage.per_unit_usd if usage else None
    included = usage.included_units if usage else None
    cap = _limit_requests(plan.limits)
    if per is not None:
        base = plan.monthly_price_usd if plan.monthly_price_usd is not None else 0.0
        limit = included if included is not None else cap
        overage = max(0, monthly_requests - (limit or 0))
        return base + overage * per
    flat_base = plan.monthly_price_usd
    if flat_base is None:
        return None
    if cap is not None and monthly_requests > cap:
        return None  # 超限额但无按量单价：无法估算
    return flat_base


def profile_from_details(
    details: dict[str, Any], evidence: list[Any] | None = None
) -> PricingProfile:
    """details（49 命名空间：plans 原始档位）→ 完整 PricingProfile（含成本估算）。

    渲染 / 导出 / 时间线 diff 共用；plans 键名沿用现有命名空间
    （``details["plans"]``），结构抽取交给 ``extract_profile``。
    """
    profile = extract_profile(details, evidence)
    if not profile.has_pricing_data:
        return profile
    # 显式 cost_scenarios（LLM/工具产物）优先；缺失时才按档位估算（不覆盖外部给定值）
    explicit = details.get("cost_scenarios")
    if isinstance(explicit, dict) and explicit:
        profile.cost_scenarios = {str(k): _to_maybe_float(v) for k, v in explicit.items()}
    else:
        profile.cost_scenarios = estimate_costs(profile, DAILY_SCENARIOS)
    return profile


def estimate_costs(profile: PricingProfile, scenarios: dict[str, int]) -> dict[str, float | None]:
    """各典型用量场景 → 最低一档的月成本估算（无数据场景为 None，避免幻觉）。"""
    out: dict[str, float | None] = {}
    if not profile.plans:
        return out
    for label, daily in scenarios.items():
        monthly = daily * 30
        values = [plan_cost(p, profile.usage, monthly) for p in profile.plans]
        numeric = [v for v in values if v is not None]
        out[label] = min(numeric) if numeric else None
    return out


def compose_summary(base: str, profile: PricingProfile) -> str:
    parts = [base] if base else []
    costs = profile.cost_scenarios
    if costs:
        med = costs.get("medium")
        if med is not None:
            parts.append(f"中等用量（100 次/天）月成本估算 ≈ ${med:g}")
        elif any(v is not None for v in costs.values()):
            parts.append("成本估算仅覆盖部分场景")
        else:
            parts.append("成本估算需询价/数据不足，不编造")
    if profile.usage is not None and profile.usage.per_unit_usd is not None:
        parts.append(f"按量计费 ${profile.usage.per_unit_usd:g}/{profile.usage.unit or 'request'}")
    if any(p.requires_quote for p in profile.plans):
        parts.append("含需询价档位")
    return "；".join(p for p in parts if p)


__all__ = [
    "DAILY_SCENARIOS",
    "PricingPlan",
    "PricingProfile",
    "UsageBilling",
    "compose_summary",
    "estimate_costs",
    "extract_profile",
    "parse_plan",
    "parse_usage",
    "plan_cost",
    "profile_from_details",
]