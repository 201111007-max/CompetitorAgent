"""PerformanceAnalyzer 榜单合并 + BenchmarkSourceProvider 单测（设计文档 25）

覆盖：Provider 解析/失败降级/TTL 新鲜度；合并优先级（榜单>页面、仅页面降档、
均无 [PARTIAL] 不编造）；GapExecutor 注入 benchmark_scores 的闭环。
"""
from __future__ import annotations

import pytest

from competitor_agent.analyzers.performance_analyzer import PerformanceAnalyzer
from competitor_agent.collector.providers.benchmark_source import BenchmarkSourceProvider
from competitor_agent.collector.source_selector import SourceCandidate, SourceSelector
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.gap_executor import GapExecutor
from competitor_agent.domain_types import BenchmarkScore, Competitor, InfoGap, Observation, SourceEvidence
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.interfaces.context import AnalysisContext


def _obs(raw_text, gap_field="performance", url="https://www.cursor.com/docs"):
    ev = SourceEvidence(source_name="web_extractor", url=url, content_hash="h1")
    return Observation(gap_field=gap_field, source="web_extractor", raw_text=raw_text, evidence=ev)


def _score(board="swe_bench_verified", score=62.0, unit="%", label="SWE-bench Verified"):
    return BenchmarkScore(
        board=board,
        board_label=label,
        metric="score",
        score=score,
        unit=unit,
        retrieved_at="2026-08-01T00:00:00+00:00",
        source_url=f"https://boards.example/{board}",
    )


class TestProvider:
    def _text_for(self, url, competitor="cursor"):
        return f"| Model | Score |\n| {competitor} | 62% |\n| other | 40% |\n"

    def test_parses_scores_across_boards(self):
        extract_calls: list[str] = []
        p = BenchmarkSourceProvider(extract_fn=lambda url: (extract_calls.append(url) or self._text_for(url)))
        scores = p.fetch_scores("cursor")
        assert set(scores) == {"swe_bench_verified", "aider_polyglot", "terminal_bench", "lm_arena"}
        s = scores["swe_bench_verified"]
        assert s.score == 62.0
        assert s.unit == "%"
        assert s.source_url == "https://www.swebench.com/"
        assert s.retrieved_at  # 新鲜度时间戳
        assert len(extract_calls) == 4

    def test_fetch_failure_returns_empty_dict(self):
        p = BenchmarkSourceProvider(extract_fn=lambda url: (_ for _ in ()).throw(RuntimeError("network down")))
        assert p.fetch_scores("cursor") == {}  # 不抛异常，正常降级

    def test_ttl_freshness_refetch(self):
        calls = {"n": 0}

        def extract_fn(url):
            calls["n"] += 1
            return f"| Model | Score |\n| cursor | 62% |\n"

        class FakeClock:
            def __init__(self, start=0.0):
                self.t = start

            def __call__(self):
                return self.t

            def advance(self, dt):
                self.t += dt

        clock = FakeClock(1000.0)
        p = BenchmarkSourceProvider(extract_fn=extract_fn, cache_ttl_seconds=3600, clock=clock)
        assert len(p.fetch_scores("cursor")) == 4
        assert calls["n"] == 4
        p.fetch_scores("cursor")  # TTL 内 → 缓存命中
        assert calls["n"] == 4
        clock.advance(3601)  # 超过 TTL → 重抓
        p.fetch_scores("cursor")
        assert calls["n"] == 8

    def test_supports_only_performance(self):
        p = BenchmarkSourceProvider(extract_fn=lambda url: "no data")
        c = Competitor(name="cursor")
        assert p.supports(InfoGap(field="performance"), c)
        assert not p.supports(InfoGap(field="feature"), c)
        cands = p.candidates(InfoGap(field="feature"), c)
        assert cands == []
        cands = p.candidates(InfoGap(field="performance"), c)
        assert cands and cands[0].kind == "benchmark"
        assert cands[0].trust_level == 0.9  # 榜单优先

    def test_fetch_no_scores_raises(self):
        from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

        p = BenchmarkSourceProvider(extract_fn=lambda url: "no competitor data here")
        c = Competitor(name="cursor")
        cand = p.candidates(InfoGap(field="performance"), c)[0]
        with pytest.raises(DataSourceUnavailableError):
            p.fetch(InfoGap(field="performance"), cand, c)


