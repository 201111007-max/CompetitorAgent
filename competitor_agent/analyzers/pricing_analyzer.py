"""PricingAnalyzer — 定价/版本维度分析器（设计文档 27 / 47）

增强为结构化定价模型：
- ``PricingPlan`` 档位（免费/付费，月付/年付、限额）、``UsageBilling``（按量单价/模型档位）；
- 典型用量场景（light/medium/heavy 请求量）成本估算（超限额按单价追加，无数据不编造 = None）；
- 隐藏定价（enterprise）标注要求询价。

设计文档 47：仅 LLM 分析（无规则降级）。LLM 产物经结构抽取为 PricingProfile
（plans[].price/period 兼容键保留，供评测与渲染契约）。
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
    PricingProfile,
    compose_summary,
    estimate_costs,
    extract_profile,
    parse_plan,
    parse_usage,
)
from competitor_agent.domain_types.report import DimensionResult


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
        mock 的 price+period 兼容键两种形态，不深层卡类型）。
        """
        return {
            "plans": {"type": "array", "items": {"type": "object"}},
            "usage": {"type": "object"},
        }


# ── 结构抽取 ─────────────────────────────────────────────────────────


# ── 结构抽取 + 成本估算（设计文档 49 工具化迁入 domain_types/pricing.py）─────
# 仅保留别名，行为与测试口径不变。
from competitor_agent.domain_types.pricing import (  # noqa: E402
    _TIER_KEYWORDS,
    _compose_summary,
    _detect_tier,
    _estimate_costs,
    _extract_profile,
    _limit_requests,
    _parse_plan,
    _parse_usage,
    _plan_cost,
    _to_maybe_float,
    _to_maybe_int,
)
