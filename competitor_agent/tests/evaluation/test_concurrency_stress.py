"""设计文档 78 §2.3：并发压测（工单 9'，asyncio 迁移已否决——纯重构配套压测）。

场景：DelegateRunner 满负荷（max_concurrent=max_parallel_subagents=6）+ 脚本化子 Agent
（固定 LLM 调用次数与固定文本长度 → 逐调用成本确定性）。

断言：
- A1 成本恒等：并行完成后 ``llm.total_cost_usd`` 与同工作负载串行累加的理论和逐位一致
  （round(,9) 容忍加法顺序差异——锁保证原子性但不保证求和顺序，doc 78 §6.3）；
- A2 无丢失：compare 任务 6 个候选子 Agent 全部被收集（delegate_collector 键数 == 6）；
- A3 wall 收敛：并行 wall < 串行 wall × 0.6（线程池确实并发，防「假并行」回归）；
- A4 取消传播：会话取消后整个编排（含委派路径）在超时内终止。
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

from competitor_agent.agent.delegate_tool import DelegateRunner, SubagentRuntime, make_delegate_tool
from competitor_agent.config.loader import AppConfig, CollectorConfig, ExecutionConfig
from competitor_agent.evaluation.benchmark import BenchmarkExtractor, BenchmarkMockLLM
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory.timeline_memory import TimelineMemory

pytestmark = pytest.mark.evaluation

_CALL_SLEEP = 0.25  # 每次脚本化 LLM 调用的模拟耗时（放大并发差异，抗计时抖动）
_CALLS_PER_SUBAGENT = 3
_SUBAGENTS = 6
_RESPONSE = "Final Answer: " + json.dumps(
    {"competitor": "cursor", "dimensions": [{"dimension": "pricing", "summary": "定费二十美元每月", "details": {}, "confidence": 0.8}]},
    ensure_ascii=False,
)


def _llm_factory() -> LLMClient:
    """脚本化 LLM：固定响应文本（token 估算确定 → 逐调用成本确定）；带模拟耗时。"""

    def call_func(messages: list[dict[str, str]], model: str | None = None, **kwargs: object) -> str:
        time.sleep(_CALL_SLEEP)
        return _RESPONSE

    return LLMClient(call_func=call_func)


def _runtime_for(llm: LLMClient) -> type:
    def factory(name: str) -> SubagentRuntime:
        def run(task: str) -> str:
            for i in range(_CALLS_PER_SUBAGENT):
                llm.complete([{"role": "user", "content": f"子任务 {i} {name} " + "x" * 120}])
            return f"<result {name}> " + "y" * 60

        return SubagentRuntime(name=name, run=run)

    return factory


class _SixRegistry:
    """6 个可委派维度的最小 registry 替身。"""

    def __init__(self) -> None:
        self._dims = {f"dim{i}": object() for i in range(_SUBAGENTS)}

    def get(self, name: str) -> object:
        return self._dims.get(name)

    def resolve(self, name: str) -> object:
        return self._dims.get(name) or object()

    def names(self) -> list[str]:
        return list(self._dims)


class TestCostIdentityAndWall:
    """A1 成本恒等 + A3 wall 收敛（DelegateRunner 满负荷 6 并发）。"""

    def test_a1_cost_identity_parallel_equals_serial(self) -> None:
        llm_parallel = _llm_factory()
        runner = DelegateRunner(_runtime_for(llm_parallel), max_concurrent=_SUBAGENTS)
        delegate = make_delegate_tool(runner, registry=_SixRegistry())
        dims = [f"dim{i}" for i in range(_SUBAGENTS)]
        delegate(dimensions=dims, task="压测任务")
        parallel_cost = llm_parallel.total_cost_usd

        llm_serial = _llm_factory()
        serial_runner = DelegateRunner(_runtime_for(llm_serial), max_concurrent=_SUBAGENTS)
        serial_delegate = make_delegate_tool(serial_runner, registry=_SixRegistry())
        for d in dims:
            serial_delegate(dimensions=[d], task="压测任务")
        serial_cost = llm_serial.total_cost_usd

        # 同一调用多重集（文本相同 → 逐调用成本相同），仅求和顺序不同
        assert parallel_cost > 0
        assert round(parallel_cost, 9) == round(serial_cost, 9)

    def test_a2_runner_all_done_merged(self) -> None:
        llm = _llm_factory()
        runner = DelegateRunner(_runtime_for(llm), max_concurrent=_SUBAGENTS)
        delegate = make_delegate_tool(runner, registry=_SixRegistry())
        text = delegate(dimensions=[f"dim{i}" for i in range(_SUBAGENTS)], task="压测任务")
        assert text.count("状态: 完成") == _SUBAGENTS  # 全部 done，无 empty/error

    def test_a3_parallel_wall_converges(self) -> None:
        llm = _llm_factory()
        runner = DelegateRunner(_runtime_for(llm), max_concurrent=_SUBAGENTS)
        delegate = make_delegate_tool(runner, registry=_SixRegistry())
        dims = [f"dim{i}" for i in range(_SUBAGENTS)]

        t0 = time.monotonic()
        delegate(dimensions=dims, task="压测任务")
        parallel_wall = time.monotonic() - t0

        t1 = time.monotonic()
        for d in dims:
            delegate(dimensions=[d], task="压测任务")
        serial_wall = time.monotonic() - t1

        # 并行 3 次调用 ≈ 0.75s + 轮询开销；串行 18 次 ≈ 4.5s——0.6 阈值宽松不抖
        assert parallel_wall < serial_wall * 0.6, (
            f"疑似假并行：parallel={parallel_wall:.2f}s serial={serial_wall:.2f}s"
        )


class TestApiLevelStress:
    """A2 无丢失（compare 6 候选全收集）+ A4 取消传播。"""

    def _api(self, slow: bool = False) -> CompetitorAnalysisAPI:
        mock = BenchmarkMockLLM(competitor="", dimension="", page="")

        def call_func(messages: list[dict[str, str]], model: str | None = None, **kwargs: object) -> object:
            if slow:
                time.sleep(0.05)
            return mock.complete(messages, model=model, **kwargs)

        cfg = AppConfig(
            execution=ExecutionConfig(max_parallel_subagents=_SUBAGENTS),
            collector=CollectorConfig(block_private_urls=False),
        )
        return CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page=""),
            llm=LLMClient(call_func=call_func),
            use_llm=True,
            config=cfg,
            enable_rag=False,
            enable_memory=False,
            timeline=TimelineMemory(data_dir=Path(tempfile.mkdtemp(prefix="stress_timeline_"))),
        )

    def test_a2_compare_six_candidates_all_collected(self) -> None:
        api = self._api()
        task = "对比 cursor、copilot、codex、windsurf、aider、trae"
        sid = "sess_stress_a2"
        loop, _result = api._run_react_loop(task, sid)
        collector = getattr(loop, "_delegate_collector", {}) or {}
        assert len(collector) == _SUBAGENTS, f"候选收集不全: {sorted(collector)}"
        assert all(str(v).strip() for v in collector.values())  # 全部 done 才被收集

    def test_a4_cancel_terminates_within_timeout(self) -> None:
        from competitor_agent.core.checkpoint import set_cancel

        api = self._api(slow=True)
        sid = "sess_stress_a4"
        set_cancel(sid)  # 先置取消 → 取消信号贯穿 Lead loop 与委派门
        done: dict[str, bool] = {}

        def _work() -> None:
            try:
                api.run("对比 cursor 和 copilot", session_id=sid)
            finally:
                done["ok"] = True

        th = threading.Thread(target=_work, daemon=True)
        th.start()
        th.join(timeout=60)
        assert done.get("ok"), "取消后编排未在超时内终止"
