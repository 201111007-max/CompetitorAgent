"""MCP Server — 综合审查工具"""
from __future__ import annotations

import logging

logger = logging.getLogger("competitor_agent.mcp_server.tools.review_tools")


def analyze_competitor(task: str) -> str:
    """综合分析一个竞品（采集→分析→报告全流程）"""
    try:
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        api = CompetitorAnalysisAPI(use_llm=False)
        report = api.analyze(task)
        return report.markdown_report or "⚠ 报告为空"
    except Exception as e:  # noqa: BLE001
        logger.warning("analyze_competitor(%s) 异常: %s", task, e)
        return f"⚠ 分析异常: {e}"
