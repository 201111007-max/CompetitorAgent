"""工具护栏测试 — Schema 校验 / 归一化 / 硬约束 / 敏感守卫 / 限速 / 审计

覆盖 design 文档 TOOL_GUARDRAIL_DESIGN.md 的测试计划与验收标准 A1-A7。
"""
from typing import Any, Dict, List, Optional

import pytest

from dota_helper.agent.tool_dispatcher import ToolDispatcher
from dota_helper.agent.tool_guard import (
    AuditLog,
    ConfirmationRequired,
    RateLimitExceeded,
    SensitiveOperationGuard,
    ToolArgumentError,
    ToolArgumentValidator,
    ToolBlockedError,
    ToolRateLimiter,
)
from dota_helper.agent.react_loop import ReActContext, ReActLoop
from dota_helper.mcp_client.types import ToolInfo


# ── 复用的 schema ──

SCHEMA_MATCH_DETAILS = {
    "type": "object",
    "properties": {
        "match_id": {"type": "integer", "description": "比赛 ID"},
    },
    "required": ["match_id"],
}

SCHEMA_SEARCH = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "maxLength": 200},
        "num_results": {"type": "integer", "minimum": 1, "maximum": 10},
        "fulltext_max_chars": {"type": "integer"},
    },
    "required": ["query"],
}

SCHEMA_MULTI = {
    "type": "object",
    "properties": {
        "match_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 100},
    },
    "required": ["match_ids"],
}

SCHEMA_RESOURCE = {
    "type": "object",
    "properties": {
        "resource": {"type": "string", "enum": ["heroes", "items", "abilities"]},
    },
    "required": ["resource"],
}


# ── TestToolArgumentValidator ──


