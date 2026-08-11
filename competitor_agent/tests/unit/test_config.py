"""配置加载冒烟测试 — M0 0.3 验证：review_config.yaml 可被 yaml.safe_load 通过

断言关键字段存在且类型正确，保证骨架配置与 M1 实现的契约一致。
M6 新增：验证 load_config() 将 YAML 加载为类型安全 AppConfig，并注入运行时。
"""
from pathlib import Path

import yaml

from competitor_agent.config.loader import AppConfig, load_config

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


# ── M6：load_config() 加载为类型安全 AppConfig ──────────────────────────────

def test_load_config_returns_appconfig() -> None:
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.budget.max_iterations == 10
    assert cfg.budget.cost_limit_usd == 1.0
    assert cfg.budget.max_parallel_subagents == 4
    assert cfg.termination.core_priority_threshold == 8
    assert cfg.termination.core_confidence == 0.8
    assert "pricing" in cfg.dimensions.enabled
    assert "feature" in cfg.stop_verifier.required_dimensions
    assert cfg.collector.rate_limit_per_second == 2
    assert cfg.memory.enabled is True
    assert cfg.observability.log_level == "INFO"


def test_load_config_missing_file_raises() -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        load_config("nonexistent_config.yaml")


def test_load_config_env_override(monkeypatch) -> None:
    """COMPETITOR_AGENT_CONFIG 环境变量覆盖默认路径。"""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write("budget:\n  max_iterations: 3\n  cost_limit_usd: 0.5\n")
        tmp = f.name
    try:
        monkeypatch.setenv("COMPETITOR_AGENT_CONFIG", tmp)
        cfg = load_config()
        assert cfg.budget.max_iterations == 3
        assert cfg.budget.cost_limit_usd == 0.5
    finally:
        import os

        os.unlink(tmp)


def test_api_uses_config_budget() -> None:
    """CompetitorAnalysisAPI 用 config 的预算值替换硬编码默认。"""
    from competitor_agent.config.loader import AppConfig, BudgetConfig
    from competitor_agent.facade.api import CompetitorAnalysisAPI

    cfg = AppConfig(budget=BudgetConfig(max_iterations=7, cost_limit_usd=0.3))
    api = CompetitorAnalysisAPI(config=cfg)
    assert api._budget.max_iterations == 7
    assert api._budget.cost_limit == 0.3


def test_api_explicit_args_override_config() -> None:
    """显式传入的 max_iterations/cost_limit 优先于 config。"""
    from competitor_agent.config.loader import AppConfig, BudgetConfig
    from competitor_agent.facade.api import CompetitorAnalysisAPI

    cfg = AppConfig(budget=BudgetConfig(max_iterations=7, cost_limit_usd=0.3))
    api = CompetitorAnalysisAPI(config=cfg, max_iterations=5, cost_limit=2.0)
    assert api._budget.max_iterations == 5
    assert api._budget.cost_limit == 2.0