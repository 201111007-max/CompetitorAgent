"""历史维度结果复用工具（设计文档 70 M3）— 精确层：未过期维度直接复用，不重跑

目标：历史报告作为知识库的核心价值之一——规划后、委派前，按 ``target × dimension``
查历史导出 JSON（``<output>/<竞品>.json``，``report_exporter.export_competitor_json``
产物，含 ``created_at`` + ``dimensions[{field, confidence, summary, evidence}]``），
命中且**未过期**（freshness TTL 内）→ 返回该维度结果供 Lead/子 Agent 直接使用；
过期/缺失 → 不返回（Lead 照常采集最新信息）。语义层（全文语义检索注入）由现有
RAG + ``kb_recall`` 承担，不在本工具范围。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("competitor_agent.core.reuse_dimensions")

# 未知维度默认 TTL（天）：未在配置 freshness.dimension_ttl_days 中的维度用保守值
_DEFAULT_TTL_DAYS = 7
# 单个维度返回的 evidence URL 上限（防 Observation 过长）
_MAX_EVIDENCE = 3


def _parse_created(created_at: Any) -> datetime | None:
    """created_at → aware datetime；解析失败返回 None（按不可复用处理）。"""
    if created_at is None:
        return None
    if isinstance(created_at, datetime):
        return created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    try:
        ts = str(created_at).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def reuse_dimension_results(target: str, dimensions: list[str]) -> str:
    """复用指定竞品未过期的历史维度结果（设计文档 70 M3）。

    读取 ``<output>/<target>.json``（若存在），按 ``created_at`` + freshness TTL
    判定每个请求维度是否新鲜；新鲜的维度以结构化文本返回（带 ``as_of`` 日期与证据），
    过期/缺失的维度不返回。全部不可复用 → 可读提示，Lead 自行采集。
    """
    from competitor_agent.config.loader import load_config
    from competitor_agent.core.report_archiver import _safe_filename, resolve_output_dir

    target = str(target or "").strip()
    dims = [str(d).strip() for d in (dimensions or []) if str(d).strip()]
    if not target:
        return "reuse_dimension_results 参数缺失：target（竞品规范名）"
    path = resolve_output_dir() / (_safe_filename(target) + ".json")
    if not path.exists():
        return f"无历史维度结果可复用（未找到 {target} 的历史报告），请自行采集所需维度。"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("历史维度 JSON 损坏，无法复用: %s", path)
        return f"历史维度结果读取失败（{target}），请自行采集。"
    if not isinstance(data, dict):
        return f"历史维度结果格式异常（{target}），请自行采集。"

    created = _parse_created(data.get("created_at"))
    as_of = created.date().isoformat() if created else ""
    ttl = dict(load_config().freshness.dimension_ttl_days)
    by_field = {str(d.get("field") or ""): d for d in (data.get("dimensions") or []) if isinstance(d, dict)}

    reusable: list[str] = []
    stale: list[str] = []
    for dim in dims:
        item = by_field.get(dim)
        if item is None or created is None:
            stale.append(dim)
            continue
        ttl_days = ttl.get(dim, _DEFAULT_TTL_DAYS)
        age = (datetime.now(timezone.utc) - created).total_seconds() / 86400.0
        if age > ttl_days:
            stale.append(dim)
            continue
        summary = str(item.get("summary") or "").strip() or "（无摘要）"
        conf = float(item.get("confidence") or 0.0)
        urls = [str(e.get("url") or "") for e in (item.get("evidence") or []) if isinstance(e, dict)]
        urls = [u for u in urls if u][:_MAX_EVIDENCE]
        line = f"- **{dim}**（置信度 {conf:.2f}，as_of {as_of}）: {summary}"
        if urls:
            line += "  证据: " + "；".join(urls)
        reusable.append(line)

    if not reusable:
        return (
            f"无未过期的历史维度可复用（{target}：{'；'.join(stale) or '无请求维度'} 已过期/缺失）。"
            "请自行采集最新信息。"
        )
    out = [f"以下历史维度结果未过期，可直接复用（as_of {as_of}，过期维度已剔除）:"]
    out.extend(reusable)
    if stale:
        out.append(f"（已剔除过期/缺失维度: {'；'.join(stale)}——请采集最新信息）")
    return "\n".join(out)


__all__ = ["reuse_dimension_results"]
