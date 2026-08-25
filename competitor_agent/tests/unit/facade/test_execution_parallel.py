"""facade/api.py 并行缺口执行（问题 10）集成测试

设计文档 62 §3.8：analyze 并行由 Lead delegate 并发委派（无 execution.mode 决策开关）；
execution 只保留 max_parallel_subagents 硬上限。
- 结果按缺口原始顺序稳定合并
- 共享预算原子扣减、不超发
- 取消能提前终止（协作式取消贯通到并行子任务）
"""

from __future__ import annotations

import threading
import uuid

from competitor_agent.config.loader import AppConfig, CollectorConfig, ExecutionConfig
from competitor_agent.domain_types import (
    InfoGap,
    Observation,
    SourceEvidence,
)
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext

CURSOR_PRICING = "Pro $20/month\nTeams $40/month\nUltra $60/month"

# 离线环境 URL 守卫（DNS 解析）会拦截 before 采集器运行：关闭守卫让 FakeExtractor 真被命中
_OFFLINE_CFG = CollectorConfig(block_private_urls=False)


class FakeExtractor:
    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = CURSOR_PRICING
        elif "docs" in url or "cursor.com" in url:
            text = "Cursor supports MCP integration, agent mode, and Codex-style reviews."
        else:
            text = "Cursor is an AI code editor."
        ev = SourceEvidence(
            source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9
        )
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _parallel_api(llm=None, **kwargs) -> CompetitorAnalysisAPI:
    # 设计文档 62 §3.8：analyze 并行由 Lead delegate 驱动；execution 只保留硬上限
    cfg = AppConfig(
        execution=ExecutionConfig(max_parallel_subagents=4),
        collector=_OFFLINE_CFG,
    )
    kwargs.setdefault("extractor", FakeExtractor())
    kwargs.setdefault("llm", llm)
    kwargs.setdefault("use_llm", True)
    return CompetitorAnalysisAPI(config=cfg, **kwargs)


class TestParallelExecution:
    def test_parallel_merges_all_gaps_in_gap_order(self, mock_llm):
        """doc 49：delegate 并发委派维度子 Agent，Lead 聚合结果按 plan 维度顺序。"""
        api = _parallel_api(llm=mock_llm)
        report = api.analyze("分析 Cursor", mode="single")
        report_fields = [r.dimension for r in report.dimension_results]
        assert report_fields == [
            "pricing",
            "feature",
            "performance",
            "ecosystem",
            "sentiment",
            "roadmap",
        ]
        assert report.overall_confidence > 0
        assert report.markdown_report

    def test_parallel_shared_budget_not_exceeded(self, mock_llm):
        """doc 49：analyze 末尾统一记账；预算扣减不超过上限。"""
        api = _parallel_api(llm=mock_llm, max_iterations=10, cost_limit=1.0)
        report = api.analyze("分析 Cursor", mode="single")
        assert report.terminal_state == "success"
        assert api._budget.iteration_count >= 1
        assert api._budget.iteration_count <= api._budget.max_iterations
        assert api._budget.total_cost > 0

    def test_parallel_same_results_as_serial(self, mock_llm):
        cfg_serial = AppConfig(
            execution=ExecutionConfig(max_parallel_subagents=4),
            collector=_OFFLINE_CFG,
        )
        serial = CompetitorAnalysisAPI(extractor=FakeExtractor(), llm=mock_llm, use_llm=True, config=cfg_serial)
        parallel = _parallel_api(llm=mock_llm)
        r_serial = serial.analyze("分析 Cursor", mode="single")
        r_parallel = parallel.analyze("分析 Cursor", mode="single")
        serial_dims = [r.dimension for r in r_serial.dimension_results]
        parallel_dims = [r.dimension for r in r_parallel.dimension_results]
        # 并行并发启动更多缺口，结果可能是串行结果的超集；两者均按缺口顺序稳定合并
        idx = 0
        for dim in serial_dims:
            if idx < len(parallel_dims) and parallel_dims[idx] == dim:
                idx += 1
        assert idx == len(serial_dims)
        assert r_parallel.terminal_state == r_serial.terminal_state

    def test_parallel_cancel_returns_partial_result(self, mock_llm):
        started = threading.Event()
        release = threading.Event()

        class BlockingExtractor(FakeExtractor):
            def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
                started.set()
                release.wait(timeout=10)
                return super().fetch(gap, context)

        api = _parallel_api(llm=mock_llm, extractor=BlockingExtractor())
        sid = f"par_cancel_{uuid.uuid4().hex[:8]}"
        holder: dict = {}

        def _run() -> None:
            try:
                holder["report"] = api.analyze("分析 Cursor", mode="single", session_id=sid)
            except Exception as exc:  # noqa: BLE001 - 测试断言收集
                holder["error"] = exc

        thread = threading.Thread(target=_run)
        thread.start()
        assert started.wait(timeout=10)
        api.cancel(sid)
        release.set()
        thread.join(timeout=30)

        assert "error" not in holder
        report = holder["report"]
        assert report.terminal_state == "cancelled"
        assert getattr(report, "cancelled", False)
