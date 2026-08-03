"""配置加载冒烟测试 — M0 0.3 验证：review_config.yaml 可被 yaml.safe_load 通过

断言关键字段存在且类型正确，保证骨架配置与 M1 实现的契约一致。
"""
from pathlib import Path

import yaml

_CONFIG_PATH = (
    Path(__file__).parent.parent.parent / "config" / "review_config.yaml"
)


def test_config_file_exists() -> None:
    assert _CONFIG_PATH.is_file(), f"缺少配置文件: {_CONFIG_PATH}"


def test_config_loads_as_yaml() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    assert isinstance(raw, dict)


def test_budget_defaults_present() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    budget = raw["budget"]
    assert budget["max_iterations"] == 10
    assert budget["cost_limit_usd"] == 1.0
    assert budget["max_parallel_subagents"] == 4


def test_termination_thresholds_valid() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    term = raw["termination"]
    assert 0 < term["core_priority_threshold"] <= 10
    assert 0.0 <= term["core_confidence"] <= 1.0


def test_dimensions_enabled_and_budgeted() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    dims = raw["dimensions"]
    enabled = dims["enabled"]
    budgets = dims["default_budget"]
    for d in enabled:
        assert d in budgets, f"维度 {d} 缺少预算分配"


def test_required_dimensions_in_stop_verifier() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    required = raw["stop_verifier"]["required_dimensions"]
    assert "pricing" in required
    assert "feature" in required