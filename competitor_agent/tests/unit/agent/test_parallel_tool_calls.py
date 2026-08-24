"""设计文档 59 §5 单测 — 并行 tool_calls 并发分发（确定性）

- 并发确实发生：注入带 ``threading.Barrier(2)`` 的 fake 工具，一个回合 2 个 tool_calls——
  Barrier 同步确保两工具真正并发进入（串行下首个在此阻塞超时破障抛 BrokenBarrierError，
  不靠 sleep 猜测）；断言回灌/transcript 顺序与原序一致。
- 边界：``max_parallel_tool_calls=1`` → 完全串行、不建线程池（回归网）；
  单 tool_call（默认并发模式）短路不建线程池；``_dispatch_call`` 单失败不影响其他
  （一个"工具不可用"其余正常，两消息都按原序回灌）。

全程 mock、零真实网络与 API Key。
"""
from __future__ import annotations

import threading

from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply


def _reply(content: str = "", *calls: ToolCall) -> ToolCallReply:
    return ToolCallReply(content=content, tool_calls=list(calls))


def _single_call(name: str, args: dict, call_id: str = "call_0") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


def _final(text: str) -> ToolCallReply:
    return _reply(content=text)


def _spy_pool_factory(instantiations: list[int]):
    """返回把 ThreadPoolExecutor 换成记录器的 pytest fixture 辅助（断言不建池）。"""

    class SpyPool:
        def __init__(self, max_workers=None):
            instantiations.append(max_workers)

        def submit(self, *a, **k):
            raise AssertionError("该路径不应创建线程池")

        def shutdown(self, wait=True):
            pass

    return SpyPool


class TestConcurrentDispatch:
    def test_two_tools_truly_concurrent_via_barrier(self):
        """Barrier(2) 确定性证明并发：两工具同时进入才不破障；回灌/transcript 按原序。"""
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        entered: list[str] = []

        def tool_a():
            with lock:
                entered.append("a")
            barrier.wait(timeout=5)  # 串行下首个在此阻塞超时抛 BrokenBarrierError
            return "a_ok"

        def tool_b():
            with lock:
                entered.append("b")
            barrier.wait(timeout=5)
            return "b_ok"

        captured: list[dict] = []
        transcript: list[str] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                return _reply(
                    "", _single_call("tool_a", {}, "c1"), _single_call("tool_b", {}, "c2")
                )
            return _final("done")

        d = ToolDispatcher({"tool_a": tool_a, "tool_b": tool_b})
        agent = ReactAgent(llm=LLMClient(call_func=spy), dispatcher=d)
        answer = agent.run(
            agent.build_system_prompt(), "任务",
            on_step=lambda rec: transcript.append(rec["tool"]),
        )
        assert answer == "done"
        assert set(entered) == {"a", "b"} and len(entered) == 2  # 两工具都真正执行
        sent = captured[1]
        tool_msgs = [m for m in sent if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]  # 按原序回灌
        contents = [m["content"] for m in tool_msgs]
        assert "a_ok" in contents[0] and "b_ok" in contents[1], "串行会因 Barrier 破障而返回异常文本"
        assert "BrokenBarrierError" not in contents[0] and "BrokenBarrierError" not in contents[1]
        assert transcript == ["tool_a", "tool_b"]  # transcript 也按原序捕获

    def test_single_tool_error_does_not_affect_others(self):
        """错误隔离：缺工具转"工具不可用"文本，其余工具正常返回，两消息都按原序回灌。"""
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                return _reply(
                    "", _single_call("missing_tool", {}, "c_bad"),
                    _single_call("echo", {"v": 1}, "c_ok"),
                )
            return _final("done")

        d = ToolDispatcher({"echo": lambda v: f"echo:{v}"})
        agent = ReactAgent(llm=LLMClient(call_func=spy), dispatcher=d)
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "done"
        sent = captured[1]
        tool_msgs = [m for m in sent if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["c_bad", "c_ok"]
        assert "工具不可用" in tool_msgs[0]["content"]  # 缺工具转可回灌文本、不冒泡
        assert "echo:1" in tool_msgs[1]["content"]  # 其余正常


class TestFacadeWiring:
    def test_api_stores_default_four(self):
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        assert CompetitorAnalysisAPI(extractor=None, use_llm=False)._max_parallel_tool_calls == 4

    def test_api_forwards_to_lead_agent(self, monkeypatch):
        """facade._react_loop 把 max_parallel_tool_calls 传给 Lead ReactAgent（设计文档 59 §3.2）。"""
        from competitor_agent.domain_types.competitor import Competitor
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        api = CompetitorAnalysisAPI(extractor=None, use_llm=False, max_parallel_tool_calls=1)
        monkeypatch.setattr(api, "_react_competitor", lambda task: Competitor(name="cursor"))
        loop = api._react_loop("分析 cursor", session_id=None)
        assert loop._agent._max_parallel_tool_calls == 1  # Lead 收到同一值


class TestParallelBoundaries:
    def test_max_parallel_one_is_fully_serial_no_pool(self, monkeypatch):
        """max_parallel_tool_calls=1 → 完全串行（回归网），不建线程池。"""
        instantiations: list[int] = []
        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor", _spy_pool_factory(instantiations)
        )
        order: list[str] = []
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                return _reply(
                    "",
                    _single_call("echo", {"v": 1}, "c1"),
                    _single_call("echo", {"v": 2}, "c2"),
                    _single_call("echo", {"v": 3}, "c3"),
                )
            return _final("done")

        d = ToolDispatcher({"echo": lambda v: (order.append(f"e{v}"), f"echo:{v}")[1]})
        agent = ReactAgent(
            llm=LLMClient(call_func=spy), dispatcher=d, max_parallel_tool_calls=1
        )
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "done"
        assert instantiations == []  # 串行分支不触碰 ThreadPoolExecutor
        assert order == ["e1", "e2", "e3"]  # 严格串行执行序
        sent = captured[1]
        tool_msgs = [m for m in sent if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2", "c3"]

    def test_single_tool_call_no_thread_pool(self, monkeypatch):
        """单 tool_call（默认并发模式）短路走串行，不建线程池。"""
        instantiations: list[int] = []
        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor", _spy_pool_factory(instantiations)
        )
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                return _reply("", _single_call("echo", {"v": 1}, "c1"))
            return _final("done")

        d = ToolDispatcher({"echo": lambda v: f"echo:{v}"})
        agent = ReactAgent(llm=LLMClient(call_func=spy), dispatcher=d)  # 默认 max_parallel=4
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "done"
        assert instantiations == []
        sent = captured[1]
        tool_msgs = [m for m in sent if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["c1"]

    def test_two_calls_limited_by_max_parallel_one(self, monkeypatch):
        """2 个 tool_calls + max_parallel=1 → 并发分支被上限压回串行（不建池）。"""
        instantiations: list[int] = []
        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor", _spy_pool_factory(instantiations)
        )
        order: list[str] = []
        captured: list[dict] = []

        def spy(messages, model=None, **kwargs):
            captured.append([dict(m) for m in messages])
            if len(captured) == 1:
                return _reply(
                    "",
                    _single_call("echo", {"v": 1}, "c1"),
                    _single_call("echo", {"v": 2}, "c2"),
                )
            return _final("done")

        d = ToolDispatcher({"echo": lambda v: (order.append(f"e{v}"), f"echo:{v}")[1]})
        agent = ReactAgent(
            llm=LLMClient(call_func=spy), dispatcher=d, max_parallel_tool_calls=1
        )
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "done"
        assert instantiations == []
        assert order == ["e1", "e2"]  # 串行
