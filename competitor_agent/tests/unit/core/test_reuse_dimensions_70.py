"""设计文档 70 M3 — 维度级增量复用工具单测（历史报告当知识库，精确复用不重跑）。

覆盖：未过期维度返回可复用结果（as_of + 证据）/ 过期不返回 / 缺失维度不返回 /
无历史文件可读提示 / 损坏 JSON 不炸 / TTL 取配置（pricing=7 天）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from competitor_agent.config.loader import AppConfig
from competitor_agent.core import report_archiver as ra
from competitor_agent.core.reuse_dimensions import reuse_dimension_results


def _history(created: str, dims: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "competitor": "cursor",
        "created_at": created,
        "dimensions": dims,
    }


def _write(out: Path, data: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / "cursor.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _patch(monkeypatch: pytest.MonkeyPatch, out: Path, cfg: AppConfig | None = None) -> None:
    monkeypatch.setattr(ra, "resolve_output_dir", lambda *a, **k: out)
    monkeypatch.setattr("competitor_agent.config.loader.load_config", lambda: cfg or AppConfig())


class TestReuseDimensionResults:
    def test_fresh_dimension_reusable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, tmp_path)
        now = datetime.now(timezone.utc).isoformat()
        _write(tmp_path, _history(
            now,
            [{"field": "pricing", "confidence": 0.8, "summary": "Pro $20/mo",
              "evidence": [{"url": "https://cursor.com/pricing"}]}],
        ))
        text = reuse_dimension_results("cursor", ["pricing"])
        assert "可直接复用" in text
        assert "pricing" in text
        assert "Pro $20/mo" in text
        assert "as_of" in text
        assert "https://cursor.com/pricing" in text

    def test_stale_dimension_not_reused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, tmp_path)
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        _write(tmp_path, _history(
            old,
            [{"field": "pricing", "confidence": 0.8, "summary": "Pro $20/mo", "evidence": []}],
        ))
        text = reuse_dimension_results("cursor", ["pricing"])
        assert "可直接复用" not in text
        assert "已过期/缺失" in text

    def test_missing_dimension_not_reused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, tmp_path)
        _write(tmp_path, _history(
            datetime.now(timezone.utc).isoformat(),
            [{"field": "feature", "confidence": 0.9, "summary": "AI 编辑器", "evidence": []}],
        ))
        text = reuse_dimension_results("cursor", ["pricing"])
        assert "可直接复用" not in text

    def test_no_history_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, tmp_path)
        text = reuse_dimension_results("cursor", ["pricing"])
        assert "无历史维度结果可复用" in text

    def test_corrupt_json_no_crash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "cursor.json").write_text("not json{{{", encoding="utf-8")
        text = reuse_dimension_results("cursor", ["pricing"])
        assert "读取失败" in text

    def test_empty_target(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, tmp_path)
        assert "参数缺失" in reuse_dimension_results("", ["pricing"])
