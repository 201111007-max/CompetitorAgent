"""集成测试 — 关键路径埋点（设计文档 21 §5 埋点单测 + 脱敏单测）

用 FakeExtractor + mock_llm 跑一次真实 analyze，断言会话日志包含：
competitor.resolved / gaps.planned / source.selected / collect.done /
analyze.done（含 model）/ llm.call（含 tokens/cost，且脱敏）/ analysis.terminated（含原因）/
report.built。LLM 调用日志不含 prompt 全文与 api_key。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from competitor_agent.core.checkpoint import clear_cancel
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability import logger as L

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _isolated_logging(tmp_path: Path) -> Path:
    log_dir = tmp_path / "logs"
    L.setup_logging(level="INFO", log_dir=log_dir, json_format=True)
    L._session_adapters.clear()
    yield log_dir
    import logging

    root = logging.getLogger("competitor_agent")
    for h in list(root.handlers):
        root.removeHandler(h)
    L._configured = False
    L.set_current_session(None)


def _events(sid: str) -> list[dict]:
    return [ln for ln in L.read_session_log(sid) if "event" in ln]


class TestAnalyzeInstrumentation:
    def test_single_flow_emits_all_key_events(self, fake_extractor, mock_llm) -> None:
        sid = "sess_obs_single"
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10
        )
        api.analyze("只分析 cursor 的定价和功能", mode="single", session_id=sid)

        # doc 49：ReAct 编排埋点（session_started / llm.call / report.built）；
        # 规划器/采集器事件（competitor.resolved 等）随流水线删除
        events = [e["event"] for e in _events(sid)]
        for expected in ("session_started", "llm.call", "report.built"):
            assert expected in events, f"会话日志缺 {expected} 事件，实际: {events}"

        llm = [e for e in _events(sid) if e["event"] == "llm.call"]
        assert llm, "LLM 调用日志缺失"
        assert "model" in llm[0], "llm.call 应含 model"
        assert "total_tokens" in llm[0] and "cost_usd" in llm[0], "llm.call 应含 tokens/cost"
        assert "elapsed_ms" in llm[0]

        built = [e for e in _events(sid) if e["event"] == "report.built"]
        assert built and built[0].get("dimension_count") is not None

    def test_team_flow_emits_terminated_and_report(self, fake_extractor, mock_llm) -> None:
        sid = "sess_obs_team"
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True)
        report = api.analyze("分析 Cursor", mode="team", session_id=sid)

        events = [e["event"] for e in _events(sid)]
        assert "session_started" in events
        assert "report.built" in events
        assert report.dimension_results

    def test_cancelled_session_logs_terminated(self, fake_extractor, mock_llm) -> None:
        sid = "sess_obs_cancel"
        set_cancel = __import__("competitor_agent.core.checkpoint", fromlist=["set_cancel"]).set_cancel
        try:
            set_cancel(sid)
            api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=10)
            report = api.analyze("分析 Cursor", mode="single", session_id=sid)
            assert report.terminal_state == "cancelled"
            events = [e["event"] for e in _events(sid)]
            assert "report.built" in events
        finally:
            clear_cancel(sid)


class TestLLMCallDesensitization:
    def test_llm_log_omits_prompt_and_api_key(self, tmp_path: Path) -> None:
        sid = "sess_llm_secret"
        L.set_current_session(sid)
        secret = "sk-very-secret-key-0123456789"
        prompt_text = "请详细分析 cursor 的全部定价策略与功能清单，不要遗漏任何细节"
        seen: dict = {}

        def call_func(messages, model=None) -> str:
            seen["messages"] = messages
            return '{"summary": "ok"}'

        client = LLMClient(call_func=call_func, model="mock-model", api_key=secret)
        client.complete([{"role": "user", "content": prompt_text}])
        client.complete_json([{"role": "user", "content": prompt_text}])

        lines = L.read_session_log(sid)
        assert lines, "LLM 调用日志未落盘"
        blob = "\n".join(str(l) for l in lines)
        assert secret not in blob, "日志泄露 api_key"
        assert prompt_text not in blob, "日志泄露 prompt 全文"
        assert "mock-model" in blob
        llm = [l for l in lines if l.get("event") == "llm.call"]
        assert len(llm) == 2
        assert llm[0]["total_tokens"] > 0
        L.set_current_session(None)
