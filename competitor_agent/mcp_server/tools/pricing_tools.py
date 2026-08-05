"""MCP Server — 定价分析工具"""
from __future__ import annotations

import logging

logger = logging.getLogger("competitor_agent.mcp_server.tools.pricing_tools")


def analyze_pricing(competitor: str, url: str = "") -> str:
    """分析竞品定价信息"""
    from competitor_agent.collector.source_selector import SourceSelector
    from competitor_agent.collector.web_extractor import WebExtractor
    from competitor_agent.domain_types.competitor import Competitor
    from competitor_agent.domain_types.info_gap import InfoGap
    from competitor_agent.interfaces.context import SourceContext

    selector = SourceSelector()
    extractor = WebExtractor()

    competitor_obj = Competitor(name=competitor)
    gap = InfoGap(field="pricing", priority=10)

    if url:
        context = SourceContext(competitor_name=competitor, kwargs={"url": url})
    else:
        context = selector.select(gap, competitor_obj)

    obs = extractor.fetch(gap, context)
    if obs.status.value == "ok":
        return f"## {competitor} 定价信息\n\n{obs.raw_text[:3000]}"
    return f"⚠ 未能获取 {competitor} 的定价信息"
