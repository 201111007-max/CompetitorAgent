"""MessageBus 异步增强测试（设计文档 33 §3.1）

- subscribe_async + publish_async：异步订阅者收到消息
- await_result=True：编排器收集 Agent 产出
- timeout：订阅者超时 → 记 DEGRADED，不阻塞流水线
- 同步订阅者与既有 publish 完全兼容
"""
from __future__ import annotations

import asyncio

from competitor_agent.team.message_bus import MessageBus


class TestMessageBusAsync:
    def test_subscribe_async_receives_message(self):
        bus = MessageBus()
        got = []

        async def handler(env):
            got.append(env.payload)

        bus.subscribe_async("t", handler)
        asyncio.run(bus.publish_async("t", {"x": 1}))
        assert got == [{"x": 1}]

    def test_await_result_collects_agent_production(self):
        bus = MessageBus()

        async def handler(env):
            return env.payload["value"] * 2

        bus.subscribe_async("t", handler)
        result = asyncio.run(bus.publish_async("t", {"value": 21}, await_result=True))
        assert result == [42]

    def test_timeout_records_degraded_without_blocking(self):
        bus = MessageBus()

        async def slow(env):
            await asyncio.sleep(5)

        bus.subscribe_async("t", slow)
        result = asyncio.run(bus.publish_async("t", {"x": 1}, await_result=True, timeout=0.05))
        assert result == [None]  # 超时返回 None 而非抛异常
        degraded = bus.degraded()
        assert len(degraded) == 1
        assert degraded[0].topic == "t"
        assert degraded[0].reason == "timeout"

    def test_async_subscriber_error_degrades(self):
        bus = MessageBus()

        async def boom(env):
            raise RuntimeError("boom")

        bus.subscribe_async("t", boom)
        result = asyncio.run(bus.publish_async("t", {}, await_result=True))
        assert result == [None]
        assert bus.degraded()[0].reason.startswith("error:")

    def test_no_async_subscribers_returns_none_list(self):
        bus = MessageBus()
        result = asyncio.run(bus.publish_async("t", {"x": 1}, await_result=True))
        assert result == [None]

    def test_publish_async_without_await_result_returns_envelope(self):
        bus = MessageBus()

        async def handler(env):
            return "ok"

        bus.subscribe_async("t", handler)
        env = asyncio.run(bus.publish_async("t", {"x": 1}))
        assert env.topic == "t"
        assert bus.history("t")  # 消息已记入审计日志

    def test_sync_subscribers_still_receive_on_async_publish(self):
        bus = MessageBus()
        got = []
        bus.subscribe("t", lambda env: got.append(env.payload))
        asyncio.run(bus.publish_async("t", {"x": 1}))
        assert got == [{"x": 1}]

    def test_parallel_await_result_via_gather(self):
        """编排器可 gather 多个请求并行等待各 Agent 产出"""
        bus = MessageBus()

        async def handler(env):
            await asyncio.sleep(0.01)
            return env.payload["i"] * 10

        bus.subscribe_async("t", handler)

        async def main() -> list[list[int]]:
            coros = [
                bus.publish_async("t", {"i": i}, await_result=True) for i in range(3)
            ]
            return await asyncio.gather(*coros)

        results = asyncio.run(main())
        assert [r[0] for r in results] == [0, 10, 20]

    def test_wildcard_async_subscriber_receives_all(self):
        bus = MessageBus()
        topics = []

        async def handler(env):
            topics.append(env.topic)

        bus.subscribe_async("", handler)
        asyncio.run(bus.publish_async("a", 1))
        asyncio.run(bus.publish_async("b", 2))
        assert topics == ["a", "b"]
