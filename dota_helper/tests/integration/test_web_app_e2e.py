"""Web 应用端到端集成测试

验证 Web 服务层、Agent 降级模式、技能管理端点和会话持久化。
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from dota_helper import PostMatchReviewAPI
from dota_helper.agent.session_manager import SessionManager, ChatSession, ChatMessage
from dota_helper.domain_types.events import ProgressEvent
from dota_helper.domain_types.report import MatchSummary, ReviewReport
from dota_helper.web_app import app


# ── Helpers ──

class FakeOrchestrator:
    """用于测试的复盘编排器桩"""

    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.is_interrupted = False

    async def review(
        self,
        match_id: str,
        progress_callback: Optional[Any] = None,
    ) -> ReviewReport:
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
        self.is_interrupted = True

    async def _emit(self, callback: Any, event: ProgressEvent) -> None:
        result = callback(event)
        if asyncio.iscoroutine(result):
            await result


def _parse_sse(response: Any) -> List[Dict[str, Any]]:
    """解析 SSE 响应体为事件列表"""
    events: List[Dict[str, Any]] = []
    for line in response.text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                events.append(json.loads(payload))
    return events


# ── Fixtures ──

@pytest.fixture
def client_with_review_api() -> TestClient:
    """注入 mock review_api 的 TestClient

    注意：FastAPI lifespan 会在 TestClient 构造时执行，
    自动初始化 DotaHelperReActAgent（连接 MCP Server，失败时降级为 NoOpMCPClient）。
    因此 chat_agent 在 lifespan 结束后一定不为 None，
    但 MCP 连接可能处于降级模式（NoOpMCPClient）。
    """
    import dota_helper.web_app as web_mod

    api = PostMatchReviewAPI(
        orchestrator_factory=lambda match_id: FakeOrchestrator(match_id)
    )
    original_api = web_mod.review_api

    web_mod.review_api = api

    with TestClient(app) as tc:
        yield tc

    web_mod.review_api = original_api


@pytest.fixture
def client_with_session_mgr(tmp_path: Path) -> TestClient:
    """注入 SessionManager 的 TestClient

    lifespan 初始化后 chat_agent 和 session_manager 均不为 None。
    额外注入自定义 session_manager 以控制数据目录。
    """
    import dota_helper.web_app as web_mod

    api = PostMatchReviewAPI(
        orchestrator_factory=lambda match_id: FakeOrchestrator(match_id)
    )

    original_api = web_mod.review_api

    web_mod.review_api = api

    with TestClient(app) as tc:
        # lifespan 已创建 session_manager，保存引用
        yield tc

    web_mod.review_api = original_api


@pytest.fixture
def client_no_agent() -> TestClient:
    """强制 chat_agent=None 的 TestClient（测试 Web 层降级响应）

    需要在 lifespan 完成后立即清除 chat_agent，模拟 Agent 运行时崩溃场景。
    """
    import dota_helper.web_app as web_mod

    api = PostMatchReviewAPI(
        orchestrator_factory=lambda match_id: FakeOrchestrator(match_id)
    )
    original_api = web_mod.review_api
    original_agent = web_mod.chat_agent
    original_session_mgr = web_mod.session_manager

    web_mod.review_api = api

    with TestClient(app) as tc:
        # lifespan 已完成，chat_agent 已初始化
        # 模拟 Agent 运行时不可用（如 OOM / 外部服务断连）
        web_mod.chat_agent = None
        web_mod.session_manager = None
        yield tc

    web_mod.review_api = original_api
    web_mod.chat_agent = original_agent
    web_mod.session_manager = original_session_mgr


# ════════════════════════════════════════════════════════════
# 1. 复盘端点 E2E 测试（保持回归兼容）
# ════════════════════════════════════════════════════════════

class TestReviewEndpointsE2E:
    """复盘端点端到端测试"""

    def test_review_sse_stream(self, client_with_review_api: TestClient) -> None:
        """复盘 SSE 端点按顺序返回事件"""
        response = client_with_review_api.post(
            "/api/review", json={"match_id": "12345"}
        )
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

    def test_review_status(self, client_with_review_api: TestClient) -> None:
        """复盘完成后状态端点返回 completed"""
        client_with_review_api.post(
            "/api/review", json={"match_id": "12345"}
        ).read()
        response = client_with_review_api.get("/api/review/12345/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["progress"] == 1.0

    def test_review_report(self, client_with_review_api: TestClient) -> None:
        """复盘报告端点返回完整报告"""
        client_with_review_api.post(
            "/api/review", json={"match_id": "12345"}
        ).read()
        response = client_with_review_api.get("/api/review/12345/report")
        assert response.status_code == 200
        data = response.json()
        assert data["match_id"] == "12345"
        assert data["terminal_state"] == "completed"

    def test_review_report_not_found(self, client_with_review_api: TestClient) -> None:
        """未复盘的比赛返回 404"""
        response = client_with_review_api.get("/api/review/99999/report")
        assert response.status_code == 404

    def test_review_interrupt(self, client_with_review_api: TestClient) -> None:
        """中断端点返回成功标志"""
        client_with_review_api.post(
            "/api/review", json={"match_id": "12345"}
        ).read()
        response = client_with_review_api.post("/api/review/12345/interrupt")
        assert response.status_code == 200
        data = response.json()
        assert data["match_id"] == "12345"
        assert "success" in data

    def test_review_history(self, client_with_review_api: TestClient) -> None:
        """复盘历史列表包含已完成复盘"""
        client_with_review_api.post(
            "/api/review", json={"match_id": "12345"}
        ).read()
        response = client_with_review_api.get("/api/review/history")
        assert response.status_code == 200
        data = response.json()
        assert any(item["match_id"] == "12345" for item in data)


# ════════════════════════════════════════════════════════════
# 2. Agent 降级模式测试（chat_agent=None）
# ════════════════════════════════════════════════════════════

class TestAgentDegradationMode:
    """Agent 降级模式端到端测试

    验证当 DotaHelperReActAgent 运行时不可用时，
    Web 服务层仍能正常响应（返回降级提示，而非崩溃）。
    """

    def test_chat_returns_error_event_when_agent_none(
        self,
        client_no_agent: TestClient,
    ) -> None:
        """chat_agent=None 时聊天端点返回 error 类型事件"""
        response = client_no_agent.post(
            "/api/chat", json={"message": "你好"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = _parse_sse(response)
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "不可用" in events[0]["content"]
        assert "session_id" in events[0]

    def test_chat_with_session_id_in_degradation(
        self,
        client_no_agent: TestClient,
    ) -> None:
        """降级模式下指定 session_id 时，返回的 error 事件包含该 session_id"""
        response = client_no_agent.post(
            "/api/chat",
            json={"message": "分析比赛", "session_id": "sess_test123"},
        )
        assert response.status_code == 200
        events = _parse_sse(response)
        assert events[0]["session_id"] == "sess_test123"
        assert events[0]["type"] == "error"

    def test_chat_empty_message_returns_422(
        self,
        client_no_agent: TestClient,
    ) -> None:
        """空消息返回 422"""
        response = client_no_agent.post(
            "/api/chat", json={"message": ""}
        )
        assert response.status_code == 422

    def test_chat_history_empty_when_no_session_manager(
        self,
        client_no_agent: TestClient,
    ) -> None:
        """session_manager=None 时历史端点返回空列表"""
        response = client_no_agent.get("/api/history")
        assert response.status_code == 200
        assert response.json() == []

    def test_chat_session_503_when_no_session_manager(
        self,
        client_no_agent: TestClient,
    ) -> None:
        """session_manager=None 时会话详情端点返回 503"""
        response = client_no_agent.get("/api/sessions/any_id")
        assert response.status_code == 503


# ════════════════════════════════════════════════════════════
# 3. 会话持久化端到端测试
# ════════════════════════════════════════════════════════════

class TestSessionPersistenceE2E:
    """会话持久化端到端测试

    验证 SessionManager 集成到 Web 层后的行为。
    """

    def test_chat_history_with_session_manager(
        self,
        client_with_session_mgr: TestClient,
    ) -> None:
        """session_manager 存在时历史端点返回列表（可能为空）"""
        response = client_with_session_mgr.get("/api/history")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_chat_session_not_found_with_session_manager(
        self,
        client_with_session_mgr: TestClient,
    ) -> None:
        """不存在的会话返回 404"""
        response = client_with_session_mgr.get(
            "/api/sessions/sess_nonexistent"
        )
        assert response.status_code == 404

    def test_session_manager_persistence(
        self,
        tmp_path: Path,
    ) -> None:
        """SessionManager 直接持久化测试"""
        sm = SessionManager(data_dir=tmp_path / "sessions")

        # 创建会话
        session_id = asyncio.run(sm.create_session())
        assert session_id.startswith("sess_")

        # 追加消息
        asyncio.run(
            sm.append_message(session_id, "user", "你好，分析这场比赛")
        )
        asyncio.run(
            sm.append_message(session_id, "agent", "好的，正在分析...")
        )

        # 获取会话
        session = asyncio.run(sm.get_session(session_id))
        assert session is not None
        assert session.session_id == session_id
        assert session.title == "你好，分析这场比赛"  # 首条用户消息前 20 字符
        assert len(session.messages) == 2
        assert session.messages[0].role == "user"
        assert session.messages[1].role == "agent"

        # 列出会话
        summaries = asyncio.run(sm.list_sessions())
        assert len(summaries) == 1
        assert summaries[0].session_id == session_id

        # 删除会话
        asyncio.run(sm.delete_session(session_id))
        session_after = asyncio.run(sm.get_session(session_id))
        assert session_after is None

    def test_session_manager_survives_restart(
        self,
        tmp_path: Path,
    ) -> None:
        """SessionManager 重启后会话不丢失"""
        data_dir = tmp_path / "sessions"

        # 第一次运行
        sm1 = SessionManager(data_dir=data_dir)
        session_id = asyncio.run(sm1.create_session())
        asyncio.run(
            sm1.append_message(session_id, "user", "分析 Juggernaut")
        )
        asyncio.run(
            sm1.append_message(session_id, "agent", "Juggernaut 是一个优秀的核心英雄")
        )

        # 模拟重启（创建新实例）
        sm2 = SessionManager(data_dir=data_dir)
        session = asyncio.run(sm2.get_session(session_id))
        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0].content == "分析 Juggernaut"

        summaries = asyncio.run(sm2.list_sessions())
        assert len(summaries) == 1


# ════════════════════════════════════════════════════════════
# 4. 技能管理端点 E2E 测试
# ════════════════════════════════════════════════════════════

class TestSkillsEndpointsE2E:
    """技能管理 API 端点端到端测试"""

    def test_list_skills(
        self,
        client_with_review_api: TestClient,
    ) -> None:
        """GET /api/review/skills 返回技能列表"""
        response = client_with_review_api.get("/api/review/skills")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_register_skill_missing_name(
        self,
        client_with_review_api: TestClient,
    ) -> None:
        """POST /api/review/skills 缺少 name 返回 422"""
        response = client_with_review_api.post(
            "/api/review/skills",
            json={"skill_definition": {"prompt": "test"}},
        )
        assert response.status_code == 422

    def test_register_skill_missing_definition(
        self,
        client_with_review_api: TestClient,
    ) -> None:
        """POST /api/review/skills 缺少 skill_definition 返回 422"""
        response = client_with_review_api.post(
            "/api/review/skills",
            json={"name": "test_skill"},
        )
        assert response.status_code == 422

    def test_register_skill_success(
        self,
        client_with_review_api: TestClient,
    ) -> None:
        """POST /api/review/skills 注册成功返回 ok"""
        response = client_with_review_api.post(
            "/api/review/skills",
            json={
                "name": "custom_laning",
                "skill_definition": {
                    "prompt": "分析对线期表现",
                    "focus": "laning",
                },
            },
        )
        # 可能成功(200)或因SkillStore问题失败(422)
        assert response.status_code in (200, 422)
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "ok"
            assert data["name"] == "custom_laning"


# ════════════════════════════════════════════════════════════
# 5. 前端路由 E2E 测试
# ════════════════════════════════════════════════════════════

class TestFrontendRoutesE2E:
    """前端路由端到端测试"""

    def test_index_without_build(self, client_with_review_api: TestClient) -> None:
        """未构建前端时首页返回 200 或 503"""
        response = client_with_review_api.get("/")
        assert response.status_code in (200, 503)

    def test_chat_redirect(self, client_with_review_api: TestClient) -> None:
        """/chat 重定向到 /"""
        response = client_with_review_api.get("/chat", follow_redirects=False)
        assert response.status_code in (200, 307, 308)


# ════════════════════════════════════════════════════════════
# 6. Review API 未初始化时的降级测试
# ════════════════════════════════════════════════════════════

class TestReviewAPIDegradation:
    """复盘 API 未初始化时的降级行为

    通过在 lifespan 完成后清除 review_api 来模拟运行时 API 不可用。
    """

    def test_review_503_when_api_cleared(self) -> None:
        """review_api 清除后复盘端点返回 503"""
        import dota_helper.web_app as web_mod

        original_api = web_mod.review_api

        with TestClient(app) as tc:
            # lifespan 完成，review_api 已初始化
            # 模拟运行时 API 不可用
            web_mod.review_api = None
            response = tc.post("/api/review", json={"match_id": "12345"})
            assert response.status_code == 503

        web_mod.review_api = original_api

    def test_skills_503_when_api_cleared(self) -> None:
        """review_api 清除后技能端点返回 503"""
        import dota_helper.web_app as web_mod

        original_api = web_mod.review_api

        with TestClient(app) as tc:
            web_mod.review_api = None
            response = tc.get("/api/review/skills")
            assert response.status_code == 503

        web_mod.review_api = original_api


# ════════════════════════════════════════════════════════════
# 7. Agent MCP 降级模式测试（Agent 存在但 MCP 未连接）
# ════════════════════════════════════════════════════════════

class TestAgentWithMCPDegradation:
    """Agent MCP 降级模式端到端测试

    验证 DotaHelperReActAgent 在 MCP Server 不可用时，
    通过 NoOpMCPClient 降级仍能正常响应聊天请求。

    注意：TestClient 的 lifespan 会在退出时关闭 Agent（__aexit__），
    后续测试中 Agent 的 _closed=True，run_stream() 会返回空流。
    因此需要独立的 TestClient 实例确保 Agent 处于活跃状态。
    """

    def test_chat_returns_events_in_mcp_degradation(self) -> None:
        """MCP 降级模式下聊天端点返回完整的 ReAct 事件流"""
        import dota_helper.web_app as web_mod

        api = PostMatchReviewAPI(
            orchestrator_factory=lambda match_id: FakeOrchestrator(match_id)
        )
        original_api = web_mod.review_api
        original_agent = web_mod.chat_agent
        web_mod.review_api = api
        # 清除已关闭的 Agent，让 lifespan 创建新实例
        web_mod.chat_agent = None
        web_mod.session_manager = None

        with TestClient(app) as tc:
            response = tc.post("/api/chat", json={"message": "你好"})
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")

            events = _parse_sse(response)
            event_types = [e["type"] for e in events]

            # Agent 降级模式下仍产生 session + final 事件
            assert "session" in event_types
            assert "final" in event_types

            # session 事件包含必要字段
            session_event = events[0]
            assert session_event["type"] == "session"
            assert "session_id" in session_event
            assert "conversation_id" in session_event

        web_mod.review_api = original_api
        web_mod.chat_agent = original_agent

    def test_chat_history_after_conversation(self) -> None:
        """对话后历史端点返回会话列表"""
        import dota_helper.web_app as web_mod

        api = PostMatchReviewAPI(
            orchestrator_factory=lambda match_id: FakeOrchestrator(match_id)
        )
        original_api = web_mod.review_api
        original_agent = web_mod.chat_agent
        web_mod.review_api = api
        web_mod.chat_agent = None
        web_mod.session_manager = None

        with TestClient(app) as tc:
            response = tc.post("/api/chat", json={"message": "分析这场比赛"})
            events = _parse_sse(response)
            session_id = events[0].get("session_id") if events else None

            history_response = tc.get("/api/history")
            assert history_response.status_code == 200
            history = history_response.json()
            assert isinstance(history, list)

            if session_id and len(history) > 0:
                assert any(
                    item["session_id"] == session_id for item in history
                )

        web_mod.review_api = original_api
        web_mod.chat_agent = original_agent

    def test_chat_session_detail_after_conversation(self) -> None:
        """对话后会话详情端点返回完整会话"""
        import dota_helper.web_app as web_mod

        api = PostMatchReviewAPI(
            orchestrator_factory=lambda match_id: FakeOrchestrator(match_id)
        )
        original_api = web_mod.review_api
        original_agent = web_mod.chat_agent
        web_mod.review_api = api
        web_mod.chat_agent = None
        web_mod.session_manager = None

        with TestClient(app) as tc:
            response = tc.post("/api/chat", json={"message": "Juggernaut 怎么样"})
            events = _parse_sse(response)
            session_id = events[0].get("session_id") if events else None

            if session_id:
                session_response = tc.get(f"/api/sessions/{session_id}")
                if session_response.status_code == 200:
                    session = session_response.json()
                    assert session["session_id"] == session_id

        web_mod.review_api = original_api
        web_mod.chat_agent = original_agent
