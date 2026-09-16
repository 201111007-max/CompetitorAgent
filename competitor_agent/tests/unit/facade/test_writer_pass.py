"""设计文档 88 §4.4/§6 —— writer pass 编排与接线单测。

覆盖：prose_override 直注全链路（骨架+注入无占位残留）、单槽 LLM 异常 → 该槽注记他槽正常、
N2 首次违规重试通过 → 注入 / 两败 → 注记、N3 锚定集成、整体异常 → 保持 assemble 产物
（降级形态一）、on_skeleton 钩子、assemble 在 writer_pass=true 时忽略 Lead body、
BenchmarkMockLLM writer 标记分发。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from competitor_agent.agent.writer_slots import MOCK_SLOT_PROSE, WRITER_SYSTEM_MARKER
from competitor_agent.config.loader import AppConfig, ReportConfig
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.facade import react_report, writer_pass


def _report() -> CompetitorReport:
    return CompetitorReport(
        competitor=Competitor(name="cursor"),
        dimension_results=[
            DimensionResult(
                dimension="pricing",
                summary="Pro 档 $20/月",
                details={"plans": [{"name": "Pro", "monthly_price_usd": 20}]},
                confidence=0.8,
                status=ResultStatus.COMPLETE,
                evidence=[
                    SourceEvidence(
                        source_name="web", url="https://a.com/p", access_time="", trust_level=0.8
                    )
                ],
            ),
            DimensionResult(
                dimension="feature",
                summary="支持 MCP",
                details={"features": ["支持 MCP 协议"]},
                confidence=0.6,
                status=ResultStatus.COMPLETE,
            ),
        ],
        overall_confidence=0.7,
        terminal_state="success",
        created_at="2026-09-10T00:00:00+00:00",
        markdown_report="LEGACY",
    )


class _FakeLLM:
    """按槽位标题脚本化（值为队列：str 内容或 Exception）。"""

    def __init__(self, script: dict[str, list[Any]]) -> None:
        self._script = script
        self.calls: list[str] = []

    def complete_with_tools(self, messages: list[dict[str, Any]], tools: Any = None, **kw: Any) -> Any:
        system = str(messages[0]["content"])
        heading = next(h for h in self._script if f"「{h}」" in system)
        self.calls.append(heading)
        queue = self._script[heading]
        item = queue.pop(0) if queue else ""
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(content=item)


_CFG = ReportConfig(writer_pass=True, writer_slot_max_retries=1)


class TestProseOverride:
    def test_override_injected_no_placeholder_left(self) -> None:
        report = _report()
        writer_pass.run_writer_pass(
            report,
            llm=None,
            config=_CFG,
            prose_override={
                "executive_summary": "整体解读。",
                "dimension_insight:pricing": "定价解读含 20 美元。",
                "market_conclusion": "格局结论。",
            },
        )
        md = report.markdown_report
        assert "{{slot:" not in md
        assert "整体解读。" in md and "格局结论。" in md
        assert "#### 定价档位" in md  # 骨架表格完好
        assert "（本维度解读暂缺）" in md  # feature 槽未 override → 降级注记

    def test_on_skeleton_hook(self) -> None:
        report = _report()
        seen: list[str] = []
        writer_pass.run_writer_pass(
            report, llm=None, config=_CFG, prose_override={}, on_skeleton=seen.append
        )
        assert len(seen) == 1
        assert "{{slot:executive_summary}}" in seen[0]  # 骨架先于注入


class TestSlotDegradation:
    def test_single_slot_exception_others_survive(self) -> None:
        report = _report()
        llm = _FakeLLM(
            {
                "执行摘要": [RuntimeError("boom")],
                "pricing 维度解读": ["Pro 档 20 美元，性价比高。"],
                "feature 维度解读": ["支持 MCP 协议。"],
                "市场格局结论": ["格局稳定。"],
            }
        )
        writer_pass.run_writer_pass(report, llm=llm, config=_CFG)
        md = report.markdown_report
        assert "（本节解读暂缺）" in md  # 执行摘要槽降级
        assert "Pro 档 20 美元" in md and "格局稳定。" in md  # 他槽不受影响
        assert "{{slot:" not in md

    def test_n2_retry_then_pass(self) -> None:
        report = _report()
        llm = _FakeLLM(
            {
                "执行摘要": ["整体ok。"],
                "pricing 维度解读": ["涨价 30 美元。", "Pro 档 20 美元。"],  # 先违规后合规
                "feature 维度解读": ["支持 MCP。"],
                "市场格局结论": ["格局ok。"],
            }
        )
        writer_pass.run_writer_pass(report, llm=llm, config=_CFG)
        assert "Pro 档 20 美元。" in report.markdown_report
        assert llm.calls.count("pricing 维度解读") == 2  # N2 重试 1 次

    def test_n2_two_failures_degrade(self) -> None:
        report = _report()
        llm = _FakeLLM(
            {
                "执行摘要": ["整体ok。"],
                "pricing 维度解读": ["涨价 30 美元。", "还是 30 美元。"],  # 两败
                "feature 维度解读": ["支持 MCP。"],
                "市场格局结论": ["格局ok。"],
            }
        )
        writer_pass.run_writer_pass(report, llm=llm, config=_CFG)
        assert "（本维度解读暂缺）" in report.markdown_report
        assert "30 美元" not in report.markdown_report
        assert llm.calls.count("pricing 维度解读") == 2


class TestN3Integration:
    def test_citation_anchored_and_url_stripped(self) -> None:
        report = _report()
        writer_pass.run_writer_pass(
            report,
            llm=None,
            config=_CFG,
            prose_override={
                "dimension_insight:pricing": "官方定价 20 美元 [1]，网传 https://fake.com 不实。"
            },
        )
        md = report.markdown_report
        assert "[1](https://a.com/p)" in md
        assert "https://fake.com" not in md


class TestOverallDegradation:
    def test_overall_exception_keeps_legacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """降级形态一：writer 整体异常 → markdown_report 保持 assemble 产物不动。"""
        report = _report()
        monkeypatch.setattr(
            writer_pass, "distill_report", lambda r: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        writer_pass.maybe_run_writer_pass(report, llm=None, config=_CFG)
        assert report.markdown_report == "LEGACY"


class TestAssembleGating:
    def test_lead_body_always_ignored(self) -> None:
        """设计文档 88 步骤 7：两段式退役——Lead 散文正文不再消费（无论 writer_pass）。"""
        answer = "散文正文，不应成为报告。" + json.dumps(
            {
                "competitor": "cursor",
                "dimensions": [
                    {
                        "dimension": "pricing",
                        "summary": "Pro 档 $20/月",
                        "details": {},
                        "confidence": 0.8,
                        "evidence_urls": [],
                    }
                ],
            }
        )
        report = react_report.assemble(
            lead_answer=answer, competitor=Competitor(name="cursor"), loop_plan=None
        )
        assert report.markdown_report != "散文正文，不应成为报告。"
        assert "散文正文" not in report.markdown_report  # 模板渲染，body 已退役


class TestBenchmarkMockDispatch:
    def test_writer_marker_returns_fixed_prose(self) -> None:
        from competitor_agent.evaluation.benchmark import BenchmarkMockLLM

        mock = BenchmarkMockLLM(competitor="x", dimension="pricing")
        out = mock.complete(
            [
                {"role": "system", "content": f"{WRITER_SYSTEM_MARKER}。你在撰写「执行摘要」。"},
                {"role": "user", "content": "..."},
            ]
        )
        assert out == MOCK_SLOT_PROSE


class TestSkeletonEvent:
    """设计文档 88 §2.1 —— report_skeleton SSE 事件接线（commit G）。"""

    def test_skeleton_event_precedes_report_event(self, mock_llm: Any, fake_extractor: Any) -> None:
        from competitor_agent.config.loader import CollectorConfig
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
        cfg.report.writer_pass = True
        events: list[Any] = []
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            config=cfg,
            event_sink=events.append,
        )
        report = api.analyze("分析 Cursor")
        kinds = [e.event for e in events]
        assert "report_skeleton" in kinds
        assert kinds.index("report_skeleton") < kinds.index("report")
        skeleton_evt = next(e for e in events if e.event == "report_skeleton")
        assert skeleton_evt.phase == "writer"
        assert "{{slot:executive_summary}}" in skeleton_evt.payload["skeleton"]  # 骨架先于注入
        assert "{{slot:" not in report.markdown_report  # 终稿已注入
        assert MOCK_SLOT_PROSE in report.markdown_report  # mock 槽 prose 确定性注入

    def test_no_skeleton_event_when_writer_off(self, mock_llm: Any, fake_extractor: Any) -> None:
        from competitor_agent.config.loader import CollectorConfig
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
        events: list[Any] = []
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            config=cfg,
            event_sink=events.append,
        )
        api.analyze("分析 Cursor")
        assert "report_skeleton" not in [e.event for e in events]
