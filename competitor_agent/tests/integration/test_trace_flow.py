"""集成测试 — analyze() 真实链路产出链路追踪（设计文档 54 三档 span + 跨线程子 Agent）

用 mock LLM + FakeExtractor 跑 Lead 编排（make_plan → delegate → 子 Agent 调工具 →
report），断言：
- trace 根记录存在且聚合 cost/token；
- 三档 span 齐全：llm.call（generation）/ tool.*（web_extract/delegate）/ subagent；
- span 树无孤儿：每个非根 span 的 parent 都能在 trace 内找到（跨线程挂接正确）；
- 落盘 JSONL 可被 render_waterfall 重建为含三档的瀑布图。
"""
from __future__ import annotations

import pytest

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability import tracer as T

pytestmark = pytest.mark.integration

_OFFLINE_CFG = AppConfig(collector=CollectorConfig(block_private_urls=False))


class TestTraceFlow:
    def test_analyze_produces_three_tier_spans(
        self, fake_extractor, mock_llm, tmp_path
    ) -> None:
        traces = tmp_path / "traces"
        t = T.Tracer(sinks=[T.JsonlSink(traces)])
        llm = LLMClient(call_func=BenchmarkMockLLM().complete, tracer=t)
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=llm, use_llm=True, config=_OFFLINE_CFG,
            tracer=t,
        )
        report = api.analyze("分析 Cursor", session_id="sess_trace_flow")

        records = T.load_trace("sess_trace_flow", traces)
        assert records, "analyze 应产出 trace 记录"
        kinds = {r.get("kind") for r in records}
        # 三档 + 根全部落盘
        assert "trace" in kinds
        assert "llm" in kinds, "应含 llm.call generation span"
        assert "tool" in kinds, "应含 tool.call span（web_extract/delegate）"
        assert "subagent" in kinds, "应含子 Agent span（delegate 跨线程挂接）"

        # span 树无孤儿：每个非根 span 的 parent 都能在 trace 内找到
        ids = {r.get("span_id") for r in records}
        for r in records:
            if r.get("parent_span_id"):
                assert r["parent_span_id"] in ids, f"孤儿 span: {r['name']} parent={r['parent_span_id']}"

        # 聚合字段：cost/token 非负且已并入根
        root = next(r for r in records if r["kind"] == "trace")
        assert isinstance(root.get("total_tokens"), int)
        assert root["total_cost_usd"] >= 0

        # 报告正常完成
        assert report.terminal_state == "success"

    def test_waterfall_renders_three_tier(self, fake_extractor, mock_llm, tmp_path) -> None:
        traces = tmp_path / "traces"
        t = T.Tracer(sinks=[T.JsonlSink(traces)])
        llm = LLMClient(call_func=BenchmarkMockLLM().complete, tracer=t)
        CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=llm, use_llm=True, config=_OFFLINE_CFG,
            tracer=t,
        ).analyze("分析 Cursor", session_id="sess_trace_wf")
        text = T.render_waterfall(T.load_trace("sess_trace_wf", traces))
        assert "analyze" in text
        assert "delegate" in text
        assert "llm.call" in text

    def test_unconfigured_env_still_runs(self, fake_extractor, mock_llm) -> None:
        """未注入 tracer（走模块单例 + 默认 JsonlSink）时 analyze 仍正常，不炸。"""
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor")
        assert report.terminal_state == "success"