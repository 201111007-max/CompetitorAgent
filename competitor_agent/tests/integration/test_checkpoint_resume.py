"""集成测试 — checkpoint 断点续跑：中断 → resume 恢复

对齐设计文档 11 §3.1（承接问题 4 / 9）：
- 慢速分析中取消 → 返回 CancelledResult（已完成维度保留）
- 取消时 checkpoint 保留 → resume(sid) 从断点恢复报告
- resume 成功即消费 checkpoint，二次 resume 抛 ValueError
"""

from __future__ import annotations

import threading
import uuid

import pytest

from competitor_agent.facade.api import CompetitorAnalysisAPI

pytestmark = pytest.mark.integration


class TestCheckpointResume:
    def test_cancel_then_resume_restores_session(self, fake_extractor) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockingExtractor:
            def fetch(self, gap, context):
                started.set()
                release.wait(timeout=10)
                return fake_extractor.fetch(gap, context)

        api = CompetitorAnalysisAPI(extractor=BlockingExtractor(), use_llm=False, max_iterations=10)
        sid = f"sess_res_{uuid.uuid4().hex[:8]}"
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
        cancelled = holder["report"]
        assert cancelled.terminal_state == "cancelled"
        assert getattr(cancelled, "cancelled", False), "取消应返回 CancelledResult"

        # 断点续跑：从 checkpoint 恢复已完成维度的部分结果
        resumed = api.resume(sid)
        assert resumed.dimension_results, "resume 应恢复已完成的维度结果"
        assert resumed.competitor.name == "cursor"

        # checkpoint 已被消费：二次 resume 应报错
        with pytest.raises(ValueError):
            api.resume(sid)

    def test_resume_missing_session_raises(self, fake_extractor) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False)
        with pytest.raises(ValueError):
            api.resume(f"sess_missing_{uuid.uuid4().hex[:8]}")
