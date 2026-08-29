"""设计文档 67 §2.3.1 — 内置调度器单测。

cron 简单解析器（* / */n / a-b / n,m / 英文缩写星期）、WeeklyScheduler 间隔唤醒调 job、
异常不崩线程（守 doc 54 纪律）。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest

from competitor_agent.core.scheduler import CronExpr, WeeklyScheduler, cron_matches


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """tz-aware datetime（cron 字段判定不依赖时区，但守 DTZ 纪律）。"""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestCronMatches:
    def test_every_minute(self):
        assert cron_matches("* * * * *", _dt(2026, 8, 1, 10, 0))

    def test_specific_minute_hour(self):
        assert cron_matches("30 3 * * *", _dt(2026, 8, 1, 3, 30))
        assert not cron_matches("30 3 * * *", _dt(2026, 8, 1, 3, 31))
        assert not cron_matches("30 3 * * *", _dt(2026, 8, 1, 4, 30))

    def test_interval_field(self):
        # */5 分钟
        assert cron_matches("*/5 * * * *", _dt(2026, 8, 1, 10, 0))
        assert cron_matches("*/5 * * * *", _dt(2026, 8, 1, 10, 5))
        assert not cron_matches("*/5 * * * *", _dt(2026, 8, 1, 10, 3))

    def test_range_and_list(self):
        assert cron_matches("0 8-10 * * *", _dt(2026, 8, 1, 9, 0))
        assert cron_matches("0 8,20 * * *", _dt(2026, 8, 1, 20, 0))
        assert not cron_matches("0 8,20 * * *", _dt(2026, 8, 1, 9, 0))

    def test_weekday_name_and_alt(self):
        # 2026-08-29 是周六；cron 0=sun..6=sat → sat=6；Python weekday Mon=0 → sat=5 → (5+1)%7=6
        assert cron_matches("0 0 * * sat", _dt(2026, 8, 29))
        assert not cron_matches("0 0 * * mon", _dt(2026, 8, 29))

    def test_day_or_weekday_any(self):
        # 日=1 或 星期=sat 任一命中
        assert cron_matches("0 0 1 * sat", _dt(2026, 8, 1))
        assert cron_matches("0 0 1 * sat", _dt(2026, 8, 29))

    def test_invalid_expr_returns_false(self):
        assert cron_matches("not a cron", datetime.now(timezone.utc)) is False


class TestWeeklyScheduler:
    def test_interval_poll_runs_job(self):
        calls: list[str] = []
        s = WeeklyScheduler(lambda: calls.append("run"), interval_hours=0.00001)  # ~36ms
        s.poll()  # interval 模式首轮立即执行
        s.poll()  # 未到间隔不重复
        s.poll()
        assert calls.count("run") == 1

    def test_cron_poll_runs_on_match_once_per_minute(self):
        calls: list[str] = []
        s = WeeklyScheduler(lambda: calls.append("run"), cron_expr="* * * * *")
        s._last_run_at = 0.0
        s.poll()
        s.poll()  # 同分钟不重复
        assert calls.count("run") == 1

    def test_start_stop_lifecycle(self):
        flag = threading.Event()
        s = WeeklyScheduler(lambda: flag.set(), interval_hours=0.00001)
        s.start()
        assert s._thread is not None and s._thread.is_alive()
        assert flag.wait(timeout=5.0)
        s.stop()
        assert s._thread is None or not s._thread.is_alive()

    def test_exception_does_not_kill_thread(self):
        flag = threading.Event()

        def job() -> None:
            try:
                raise RuntimeError("boom")
            finally:
                flag.set()

        s = WeeklyScheduler(job, interval_hours=0.00001)
        s.start()
        assert flag.wait(timeout=5.0)
        time.sleep(0.05)  # 异常已被吞掉，线程应仍存活
        assert s._thread is not None and s._thread.is_alive()
        s.stop()

    def test_cron_expr_validation(self):
        with pytest.raises(ValueError):
            CronExpr("0 3 * *")  # 只有 4 段
