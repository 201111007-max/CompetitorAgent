"""JSON 持久化基类 — 记忆各层共用的小型键值/列表存储

语义：
- 每个记忆层一个独立 JSON 文件（data_dir/<name>.json）
- 写入为原子写（先写临时文件再 rename），避免并发/中断破话
- 从磁盘惰性加载，仅在有变更时落盘
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.memory.json_store")


class JsonStore:
    """将任意可 JSON 序列化对象持久化到一个文件"""

    def __init__(self, name: str, data_dir: Path | str | None = None) -> None:
        self._name = name
        base = Path(data_dir) if data_dir else get_data_dir()
        base = base / "memory"
        base.mkdir(parents=True, exist_ok=True)
        self._path = base / f"{name}.json"
        self._data: dict[str, Any] = {}
        self._dirty = False
        self._load()

    # ---- 读取接口 ----
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def all(self) -> dict[str, Any]:
        return dict(self._data)

    def __iter__(self) -> Any:
        return iter(self._data)

    # ---- 写入接口 ----
    def put(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True

    def remove(self, key: str) -> None:
        if key in self._data:
            del self._data[key]
            self._dirty = True

    def clear(self) -> None:
        self._data.clear()
        self._dirty = True

    # ---- 持久化 ----
    def save(self) -> None:
        """显式落盘（可批量化延迟写）"""
        if not self._dirty:
            return
        tmp = self._path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)
        self._dirty = False
        logger.debug("记忆层 %s 已落盘: %s", self._name, self._path)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                loaded = json.load(f)
            self._data = loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("记忆层 %s 加载失败，重置: %s", self._name, exc)
            self._data = {}


def now_iso() -> str:
    """UTC ISO 时间戳"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())