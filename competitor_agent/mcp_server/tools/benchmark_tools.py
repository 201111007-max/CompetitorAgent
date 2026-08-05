"""MCP Server — 评测基准工具"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("competitor_agent.mcp_server.tools.benchmark_tools")


def run_benchmark() -> str:
    """运行竞品分析评测基准"""
    try:
        from competitor_agent.evaluation.benchmark import Benchmark

        fixtures_dir = Path(__file__).parent.parent.parent / "tests" / "evaluation" / "fixtures"
        bm = Benchmark(fixtures_dir=fixtures_dir)
        report = bm.run()
        return (
            f"## 评测结果\n\n"
            f"- 字段准确率: {report.accuracy.field_accuracy:.2%}\n"
            f"- 幻觉率: {report.accuracy.hallucination_rate:.2%}\n"
            f"- 工具选择准确率: {report.strategy.tool_selection_accuracy:.2%}\n"
            f"- 用例数: {report.n_cases}\n"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("run_benchmark 异常: %s", e)
        return f"⚠ 评测运行异常: {e}"