class TestMergePriority:
    def _perf_llm(self, benchmarks, confidence=0.8):
        import json

        from competitor_agent.llm.client import LLMClient

        def fake_llm(messages, model):
            return json.dumps(
                {"summary": "ok", "details": {"benchmarks": benchmarks}, "confidence": confidence}
            )

        return PerformanceAnalyzer(llm=LLMClient(call_func=fake_llm))

    def test_board_wins_over_page(self):
        a = self._perf_llm([{"name": "SWE-bench Verified", "score": "58%"}])
        obs = _obs("SWE-bench Verified: 58%")
        ctx = AnalysisContext(benchmark_scores={"swe_bench_verified": _score(score=62.0)})
        result = a.analyze(obs, InfoGap(field="performance"), ctx)
        board_entries = [b for b in result.details["benchmarks"] if b.get("board") == "swe_bench_verified"]
        assert board_entries[0]["score"] == 62.0
        assert board_entries[0]["source"] == "leaderboard"
        assert board_entries[0]["source_url"] == "https://boards.example/swe_bench_verified"
        assert result.details["board_priority"] is True
        assert result.confidence == 0.85
        # 页面同指标条目让位（不重复出现在合并结果里）
        assert not any(b.get("source") == "page" for b in result.details["benchmarks"])

    def test_page_only_downgrades_confidence(self):
        # LLM 抽出页面基准；无权威榜单 → 置信度降档（min(0.8, 0.6)），页面条目保留
        a = self._perf_llm([{"name": "SWE-bench Verified", "score": "58%"}])
        obs = _obs("SWE-bench Verified: 58%")
        result = a.analyze(obs, InfoGap(field="performance"), AnalysisContext())
        assert result.details["board_priority"] is False
        assert result.confidence == 0.6  # min(mock 0.8, 页面兜底上限 0.6) → 降档
        assert result.details["benchmarks"], "页面条目应保留（原结构，供评测抽取）"

    def test_neither_partial_no_fabrication(self):
        a = self._perf_llm([], confidence=0.5)
        obs = _obs("just marketing copy with no numbers")
        result = a.analyze(obs, InfoGap(field="performance"), AnalysisContext())
        assert result.status == ResultStatus.PARTIAL
        assert result.confidence == 0.3
        assert "无权威榜单数据" in result.summary

    def test_llm_path_keeps_board_merge(self):
        import json

        from competitor_agent.llm.client import LLMClient

        def fake_llm(messages, model):
            return json.dumps(
                {"summary": "ok", "details": {"benchmarks": [{"name": "aider", "score": 55}]}, "confidence": 0.9}
            )

        a = PerformanceAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("SWE-bench Verified: 58%")
        ctx = AnalysisContext(benchmark_scores={"aider_polyglot": _score(board="aider_polyglot", score=70.0, label="Aider polyglot")})
        result = a.analyze(obs, InfoGap(field="performance"), ctx)
        assert result.confidence == 0.85  # 榜单存在 → 高置信
        aider = [b for b in result.details["benchmarks"] if b.get("board") == "aider_polyglot"]
        assert aider[0]["score"] == 70.0


class TestGapExecutorInjection:
    def test_injects_benchmark_scores_into_analyzer(self, mock_llm):
        class FakeSelector(SourceSelector):
            def __init__(self, cands):
                self._cands = cands

            def candidates(self, gap, competitor):
                return self._cands

        provider = BenchmarkSourceProvider(extract_fn=lambda url: "| cursor | 62% |")
        competitor = Competitor(name="cursor")
        cand = SourceCandidate(
            source_name="benchmark_board",
            url="https://www.swebench.com/",
            trust_level=0.9,
            kind="benchmark",
        )
        executor = GapExecutor(
            selector=FakeSelector([cand]),
            extractor=object(),
            analyzer=PerformanceAnalyzer(llm=mock_llm, use_llm=True),
            budget=IterationBudget(max_iterations=5, cost_limit=1.0),
            providers={"benchmark": provider},
        )
        result = executor.execute(InfoGap(field="performance"), competitor)
        assert result is not None
        assert result.details["board_priority"] is True
        board_entries = [b for b in result.details["benchmarks"] if b.get("source") == "leaderboard"]
        assert board_entries
        assert board_entries[0]["source_url"].startswith("https://")
        assert result.evidence[0].source_name == "benchmark_board"
