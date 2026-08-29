"""内置调度器（设计文档 67 §2.3.1）— 轻量 daemon 线程，无 apscheduler 硬依赖

- ``cron_matches``：简单 cron 表达式解析（minute hour day month weekday，支持
  ``*`` / ``*/n`` / ``a-b`` / ``n,m``），不引 apscheduler；
- ``WeeklyScheduler``：daemon 线程，interval 模式（``interval_hours``）或
  cron 模式（``cron_expr``）二选一；每次唤醒调 ``job()``（如 ``run_scheduled``），
  失败记日志不崩进程（守 doc 54 纪律）；
- 装配：Web 启动时若 ``schedule.enabled`` 则 ``start()``；CLI ``schedule --daemon`` 前台跑。
  外部 cron 仍可用，二者互斥由配置决定。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("competitor_agent.core.scheduler")


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """解析单字段 cron 表达式 → 命中值集合（* / */n / a-b / n,m / n）。"""
    values: set[int] = set()
    field = field.strip()
    if field == "*":
        return set(range(lo, hi + 1))
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            values.update(range(lo, hi + 1, step))
            continue
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            values.update(range(start, min(end, hi) + 1))
            continue
        values.add(int(part))
    return values


_WEEKDAY_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}


def _parse_weekday(field: str) -> set[int]:
    """weekday 字段（0-6，Sun=0）——支持英文缩写 mon..sun。"""
    lowered = field.strip().lower()
    if lowered in _WEEKDAY_NAMES:
        return {_WEEKDAY_NAMES[lowered]}
    return _parse_field(field, 0, 6)


class CronExpr:
    """简单 cron 表达式匹配器（5 字段：minute hour day month weekday）。

    日/星期语义对齐 Vixie cron：仅一个受限（另一为 ``*``）时按受限字段匹配；
    两者都受限时任一命中即可（OR）。
    """

    def __init__(self, expr: str) -> None:
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron 表达式需 5 段（minute hour day month weekday），得到: {expr!r}")
        self._minute = _parse_field(parts[0], 0, 59)
        self._hour = _parse_field(parts[1], 0, 23)
        self._day = _parse_field(parts[2], 1, 31)
        self._month = _parse_field(parts[3], 1, 12)
        self._weekday = _parse_weekday(parts[4])
        self._day_any = parts[2].strip() == "*"
        self._weekday_any = parts[4].strip() == "*"

    def matches(self, dt: datetime) -> bool:
        """判定 dt 是否命中（分钟级精度）。"""
        if dt.minute not in self._minute:
            return False
        if dt.hour not in self._hour:
            return False
        if dt.month not in self._month:
            return False
        day_ok = dt.day in self._day
        weekday_ok = (dt.weekday() + 1) % 7 in self._weekday  # Python Mon=0 → cron Sun=0
        if self._day_any and self._weekday_any:
            return True
        if self._day_any:  # 仅 day-of-week 受限 → 按星期匹配
            return weekday_ok
        if self._weekday_any:  # 仅 day-of-month 受限 → 按日匹配
            return day_ok
        return day_ok or weekday_ok  # 两者都受限 → 任一命中


def cron_matches(expr: str, dt: datetime) -> bool:
    """便捷入口：expr 命中 dt 则 True（解析失败记日志并返回 False，不崩）。"""
    try:
        return CronExpr(expr).matches(dt)
    except Exception:
        logger.warning("cron 表达式解析失败: %r", expr, exc_info=True)
        return False


class WeeklyScheduler:
    """轻量内置调度器：daemon 线程按 interval/cron 唤醒执行 job()。

    每轮唤醒（interval 模式：间隔到期；cron 模式：分钟命中且本分钟未跑）执行一次
    ``job()``；job 抛异常仅记日志不终止线程（守 doc 54 纪律）。
    """

    def __init__(
        self,
        job: Callable[[], Any],
        *,
        interval_hours: float = 24.0,
        cron_expr: str = "",
    ) -> None:
        if cron_expr and interval_hours:
            logger.info("同时给了 cron_expr 与 interval_hours，优先 cron_expr")
        self._job = job
        self._interval_hours = interval_hours
        self._cron_expr = cron_expr
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_run_at = 0.0
        self._last_cron_minute: str = ""

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self) -> None:
        """启动 daemon 线程（幂等：已启动直接返回）。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="weekly-scheduler")
            self._thread.start()
            logger.info("内置调度器已启动（%s）", self._describe())

    def stop(self) -> None:
        """停止调度线程（等待其退出）。"""
        self._stop.set()
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)
            logger.info("内置调度器已停止")

    def poll(self) -> None:
        """单次轮询判定 + 执行（供测试/手动触发；与 _run_loop 同语义）。"""
        now = datetime.now(timezone.utc)
        if self._should_run(now):
            self._run_job(now)

    # ── 内部 ──────────────────────────────────────────────────

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            if self._should_run(now):
                self._run_job(now)
            # 每 30s 轮询一次；cron 模式命中在分钟粒度，interval 模式由时间戳判定
            self._stop.wait(30.0)

    def _should_run(self, now: datetime) -> bool:
        if self._cron_expr:
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            if not cron_matches(self._cron_expr, now) or minute_key == self._last_cron_minute:
                return False
            self._last_cron_minute = minute_key
            return True
        if time.monotonic() - self._last_run_at < self._interval_hours * 3600:
            return False
        self._last_run_at = time.monotonic()
        return True

    def _run_job(self, now: datetime) -> None:
        logger.info("调度任务触发: %s", now.isoformat())
        try:
            self._job()
        except Exception:
            logger.exception("调度任务执行失败（不终止调度线程）")

    def _describe(self) -> str:
        if self._cron_expr:
            return f"cron={self._cron_expr!r}"
        return f"interval={self._interval_hours:g}h"


__all__ = ["CronExpr", "WeeklyScheduler", "cron_matches"]
