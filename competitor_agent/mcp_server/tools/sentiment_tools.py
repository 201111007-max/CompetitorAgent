"""MCP Server — 舆情采样工具"""
from __future__ import annotations

import logging

from competitor_agent.collector.sentiment_sources import (
    SentimentError,
    _sample_meta,
    build_sentiment_provider,
)

logger = logging.getLogger("competitor_agent.mcp_server.tools.sentiment_tools")


def sentiment_sampling(competitor: str, platform: str = "hackernews") -> str:
    """采样竞品相关舆情（结构化采样源，带样本量与时间窗）。

    - 经 ``build_sentiment_provider`` 取提供方（主开关关/未配置 → None）；
    - provider 为空 → 返回可读提示（与现状一致，不抛，不编造结果）；
    - 有 provider → ``sample`` → 输出头带「平台 / 样本量 / 时间窗」元数据 +
      逐条 `标题 [URL] [时间]`（供 sentiment 维度子 Agent 读取）；
    - 采样失败（网络/非 2xx/响应异常）→ 返回可读错误文案（降级不编造，守 doc 47）。
    """
    from competitor_agent.config.loader import load_config

    try:
        provider = build_sentiment_provider(load_config().collector)
    except Exception:
        logger.warning("build_sentiment_provider 失败", exc_info=True)
        provider = None
    if provider is None:
        return (
            f"舆情采样未启用：需要 collector.enable_external_sources + sentiment_provider "
            f"（hackernews | reddit）。\n"
            f"目标: {competitor}（platform={platform}）\n"
            f"建议: 使用 web_search 泛搜索，或配置 sentiment_provider。"
        )
    try:
        samples = provider.sample(competitor, max_samples=10)
    except SentimentError as exc:
        logger.warning("sentiment_sampling(%s) 失败: %s", competitor, exc)
        return f"舆情采样失败: {exc}"
    if not samples:
        return f"未采样到与 {competitor!r} 相关的舆情。"
    meta = _sample_meta(samples)
    lines = [
        (
            f"# {competitor} 舆情采样（platform={meta['platform']} | 样本量={meta['sample_size']} "
            f"| 时间窗 {meta['start'] or '-'} ~ {meta['end'] or '-'}）"
        )
    ]
    for s in samples:
        date = str(s.posted_at)[:10] or "-"
        lines.append(f"- {s.text} [{s.source_url}] ({date})")
    return "\n".join(lines)
