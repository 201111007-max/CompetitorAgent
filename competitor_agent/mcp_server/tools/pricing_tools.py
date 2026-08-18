"""MCP Server — 定价分析工具"""
from __future__ import annotations

import logging

logger = logging.getLogger("competitor_agent.mcp_server.tools.pricing_tools")


def analyze_pricing(competitor: str, url: str = "") -> str:
    """分析竞品定价信息（设计文档 49：去 SourceSelector，registry 查官方定价页 + 直抓）"""
    from competitor_agent.collector.web_extractor import WebExtractor
    from competitor_agent.core.competitor_registry import resolve_competitor
    from competitor_agent.domain_types.info_gap import InfoGap
    from competitor_agent.interfaces.context import SourceContext

    extractor = WebExtractor()
    gap = InfoGap(field="pricing", priority=10)

    # 无显式 URL：从注册表查官方定价页/官网兜底（确定性候选，代码生成不进 LLM）
    if not url:
        try:
            comp = resolve_competitor(competitor)
            links = comp.official_links or {}
        except ValueError:
            links = {}
        url = links.get("pricing") or links.get("home") or ""

    if not url:
        return f"⚠ 未能定位 {competitor} 的定价页（无官方定价链接），请显式提供 url"

    context = SourceContext(competitor_name=competitor, kwargs={"url": url})
    obs = extractor.fetch(gap, context)
    if obs.status.value == "ok":
        return f"## {competitor} 定价信息\n\n{obs.raw_text[:3000]}"
    return f"⚠ 未能获取 {competitor} 的定价信息"
