"""设计文档 46 §5 验证（49 迁移后保留段）：默认值统一（③）+ 计价可配（④）

- ③ cli use_llm 默认与库一致（True），无配置时计价沿用内置近似（回归）
- ④ pricing_per_1k 从 config 读取、注入 LLMClient 成本核算
（① 共享分析段 analyze_with_context/retrieve_rag_text 已随 analyzers/ 删除，设计文档 49）
"""
import inspect

import pytest
from competitor_agent.config.loader import LLMConfig, load_config
from competitor_agent.llm.client import LLMClient

# ── ③ 默认值统一 ──────────────────────────────────────────────


class TestUseLLMDefaults:
    def test_run_analyze_default_true(self):
        from competitor_agent.cli import _run_analyze

        sig = inspect.signature(_run_analyze)
        assert sig.parameters["use_llm"].default is True

    def test_repl_default_true(self):
        from competitor_agent.cli import _repl

        sig = inspect.signature(_repl)
        assert sig.parameters["use_llm"].default is True


# ── ④ 计价可配 ────────────────────────────────────────────────


class TestPricingConfig:
    def test_default_pricing_preserved(self):
        """无配置注入时沿用内置 DeepSeek 量级近似（回归：行为不变）。"""
        client = LLMClient(call_func=lambda messages, model: "ok")
        assert client._pricing_per_1k["input"] == 0.0003
        assert client._pricing_per_1k["output"] == 0.0006

    def test_custom_pricing_injected(self):
        client = LLMClient(
            call_func=lambda messages, model: "ok",
            pricing_per_1k={"input": 0.01, "output": 0.02},
        )
        assert client._pricing_per_1k["input"] == 0.01
        assert client._pricing_per_1k["output"] == 0.02

    def test_cost_uses_configured_pricing(self):
        """成本核算按配置单价：1 input + 1 output token → 0.01/1000 + 0.02/1000。"""
        client = LLMClient(
            call_func=lambda messages, model: "world",
            pricing_per_1k={"input": 0.01, "output": 0.02},
        )
        client.complete([{"role": "user", "content": "hello"}])
        # 1 input + 1 output token，按配置单价核算
        assert client.total_cost_usd == pytest.approx(1 / 1000 * 0.01 + 1 / 1000 * 0.02)

    def test_llm_config_field_default_none(self):
        assert LLMConfig().pricing_per_1k is None

    def test_load_config_parses_pricing(self):
        cfg = load_config()
        assert cfg.llm.pricing_per_1k == {"input": 0.0003, "output": 0.0006}

    def test_config_to_client_wiring(self):
        """cli._build_llm 把 config 计价注入 LLMClient。"""
        from competitor_agent.cli import _build_llm

        cfg = load_config()
        client = _build_llm(cfg)
        assert client._pricing_per_1k["input"] == cfg.llm.pricing_per_1k["input"]
        assert client._pricing_per_1k["output"] == cfg.llm.pricing_per_1k["output"]


# ── 设计文档 70 §8.4 D4：工具启停 + 超时配置默认值 ──────────────


class TestDesign70ToolDefaults:
    """D4a/D4b/D4c：默认配置即启用榜单/舆情直连 + 加长子 Agent 采集超时；
    D4d：build_*_provider 据此返回非 None。"""

    def test_default_benchmark_provider_enabled(self):
        cfg = load_config()
        assert cfg.collector.benchmark_provider == "swebench"
        from competitor_agent.collector.benchmark_sources import build_benchmark_provider
        from competitor_agent.config.loader import CollectorConfig

        c = CollectorConfig(
            enable_external_sources=True, benchmark_provider=cfg.collector.benchmark_provider
        )
        assert build_benchmark_provider(c) is not None

    def test_default_sentiment_provider_enabled(self):
        cfg = load_config()
        assert cfg.collector.sentiment_provider == "hackernews"
        from competitor_agent.collector.sentiment_sources import build_sentiment_provider
        from competitor_agent.config.loader import CollectorConfig

        c = CollectorConfig(
            enable_external_sources=True, sentiment_provider=cfg.collector.sentiment_provider
        )
        assert build_sentiment_provider(c) is not None

    def test_default_subagent_timeout_300(self):
        cfg = load_config()
        assert cfg.subagents.timeout_seconds == 300
