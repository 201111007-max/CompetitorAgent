"""设计文档 88 §5 —— report.writer_pass / writer_slot_max_retries 配置键单测。

覆盖：dataclass 默认值（writer_pass=False 纯骨架确定路径 / 重试 1 次）、
repo 自带 review_config.yaml 加载后两键生效、yaml 缺省时默认值兜底。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from competitor_agent.config.loader import ReportConfig, load_config

_REPO_YAML = Path(__file__).resolve().parents[3] / "config" / "review_config.yaml"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # load_config 优先读 COMPETITOR_AGENT_CONFIG 环境变量，测试须隔离
    monkeypatch.delenv("COMPETITOR_AGENT_CONFIG", raising=False)


class TestWriterConfigDefaults:
    def test_defaults(self) -> None:
        cfg = ReportConfig()
        assert cfg.writer_pass is False
        assert cfg.writer_slot_max_retries == 1

    def test_repo_yaml_loads_writer_keys(self) -> None:
        cfg = load_config(_REPO_YAML)
        assert cfg.report.writer_pass is False
        assert cfg.report.writer_slot_max_retries == 1

    def test_yaml_override(self, tmp_path: Path) -> None:
        override = tmp_path / "cfg.yaml"
        override.write_text(
            "report:\n  writer_pass: true\n  writer_slot_max_retries: 2\n", encoding="utf-8"
        )
        cfg = load_config(override)
        assert cfg.report.writer_pass is True
        assert cfg.report.writer_slot_max_retries == 2

    def test_missing_keys_fall_back_to_defaults(self, tmp_path: Path) -> None:
        minimal = tmp_path / "minimal.yaml"
        minimal.write_text("report:\n  export_json: true\n", encoding="utf-8")
        cfg = load_config(minimal)
        assert cfg.report.writer_pass is False
        assert cfg.report.writer_slot_max_retries == 1
