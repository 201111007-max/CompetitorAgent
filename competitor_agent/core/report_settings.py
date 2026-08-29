"""报告目录设置 — 项目默认 output/download + <data_dir>/settings.json 持久化覆盖（设计文档 70）

用户决策（2026-08-29）：落盘默认项目 `output/`、下载默认项目 `download/`、
Web 运行时入口（A2）可改、持久化 `<data_dir>/settings.json`。

目录解析优先级（report_archiver.resolve_output_dir）：
显式 output_dir 参数 > settings.json > config.report.output_dir（YAML，置空则跳过）> 项目默认。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from competitor_agent.core.checkpoint import _write_bytes_atomic
from competitor_agent.secret_vault import get_data_dir

logger = logging.getLogger("competitor_agent.core.report_settings")

_OUTPUT_KEY = "report_output_dir"
_DOWNLOAD_KEY = "report_download_dir"
_VALID_KEYS = frozenset({_OUTPUT_KEY, _DOWNLOAD_KEY})


def project_dir() -> Path:
    """项目根目录 = 本包 __file__ 的上级三级（core → competitor_agent → 仓库根）。"""
    return Path(__file__).resolve().parents[2]


def default_output_dir() -> Path:
    """默认报告落盘目录：<项目根>/output（设计文档 70）。"""
    return project_dir() / "output"


def default_download_dir() -> Path:
    """默认下载目录：<项目根>/download（设计文档 70）。"""
    return project_dir() / "download"


def settings_path() -> Path:
    """设置文件路径：<data_dir>/settings.json（data_dir 默认 ~/.competitor_agent）。"""
    return get_data_dir() / "settings.json"


def read_settings() -> dict[str, str]:
    """读取 settings.json；缺文件/坏 JSON/非对象 → 空 dict（不抛）。"""
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in _VALID_KEYS}


def write_settings(updates: dict[str, str]) -> dict[str, str]:
    """合并写入 settings.json（原子）；未涉及的键保留。返回更新后全量。"""
    data = read_settings()
    for k, v in updates.items():
        if k in _VALID_KEYS:
            data[k] = str(v)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomic(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    return data


def get_setting(key: str) -> str:
    """读取单个设置值（未设置 → ""）。"""
    return read_settings().get(key, "")


__all__ = [
    "default_download_dir",
    "default_output_dir",
    "get_setting",
    "project_dir",
    "read_settings",
    "settings_path",
    "write_settings",
]
