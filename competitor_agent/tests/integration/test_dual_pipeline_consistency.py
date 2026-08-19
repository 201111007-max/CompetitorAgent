"""问题 20 统一流水线行为测试（设计文档 18 §5 / 49 迁移）

设计文档 49 后 single/team 收敛为单一 ReAct 编排（mode 废弃），保留统一语义验证：
- 取消后保留 checkpoint，resume() 可从断点续跑；
- 完成后清理 checkpoint（成功路径不留残留）；
- 预算耗尽提前终止（同一 BudgetController，终态 partial）；
- 分析沉淀记忆（skills / source_success_rates 写入）。
"""
from __future__ import annotations

import threading
import uuid

import pytest

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.core.checkpoint import (
    clear_cancel,
    load_checkpoint,
)
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.memory import FourLayerMemory
from competitor_agent.observability import logger as L

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _isolated_logging(tmp_path) -> None:
    import logging
    from pathlib import Path

    L.setup_logging(level="INFO", log_dir=tmp_path / "logs", json_format=True)
    L._session_adapters.clear()
    yield
    root = logging.getLogger("competitor_agent")
    for h in list(root.handlers):
        root.removeHandler(h)
    L._configured = False
    L.set_current_session(None)


def _new_sid() -> str:
    return f"sess_dual_{uuid.uuid4().hex[:8]}"


class TestCancelResume:
    def test_cancel_keeps_checkpoint_and_resumes(self, fake_extractor, mock_llm) -> None:
        """取消后保留 checkpoint，resume 能从断点续跑（设计文档 14 承诺）。"""
        started = threading.Event()
        release = threading.Event()

        class BlockingExtractor:
            def fetch(self, gap, context):
                started.set()
                release.wait(timeout=10)
                return fake_extractor.fetch(gap, context)

        cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
        api = CompetitorAnalysisAPI(extractor=BlockingExtractor(), llm=mock_llm, use_llm=True, max_iterations=10, config=cfg)
        sid = _new_sid()
        holder: dict = {}

        def _run() -> None:
            try:
                holder["report"] = api.analyze("分析 Cursor", mode="single", session_id=sid)
            except Exception as exc:  # noqa: BLE001
                holder["error"] = exc

        thread = threading.Thread(target=_run)
        thread.start()
        assert started.wait(timeout=10)
        api.cancel(sid)
        release.set()
        thread.join(timeout=30)

        assert "error" not in holder
        cancelled = holder["report"]
        assert cancelled.terminal_state == "cancelled"
        assert getattr(cancelled, "cancelled", False), "取消应返回 CancelledResult"
        assert load_checkpoint(sid) is not None, "取消后应保留 checkpoint 供 resume"

        clear_cancel(sid)
        resumed = api.resume(sid)
        assert resumed.dimension_results, "resume 应恢复维度结果"
        assert resumed.competitor.name == "cursor"

        with pytest.raises(ValueError):
            api.resume(sid)

    def test_completion_deletes_checkpoint(self, fake_extractor, mock_llm) -> None:
        """正常完成后清理 checkpoint（不留残留）。"""
        sid = _new_sid()
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True)
        report = api.analyze("分析 Cursor", mode="single", session_id=sid)
        assert report.terminal_state == "success"
        assert load_checkpoint(sid) is None, "完成后应删除 checkpoint"


class TestBudgetConsistency:
    def test_budget_exhaustion_terminates_early(self, fake_extractor, mock_llm) -> None:
        """预算耗尽时提前终止（同一 BudgetController，终态 partial）。"""
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, max_iterations=0)
        report = api.analyze("分析 Cursor", mode="single")
        assert report.terminal_state == "partial", "预算耗尽应标记 partial"


class TestMemoryConsistency:
    def test_analysis_sediments_memory(self, fake_extractor, tmp_path, mock_llm) -> None:
        """分析沉淀 skills 与 source_success_rates（记忆闭环）。"""
        m1 = FourLayerMemory(tmp_path / "m1")
        api1 = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, memory=m1)
        api1.analyze("分析 Cursor", mode="single")

        assert m1.retrieve_skills("cursor"), "应沉淀技能"
        assert m1.source_success_rates(), "应记录源成功率"
