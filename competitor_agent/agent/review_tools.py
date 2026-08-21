"""复核 / 选源 / 成本工具（设计文档 49 §2 保留逻辑 → 工具化）

把 competitor_agent 独有的流程/校验脚本暴露为 Lead 可调工具：
- ``validate_facts``：数值真值核对（原 ``FactValidator`` / ``_count_numeric_conflicts`` 语义）；
- ``detect_conflict``：跨维度同源冲突检测（原 ``ConflictRegistry`` 语义，按证据 URL 键）；
- ``check_freshness``：维度新鲜度判定（原 ``FreshnessGate`` 语义，api 注入归档/时间线提供方）；
- ``select_source``：确定性选源路由（原 ``SourceSelector``，api 注入候选生成）；
- ``estimate_costs``：定价档位 → 典型用量成本估算（原 ``PricingAnalyzer`` 成本段）。

均为纯函数/闭包，注册进 Lead dispatcher（``extra_tools``）。安全兜底仍在代码：
这些工具只提供"信息"，不决定预算/取消/渲染（那些不进 LLM）。

设计文档 56 M2：``extract_verified_facts`` 从复核工具的 transcript 记录抽取
「已核验事实」行（pinning 写侧），与压缩侧的 pinned 段插入（react_agent）配对。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from competitor_agent.domain_types.pricing import (
    DAILY_SCENARIOS,
    estimate_costs,
    extract_profile,
)
from competitor_agent.domain_types.verification import _VERIFY_NUMERIC_KEYS


def extract_verified_facts(rec: dict[str, Any]) -> list[str]:
    """从复核工具的 transcript 记录抽取「已核验事实」行（设计文档 56 M2 pinning）。

    只收 ``validate_facts``/``detect_conflict`` 的核验**通过**结论；details 中的
    实体数值按 fact_verification 键空间（``_VERIFY_NUMERIC_KEYS``）抽为一行一条，
    无数值命中时保留一条结论行（核验行为本身亦是事实）。
    """
    tool = str(rec.get("tool") or "")
    brief = str(rec.get("result_brief") or "")
    args = rec.get("args")
    if not isinstance(args, dict):
        return []
    if tool == "validate_facts" and brief.startswith("真值核对通过"):
        hits = _walk_verify_numeric(_parse_json_arg(args.get("details_json")))
        return [f"{k}={v}（validate_facts 核验通过）" for k, v in hits] or [
            "details 数值均可回溯到原文证据（validate_facts 核验通过）"
        ]
    if tool == "detect_conflict" and brief.startswith("跨维度冲突检测通过"):
        hits = _walk_verify_numeric(_parse_json_arg(args.get("dimensions_json")))
        return [f"{k}={v}（detect_conflict 核验通过）" for k, v in hits] or [
            "各维度引用的同源事实值一致（detect_conflict 核验通过）"
        ]
    return []


def _parse_json_arg(value: Any) -> Any:
    """transcript args 可能是 dict/list 或 JSON 字符串（文本协议），统一解析。"""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _walk_verify_numeric(node: Any) -> list[tuple[str, Any]]:
    """按 _VERIFY_NUMERIC_KEYS 键空间遍历抽取实体数值（与 verification 同纪律：非 0）。"""
    hits: list[tuple[str, Any]] = []
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, value in cur.items():
                if (
                    key in _VERIFY_NUMERIC_KEYS
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and value != 0
                ):
                    shown = int(value) if isinstance(value, float) and value.is_integer() else value
                    hits.append((key, shown))
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(cur, list):
            stack.extend(item for item in cur if isinstance(item, (dict, list)))
    return hits


def build_validate_facts_tool() -> Callable[..., str]:
    """validate_facts(details_json, raw_text) — details 数值与原文交叉核对。"""
    from competitor_agent.domain_types.verification import count_numeric_conflicts

    def validate_facts(details_json: Any, raw_text: str = "") -> str:
        try:
            details = details_json if isinstance(details_json, dict) else json.loads(details_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return "validate_facts 参数解析失败：details_json 须是 JSON 对象"
        if not isinstance(details, dict):
            return "validate_facts 参数解析失败：details 须是 JSON 对象"
        conflicts = count_numeric_conflicts(details, raw_text)
        if conflicts == 0:
            return "真值核对通过：details 数值均可回溯到原文证据，无冲突。"
        return (
            f"真值核对发现 {conflicts} 处数值与原文不符（声称自原文却找不到），"
            "请重新抓取核验或修正 details，勿保留未证实数值。"
        )

    return validate_facts


def build_detect_conflict_tool() -> Callable[..., str]:
    """detect_conflict(dimensions_json) — 跨维度同源冲突检测（按证据 URL 键）。"""
    from competitor_agent.domain_types.conflict import detect_conflicts_across

    def detect_conflict(dimensions_json: Any) -> str:
        try:
            payloads = dimensions_json if isinstance(dimensions_json, list) else json.loads(dimensions_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return "detect_conflict 参数解析失败：dimensions_json 须是数组"
        if not isinstance(payloads, list):
            return "detect_conflict 参数解析失败：dimensions 须是数组"
        conflicts = detect_conflicts_across(payloads)
        if not conflicts:
            return "跨维度冲突检测通过：各维度引用的同源事实值一致。"
        lines = [f"- {c.summary}" for c in conflicts]
        return "跨维度冲突检测发现：\n" + "\n".join(lines) + "\n请核对修正冲突维度。".strip()

    return detect_conflict


def build_estimate_costs_tool() -> Callable[..., str]:
    """estimate_costs(plans_json) — 定价档位 → 典型用量成本估算（不编造）。"""
    def estimate_costs_tool(plans_json: Any) -> str:
        try:
            details = plans_json if isinstance(plans_json, dict) else json.loads(plans_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return "estimate_costs 参数解析失败：plans_json 须是 JSON 对象（含 plans 数组）"
        if not isinstance(details, dict):
            return "estimate_costs 参数解析失败：plans 须是 JSON 对象"
        profile = extract_profile(details)
        if not profile.has_pricing_data:
            return "estimate_costs 无定价档位数据，无法估算成本（不编造）。"
        costs = estimate_costs(profile, DAILY_SCENARIOS)
        lines = []
        for label, value in costs.items():
            lines.append(f"- {label}: " + (f"≈ ${value:g}/月" if value is not None else "需询价/无法估算"))
        return "典型用量月成本估算：\n" + "\n".join(lines)

    return estimate_costs_tool


def build_check_freshness_tool(
    freshness_provider: Callable[[str, list[str]], dict[str, str]],
) -> Callable[..., str]:
    """check_freshness(competitor, dimensions) — 维度新鲜度判定。

    ``freshness_provider(competitor, dimensions) -> {dimension: "stale"/"fresh"/"skip"}``
    由 api 注入（读归档年龄 + 时间线事件，原 FreshnessGate.decide 语义）。
    """
    def check_freshness(competitor: str, dimensions: list[str]) -> str:
        try:
            decisions = freshness_provider(str(competitor), list(dimensions or []))
        except Exception as exc:  # noqa: BLE001 — 新鲜度查询失败不阻塞
            return f"check_freshness 查询失败: {exc}"
        if not decisions:
            return "无归档新鲜度信息，各维度需正常采集。"
        lines = []
        for dim, decision in decisions.items():
            label = {"stale": "已过期需重采", "fresh": "新鲜可复用", "skip": "正常采集"}.get(decision, decision)
            lines.append(f"- {dim}: {label}")
        return "维度新鲜度判定：\n" + "\n".join(lines)

    return check_freshness


def build_select_source_tool(
    source_provider: Callable[[str, str], list[str]],
) -> Callable[..., str]:
    """select_source(competitor, dimension) — 确定性候选源（原 SourceSelector 语义）。

    ``source_provider(competitor, dimension) -> [url, ...]`` 由 api 注入
    （注册表 official_links + 候选链，代码生成确定性候选）。
    """
    def select_source(competitor: str, dimension: str) -> str:
        try:
            candidates = source_provider(str(competitor), str(dimension))
        except Exception as exc:  # noqa: BLE001 — 选源失败不阻塞
            return f"select_source 查询失败: {exc}"
        if not candidates:
            return f"未找到 {competitor} 的 {dimension} 维度候选源。"
        lines = [f"- {url}" for url in candidates]
        return f"{competitor} 的 {dimension} 维度候选源（优先顺序）：\n" + "\n".join(lines)

    return select_source
