"""MCP Server — 评测基准工具"""
from __future__ import annotations

import logging
from pathlib import Path

from competitor_agent.collector.benchmark_sources import (
    BenchmarkError,
    build_benchmark_provider,
)

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


def benchmark_scores(benchmark: str = "") -> str:
    """查询结构化榜单分数（SWE-bench / Terminal-Bench / Aider 官方榜单直连）。

    - 经 ``build_benchmark_provider`` 取提供方（主开关关/未配置 → None）；
    - provider 为空 → 返回可读提示（与现状一致，不抛，不编造结果）；
    - 有 provider → ``fetch`` → 逐条格式化为 `排名 | 模型 | 分数` 文本返回
      （供 performance 维度子 Agent 读取，对齐 str 契约）；
    - 抓取失败（网络/非 2xx/解析失败）→ 返回可读错误文案（降级不编造，守 doc 47）。
    """
    from competitor_agent.config.loader import load_config

    try:
        provider = build_benchmark_provider(load_config().collector)
    except Exception:
        logger.warning("build_benchmark_provider 失败", exc_info=True)
        provider = None
    if provider is None:
        return (
            f"榜单查询未启用：需要 collector.enable_external_sources + benchmark_provider "
            f"（swebench | terminalbench | aider）。\n"
            f"请求榜单: {benchmark or '（默认）'}\n"
            f"建议: 使用 web_extract 直接采集已知榜单页，或配置 benchmark_provider。"
        )
    try:
        hits = provider.fetch(benchmark)
    except BenchmarkError as exc:
        logger.warning("benchmark_scores(%s) 失败: %s", benchmark, exc)
        return f"榜单查询失败: {exc}"
    if not hits:
        return f"榜单 {benchmark or '（默认）'} 暂无数据。"
    lines = [f"# {hits[0].benchmark} 榜单（来源: {hits[0].source_url}）"]
    for h in hits[:20]:
        rank = h.rank or "-"
        lines.append(f"- #{rank} {h.model}: {h.score}（{h.date or '日期未知'}）")
    return "\n".join(lines)
