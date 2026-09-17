"""蒸馏事实层（设计文档 88 §4.1，单一事实源的 writer 侧视图）

三层结构（粒度各配，四消费点同源）：

- **第 0 层 命名空间归一原语**：从维度 ``details`` dict 提取结构化字段——
  ``pricing_plans``/``plan_price``/``feature_present``/``benchmark_entries``/
  ``benchmark_score``/``ecosystem_signal``/``sentiment_signal``/``roadmap_events``。
  benchmark 评测（五分支）、timeline_memory（plans 双命名空间回退）、
  report_exporter（benchmarks 透传）的既有读取逻辑**行为等价平移**于此，
  键兼容矩阵不重写（pricing 复用 ``parse_plan``/``profile_from_details`` 唯一权威）。
- **第 1 层 facts 视图**：``distill_dimension``/``distill_report`` 把 DimensionResult
  蒸馏为 ``DimensionFacts``（writer 唯一输入，幻觉防火墙——writer 不接触原始 details）。
- **第 2 层 查询 helper**：``fact_by_term``/``numeric_allowlist``（N2 保真校验用）。

依赖铁律：本模块只允许 import domain_types 内部（pricing/report），
禁止 import core/facade/memory/evaluation（防循环）。
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from competitor_agent.domain_types.pricing import (
    PricingPlan,
    parse_plan,
    profile_from_details,
)
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult

# ────────────────────────────────────────────────────────────
# 第 0 层：命名空间归一原语
# ────────────────────────────────────────────────────────────

_PERIOD_ALIAS = {"mo": "month"}

# 真实 LLM 输出漂移兜底：plans 可能是 {"Pro": "30 USD/month"} 字典形态（real 轨实测暴露）
_PRICE_VALUE_RE = re.compile(r"[$¥€]?\s*([\d.,]+)\s*(?:USD|CNY|RMB|美元|元)?\s*/\s*([A-Za-z一-鿿]+)")


def pricing_plans(details: dict[str, Any]) -> list[PricingPlan]:
    """定价档位归一：``details["plans"]``（49 命名空间），兼容旧 ``details["pricing"]["plans"]``。

    逐档走 ``parse_plan``（键兼容矩阵唯一权威）；非 list/非 dict 条目容忍跳过。
    双命名空间回退原在 timeline_memory，收敛至此一处（设计文档 88 §4.1）；
    优先级与 timeline 原实现严格一致：``pricing`` 为 dict 即取其 plans（缺省空，
    不回退顶层），否则取顶层 ``plans``。
    """
    pricing_ns = details.get("pricing")
    if isinstance(pricing_ns, dict):
        raw = pricing_ns.get("plans") or []
    else:
        raw = details.get("plans") or []
    if not isinstance(raw, list):
        return []
    return [p for p in (parse_plan(d) for d in raw) if p is not None]


def _coerce_plan_value(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {"price": str(value.get("price") or ""), "period": str(value.get("period") or "")}
    match = _PRICE_VALUE_RE.search(str(value))
    if not match:
        return {}
    return {"price": match.group(1), "period": match.group(2)}


def plan_price(details: dict[str, Any], term: str) -> str:
    """从 plans[].price/period 拼装 "$N/unit"（与 ground_truth 同命名空间）。

    benchmark ``_plan_price`` 行为等价平移：raw 键读取（不经 parse_plan 归一，
    period 原样走别名映射），plans 为 dict 形态时经 ``_coerce_plan_value`` 兜底。
    """
    plans = details.get("plans", [])
    if isinstance(plans, dict):
        plans = [{"name": str(name), **_coerce_plan_value(value)} for name, value in plans.items()]
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        name = str(plan.get("name") or "").lower()
        if term.lower() in name:
            price = str(plan.get("price") or "").strip().lstrip("$¥€")
            period_raw = str(plan.get("period") or "").lower()
            period = _PERIOD_ALIAS.get(period_raw, period_raw)
            return f"${price}/{period}" if period else f"${price}"
    return ""


def feature_list(details: dict[str, Any]) -> list[str]:
    """特性清单归一：``details["features"]`` 的字符串项（非 list/非 str 容忍跳过）。"""
    raw = details.get("features")
    if not isinstance(raw, list):
        return []
    return [str(f) for f in raw if str(f).strip()]


def feature_present(details: dict[str, Any], term: str) -> str:
    """特征存在性：term 出现在任一 features 行则 "true"，否则 "false"（防幻觉，拒绝虚构）。

    benchmark ``_feature_present`` 行为等价平移（子串匹配语义不变）。
    """
    for feature in details.get("features", []):
        if term.lower() in str(feature).lower():
            return "true"
    return "false"


def benchmark_entries(details: dict[str, Any]) -> list[dict[str, Any]]:
    """榜单条目归一：``details["benchmarks"]`` 的 dict 项（report_exporter 平移）。"""
    raw = details.get("benchmarks")
    if not isinstance(raw, list):
        return []
    return [b for b in raw if isinstance(b, dict)]


def benchmark_score(details: dict[str, Any], term: str) -> str:
    """基准分：按名匹配 benchmarks[]（兼容 mock 的 name/score 与规则层的 raw 行）。

    benchmark ``_benchmark_score`` 行为等价平移。
    """
    for benchmark in details.get("benchmarks", []):
        if not isinstance(benchmark, dict):
            continue
        name = str(benchmark.get("name") or "").lower()
        raw = str(benchmark.get("raw") or "").lower()
        if term.lower() in name or (raw and term.lower() in raw):
            if "score" in benchmark:
                return str(benchmark["score"])
            if ":" in raw:
                return raw.split(":", 1)[1].strip()
            return raw
    return ""


def ecosystem_signal(details: dict[str, Any], key: str) -> Any:
    """生态信号（设计文档 24 的 EcosystemAnalyzer details）：MCP 数量 / IDE 支持 / 插件市场。

    benchmark ``_ecosystem_signal`` 行为等价平移。
    """
    if key == "mcp_servers":
        return len(details.get("mcp_servers") or [])
    if key == "plugins":
        plugins = details.get("plugins")
        return plugins.get("count", 0) if isinstance(plugins, dict) else 0
    if key == "stars":
        activity = details.get("repo_activity")
        return activity.get("stars", 0) if isinstance(activity, dict) else 0
    if key in ("vscode", "jetbrains", "terminal"):
        ide = [str(i).lower() for i in (details.get("ide_support") or [])]
        return "true" if key in ide else "false"
    if key == "ide":
        return " ".join(str(i) for i in (details.get("ide_support") or []))
    return ""


def sentiment_signal(details: dict[str, Any], key: str) -> Any:
    """口碑信号（设计文档 24 的 SentimentAnalyzer details）：极性主导 / 正负信号有无。

    benchmark ``_sentiment_signal`` 行为等价平移。
    """
    ratio = details.get("polarity_ratio")
    if not isinstance(ratio, dict):
        ratio = {}
    if key == "polarity":
        pos = float(ratio.get("pos") or 0.0)
        neg = float(ratio.get("neg") or 0.0)
        neu = float(ratio.get("neu") or 0.0)
        if pos > neg and pos > neu:
            return "pos"
        if neg > pos and neg > neu:
            return "neg"
        return "neu"
    if key == "positive":
        return "true" if (ratio.get("pos") or 0) > 0 else "false"
    if key == "negative":
        return "true" if (ratio.get("neg") or 0) > 0 else "false"
    if key == "neutral":
        return "true" if (ratio.get("neu") or 0) > 0 else "false"
    if key in ("pos", "neg", "neu"):
        return ratio.get(key, 0.0)
    return ""


def roadmap_events(details: dict[str, Any]) -> list[dict[str, Any]]:
    """路线图事件归一：``details["events"]`` 的 dict 项（非 list/非 dict 容忍跳过）。"""
    raw = details.get("events")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


# ────────────────────────────────────────────────────────────
# 第 1 层：facts 视图（writer 唯一输入 / N2 校验基准）
# ────────────────────────────────────────────────────────────

# generic 蒸馏的浅层标量叶子上限（writer prompt 预算护栏）
_GENERIC_FACTS_CAP = 20


@dataclass(frozen=True)
class DistilledFact:
    """单条蒸馏事实：稳定查找键 + 人读标签 + 归一值（可选数值/单位/证据）。"""

    term: str  # 稳定查找键："plan:pro:monthly" / "benchmark:MMLU" / "polarity:pos"
    label: str  # 人读标签："Pro 档月价"
    value: str  # 归一文本："20"
    unit: str = ""  # "USD/month"
    numeric: float | None = None
    evidence_urls: tuple[str, ...] = ()


@dataclass
class DimensionFacts:
    """单维度蒸馏事实清单（writer 槽位 input_facts 的元素）。"""

    dimension: str
    confidence: float
    status: str
    summary: str
    facts: list[DistilledFact] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)
    # 设计文档 95：comparison 路径由 writer pass 回填候选竞品名（写入 facts payload，
    # 供横向格局 prose 说清"谁在何维度领先"）；单竞品路径留空 → payload 不含该键。
    competitor: str = ""


def _to_maybe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evidence_urls(result: DimensionResult) -> list[str]:
    return [str(e.url) for e in (result.evidence or []) if getattr(e, "url", "")]


def _distill_pricing(result: DimensionResult) -> list[DistilledFact]:
    urls = tuple(_evidence_urls(result))
    profile = profile_from_details(result.details, result.evidence or [])
    facts: list[DistilledFact] = []
    for plan in profile.plans:
        name = plan.name or plan.tier
        if plan.monthly_price_usd is not None:
            facts.append(
                DistilledFact(
                    term=f"plan:{plan.tier}:monthly",
                    label=f"{name} 档月价",
                    value=f"{plan.monthly_price_usd:g}",
                    unit="USD/month",
                    numeric=plan.monthly_price_usd,
                    evidence_urls=urls,
                )
            )
        if plan.annual_price_usd is not None:
            facts.append(
                DistilledFact(
                    term=f"plan:{plan.tier}:annual",
                    label=f"{name} 档年价",
                    value=f"{plan.annual_price_usd:g}",
                    unit="USD/year",
                    numeric=plan.annual_price_usd,
                    evidence_urls=urls,
                )
            )
        if plan.requires_quote:
            facts.append(
                DistilledFact(
                    term=f"plan:{plan.tier}:quote",
                    label=f"{name} 档定价",
                    value="需询价",
                    evidence_urls=urls,
                )
            )
    if profile.usage is not None and profile.usage.per_unit_usd is not None:
        facts.append(
            DistilledFact(
                term="usage:per_unit",
                label=f"按量计费单价（{profile.usage.unit or 'request'}）",
                value=f"{profile.usage.per_unit_usd:g}",
                unit=f"USD/{profile.usage.unit or 'request'}",
                numeric=profile.usage.per_unit_usd,
                evidence_urls=urls,
            )
        )
    for scenario, cost in profile.cost_scenarios.items():
        if cost is not None:
            facts.append(
                DistilledFact(
                    term=f"cost_scenario:{scenario}",
                    label=f"{scenario} 用量月成本估算",
                    value=f"{cost:g}",
                    unit="USD/month",
                    numeric=cost,
                    evidence_urls=urls,
                )
            )
    return facts


def _distill_feature(result: DimensionResult) -> list[DistilledFact]:
    urls = tuple(_evidence_urls(result))
    return [
        DistilledFact(term=f"feature:{i}", label=feat, value="具备", evidence_urls=urls)
        for i, feat in enumerate(feature_list(result.details))
    ]


def _distill_performance(result: DimensionResult) -> list[DistilledFact]:
    urls = tuple(_evidence_urls(result))
    facts: list[DistilledFact] = []
    for entry in benchmark_entries(result.details):
        name = str(entry.get("name") or entry.get("raw") or "").strip()
        if not name:
            continue
        score = entry.get("score")
        value = str(score) if score is not None else str(entry.get("raw") or "")
        facts.append(
            DistilledFact(
                term=f"benchmark:{name}",
                label=f"{name} 得分",
                value=value,
                unit="score",
                numeric=_to_maybe_float(score),
                evidence_urls=urls,
            )
        )
    return facts


def _distill_ecosystem(result: DimensionResult) -> list[DistilledFact]:
    urls = tuple(_evidence_urls(result))
    details = result.details
    facts: list[DistilledFact] = []
    mcp = ecosystem_signal(details, "mcp_servers")
    facts.append(
        DistilledFact(
            term="ecosystem:mcp_servers",
            label="MCP 服务器数量",
            value=str(mcp),
            unit="count",
            numeric=_to_maybe_float(mcp),
            evidence_urls=urls,
        )
    )
    plugins = ecosystem_signal(details, "plugins")
    facts.append(
        DistilledFact(
            term="ecosystem:plugins",
            label="插件市场数量",
            value=str(plugins),
            unit="count",
            numeric=_to_maybe_float(plugins),
            evidence_urls=urls,
        )
    )
    stars = ecosystem_signal(details, "stars")
    facts.append(
        DistilledFact(
            term="ecosystem:stars",
            label="仓库 stars",
            value=str(stars),
            unit="count",
            numeric=_to_maybe_float(stars),
            evidence_urls=urls,
        )
    )
    ide = ecosystem_signal(details, "ide")
    if ide:
        facts.append(
            DistilledFact(
                term="ecosystem:ide_support",
                label="IDE 支持",
                value=str(ide),
                evidence_urls=urls,
            )
        )
    return facts


def _distill_sentiment(result: DimensionResult) -> list[DistilledFact]:
    urls = tuple(_evidence_urls(result))
    details = result.details
    facts: list[DistilledFact] = []
    for key, label in (("pos", "正面占比"), ("neg", "负面占比"), ("neu", "中性占比")):
        value = _to_maybe_float(sentiment_signal(details, key))
        if value is not None:
            facts.append(
                DistilledFact(
                    term=f"polarity:{key}",
                    label=label,
                    value=f"{value:g}",
                    numeric=value,
                    evidence_urls=urls,
                )
            )
    dominant = sentiment_signal(details, "polarity")
    facts.append(
        DistilledFact(
            term="polarity:dominant",
            label="极性主导",
            value=str(dominant),
            evidence_urls=urls,
        )
    )
    return facts


def _distill_roadmap(result: DimensionResult) -> list[DistilledFact]:
    urls = tuple(_evidence_urls(result))
    facts: list[DistilledFact] = []
    for i, event in enumerate(roadmap_events(result.details)):
        label = str(event.get("title") or event.get("event") or event.get("name") or f"事件 {i + 1}")
        date = str(event.get("date") or "")
        facts.append(
            DistilledFact(
                term=f"roadmap:event:{i}",
                label=label,
                value=date or "见证据",
                evidence_urls=urls,
            )
        )
    return facts


def _distill_generic(result: DimensionResult) -> list[DistilledFact]:
    """未知维度兜底：浅层标量叶子（上限 ``_GENERIC_FACTS_CAP`` 条，prompt 预算护栏）。"""
    urls = tuple(_evidence_urls(result))
    facts: list[DistilledFact] = []
    for key, value in result.details.items():
        if len(facts) >= _GENERIC_FACTS_CAP:
            break
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        text = str(value).strip()
        if not text:
            continue
        facts.append(
            DistilledFact(
                term=str(key),
                label=str(key),
                value=text,
                numeric=_to_maybe_float(value),
                evidence_urls=urls,
            )
        )
    return facts


_DISTILLERS = {
    "pricing": _distill_pricing,
    "feature": _distill_feature,
    "performance": _distill_performance,
    "ecosystem": _distill_ecosystem,
    "sentiment": _distill_sentiment,
    "roadmap": _distill_roadmap,
}


def distill_dimension(result: DimensionResult) -> DimensionFacts:
    """DimensionResult → DimensionFacts（按维度命名空间分派，未知维度走 generic）。"""
    fn = _DISTILLERS.get(result.dimension, _distill_generic)
    status = getattr(result.status, "value", str(result.status))
    return DimensionFacts(
        dimension=result.dimension,
        confidence=float(result.confidence or 0.0),
        status=str(status),
        summary=str(result.summary or ""),
        facts=fn(result),
        evidence_urls=_evidence_urls(result),
    )


def distill_report(report: CompetitorReport) -> list[DimensionFacts]:
    """整份报告 → 各维度蒸馏事实清单（顺序 = dimension_results 序，确定性）。"""
    return [distill_dimension(r) for r in report.dimension_results]


# ────────────────────────────────────────────────────────────
# 第 2 层：查询 helper（benchmark / N2 用）
# ────────────────────────────────────────────────────────────


def fact_by_term(facts: Iterable[DistilledFact], term: str) -> DistilledFact | None:
    """按 term 查单条事实：先精确匹配，再大小写不敏感子串匹配（term/label）。"""
    pool = list(facts)
    for fact in pool:
        if fact.term == term:
            return fact
    needle = term.lower()
    for fact in pool:
        if needle in fact.term.lower() or needle in fact.label.lower():
            return fact
    return None


def numeric_allowlist(facts: Iterable[DistilledFact]) -> set[str]:
    """N2 保真校验的合法数字文本集合：每条数值事实产出 {:g} / {:.2f} / int 三形态。

    覆盖 "$20" / "20.00" / "20" 写法；单位不进 token（由 prompt 指令约束，不进 N2）。
    """
    out: set[str] = set()
    for fact in facts:
        v = fact.numeric
        if v is None:
            continue
        out.add(f"{v:g}")
        out.add(f"{v:.2f}")
        if v == int(v):
            out.add(str(int(v)))
    return out


__all__ = [
    "DimensionFacts",
    "DistilledFact",
    "benchmark_entries",
    "benchmark_score",
    "distill_dimension",
    "distill_report",
    "ecosystem_signal",
    "fact_by_term",
    "feature_list",
    "feature_present",
    "numeric_allowlist",
    "plan_price",
    "pricing_plans",
    "roadmap_events",
    "sentiment_signal",
]
