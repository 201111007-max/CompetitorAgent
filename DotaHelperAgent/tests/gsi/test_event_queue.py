"""GSI 事件队列测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.models import GSIEvent
from gsi.event_queue import GSIEventQueue


class TestGSIEventQueue:
    def test_put_and_get(self):
        eq = GSIEventQueue()
        eq.put(GSIEvent(event_type="stack", message="堆野"))
        result = eq.get(timeout=1.0)
        assert result is not None
        assert result.event_type == "stack"

    def test_get_timeout(self):
        eq = GSIEventQueue()
        assert eq.get(timeout=0.1) is None

    def test_get_recent(self):
        eq = GSIEventQueue()
        for i in range(5):
            eq.put(GSIEvent(event_type=f"t_{i}", message=f"m_{i}"))
        recent = eq.get_recent(3)
        assert len(recent) == 3
        assert recent[0].event_type == "t_2"

    def test_max_history(self):
        eq = GSIEventQueue(max_history=5)
        for i in range(10):
            eq.put(GSIEvent(event_type=f"t_{i}", message=f"m_{i}"))
        recent = eq.get_recent(10)
        assert len(recent) == 5

    def test_subscribe_unsubscribe(self):
        eq = GSIEventQueue()
        sub = eq.subscribe()
        assert eq.subscriber_count == 1
        eq.unsubscribe(sub)
        assert eq.subscriber_count == 0

    def test_subscriber_receives_events(self):
        eq = GSIEventQueue()
        sub = eq.subscribe()
        eq.put(GSIEvent(event_type="rune", message="中符"))
        received = sub.get(timeout=1.0)
        assert received.event_type == "rune"

    def test_clear_history(self):
        eq = GSIEventQueue()
        eq.put(GSIEvent(event_type="t1", message="m1"))
        eq.clear_history()
        assert len(eq.get_recent(10)) == 0
