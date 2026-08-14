"""集成测试 — TeamOrchestrator.run_async 真异步并行编排（设计文档 33）

- run_async 产出报告与同步 run() 串行语义一致（维度/证据 URL）
- Collector 总线驱动 + Analyzer 按缺口并行（慢 LLM 下并行显著快于串行）
- Validator 仲裁 + 报告标注
- 取消贯穿 async 各 await 边界
- CompetitorAnalysisAPI.analyze_team_async 端到端
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest

from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient
from competitor_agent.team.orchestrator import TeamOrchestrator
from competitor_agent.team.reporter_agent import ReporterAgent
from competitor_agent.team.validator_agent import FactValidator, ValidationResult

pytestmark = pytest.mark.integration


class SlowLLM:
    """确定性慢 LLM：模拟真实模型延迟，用于并行提速断言"""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def complete(self, messages, model=None) -> str:
        time.sleep(self._delay)
        return BenchmarkMockLLM().complete(messages)


def _slow_llm_client(delay: float) -> LLMClient:
    return LLMClient(call_func=SlowLLM(delay).complete)


class TestRunAsync:
    def test_run_async_produces_complete_report(self, fake_extractor) -> None:
        orch = TeamOrchestrator(extractor=fake_extractor, use_llm=False)
        report = asyncio.run(orch.run_async("分析 Cursor"))
        assert report.competitor.name == "cursor"
        assert report.dimension_results
        assert report.terminal_state == "success"
        assert "## 维度结论" in report.markdown_report
        assert orch.bus.history("draft")

    def test_run_async_matches_serial_results(self, fake_extractor) -> None:
        serial = TeamOrchestrator(extractor=fake_extractor, use_llm=False)
        parallel = TeamOrchestrator(extractor=fake_extractor, use_llm=False)
        r_serial = serial.run("分析 Cursor")
        r_async = asyncio.run(parallel.run_async("分析 Cursor"))

        def _fields(report) -> list[str]:
            return [r.dimension for r in report.dimension_results]

        assert _fields(r_async) == _fields(r_serial)
        # 证据 URL 一致（并行不改变证据来源）
        ser_ev = {r.dimension: [e.url for e in r.evidence] for r in r_serial.dimension_results}
        par_ev = {r.dimension: [e.url for e in r.evidence] for r in r_async.dimension_results}
        assert par_ev == ser_ev
        assert r_async.terminal_state == r_serial.terminal_state

    def test_parallel_analyzer_faster_than_serial(self, fake_extractor) -> None:
        """慢 LLM（3 个维度各 0.15s）：并行应显著快于串行"""
        serial = TeamOrchestrator(extractor=fake_extractor, llm=_slow_llm_client(0.15), use_llm=True)
        parallel = TeamOrchestrator(
            extractor=fake_extractor, llm=_slow_llm_client(0.15), use_llm=True, max_parallel=3
        )

        start = time.monotonic()
        serial.run("分析 Cursor 的定价、功能与口碑")
        serial_elapsed = time.monotonic() - start

        start = time.monotonic()
        asyncio.run(parallel.run_async("分析 Cursor 的定价、功能与口碑"))
        parallel_elapsed = time.monotonic() - start

        assert parallel_elapsed < serial_elapsed, f"并行 {parallel_elapsed:.2f}s 应快于串行 {serial_elapsed:.2f}s"

    def test_api_analyze_team_async_end_to_end(self, fake_extractor) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False, enable_rag=False)
        report = asyncio.run(api.analyze_team_async("分析 Cursor"))
        assert report.dimension_results
        assert report.terminal_state == "success"
        for result in report.dimension_results:
            assert result.evidence and all(e.url.startswith("https://") for e in result.evidence)


class TestArbitrationChain:
    def test_arbitration_annotated_in_report(self, fake_extractor) -> None:
        """仲裁 → 报告标注链路：同维度多来源取优并保留 conflict_evidence"""
        winner = DimensionResult(
            dimension="pricing",
            summary="官方 Pro $20/month",
            confidence=0.9,
            evidence=[SourceEvidence(source_name="official", url="https://cursor.com/pricing", trust_level=0.9)],
        )
        loser = DimensionResult(
            dimension="pricing",
            summary="第三方称 Pro $30/month",
            confidence=0.4,
            evidence=[SourceEvidence(source_name="rumor", url="https://rumor.io/p", trust_level=0.3)],
        )

        orch = TeamOrchestrator(extractor=fake_extractor, use_llm=False)
        arbitrated = orch._validator.arbitrate([loser, winner])
        assert arbitrated["pricing"] is winner
        assert winner.conflict_evidence

        reporter = ReporterAgent(orch.bus)
        report = reporter.draft(
            competitor=_cursor_competitor(),
            results=list(arbitrated.values()),
            validation=ValidationResult(passed=True, issues=[]),
        )
        assert "## 多来源仲裁备注" in report.markdown_report
        assert "第三方称 Pro" in report.markdown_report


class TestRunAsyncCancellation:
    def test_async_cancel_returns_cancelled_result(self, fake_extractor) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockingExtractor:
            source_name = "web_extractor"

            def fetch(self, gap, context) -> object:
                from competitor_agent.domain_types.observation import Observation

                started.set()
                release.wait(timeout=10)
                return fake_extractor.fetch(gap, context)

        sid = f"async_cancel_{uuid.uuid4().hex[:8]}"
        api = CompetitorAnalysisAPI(extractor=BlockingExtractor(), use_llm=False, enable_rag=False)
        holder: dict = {}

        def _run() -> None:
            try:
                holder["report"] = asyncio.run(api.analyze_team_async("分析 Cursor", session_id=sid))
            except Exception as exc:  # noqa: BLE001
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

    def test_run_async_cancel_returns_degraded_without_error(self, fake_extractor) -> None:
        """TeamOrchestrator 层取消：返回部分结果（内部 degraded，facade 层转 cancelled）"""
        started = threading.Event()
        release = threading.Event()

        class BlockingExtractor:
            def fetch(self, gap, context):
                started.set()
                release.wait(timeout=10)
                return fake_extractor.fetch(gap, context)

        sid = f"async_cancel2_{uuid.uuid4().hex[:8]}"
        orch = TeamOrchestrator(extractor=BlockingExtractor(), use_llm=False, session_id=sid)
        holder: dict = {}

        def _run() -> None:
            try:
                holder["report"] = asyncio.run(orch.run_async("分析 Cursor"))
            except Exception as exc:  # noqa: BLE001
                holder["error"] = exc

        thread = threading.Thread(target=_run)
        thread.start()
        assert started.wait(timeout=10)
        orch.cancel(sid)
        release.set()
        thread.join(timeout=30)

        assert "error" not in holder
        assert holder["report"].dimension_results is not None


def _cursor_competitor():
    from competitor_agent.domain_types.competitor import Competitor

    return Competitor(name="cursor", official_links={"pricing": "https://www.cursor.com/pricing"})
