"""设计文档 46 §3.3/§5：BaseAgent 状态机直接覆盖测试（⑤ 真实评测补充）

BaseAgent（team/base_agent.py）此前无直接覆盖测试（codegraph ⚠️ no covering tests）。
本文件覆盖：
- _retry 决策：可重试 → RETRY 且递减剩余次数；不可重试（次数耗尽）→ FAILED
- run() 决策路径：SUCCESS（正常产出）/ DEGRADED（无观测降级）
- AgentResult.ok 语义（SUCCESS/DEGRADED 通过，RETRY/FAILED 不通过）
- AgentStatus 枚举值契约
"""
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.team.base_agent import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
)
from competitor_agent.team.message_bus import MessageBus


class DummyAgent(BaseAgent):
    """最小实现：把 run 委托给注入的回调，供状态机决策路径测试"""

    def __init__(self, run_fn=None, **kwargs):
        super().__init__("dummy", MessageBus(), **kwargs)
        self._run_fn = run_fn

    def run(self, ctx: AgentContext) -> AgentResult:
        return self._run_fn(ctx)


def _ctx(max_retries: int = 1) -> AgentContext:
    return AgentContext(
        task="分析 Cursor",
        strategy=CompetitorStrategy(
            competitor=Competitor(name="cursor"),
            gaps=[],
            budget_allocation={},
        ),
        max_retries=max_retries,
    )


class TestRetryStateMachine:
    """_retry 决策：RETRY（可重试）→ FAILED（次数耗尽）"""

    def test_retry_available_returns_retry_and_decrements(self):
        agent = DummyAgent()
        ctx = _ctx(max_retries=2)
        result = agent._retry(ctx, RuntimeError("boom"))
        assert result.status == AgentStatus.RETRY
        assert result.reason == "boom"
        assert not result.ok
        assert ctx.max_retries == 1  # 剩余次数递减

    def test_retry_exhausted_returns_failed(self):
        agent = DummyAgent()
        ctx = _ctx(max_retries=0)
        result = agent._retry(ctx, RuntimeError("boom"))
        assert result.status == AgentStatus.FAILED
        assert result.reason == "boom"
        assert not result.ok

    def test_retry_then_failed_full_cycle(self):
        """retries=1：首次 RETRY、次数耗尽后第二次 FAILED（真实编排路径）"""
        agent = DummyAgent()
        ctx = _ctx(max_retries=1)
        first = agent._retry(ctx, RuntimeError("transient"))
        assert first.status == AgentStatus.RETRY
        assert ctx.max_retries == 0
        second = agent._retry(ctx, RuntimeError("still failing"))
        assert second.status == AgentStatus.FAILED
        assert ctx.max_retries == 0


class TestRunDecisionPaths:
    """run() 决策路径：SUCCESS / DEGRADED"""

    def test_success_payload_passed_through(self):
        payload = [{"dimension": "pricing"}]
        agent = DummyAgent(run_fn=lambda ctx: AgentResult(status=AgentStatus.SUCCESS, payload=payload))
        result = agent.run(_ctx())
        assert result.status == AgentStatus.SUCCESS
        assert result.payload == payload
        assert result.ok

    def test_degraded_is_ok(self):
        agent = DummyAgent(run_fn=lambda ctx: AgentResult(status=AgentStatus.DEGRADED, reason="缺数据"))
        result = agent.run(_ctx())
        assert result.status == AgentStatus.DEGRADED
        assert result.ok
        assert result.reason == "缺数据"

    def test_failed_not_ok(self):
        agent = DummyAgent(run_fn=lambda ctx: AgentResult(status=AgentStatus.FAILED, reason="x"))
        result = agent.run(_ctx())
        assert not result.ok
        assert result.status == AgentStatus.FAILED


class TestAgentStatusContract:
    def test_enum_values(self):
        assert AgentStatus.SUCCESS.value == "success"
        assert AgentStatus.RETRY.value == "retry"
        assert AgentStatus.DEGRADED.value == "degraded"
        assert AgentStatus.FAILED.value == "failed"

    def test_ok_semantics(self):
        assert AgentResult(status=AgentStatus.SUCCESS).ok is True
        assert AgentResult(status=AgentStatus.DEGRADED).ok is True
        assert AgentResult(status=AgentStatus.RETRY).ok is False
        assert AgentResult(status=AgentStatus.FAILED).ok is False
