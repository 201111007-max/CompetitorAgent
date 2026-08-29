"""设计文档 67 §2.1 — 榜单结构化直连单测。

mock httpx：SWE-bench/Terminal-Bench HTML 表解析成 BenchmarkHit、字段缺失容错、
非 2xx/超时/解析失败返回可读提示不抛、build_benchmark_provider 无开关/未知名 → None。
"""
from __future__ import annotations

import httpx
import pytest

from competitor_agent.collector.benchmark_sources import (
    BenchmarkError,
    BenchmarkHit,
    SweBenchProvider,
    TableBenchmarkProvider,
    TerminalBenchProvider,
    build_benchmark_provider,
)
from competitor_agent.config.loader import CollectorConfig

_LEADERBOARD_HTML = """<html><body>
<table>
<tr><th>Model</th><th>% Resolved</th><th>Date</th></tr>
<tr><td>agent-alpha</td><td>45.2%</td><td>2026-08-01</td></tr>
<tr><td>agent-beta</td><td>38.7%</td><td>2026-08-15</td></tr>
</table>
</body></html>"""

_EMPTY_TABLE_HTML = """<html><body><table>
<tr><th>Foo</th><th>Bar</th></tr>
<tr><td>x</td><td>y</td></tr>
</table></body></html>"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _html_client(html: str, status: int = 200) -> httpx.Client:
    return _client(lambda req: httpx.Response(status, text=html))


class TestTableParse:
    def test_parses_rows_to_hits(self):
        p = SweBenchProvider(client=_html_client(_LEADERBOARD_HTML))
        hits = p.fetch("swe-bench")
        assert len(hits) == 2
        h = hits[0]
        assert h.benchmark == "swe-bench"
        assert h.model == "agent-alpha"
        assert h.score == "45.2"
        assert h.date == "2026-08-01"
        assert h.source_url.startswith("http")

    def test_terminal_bench_provider(self):
        p = TerminalBenchProvider(client=_html_client(_LEADERBOARD_HTML))
        hits = p.fetch("terminal-bench")
        assert hits[0].benchmark == "terminal-bench"

    def test_missing_columns_tolerated(self):
        html = """<table>
        <tr><th>Model</th><th>Rank</th></tr>
        <tr><td>agent-a</td><td>3</td></tr>
        </table>"""
        p = TableBenchmarkProvider("swe-bench", base_url="https://x.test/", client=_html_client(html))
        hits = p.fetch("swe-bench")
        assert len(hits) == 1
        assert hits[0].score == ""  # 缺失列容错为空串
        assert hits[0].rank == "3"

    def test_unrecognized_table_raises_readable(self):
        p = TableBenchmarkProvider("swe-bench", base_url="https://x.test/", client=_html_client(_EMPTY_TABLE_HTML))
        with pytest.raises(BenchmarkError, match="无可解析"):
            p.fetch("swe-bench")


class TestProviderErrors:
    def test_non_2xx_raises(self):
        p = SweBenchProvider(client=_html_client("nope", status=403))
        with pytest.raises(BenchmarkError):
            p.fetch("swe-bench")

    def test_network_error_raises(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        p = SweBenchProvider(client=_client(handler))
        with pytest.raises(BenchmarkError):
            p.fetch("swe-bench")

    def test_timeout_raises(self):
        def handler(request):
            raise httpx.ReadTimeout("slow")

        p = SweBenchProvider(client=_client(handler))
        with pytest.raises(BenchmarkError):
            p.fetch("swe-bench")


class TestBuildBenchmarkProvider:
    def test_disabled_by_default(self):
        assert build_benchmark_provider(CollectorConfig(benchmark_provider="swebench")) is None

    def test_unknown_name_returns_none(self):
        cfg = CollectorConfig(enable_external_sources=True, benchmark_provider="foo")
        assert build_benchmark_provider(cfg) is None

    def test_enabled_returns_instance(self):
        cfg = CollectorConfig(enable_external_sources=True, benchmark_provider="swebench")
        assert isinstance(build_benchmark_provider(cfg), SweBenchProvider)

    def test_gated_by_enable_benchmark(self):
        cfg = CollectorConfig(
            enable_external_sources=True,
            enable_benchmark=False,
            benchmark_provider="swebench",
        )
        assert build_benchmark_provider(cfg) is None


class TestBenchmarkHit:
    def test_to_dict(self):
        h = BenchmarkHit("swe-bench", "1", "agent", "45.2", "2026-08-01", "https://x/")
        d = h.to_dict()
        assert d["benchmark"] == "swe-bench"
        assert d["score"] == "45.2"
