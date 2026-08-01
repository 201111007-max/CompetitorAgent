"""消息总线单元测试"""
import pytest

from dota_helper.agent.message_bus import MessageBus, EventType, Message


class TestMessageBus:
    """测试 MessageBus 的发布/订阅功能"""

    def setup_method(self) -> None:
        self.bus = MessageBus(max_history=100)

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self) -> None:
        """订阅和发布消息"""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        self.bus.subscribe(EventType.RESULT_READY, handler)

        msg = Message(
            event_type=EventType.RESULT_READY,
            sender="agent_1",
            payload={"phase": "laning", "confidence": 0.8},
        )
        delivered = await self.bus.publish(msg)

        assert delivered == 1
        assert len(received) == 1
        assert received[0].sender == "agent_1"
        assert received[0].payload["phase"] == "laning"

    @pytest.mark.asyncio
    async def test_publish_with_no_subscribers(self) -> None:
        """无订阅者时发布消息"""
        msg = Message(
            event_type=EventType.RESULT_READY,
            sender="agent_1",
            payload="data",
        )
        delivered = await self.bus.publish(msg)
        assert delivered == 0

    @pytest.mark.asyncio
    async def test_subscribe_with_sender_filter(self) -> None:
        """按发送者过滤订阅"""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        self.bus.subscribe(EventType.RESULT_READY, handler, sender_filter="agent_1")

        msg1 = Message(EventType.RESULT_READY, "agent_1", "data1")
        msg2 = Message(EventType.RESULT_READY, "agent_2", "data2")

        await self.bus.publish(msg1)
        await self.bus.publish(msg2)

        assert len(received) == 1
        assert received[0].sender == "agent_1"

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        """取消订阅"""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        self.bus.subscribe(EventType.RESULT_READY, handler)
        result = self.bus.unsubscribe(EventType.RESULT_READY, handler)
        assert result is True

        await self.bus.publish(Message(EventType.RESULT_READY, "agent_1", "data"))
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent(self) -> None:
        """取消不存在的订阅返回 False"""
        async def handler(msg: Message) -> None:
            pass

        result = self.bus.unsubscribe(EventType.RESULT_READY, handler)
        assert result is False

    @pytest.mark.asyncio
    async def test_publish_result_ready(self) -> None:
        """快捷发布 RESULT_READY"""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        self.bus.subscribe(EventType.RESULT_READY, handler)
        delivered = await self.bus.publish_result_ready("agent_1", {"phase": "laning"})

        assert delivered == 1
        assert received[0].event_type == EventType.RESULT_READY
        assert received[0].sender == "agent_1"

    @pytest.mark.asyncio
    async def test_publish_error(self) -> None:
        """快捷发布 ERROR"""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        self.bus.subscribe(EventType.ERROR, handler)
        delivered = await self.bus.publish_error("agent_1", ValueError("bad data"))

        assert delivered == 1
        assert received[0].event_type == EventType.ERROR
        assert received[0].payload["error_type"] == "ValueError"
        assert received[0].payload["error_msg"] == "bad data"

    @pytest.mark.asyncio
    async def test_publish_status(self) -> None:
        """快捷发布 STATUS_CHANGE"""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        self.bus.subscribe(EventType.STATUS_CHANGE, handler)
        delivered = await self.bus.publish_status("agent_1", "running")

        assert delivered == 1
        assert received[0].event_type == EventType.STATUS_CHANGE
        assert received[0].payload["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_history(self) -> None:
        """查询消息历史"""
        await self.bus.publish_result_ready("agent_1", "result1")
        await self.bus.publish_result_ready("agent_2", "result2")
        await self.bus.publish_error("agent_1", ValueError("err"))

        # 按类型过滤
        results = self.bus.get_history(event_type=EventType.RESULT_READY)
        assert len(results) == 2

        # 按发送者过滤
        agent1_msgs = self.bus.get_history(sender="agent_1")
        assert len(agent1_msgs) == 2

        # 组合过滤
        filtered = self.bus.get_history(event_type=EventType.ERROR, sender="agent_1")
        assert len(filtered) == 1
        assert filtered[0].payload["error_type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_history_limit(self) -> None:
        """历史消息数量限制"""
        bus = MessageBus(max_history=5)
        for i in range(10):
            await bus.publish_result_ready(f"agent_{i}", f"result_{i}")

        assert bus.history_count == 5

    @pytest.mark.asyncio
    async def test_clear_history(self) -> None:
        """清空历史"""
        await self.bus.publish_result_ready("agent_1", "data")
        assert self.bus.history_count == 1

        self.bus.clear_history()
        assert self.bus.history_count == 0

    @pytest.mark.asyncio
    async def test_subscriber_count(self) -> None:
        """订阅者计数"""
        assert self.bus.subscriber_count == 0

        async def h1(msg: Message) -> None:
            pass

        async def h2(msg: Message) -> None:
            pass

        self.bus.subscribe(EventType.RESULT_READY, h1)
        self.bus.subscribe(EventType.ERROR, h2)
        assert self.bus.subscriber_count == 2

    @pytest.mark.asyncio
    async def test_handler_error_does_not_break_bus(self) -> None:
        """处理函数异常不影响总线"""
        received: list[Message] = []

        async def broken_handler(msg: Message) -> None:
            raise RuntimeError("broken")

        async def good_handler(msg: Message) -> None:
            received.append(msg)

        self.bus.subscribe(EventType.RESULT_READY, broken_handler)
        self.bus.subscribe(EventType.RESULT_READY, good_handler)

        delivered = await self.bus.publish_result_ready("agent_1", "data")
        # delivered 只计数成功处理的订阅者
        assert delivered == 1
        # good_handler 正常处理
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_message_has_unique_id(self) -> None:
        """每条消息有唯一 ID"""
        msg1 = Message(EventType.CUSTOM, "agent_1", "data")
        msg2 = Message(EventType.CUSTOM, "agent_1", "data")
        assert msg1.message_id != msg2.message_id
