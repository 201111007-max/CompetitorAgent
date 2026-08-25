"""结构化日志 — JSON 格式 + 会话级落盘 + 关键路径埋点（设计文档 21）

能力：
- ``setup_logging()``：配置根 logger（JSON 或文本格式，注入 ObservabilityConfig.log_level）
- ``get_session_logger(sid)``：返回注入 ``session_id`` 的 LoggerAdapter；
  记录经根 logger 的 ``SessionRouterHandler`` 实时路由到 ``logs/<sid>.log``（每次 flush，不缓冲）
- ``log_event()``：结构化事件埋点（event/phase/字段并入 JSON）
- ``set_current_session()/current_session()``：线程局部会话上下文（LLM/并行工作线程无需显式传 sid）

detached / 重定向场景：会话日志直接写文件，不受 stdout 缓冲影响。
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from competitor_agent.secret_vault import get_data_dir

_ROOT = "competitor_agent"
_DEFAULT_LEVEL = logging.INFO

# LogRecord 保留属性（除这些之外的 record 属性视为埋点 extra 字段，并入 JSON）
_RESERVED_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
        "session_id", "event", "phase",
    }
)

_log_dir: Path = get_data_dir() / "logs"
_level = _DEFAULT_LEVEL
_json_format = True
_auto_flush = True
_configured = False
_config_lock = threading.Lock()

# 线程局部会话上下文：分析入口设置后，并行工作线程/LLM 调用无需显式传 sid
_session_ctx = threading.local()


def _current_session_id() -> str | None:
    return getattr(_session_ctx, "session_id", None)


def set_current_session(session_id: str | None) -> None:
    """为当前线程设置会话上下文（None 清除）"""
    _session_ctx.session_id = session_id


def current_session() -> str | None:
    """当前线程的会话 ID（无则 None）"""
    return _current_session_id()


# ── 格式化器 ───────────────────────────────────────────────────────────────


class SessionJSONFormatter(logging.Formatter):
    """结构化 JSON 格式器：ts/level/logger/session_id/phase/event + 埋点字段 + message"""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
        }
        session_id = getattr(record, "session_id", None) or _current_session_id()
        if session_id:
            data["session_id"] = session_id
        for key in ("event", "phase"):
            val = getattr(record, key, None)
            if val:
                data[key] = val
        for key, val in record.__dict__.items():
            if key.startswith("_") or key in _RESERVED_ATTRS:
                continue
            data[key] = val
        data["message"] = record.getMessage()
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """非 JSON 回退的文本格式器（json_format=False 时使用）"""

    _FMT = "%(asctime)s %(levelname)s [%(name)s]"

    def format(self, record: logging.LogRecord) -> str:
        record.asctime = self.formatTime(record, self.datefmt)
        prefix = self._FMT % record.__dict__
        session_id = getattr(record, "session_id", None) or _current_session_id()
        if session_id:
            prefix += f" (session={session_id})"
        event = getattr(record, "event", None)
        if event:
            prefix += f" [{event}]"
        return f"{prefix} {record.getMessage()}"


# ── 会话文件 handler ────────────────────────────────────────────────────────


class SessionFileHandler(logging.Handler):
    """会话级文件 handler：路径 logs/<session_id>.log，每次 emit 后 flush（不缓冲）。"""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._fh: IO[str] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _open_fh(self) -> IO[str]:
        if self._fh is None or self._fh.closed:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("a", encoding="utf-8")
        return self._fh

    def emit(self, record: logging.LogRecord) -> None:
        try:
            fh = self._open_fh()
            fh.write(self.format(record) + "\n")
            fh.flush()  # 实时落盘，detached/重定向也不丢日志
        except Exception:  # noqa: BLE001 - 日志写入失败不影响主流程
            self.handleError(record)

    def close(self) -> None:  # pragma: no cover - 进程结束时清理
        if self._fh is not None and not self._fh.closed:
            self._fh.flush()
            self._fh.close()
            self._fh = None
        super().close()


class SessionRouterHandler(logging.Handler):
    """根 handler：按记录 session_id 路由到 logs/<sid>.log（SessionFileHandler 实例）。"""

    def __init__(self, log_dir: Path) -> None:
        super().__init__()
        self._log_dir = Path(log_dir)
        self._handlers: dict[str, SessionFileHandler] = {}
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        session_id = getattr(record, "session_id", None) or _current_session_id()
        if not session_id:
            return
        with self._lock:
            handler = self._handlers.get(session_id)
            if handler is None:
                handler = SessionFileHandler(self._log_dir / f"{_safe_name(session_id)}.log")
                handler.setFormatter(self.formatter)
                self._handlers[session_id] = handler
            handler.emit(record)

    def close_session(self, session_id: str) -> None:
        with self._lock:
            handler = self._handlers.pop(session_id, None)
        if handler is not None:
            handler.close()


def _safe_name(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)


def log_file_path(session_id: str) -> Path:
    """会话日志文件路径（与 SessionRouterHandler 落盘一致，供 Web /api/logs 读取）"""
    return _log_dir / f"{_safe_name(session_id)}.log"


def read_session_log(session_id: str, tail: int | None = None) -> list[dict[str, Any]]:
    """读取会话日志为结构化行列表（tail 限定最近 N 行；文件不存在返回空列表）"""
    path = log_file_path(session_id)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if tail is not None and tail > 0:
        lines = lines[-tail:]
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"message": line})
    return out


# ── 初始化 ──────────────────────────────────────────────────────────────────


def setup_logging(
    *,
    level: str = "INFO",
    log_dir: Path | None = None,
    json_format: bool = True,
    auto_flush: bool = True,
) -> None:
    """配置根 logger：控制台 handler（JSON/文本）+ 会话路由 handler（落盘）。

    应仅在入口（web_app.main / cli.main / mcp）调用一次；幂等。
    """
    global _level, _json_format, _auto_flush, _log_dir, _configured
    with _config_lock:
        _level = getattr(logging, str(level).upper(), _DEFAULT_LEVEL)
        _json_format = json_format
        _auto_flush = auto_flush
        _log_dir = Path(log_dir) if log_dir is not None else (get_data_dir() / "logs")
        _log_dir.mkdir(parents=True, exist_ok=True)

        root = logging.getLogger(_ROOT)
        root.setLevel(_level)
        # 保持 propagate=True：兼容既有 caplog/根 logger 捕获行为
        root.propagate = True

        for handler in list(root.handlers):
            root.removeHandler(handler)

        formatter: logging.Formatter = (
            SessionJSONFormatter() if _json_format else TextFormatter()
        )
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

        router = SessionRouterHandler(_log_dir)
        router.setFormatter(formatter)
        root.addHandler(router)

        _configured = True


def _ensure_configured() -> None:
    """首次调用 get_logger 时若未 setup_logging，用默认配置兜底（保持向后兼容）。"""
    global _configured
    if _configured:
        return
    root = logging.getLogger(_ROOT)
    if not root.handlers:
        setup_logging()
    else:
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """按命名空间取 logger（首次调用自动配置根 logger，兼容旧行为）"""
    _ensure_configured()
    return logging.getLogger(f"{_ROOT}.{name}") if name != _ROOT else logging.getLogger(_ROOT)


# ── 会话级 logger ────────────────────────────────────────────────────────────

_session_adapters: dict[str, logging.LoggerAdapter] = {}
_session_adapters_lock = threading.Lock()


def get_session_logger(session_id: str | None = None) -> logging.LoggerAdapter:
    """按 session 返回 logger：记录自动携带 session_id，并实时落盘 logs/<sid>.log。

    session_id 缺省时取当前线程上下文（set_current_session 注入）。
    """
    _ensure_configured()
    sid = session_id or _current_session_id()
    if not sid:
        return logging.LoggerAdapter(logging.getLogger(_ROOT), {})
    with _session_adapters_lock:
        cached = _session_adapters.get(sid)
        if cached is not None:
            return cached
        name = f"{_ROOT}.session.{sid}"
        logger = logging.getLogger(name)
        logger.propagate = True
        logger.setLevel(_level)
        adapter = logging.LoggerAdapter(logger, {"session_id": sid})
        _session_adapters[sid] = adapter
        return adapter


def close_session_log(session_id: str | None) -> None:
    """会话结束时关闭会话文件句柄（flush 落盘 + 释放资源）。"""
    if not session_id:
        return
    with _session_adapters_lock:
        _session_adapters.pop(session_id, None)
    for handler in list(logging.getLogger(_ROOT).handlers):
        if isinstance(handler, SessionRouterHandler):
            handler.close_session(session_id)


# ── 结构化事件埋点 ───────────────────────────────────────────────────────────


def _emit_with_extra(
    logger: logging.Logger | logging.LoggerAdapter, message: str, extra: dict[str, Any]
) -> None:
    """向 logger 打日志并合并 extra。

    LoggerAdapter.process 会用 self.extra 覆盖调用方 extra，因此这里直接合并后
    调用底层 logger，确保 event/phase/字段都进入记录。
    """
    # 过滤与 LogRecord 保留属性冲突的字段（如 name/msg），避免 makeRecord 抛 KeyError
    extra = {k: v for k, v in extra.items() if k not in _RESERVED_ATTRS or k in ("session_id", "event", "phase")}
    if isinstance(logger, logging.LoggerAdapter):
        merged = {**(logger.extra or {}), **extra}
        logger.logger.info(message, extra=merged)
    else:
        if "session_id" not in extra and _current_session_id():
            extra["session_id"] = _current_session_id()
        logger.info(message, extra=extra)


def log_event(
    logger: logging.Logger | logging.LoggerAdapter,
    event: str,
    phase: str = "",
    message: str = "",
    **fields: Any,
) -> None:
    """结构化事件日志：event/phase/自定义字段并入 JSON（session_id 由 adapter/线程上下文注入）。"""
    extra: dict[str, Any] = {"event": event, "phase": phase}
    extra.update(fields)
    _emit_with_extra(logger, message, extra)


def emit_session_event(
    event: str,
    phase: str = "",
    message: str = "",
    session_id: str | None = None,
    **fields: Any,
) -> None:
    """用会话 logger 打结构化事件（无会话时落根 logger，不抛错）。"""
    slog = get_session_logger(session_id)
    extra: dict[str, Any] = {"event": event, "phase": phase}
    extra.update(fields)
    _emit_with_extra(slog, message, extra)


__all__ = [
    "SessionFileHandler",
    "SessionJSONFormatter",
    "SessionRouterHandler",
    "TextFormatter",
    "close_session_log",
    "current_session",
    "emit_session_event",
    "get_logger",
    "get_session_logger",
    "log_event",
    "log_file_path",
    "read_session_log",
    "set_current_session",
    "setup_logging",
]
