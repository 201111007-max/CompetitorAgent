"""设计文档 74 §3.1：默认 LLM 端点自检（_default_llm）。

- 未注入 llm 时默认构造以 config.llm 的 api_base_url/model 为准（不静默继承 shell env）；
- env OPENAI_BASE_URL 与 config 漂移 → WARNING 告警但仍用 config 端点。
"""

import logging

from competitor_agent.config.loader import AppConfig, LLMConfig
from competitor_agent.facade.api import CompetitorAnalysisAPI


def _api(cfg: AppConfig) -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(config=cfg)


def test_default_llm_uses_config_endpoint(monkeypatch) -> None:
    """即使 shell env 被污染，默认构造也用 config 声明的端点/模型。"""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-shell-polluted")
    cfg = AppConfig()
    cfg.llm = LLMConfig(
        api_base_url="https://ark.cn-beijing.volces.com/api/plan/v1",
        model="deepseek-v4-flash",
    )
    llm = _api(cfg)._default_llm()
    assert llm._model == "deepseek-v4-flash"
    assert llm._base_url == "https://ark.cn-beijing.volces.com/api/plan/v1"


def test_default_llm_drift_warns_but_uses_config(monkeypatch, caplog) -> None:
    """env 与 config 端点不一致 → WARNING 漂移检测，实际采用 config 端点。"""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    cfg = AppConfig()
    cfg.llm = LLMConfig(api_base_url="https://ark.example/v1", model="deepseek-v4-flash")
    with caplog.at_level(logging.WARNING, logger="competitor_agent.facade.api"):
        llm = _api(cfg)._default_llm()
    assert llm._base_url == "https://ark.example/v1"
    assert "端点漂移检测" in caplog.text


def test_default_llm_no_drift_warning_when_matching(monkeypatch, caplog) -> None:
    """env 与 config 端点一致 → 不告警。"""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ark.example/v1")
    cfg = AppConfig()
    cfg.llm = LLMConfig(api_base_url="https://ark.example/v1", model="deepseek-v4-flash")
    with caplog.at_level(logging.WARNING, logger="competitor_agent.facade.api"):
        _api(cfg)._default_llm()
    assert "端点漂移检测" not in caplog.text


def test_default_llm_cached_singleton(monkeypatch) -> None:
    cfg = AppConfig()
    cfg.llm = LLMConfig(api_base_url="https://ark.example/v1", model="deepseek-v4-flash")
    api = _api(cfg)
    first = api._default_llm()
    second = api._default_llm()
    assert first is second
