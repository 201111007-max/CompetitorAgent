"""MCP Server — 综合审查工具"""
from __future__ import annotations

import logging

logger = logging.getLogger("competitor_agent.mcp_server.tools.review_tools")


def analyze_competitor(task: str) -> str:
    """综合分析一个竞品（采集→分析→报告全流程）"""
    try:
        from competitor_agent.config.loader import load_config
        from competitor_agent.domain_types.report import ChatResult
        from competitor_agent.facade.api import CompetitorAnalysisAPI
        from competitor_agent.llm.client import LLMClient

        api = CompetitorAnalysisAPI(llm=LLMClient(), use_llm=True, config=load_config())
        # 设计文档 62 §3.7：内部走统一入口 run()（单竞品/对比/普查由库内路由）
        # 设计文档 64 §5：普通提问 → ChatResult（直接返回对话答案，无报告面板）
        report = api.run(task)
        if isinstance(report, ChatResult):
            return report.answer or "⚠ 无回答"
        return report.markdown_report or "⚠ 报告为空"
    except Exception as e:  # noqa: BLE001
        logger.warning("analyze_competitor(%s) 异常: %s", task, e)
        return f"⚠ 分析异常: {e}"
