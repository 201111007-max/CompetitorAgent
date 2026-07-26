"""Web 应用集成测试

验证 FastAPI 复盘端点、聊天 mock 端点、静态文件服务的行为。
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from dota_helper import PostMatchReviewAPI
from dota_helper.domain_types.events import ProgressEvent
from dota_helper.domain_types.report import MatchSummary, ReviewReport
from dota_helper.web_app import app, chat_agent


class FakeOrchestrator:
    """用于测试的复盘编排器桩"""

    def __init__(self, match_id: str) -> None:
        """初始化假编排器

        Args:
            match_id: 比赛 ID
        """
        self.match_id = match_id
        self.is_interrupted = False

    async def review(
        self,
        match_id: str,
        progress_callback: Optional[Any] = None,
    ) -> ReviewReport:
        """模拟复盘执行

        Args:
            match_id: 比赛 ID
            progress_callback: 进度回调

        Returns:
            ReviewReport: 模拟报告
        """
        if progress_callback is not None:
            await self._emit(progress_callback, ProgressEvent(
                event="phase_start",
                phase="laning",
                progress=0.2,
                message="开始分析阶段: laning",
            ))
            await asyncio.sleep(0.01)
            await self._emit(progress_callback, ProgressEvent(
                event="phase_complete",
                phase="laning",
                progress=0.5,
                message="阶段 laning 分析完成",
            ))
            await self._emit(progress_callback, ProgressEvent(
                event="progress",
                progress=0.9,
                message="报告构建完成",
            ))
        return ReviewReport(
            match_id=match_id,
            match_summary=MatchSummary(
                match_id=match_id,
                duration=1800,
                radiant_win=True,
                radiant_score=30,
                dire_score=20,
                user_hero="Juggernaut",
                user_team_win=True,
            ),
            phase_results=[],
            overall_score=0.75,
            overall_confidence=0.8,
            key_findings=["Findings"],
            improvement_areas=["Improvements"],
            markdown_report="# Test Report",
            terminal_state="completed",
            created_at="2026-07-27T00:00:00",
        )

    def interrupt(self) -> None:
        """标记中断"""
        self.is_interrupted = True

    async def _emit(
        self,
        callback: Any,
        event: ProgressEvent,
    ) -> None:
        """发送进度事件"""
        result = callback(event)
        if asyncio.iscoroutine(result):
            await result


@pytest.fixture
def client() -> TestClient:
    """构造已注入 mock API 的 TestClient"""
    api = PostMatchReviewAPI(orchestrator_factory=lambda match_id: FakeOrchestrator(match_id))
    # 直接替换应用生命周期创建的 review_api
    import dota_helper.web_app as web_app_module
    original_api = web_app_module.review_api
    web_app_module.review_api = api
    with TestClient(app) as test_client:
        yield test_client
    web_app_module.review_api = original_api


def _parse_sse(response: Any) -> List[Dict[str, Any]]:
    """解析 SSE 响应体为事件列表

    Args:
        response: TestClient 响应对象

    Returns:
        List[Dict[str, Any]]: 解析后的事件字典列表
    """
    events: List[Dict[str, Any]] = []
    for line in response.text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                events.append(json.loads(payload))
    return events


def test_review_sse_stream(client: TestClient) -> None:
    """复盘 SSE 端点按顺序返回事件"""
    response = client.post("/api/review", json={"match_id": "12345"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response)
    event_types = [e["event"] for e in events]
    assert "phase_start" in event_types
    assert "phase_complete" in event_types
    assert "report" in event_types

    report_event = events[-1]
    assert report_event["event"] == "report"
    assert report_event["progress"] == 1.0
    assert report_event["payload"]["report"]["match_id"] == "12345"


def test_review_status(client: TestClient) -> None:
    """复盘完成后状态端点返回 completed"""
    client.post("/api/review", json={"match_id": "12345"}).read()
    response = client.get("/api/review/12345/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["progress"] == 1.0


def test_review_report(client: TestClient) -> None:
    """复盘报告端点返回完整报告"""
    client.post("/api/review", json={"match_id": "12345"}).read()
    response = client.get("/api/review/12345/report")
    assert response.status_code == 200
    data = response.json()
    assert data["match_id"] == "12345"
    assert data["terminal_state"] == "completed"


def test_review_report_not_found(client: TestClient) -> None:
    """未复盘的比赛返回 404"""
    response = client.get("/api/review/99999/report")
    assert response.status_code == 404


def test_review_interrupt(client: TestClient) -> None:
    """中断端点返回成功标志"""
    # 先启动一次复盘再中断（FakeOrchestrator 执行很快，但仍可验证接口）
    client.post("/api/review", json={"match_id": "12345"}).read()
    response = client.post("/api/review/12345/interrupt")
    assert response.status_code == 200
    data = response.json()
    assert data["match_id"] == "12345"
    assert "success" in data


def test_review_history(client: TestClient) -> None:
    """复盘历史列表包含已完成复盘"""
    client.post("/api/review", json={"match_id": "12345"}).read()
    response = client.get("/api/review/history")
    assert response.status_code == 200
    data = response.json()
    assert any(item["match_id"] == "12345" for item in data)


def test_chat_sse_mock(client: TestClient) -> None:
    """聊天端点按顺序返回 session/thought/action/observation/final"""
    response = client.post("/api/chat", json={"message": "分析眼位"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response)
    event_types = [e["type"] for e in events]
    assert event_types == ["session", "thought", "action", "observation", "final"]

    final_event = events[-1]
    assert "ward_html" in final_event
    assert final_event["ward_html"] == "/ward_analysis/demo.html"


def test_chat_history_and_session(client: TestClient) -> None:
    """聊天历史与会话详情端点工作正常"""
    response = client.post("/api/chat", json={"message": "Hello"})
    events = _parse_sse(response)
    session_id = events[0]["session_id"]

    history_response = client.get("/api/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert any(item["session_id"] == session_id for item in history)

    session_response = client.get(f"/api/sessions/{session_id}")
    assert session_response.status_code == 200
    session = session_response.json()
    assert session["session_id"] == session_id
    assert len(session["messages"]) == 2


def test_chat_session_not_found(client: TestClient) -> None:
    """不存在的会话返回 404"""
    response = client.get("/api/sessions/nonexistent")
    assert response.status_code == 404


def test_index_without_build(client: TestClient) -> None:
    """未构建前端时首页返回 503"""
    response = client.get("/")
    # 若已存在 dist/index.html 则返回 200，否则 503
    assert response.status_code in (200, 503)