class TestToolArgumentValidator:
    """Schema 校验 / 归一化 / 硬约束表"""

    @pytest.fixture
    def validator(self) -> ToolArgumentValidator:
        return ToolArgumentValidator()

    # Schema 校验

    def test_type_error_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_match_details", {"match_id": "abc"}, SCHEMA_MATCH_DETAILS)
        assert not result.valid
        assert any("match_id" in e for e in result.errors)

    def test_required_missing_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("search_dota_history", {"num_results": 3}, SCHEMA_SEARCH)
        assert not result.valid
        assert any("缺少必填参数" in e for e in result.errors)

    def test_range_violation_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("search_dota_history", {"query": "x", "num_results": 99}, SCHEMA_SEARCH)
        assert not result.valid
        assert any("num_results" in e for e in result.errors)

    def test_max_length_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("search_dota_history", {"query": "x" * 300}, SCHEMA_SEARCH)
        assert not result.valid
        assert any("query" in e for e in result.errors)

    def test_enum_whitelist(self, validator: ToolArgumentValidator) -> None:
        ok = validator.validate("get_constants", {"resource": "heroes"}, SCHEMA_RESOURCE)
        assert ok.valid
        bad = validator.validate("get_constants", {"resource": "../../etc"}, SCHEMA_RESOURCE)
        assert not bad.valid
        assert any("resource" in e for e in bad.errors)

    # 归一化

    def test_string_int_normalized(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_match_details", {"match_id": "8650430843"}, SCHEMA_MATCH_DETAILS)
        assert result.valid
        assert result.normalized_args["match_id"] == 8650430843

    def test_bool_not_accepted_as_int(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_match_details", {"match_id": True}, SCHEMA_MATCH_DETAILS)
        assert not result.valid

    def test_invalid_string_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_match_details", {"match_id": "1; DROP TABLE"}, SCHEMA_MATCH_DETAILS)
        assert not result.valid

    # 硬约束表

    def test_count_out_of_bounds_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_public_matches", {"limit": 2**31}, {})
        assert not result.valid
        assert any("limit" in e for e in result.errors)

    def test_match_id_beyond_64bit_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_match_details", {"match_id": 2**64}, SCHEMA_MATCH_DETAILS)
        assert not result.valid

    def test_legit_match_id_accepted(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_match_details", {"match_id": 8650430843}, SCHEMA_MATCH_DETAILS)
        assert result.valid

    def test_match_ids_too_many_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("analyze_multi_match_wards", {"match_ids": list(range(101))}, SCHEMA_MULTI)
        assert not result.valid
        assert any("match_ids" in e for e in result.errors)

    def test_match_ids_item_type_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("analyze_multi_match_wards", {"match_ids": [1, "abc", 3]}, SCHEMA_MULTI)
        assert not result.valid

    def test_sites_url_protocol_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate(
            "search_dota_history",
            {"query": "x", "sites": ["https://evil.com"]},
            SCHEMA_SEARCH,
        )
        assert not result.valid
        assert any("sites" in e for e in result.errors)

    def test_long_string_rejected(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("get_records", {"field": "x" * 500}, {})
        assert not result.valid

    def test_unknown_tool_empty_schema_pass(self, validator: ToolArgumentValidator) -> None:
        result = validator.validate("some_unknown_tool", {"foo": "bar"}, {})
        assert result.valid


# ── TestSensitiveOperationGuard ──


class TestSensitiveOperationGuard:
    """敏感守卫 BLOCK / CONFIRM / 确认放行 / 审计"""

    @pytest.fixture
    def audit(self) -> AuditLog:
        return AuditLog()

    @pytest.fixture
    def guard(self, audit: AuditLog) -> SensitiveOperationGuard:
        return SensitiveOperationGuard(audit_log=audit)

    def test_read_only_tool_allowed(self, guard: SensitiveOperationGuard) -> None:
        decision, _ = guard.check("get_match_details", {"match_id": 1}, "s1")
        assert decision == SensitiveOperationGuard.ALLOW

    def test_search_dota_history_blocked(self, guard: SensitiveOperationGuard) -> None:
        decision, reason = guard.check("search_dota_history", {"query": "x"}, "s1")
        assert decision == SensitiveOperationGuard.BLOCK
        assert reason

    def test_request_match_parse_confirm(self, guard: SensitiveOperationGuard) -> None:
        decision, _ = guard.check("request_match_parse", {"match_id": 1}, "s1")
        assert decision == SensitiveOperationGuard.CONFIRM

    def test_confirm_then_allowed_in_session(
        self, guard: SensitiveOperationGuard
    ) -> None:
        assert guard.check("request_match_parse", {"match_id": 1}, "s1")[0] == "confirm"
        guard.confirm("request_match_parse", "s1")
        decision, _ = guard.check("request_match_parse", {"match_id": 1}, "s1")
        assert decision == SensitiveOperationGuard.ALLOW
        # 其他会话仍需确认
        assert guard.check("request_match_parse", {"match_id": 1}, "s2")[0] == "confirm"

    def test_audit_recorded(self, guard: SensitiveOperationGuard, audit: AuditLog) -> None:
        guard.check("request_match_parse", {"match_id": 1}, "s1")
        guard.check("search_dota_history", {"query": "x"}, "s1")
        guard.check("get_match_details", {"match_id": 1}, "s1")
        assert len(audit.records) == 2
        decisions = {r.decision for r in audit.records}
        assert decisions == {"confirm_required", "blocked"}


# ── TestToolRateLimiter ──


class TestToolRateLimiter:
    """限速：超频拒绝 / 冷却放行 / 工具独立 / enabled=False 放行"""

    @pytest.fixture
    def limiter(self) -> ToolRateLimiter:
        # 低速率便于测试：1 次/分钟
        return ToolRateLimiter(config={"default": 1, "global": 100})

    def test_burst_then_reject(self, limiter: ToolRateLimiter) -> None:
        # 突发容量 = 速率 × 突发倍数 = 1×2 = 2，前 2 次放行，第 3 次拒绝
        assert limiter.allow("get_match_details", "s1")[0] is True
        assert limiter.allow("get_match_details", "s1")[0] is True
        ok, wait = limiter.allow("get_match_details", "s1")
        assert ok is False
        assert wait > 0

    def test_per_tool_independent(self, limiter: ToolRateLimiter) -> None:
        limiter.allow("get_match_details", "s1")
        assert limiter.allow("get_match_items", "s1")[0] is True

    def test_cool_down_releases(self, limiter: ToolRateLimiter) -> None:
        limiter.allow("get_match_details", "s1")
        limiter.reset("s1")
        assert limiter.allow("get_match_details", "s1")[0] is True

    def test_disabled_allows_all(self) -> None:
        limiter = ToolRateLimiter(enabled=False)
        for _ in range(5):
            assert limiter.allow("get_match_details", "s1")[0] is True

    def test_global_session_bucket(self) -> None:
        # global 速率 2/分钟 → 突发容量 4
        limiter = ToolRateLimiter(config={"global": 2})
        for _ in range(4):
            assert limiter.allow("tool_x", "s1")[0] is True
        # 全局桶耗尽，即使工具桶未耗尽也被拒
        ok, _ = limiter.allow("tool_y", "s1")
        assert ok is False
        # 其他会话不受影响
        assert limiter.allow("tool_z", "s2")[0] is True


# ── TestToolDispatcherGuardrail ──


class MockMCPClient:
    """模拟 MCPClient（带 schema 的工具列表）"""

    def __init__(self) -> None:
        self._connected = True
        self._call_count: Dict[str, int] = {}
        self.tools: List[ToolInfo] = [
            ToolInfo(
                name="get_match_details",
                description="Get match details",
                parameters=SCHEMA_MATCH_DETAILS,
            ),
            ToolInfo(
                name="search_dota_history",
                description="Search dota history",
                parameters=SCHEMA_SEARCH,
            ),
            ToolInfo(
                name="request_match_parse",
                description="Request match parse",
                parameters=SCHEMA_MATCH_DETAILS,
            ),
        ]

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        self._call_count[tool_name] = self._call_count.get(tool_name, 0) + 1
        return f"{tool_name} called"

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def list_tools(self) -> List[ToolInfo]:
        return self.tools


@pytest.fixture
def mock_client() -> MockMCPClient:
    return MockMCPClient()


@pytest.fixture
def dispatcher(mock_client: MockMCPClient) -> ToolDispatcher:
    return ToolDispatcher(mcp_client=mock_client)


class TestToolDispatcherGuardrail:
    """dispatch 集成护栏（A1/A2/A3/A4/A5/A6）"""

    @pytest.mark.asyncio
    async def test_valid_args_pass(
        self, dispatcher: ToolDispatcher, mock_client: MockMCPClient
    ) -> None:
        result = await dispatcher.dispatch("get_match_details", {"match_id": "8650430843"})
        assert result == "get_match_details called"
        assert mock_client._call_count["get_match_details"] == 1

    @pytest.mark.asyncio
    async def test_invalid_args_never_reach_mcp(
        self, dispatcher: ToolDispatcher, mock_client: MockMCPClient
    ) -> None:
        with pytest.raises(ToolArgumentError):
            await dispatcher.dispatch("get_match_details", {"match_id": "abc"})
        assert "get_match_details" not in mock_client._call_count

    @pytest.mark.asyncio
    async def test_confirmation_required_raises(self, dispatcher: ToolDispatcher) -> None:
        with pytest.raises(ConfirmationRequired):
            await dispatcher.dispatch("request_match_parse", {"match_id": 123}, "s1")

    @pytest.mark.asyncio
    async def test_confirm_then_call_passes(
        self, dispatcher: ToolDispatcher, mock_client: MockMCPClient
    ) -> None:
        dispatcher.confirm_tool("request_match_parse", "s1")
        result = await dispatcher.dispatch("request_match_parse", {"match_id": 123}, "s1")
        assert result == "request_match_parse called"

    @pytest.mark.asyncio
    async def test_blocked_tool_raises(self, dispatcher: ToolDispatcher) -> None:
        with pytest.raises(ToolBlockedError):
            await dispatcher.dispatch("search_dota_history", {"query": "x"}, "s1")

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, mock_client: MockMCPClient) -> None:
        dispatcher = ToolDispatcher(
            mcp_client=mock_client,
            guard_config={"rate_limits": {"default": 1, "global": 100}},
        )
        # 突发容量 2，前 2 次放行
        assert await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")
        assert await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")
        with pytest.raises(RateLimitExceeded):
            await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")
        # 被拒调用不达 MCP
        assert mock_client._call_count.get("get_match_details", 0) == 2

    @pytest.mark.asyncio
    async def test_rate_limit_config_rejects(self, mock_client: MockMCPClient) -> None:
        dispatcher = ToolDispatcher(
            mcp_client=mock_client,
            guard_config={"rate_limits": {"default": 1, "global": 100}},
        )
        await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")
        await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")
        with pytest.raises(RateLimitExceeded):
            await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")

    @pytest.mark.asyncio
    async def test_guard_disabled_passes_through(self, mock_client: MockMCPClient) -> None:
        dispatcher = ToolDispatcher(mcp_client=mock_client, enable_tool_guard=False)
        result = await dispatcher.dispatch("get_match_details", {"match_id": "not_a_number"})
        assert result == "get_match_details called"

    @pytest.mark.asyncio
    async def test_tool_rate_limit_disabled_only(
        self, mock_client: MockMCPClient
    ) -> None:
        dispatcher = ToolDispatcher(
            mcp_client=mock_client,
            tool_rate_limit=False,
            guard_config={"rate_limits": {"default": 1, "global": 100}},
        )
        # 限速关闭，可连续调用
        for _ in range(3):
            result = await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")
            assert result == "get_match_details called"

    @pytest.mark.asyncio
    async def test_audit_records_all_calls(self, dispatcher: ToolDispatcher) -> None:
        await dispatcher.dispatch("get_match_details", {"match_id": 1}, "s1")
        with pytest.raises(ToolArgumentError):
            await dispatcher.dispatch("get_match_details", {"match_id": "abc"}, "s1")
        with pytest.raises(ConfirmationRequired):
            await dispatcher.dispatch("request_match_parse", {"match_id": 1}, "s1")
        records = dispatcher.audit_log.records
        assert len(records) == 3
        assert {r.decision for r in records} == {"allowed", "rejected", "confirm_required"}

    @pytest.mark.asyncio
    async def test_local_tool_validated(self, mock_client: MockMCPClient) -> None:
        def local_handler(args: Dict[str, Any]) -> str:
            return "local ok"

        dispatcher = ToolDispatcher(
            mcp_client=mock_client,
            tool_registry=None,
        )
        dispatcher._tool_registry.register(
            "local_combo",
            local_handler,
            description="本地组合工具",
            schema={"properties": {"match_id": {"type": "integer"}}, "required": ["match_id"]},
        )
        # 非法参数不达 handler
        with pytest.raises(ToolArgumentError):
            await dispatcher.dispatch("local_combo", {"match_id": "abc"})
        # 合法参数正常
        result = await dispatcher.dispatch("local_combo", {"match_id": "5"})
        assert result == "local ok"
        # 全局硬约束也作用于本地工具
        with pytest.raises(ToolArgumentError):
            await dispatcher.dispatch("local_combo", {"match_id": 2**63})


# ── ReAct 循环集成（确认回调 + 护栏异常转 Observation） ──


class MockConfirmationProvider:
    """确认回调 Mock"""

    def __init__(self, decision: bool = True) -> None:
        self._decision = decision
        self.called: List[str] = []

    async def confirm(self, tool_name: str, args: Dict[str, Any]) -> bool:
        self.called.append(tool_name)
        return self._decision


class ScriptedLLM:
    """脚本化 LLM：按调用次数返回预设输出"""

    def __init__(self, outputs: List[str]) -> None:
        self._outputs = list(outputs)
        self.calls = 0

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "",
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        idx = min(self.calls, len(self._outputs) - 1)
        self.calls += 1
        return self._outputs[idx]


class TestReActLoopGuardrail:
    """端到端：确认回调放行 / 拒绝 / 参数错误转 Observation"""

    @pytest.mark.asyncio
    async def test_confirmation_accepted_reaches_mcp(self, mock_client: MockMCPClient) -> None:
        llm = ScriptedLLM([
            'Thought: 需要解析该比赛\n<action>request_match_parse({"match_id": 123})</action>',
            "Final Answer: 已解析",
        ])
        provider = MockConfirmationProvider(decision=True)
        dispatcher = ToolDispatcher(mcp_client=mock_client)
        loop = ReActLoop(llm_client=llm, tool_dispatcher=dispatcher, confirmation_provider=provider)
        context = ReActContext(session_id="s1")
        events = []
        async for ev in loop.execute("解析比赛", context):
            events.append(ev)
        assert provider.called == ["request_match_parse"]
        assert mock_client._call_count.get("request_match_parse", 0) == 1
        finals = [e for e in events if e["type"] == "final"]
        assert finals and finals[0]["content"] == "已解析"

    @pytest.mark.asyncio
    async def test_confirmation_rejected_skips_mcp(self, mock_client: MockMCPClient) -> None:
        llm = ScriptedLLM([
            'Thought: 需要解析该比赛\n<action>request_match_parse({"match_id": 123})</action>',
            "Final Answer: 未执行",
        ])
        provider = MockConfirmationProvider(decision=False)
        dispatcher = ToolDispatcher(mcp_client=mock_client)
        loop = ReActLoop(llm_client=llm, tool_dispatcher=dispatcher, confirmation_provider=provider)
        context = ReActContext(session_id="s1")
        observations = []
        async for ev in loop.execute("解析比赛", context):
            if ev["type"] == "observation":
                observations.append(ev["content"])
        assert provider.called == ["request_match_parse"]
        assert mock_client._call_count.get("request_match_parse", 0) == 0
        assert observations and "需要确认后调用" in observations[0]

    @pytest.mark.asyncio
    async def test_argument_error_becomes_observation(self, mock_client: MockMCPClient) -> None:
        llm = ScriptedLLM([
            'Thought: 查询比赛\n<action>get_match_details({"match_id": "abc"})</action>',
            "Final Answer: 完成",
        ])
        dispatcher = ToolDispatcher(mcp_client=mock_client)
        loop = ReActLoop(llm_client=llm, tool_dispatcher=dispatcher)
        context = ReActContext(session_id="s1")
        observations = []
        async for ev in loop.execute("查询", context):
            if ev["type"] == "observation":
                observations.append(ev["content"])
        assert mock_client._call_count.get("get_match_details", 0) == 0
        assert observations and "参数不合法" in observations[0]

    @pytest.mark.asyncio
    async def test_blocked_tool_becomes_observation(self, mock_client: MockMCPClient) -> None:
        llm = ScriptedLLM([
            'Thought: 搜索资料\n<action>search_dota_history({"query": "dota"})</action>',
            "Final Answer: 完成",
        ])
        dispatcher = ToolDispatcher(mcp_client=mock_client)
        loop = ReActLoop(llm_client=llm, tool_dispatcher=dispatcher)
        context = ReActContext(session_id="s1")
        observations = []
        async for ev in loop.execute("搜索", context):
            if ev["type"] == "observation":
                observations.append(ev["content"])
        assert mock_client._call_count.get("search_dota_history", 0) == 0
        assert observations and "已被禁用" in observations[0]
