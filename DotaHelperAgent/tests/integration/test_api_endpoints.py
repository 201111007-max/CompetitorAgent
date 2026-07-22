"""赛后复盘 API 端点集成测试

测试 Flask 后端 `/api/review/*` 端点，包括 SSE 流式复盘、状态查询、
报告获取、中断和历史列表。所有外部依赖通过 mock 的 `review_api` 隔离。
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from web.app import app as flask_app


class FakeReport:
    """模拟复盘报告对象"""

    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.overall_score = 7.5
        self.overall_confidence = 0.75
        self.terminal_state = "completed"
        self.created_at = datetime.now().isoformat()
        self.markdown_report = f"# 复盘报告\n\n比赛 {match_id} 分析完成。"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "match_summary": {
                "match_id": self.match_id,
                "duration": 1800,
                "radiant_win": True,
                "radiant_score": 35,
                "dire_score": 22,
                "user_hero": "Anti-Mage",
                "user_team_win": True,
                "key_events": [],
            },
            "phase_results": [],
            "overall_score": self.overall_score,
            "overall_confidence": self.overall_confidence,
            "key_findings": ["对线期表现稳定"],
            "improvement_areas": ["提高团战站位"],
            "markdown_report": self.markdown_report,
            "terminal_state": self.terminal_state,
            "created_at": self.created_at,
        }


class FakeReviewAPI:
    """模拟赛后复盘 API 门面"""

    def __init__(self) -> None:
        self._status: Dict[str, Any] = {
            "match_id": "12345",
            "status": "running",
            "progress": 0.5,
            "current_phase": "teamfight",
            "error_message": None,
        }
        self._history: List[Dict[str, Any]] = [
            {
                "match_id": "12345",
                "status": "completed",
                "overall_score": 7.5,
                "overall_confidence": 0.75,
                "terminal_state": "completed",
                "created_at": datetime.now().isoformat(),
                "completed_at": datetime.now().isoformat(),
            }
        ]

    async def review_stream(self, match_id: str):
        """SSE 流式复盘"""
        events = [
            {
                "event": "phase_start",
                "phase": "laning",
                "progress": 0.2,
                "message": "开始分析阶段: laning",
                "payload": {"phase_index": 0, "total_phases": 2},
            },
            {
                "event": "phase_complete",
                "phase": "laning",
                "progress": 0.5,
                "message": "阶段 laning 分析完成",
                "payload": {"confidence": 0.7, "conclusions_count": 1},
            },
            {
                "event": "phase_start",
                "phase": "teamfight",
                "progress": 0.5,
                "message": "开始分析阶段: teamfight",
                "payload": {"phase_index": 1, "total_phases": 2},
            },
            {
                "event": "phase_complete",
                "phase": "teamfight",
                "progress": 0.8,
                "message": "阶段 teamfight 分析完成",
                "payload": {"confidence": 0.65, "conclusions_count": 1},
            },
            {
                "event": "report",
                "progress": 1.0,
                "message": "复盘报告生成完成",
                "payload": {"report": FakeReport(match_id).to_dict()},
            },
        ]
        for evt in events:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    async def get_status(self, match_id: str) -> Dict[str, Any]:
        self._status["match_id"] = match_id
        return self._status

    async def get_report(self, match_id: str) -> FakeReport:
        return FakeReport(match_id)

    async def interrupt(self, match_id: str) -> Dict[str, Any]:
        self._status["status"] = "interrupted"
        self._status["current_phase"] = None
        return {"match_id": match_id, "success": True, "status": "interrupted"}

    async def list_history(self) -> List[Dict[str, Any]]:
        return list(self._history)


@pytest.fixture
def client():
    """Flask 测试客户端 fixture"""
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as test_client:
        yield test_client


@pytest.fixture
def mock_review_api(client, monkeypatch):
    """用 mock 替换全局 review_api"""
    fake_api = FakeReviewAPI()
    monkeypatch.setattr("web.app.review_api", fake_api)
    monkeypatch.setattr("web.app.REVIEW_API_AVAILABLE", True)
    return fake_api


class TestReviewSSEEndpoint:
    """测试复盘 SSE 端点"""

    def test_start_review_requires_match_id(self, client, mock_review_api):
        """缺少 match_id 时返回 400"""
        response = client.post("/api/review")
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "match_id" in data["error"]

    def test_start_review_sse_stream(self, client, mock_review_api):
        """SSE 流按顺序输出阶段事件和最终报告"""
        response = client.post("/api/review?match_id=12345")
        assert response.status_code == 200
        assert "text/event-stream" in response.content_type

        text = response.get_data(as_text=True)
        lines = [line for line in text.split("\n") if line.startswith("data: ")]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue

        event_names = [e["event"] for e in events]
        assert "phase_start" in event_names
        assert "phase_complete" in event_names
        assert "report" in event_names
        assert events[-1]["event"] == "report"
        assert events[-1]["payload"]["report"]["match_id"] == "12345"


class TestReviewStatusEndpoint:
    """测试复盘状态端点"""

    def test_get_review_status(self, client, mock_review_api):
        """获取复盘状态"""
        response = client.get("/api/review/12345/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["status"]["match_id"] == "12345"


class TestReviewReportEndpoint:
    """测试复盘报告端点"""

    def test_get_review_report(self, client, mock_review_api):
        """获取完整复盘报告"""
        response = client.get("/api/review/12345/report")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["report"]["match_id"] == "12345"
        assert "overall_score" in data["report"]
        assert "markdown_report" in data["report"]

    def test_get_review_report_not_found(self, client, mock_review_api, monkeypatch):
        """报告不存在时返回 404"""
        monkeypatch.setattr("web.app.review_api", FakeReviewAPI())
        monkeypatch.setattr("web.app.REVIEW_API_AVAILABLE", True)

        async def _return_none(match_id: str):
            return None

        monkeypatch.setattr("web.app.review_api.get_report", _return_none)
        response = client.get("/api/review/99999/report")
        assert response.status_code == 404
        data = response.get_json()
        assert data["success"] is False


class TestReviewInterruptEndpoint:
    """测试复盘中断端点"""

    def test_interrupt_review(self, client, mock_review_api):
        """中断正在进行的复盘"""
        response = client.post("/api/review/12345/interrupt")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["result"]["success"] is True
        assert data["result"]["status"] == "interrupted"


class TestReviewHistoryEndpoint:
    """测试复盘历史列表端点"""

    def test_list_review_history(self, client, mock_review_api):
        """获取复盘历史列表"""
        response = client.get("/api/review/history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert isinstance(data["history"], list)
        assert len(data["history"]) == 1
        assert data["history"][0]["match_id"] == "12345"
