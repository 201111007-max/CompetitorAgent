"""结构化日志"""
from __future__ import annotations

import logging
import sys

_ROOT = "competitor_agent"
_configured = False


def get_logger(name: str) -> logging.Logger:
    """按命名空间取 logger（首次自动配置根 logger）"""
    global _configured
    if not _configured:
        _setup_root()
        _configured = True
    return logging.getLogger(f"{_ROOT}.{name}") if name != _ROOT else logging.getLogger(_ROOT)


def _setup_root() -> None:
    root = logging.getLogger(_ROOT)
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)