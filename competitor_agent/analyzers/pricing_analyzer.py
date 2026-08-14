"""PricingAnalyzer — 定价/版本维度分析器（设计文档 27）

增强为结构化定价模型：
- ``PricingPlan`` 档位（免费/付费，月付/年付、限额）、``UsageBilling``（按量单价/模型档位）；
- 典型用量场景（light/medium/heavy 请求量）成本估算（超限额按单价追加，无数据不编造 = None）；
- 隐藏定价（enterprise）标注要求询价。

规则路径同时保留 plans[].price/period 键兼容既有评测与渲染契约。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
from competitor_agent.domain_types.enums import DimensionType, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.pricing import (
    DAILY_SCENARIOS,
    PricingPlan,
    PricingProfile,
    UsageBilling,
)
from competitor_agent.domain_types.report import DimensionResult

_MO_PRICE_RE = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(?:/|per\s+)?\s*(mo\b|month|user|seat|developer|dev)\b", re.IGNORECASE
)
_YR_PRICE_RE = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(?:/|per\s+)?\s*(year|yr|annual)\b", re.IGNORECASE
)
_FIRST_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
_LIMIT_RE = re.compile(r"(\d[\d,]*)\s*(requests?|messages?|conversations?|tokens?|seats?|users?)\b", re.IGNORECASE)
_ENTERPRISE_MARKER = re.compile(r"enterprise|ent\b|contact sales|联系方式|询价", re.IGNORECASE)
_PER_UNIT_RE = re.compile(
    r"per\s+(\d+)\s+(requests?|tokens?|runs?|messages?|seats?)\b[^$]{0,30}?\$\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_INCLUDED_RE = re.compile(r"(?:includ|含|contain)[^0-9]{0,15}?(\d+)\s+(requests?|messages?|runs?|tokens?)\b", re.IGNORECASE)
_MODEL_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)\s*/\s*(request|token|run)\b", re.IGNORECASE)

_TIER_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("enterprise", ("enterprise", "ent ", "contact sales")),
    ("business", ("business", "team", "teams")),
    ("pro", ("pro", "plus", "standard", "start")),
    ("free", ("free",)),
)


class PricingAnalyzer(BaseCompetitorAnalyzer):
    """从定价页提取结构化定价模型：档位 + 按量计费 + 成本场景"""

    dimension = DimensionType.PRICING

    def analyze(
        self,
        observation: Observation,
        gap: InfoGap,
        context: Any,
    ) -> DimensionResult:
        """在基类骨架之上附加值：结构化档位 + 成本估算 + 询价标注（设计文档 27）。"""
        result = super().analyze(observation, gap, context)
        details = dict(result.details) if isinstance(result.details, dict) else {}
        profile = _extract_profile(details, result.evidence)
        if profile.has_pricing_data:
            profile.cost_scenarios = _estimate_costs(profile, DAILY_SCENARIOS)
            summary = _compose_summary(result.summary, profile)
            confidence = result.confidence
            status = result.status
        else:
            summary = "未检测到定价信息，未编造价格或成本估算"
            confidence = 0.3
            status = ResultStatus.PARTIAL
        details["pricing"] = profile.to_dict()
        return DimensionResult(
            dimension=self.dimension.value,
            summary=summary,
            details=details,
            confidence=confidence,
            evidence=result.evidence,
            status=status,
        )

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是竞品定价分析师。从给定网页文本中提取结构化定价模型，"
                    "不要编造页面没有的价格或档位。"
                    "输出 JSON: {\"summary\": 一句话总结, "
                    "\"details\": {\"plans\": [{\"name\": ..., \"tier\": free/pro/business/enterprise, "
                    "\"monthly_price\": 数字或 null, \"annual_price\": 数字或 null, "
                    "\"limits\": {\"requests\": \"1000 requests/month\"}, "
                    "\"requires_quote\": true仅当企业档需联系销售询价}, "
                    "\"usage\": {\"unit\": \"request\", \"per_unit_price\": 数字或 null, "
                    "\"quantity\": 档内包含量数字或 null, \"model_tiers\": {\"basic\": 1.0, \"advanced\": 2.0}}}, "
                    "\"confidence\": 0-1}"
                ),
            },
            {"role": "user", "content": wrap_untrusted(observation.raw_text[:4000], observation.evidence.url)},
        ]

    def _details_properties(self) -> dict[str, Any]:
        """details 结构（设计文档 34）：plans/usage 与评测 _plan_price 抽取键对齐。

        plans 元素仅约束为 object（兼容 LLM 的 monthly_price_usd 契约键与
        mock/规则的 price+period 兼容键两种形态，不深层卡类型）。
        """
        return {
            "plans": {"type": "array", "items": {"type": "object"}},
            "usage": {"type": "object"},
        }

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        lines = [ln.strip() for ln in observation.raw_text.splitlines() if ln.strip()]
        plans = []
        for line in lines:
            plan = _parse_plan_line(line)
            if plan is not None:
                plans.append(plan)
        usage = _build_usage(lines)
        details: dict[str, Any] = {"plans": plans[:12]}
        if usage:
            details["usage"] = usage
        summary_parts = [f"检测到 {len(plans)} 个定价档位"]
        if usage:
            summary_parts.append("含按量计费")
        if any(p.get("requires_quote") for p in plans):
            summary_parts.append("含需询价档位")
        return {
            "summary": "，".join(summary_parts),
            "details": details,
        }


# ── 结构抽取 ─────────────────────────────────────────────────────────


def _parse_plan_line(line: str) -> dict[str, Any] | None:
    """单行 → 计划 dict（保留 plans[].price/period 兼容键 + 结构化键）。"""
    if _PER_UNIT_RE.search(line):
        return None  # 按量单价行，不属于档位
    if _MODEL_PRICE_RE.search(line) and "model" in line.lower():
        return None  # 模型档位行，不属于档位
    if "$" not in line:
        if _ENTERPRISE_MARKER.search(line) and len(line) < 120:
            return {
                "name": line[:60],
                "tier": "enterprise",
                "monthly_price_usd": None,
                "annual_price_usd": None,
                "limits": {},
                "requires_quote": True,
                "price": None,
                "period": "",
            }
        return None
    prefix = line.split("$", 1)[0].strip()
    name = prefix[:40] or "plan"
    tier = _detect_tier(name)
    monthly = _first_price(_MO_PRICE_RE, line)
    annual = _first_price(_YR_PRICE_RE, line)
    if monthly is None and annual is None:
        monthly = _first_price(_FIRST_PRICE_RE, line)
    limits: dict[str, str] = {}
    for m in _LIMIT_RE.finditer(line):
        unit = m.group(2).lower()
        if unit not in limits:
            limits[unit] = f"{m.group(1).replace(',', '')} {m.group(2)}"
    requires_quote = bool(_ENTERPRISE_MARKER.search(line)) and monthly is None and annual is None
    return {
        "name": name,
        "tier": tier,
        "monthly_price_usd": monthly,
        "annual_price_usd": annual,
        "limits": limits,
        "requires_quote": requires_quote,
        "price": None if monthly is None else _fmt_usd(monthly),
        "period": "month" if monthly is not None else ("year" if annual is not None else ""),
    }


def _parse_plan(data: Any) -> PricingPlan | None:
    """plan dict（LLM/规则两种键形态）→ PricingPlan。"""
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


def _build_usage(lines: list[str]) -> dict[str, Any]:
    """规则：从文本行提取按量计费（单价/档内包含/模型档位表）。"""
    per_by_unit: dict[str, float] = {}
    model_tiers: dict[str, float] = {}
    included: int | None = None
    for line in lines:
        m = _PER_UNIT_RE.search(line)
        if m:
            per_by_unit[m.group(2).lower()] = float(m.group(3)) / float(m.group(1))
        mt = _model_tier(line)
        if mt is not None:
            model_tiers[mt[0]] = mt[1]
        if per_by_unit:
            im = _INCLUDED_RE.search(line)
            if im is not None:
                included = int(im.group(1))
    if not per_by_unit and not model_tiers:
        return {}
    key = "request" if "request" in per_by_unit else next(iter(per_by_unit), "request")
    unit = key.removesuffix("s")  # "requests" → "request" 单数
    return {
        "unit": unit,
        "per_unit_price": per_by_unit.get(key),
        "quantity": included,
        "model_tiers": model_tiers,
    }


def _model_tier(line: str) -> tuple[str, float] | None:
    """形如 "Advanced model $2.00/request" / "basic model $0.5 per request"。"""
    m = _MODEL_PRICE_RE.search(line)
    if m is None:
        return None
    seg = line[: m.start()].strip().rstrip(":$- ")
    mm = re.search(r"([a-zA-Z][\w .&\-/]*) model$", seg, re.IGNORECASE) or re.search(r"([a-zA-Z][\w .&\-/]*) model\s", seg, re.IGNORECASE)
    tier = mm.group(1).strip() if mm else (seg.split()[-1] if seg.split() else "")
    return (tier.lower(), float(m.group(1))) if tier else None


def _parse_usage(data: Any) -> UsageBilling | None:
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


def _extract_profile(details: dict[str, Any], evidence: list[Any]) -> PricingProfile:
    """details（LLM / 规则产物）→ PricingProfile（结构抽取，设计文档 27 §2.1）。"""
    plans = [_parse_plan(d) for d in details.get("plans") or []]
    plans = [p for p in plans if p is not None]
    usage = _parse_usage(details.get("usage"))
    urls = [str(getattr(e, "url", "")) for e in evidence if getattr(e, "url", "")]
    return PricingProfile(
        plans=plans,
        usage=usage,
        as_of=datetime.now(timezone.utc).isoformat(),
        source_urls=urls,
    )


# ── 成本估算（设计文档 27 §2.2） ─────────────────────────────────────


def _limit_requests(limits: dict[str, str]) -> int | None:
    """计划限额里按请求/消息计的数值上限（用于无按量单价时判定超限）。"""
    for value in limits.values():
        m = re.search(r"(\d+)\s*(requests?|messages?|conversations?|runs?)\b", str(value), re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _plan_cost(plan: PricingPlan, usage: UsageBilling | None, monthly_requests: int) -> float | None:
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
    base = plan.monthly_price_usd
    if base is None:
        return None
    if cap is not None and monthly_requests > cap:
        return None  # 超限额但无按量单价：无法估算
    return base


def _estimate_costs(profile: PricingProfile, scenarios: dict[str, int]) -> dict[str, float | None]:
    """各典型用量场景 → 最低一档的月成本估算（无数据场景为 None，避免幻觉）。"""
    out: dict[str, float | None] = {}
    if not profile.plans:
        return out
    for label, daily in scenarios.items():
        monthly = daily * 30
        values = [_plan_cost(p, profile.usage, monthly) for p in profile.plans]
        numeric = [v for v in values if v is not None]
        out[label] = min(numeric) if numeric else None
    return out


# ── 业务辅助 ─────────────────────────────────────────────────────────


def _compose_summary(base: str, profile: PricingProfile) -> str:
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


def _detect_tier(name: str) -> str:
    low = name.lower()
    for tier, keywords in _TIER_KEYWORDS:
        if any(keyword in low for keyword in keywords):
            return tier
    return "plan"


def _first_price(pattern: re.Pattern[str], line: str) -> float | None:
    m = pattern.search(line)
    return _to_maybe_float(m.group(1)) if m else None


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


def _fmt_usd(value: float) -> str:
    return f"{value:g}"