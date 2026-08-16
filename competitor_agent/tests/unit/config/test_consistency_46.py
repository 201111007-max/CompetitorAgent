"""设计文档 46 §5 验证：编排收敛（①）+ 默认值统一（③）+ 计价可配（④）

- ① analyze_with_context / retrieve_rag_text 共享分析段：两条路径（GapExecutor/单测）
  注入相同上下文字段（competitor_name/dimension/rag/memory/benchmark）
- ③ cli use_llm 默认与库一致（True），无配置时计价沿用内置近似（回归）
- ④ pricing_per_1k 从 config 读取、注入 LLMClient 成本核算
"""
import inspect

import pytest
from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.analyzers.base import analyze_with_context, retrieve_rag_text
from competitor_agent.config.loader import LLMConfig, load_config
from competitor_agent.domain_types import (
    Competitor,
    DimensionType,
    InfoGap,
    Observation,
    ResultStatus,
    SourceEvidence,
)
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.llm.client import LLMClient

# ── ① 共享分析段 ──────────────────────────────────────────────


class RecordingAnalyzer:
    """记录注入的 AnalysisContext，返回固定结果（模拟 BaseCompetitorAnalyzer 契约）"""

    dimension = DimensionType.PRICING

    def __init__(self) -> None:
        self.calls: list = []

    def analyze(self, observation, gap, context):
        self.calls.append(context)
        return DimensionResult(
            dimension="pricing",
            summary="ok",
            details={},
            confidence=0.9,
            evidence=[observation.evidence],
            status=ResultStatus.COMPLETE,
        )


class _FakeRetriever:
    def retrieve(self, query, competitor, dimension, top_k=5):
        return [
            type("Chunk", (), {
                "competitor": competitor,
                "dimension": dimension,
                "text": "Cursor Pro $20/month（历史片段）",
                "source_url": "https://www.cursor.com/pricing",
            })()
        ]


class _BoomRetriever:
    def retrieve(self, *args, **kwargs):
        raise RuntimeError("检索故障")


def _obs(field: str = "pricing") -> Observation:
    return Observation(
        gap_field=field,
        source="web_extractor",
        raw_text="Pro plan: $20/month",
        evidence=SourceEvidence(source_name="web_extractor", url="https://www.cursor.com/pricing"),
    )


class TestSharedAnalysisSegment:
    def test_analyze_with_context_wires_all_fields(self):
        analyzer = RecordingAnalyzer()
        result = analyze_with_context(
            analyzer,
            _obs(),
            InfoGap(field="pricing"),
            competitor_name="cursor",
            rag_context="知识库片段",
            memory_context="历史经验",
            benchmark_scores={"board": "SWE-bench", "score": 12.0},
        )
        assert result.dimension == "pricing"
        assert len(analyzer.calls) == 1
        ctx = analyzer.calls[0]
        assert ctx.competitor_name == "cursor"
        assert ctx.dimension == DimensionType.PRICING
        assert ctx.rag_context == "知识库片段"
        assert ctx.memory_context == "历史经验"
        assert ctx.benchmark_scores == {"board": "SWE-bench", "score": 12.0}

    def test_analyze_with_context_no_benchmark(self):
        analyzer = RecordingAnalyzer()
        analyze_with_context(
            analyzer,
            _obs(),
            InfoGap(field="pricing"),
            competitor_name="cursor",
        )
        ctx = analyzer.calls[0]
        assert ctx.benchmark_scores == {}  # 未提供时保持默认空，不注入榜单

    def test_retrieve_rag_text_formats_with_source(self):
        text = retrieve_rag_text(_FakeRetriever(), "cursor", "pricing")
        assert "cursor" in text
        assert "Cursor Pro $20/month（历史片段）" in text
        assert "（来源: https://www.cursor.com/pricing）" in text

    def test_retrieve_rag_text_none_and_error(self):
        assert retrieve_rag_text(None, "cursor", "pricing") == ""
        assert retrieve_rag_text(_BoomRetriever(), "cursor", "pricing") == ""

    def test_gap_executor_injects_rag_via_shared_segment(self):
        """GapExecutor 经 analyze_with_context 注入 rag（回归：共享段未破坏注入）"""
        from competitor_agent.collector.source_selector import SourceCandidate
        from competitor_agent.core.budget import IterationBudget
        from competitor_agent.core.gap_executor import GapExecutor

        class Selector:
            def candidates(self, gap, competitor):
                return [
                    SourceCandidate(
                        source_name="official_pricing",
                        url="https://www.cursor.com/pricing",
                        trust_level=0.9,
                    )
                ]

        class Extractor:
            def fetch(self, gap, context):
                return _obs(gap.field)

        analyzer = RecordingAnalyzer()
        executor = GapExecutor(
            selector=Selector(),
            extractor=Extractor(),
            analyzer=analyzer,
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
            retriever=_FakeRetriever(),
        )
        executor.execute(InfoGap(field="pricing"), Competitor(name="cursor"))
        assert analyzer.calls
        ctx = analyzer.calls[0]
        assert ctx.rag_context  # RAG 片段经共享段注入
        assert "Cursor Pro $20/month（历史片段）" in ctx.rag_context

    def test_shared_segment_wraps_untrusted_rag(self):
        """共享段注入的 rag 在分析器 prompt 中按不可信块包裹（问题 6 防护不丢）"""
        from competitor_agent.analyzers.base import BaseCompetitorAnalyzer

        messages = [{"role": "user", "content": "分析"}]
        out = BaseCompetitorAnalyzer()._inject_rag_context(messages, "外部片段")
        assert "外部片段" in out[-1]["content"]
        assert wrap_untrusted("外部片段") in out[-1]["content"]


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
