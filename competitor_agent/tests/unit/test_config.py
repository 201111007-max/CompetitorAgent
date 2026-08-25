"""配置加载冒烟测试 — M0 0.3 验证：review_config.yaml 可被 yaml.safe_load 通过

断言关键字段存在且类型正确，保证骨架配置与 M1 实现的契约一致。
M6 新增：验证 load_config() 将 YAML 加载为类型安全 AppConfig，并注入运行时。
"""

from pathlib import Path

import yaml

from competitor_agent.config.loader import AppConfig, load_config

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "review_config.yaml"


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


def test_dimensions_enabled_present() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    enabled = raw["dimensions"]["enabled"]
    assert "pricing" in enabled
    assert "feature" in enabled


def test_subagents_config_section() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    sub = raw["subagents"]
    assert sub["enabled"] is True
    # 并发硬上限收敛到 execution.max_parallel_subagents（设计文档 62 §3.8）
    assert raw["execution"]["max_parallel_subagents"] >= 1


# ── M6：load_config() 加载为类型安全 AppConfig ──────────────────────────────


def test_load_config_returns_appconfig() -> None:
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.budget.max_iterations == 10
    assert cfg.budget.cost_limit_usd == 1.0
    assert cfg.budget.max_parallel_subagents == 4
    assert "pricing" in cfg.dimensions.enabled
    assert cfg.collector.rate_limit_per_second == 2
    assert cfg.memory.enabled is True
    assert cfg.observability.log_level == "INFO"
    assert cfg.execution.max_parallel_subagents == 4
    assert cfg.lead.max_orchestration_steps == 24
    assert cfg.lead.max_history_steps == 12
    assert cfg.subagents.enabled is True
    assert cfg.tools.validate_facts is True


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


def test_load_config_parses_execution_and_lead_section(tmp_path) -> None:
    """execution/lead section 解析：硬上限 + Lead 编排步数进入对应 Config（设计文档 62 §3.8）。"""
    from competitor_agent.config.loader import ExecutionConfig, LeadConfig

    p = tmp_path / "cfg.yaml"
    p.write_text(
        "execution:\n  max_parallel_subagents: 8\nlead:\n  max_orchestration_steps: 30\n"
        "  max_history_steps: 10\nbudget:\n  max_iterations: 3\n",
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert isinstance(cfg.execution, ExecutionConfig)
    assert cfg.execution.max_parallel_subagents == 8
    assert isinstance(cfg.lead, LeadConfig)
    assert cfg.lead.max_orchestration_steps == 30
    assert cfg.lead.max_history_steps == 10
    assert cfg.budget.max_iterations == 3


def test_load_config_ignores_unknown_execution_key(tmp_path) -> None:
    """execution.mode 已删除（设计文档 62 §3.8）：未知键被忽略不报错。"""
    p = tmp_path / "cfg.yaml"
    p.write_text("execution:\n  mode: parallel\n  max_parallel_subagents: 4\n", encoding="utf-8")
    cfg = load_config(str(p))
    assert not hasattr(cfg.execution, "mode")
    assert cfg.execution.max_parallel_subagents == 4


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
