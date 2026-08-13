"""BenchmarkSourceProvider — 性能榜单直连源（设计文档 25）

SWE-bench Verified / Aider polyglot / Terminal-Bench / LMArena 等权威榜单，
按竞品名匹配分数（trust 0.9，榜单优先）。薄封装 MCP web_extract，可注入
extract_fn（测试用 mock，不触发真实网络）；抓取失败返回空 dict（正常降级）。
分数按 competitor + TTL 缓存，retrieved_at 供设计文档 26（新鲜度/时间线）消费。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Callable

from competitor_agent.collector.source_selector import SourceCandidate
from competitor_agent.domain_types.benchmark import BenchmarkScore
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

_TRUST = 0.9

# board: (URL, 展示名)
BOARDS: dict[str, tuple[str, str]] = {
    "swe_bench_verified": ("https://www.swebench.com/", "SWE-bench Verified"),
    "aider_polyglot": ("https://aider.chat/docs/leaderboards/", "Aider polyglot"),
    "terminal_bench": ("https://www.terminal-bench.com/", "Terminal-Bench"),
    "lm_arena": ("https://lmarena.ai/leaderboard", "LMArena"),
}

_SCORE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|points|elo)?", re.IGNORECASE)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _parse_board(
    text: str, competitor: str, board: str, label: str, url: str, retrieved_at: str
) -> BenchmarkScore | None:
    """在榜单文本中找含竞品名的行，提取首个分数（找不到返回 None）"""
    name = competitor.lower()
    for line in text.splitlines():
        if name not in line.lower():
            continue
        m = _SCORE_RE.search(line)
        if not m:
            continue
        return BenchmarkScore(
            board=board,
            board_label=label,
            metric="score",
            score=float(m.group(1)),
            unit=m.group(2) or "",
            retrieved_at=retrieved_at,
            source_url=url,
        )
    return None


def _wrap_observation(gap: InfoGap, candidate: SourceCandidate, text: str) -> Observation:
    return Observation(
        gap_field=gap.field,
        source=candidate.source_name,
        raw_text=text,
        evidence=SourceEvidence(
            source_name=candidate.source_name,
            url=candidate.url,
            content_hash=SourceEvidence.compute_hash(text),
            trust_level=candidate.trust_level,
        ),
    )


class BenchmarkSourceProvider:
    """榜单源（trust 0.9）：performance 缺口 → 权威榜单分数，页面数字兜底"""

    kind = "benchmark"
    name = "benchmark_board"

    def __init__(
        self,
        extract_fn: Callable[[str], str] | None = None,
        cache_ttl_seconds: int = 86400,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if extract_fn is None:
            from competitor_agent.mcp_server.tools.web_tools import web_extract  # 惰性导入

            extract_fn = web_extract
        self._extract = extract_fn
        self._cache_ttl = cache_ttl_seconds
        self._clock = clock or time.time
        self._cache: dict[str, tuple[float, dict[str, BenchmarkScore]]] = {}

    def supports(self, gap: InfoGap, competitor: Competitor) -> bool:
        return gap.field == "performance"

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        if not self.supports(gap, competitor):
            return []
        url = BOARDS["swe_bench_verified"][0]
        return [
            SourceCandidate(
                source_name="benchmark_board",
                url=url,
                trust_level=_TRUST,
                kind="benchmark",
            )
        ]

    def fetch_scores(self, competitor_name: str) -> dict[str, BenchmarkScore]:
        """返回 {board: BenchmarkScore}；按 competitor + TTL 缓存，失败的空 dict 正常降级。"""
        now = self._clock()
        cached = self._cache.get(competitor_name)
        if cached is not None and now - cached[0] < self._cache_ttl:
            return cached[1]

        scores: dict[str, BenchmarkScore] = {}
        for board, (url, label) in BOARDS.items():
            try:
                text = self._extract(url)
            except Exception:  # noqa: BLE001 — 抓取失败正常降级，不阻塞主流程
                continue
            if text.startswith("⚠"):
                continue
            parsed = _parse_board(text, competitor_name, board, label, url, _iso(now))
            if parsed is not None:
                scores[board] = parsed

        self._cache[competitor_name] = (now, scores)
        return scores

    def fetch(self, gap: InfoGap, candidate: SourceCandidate, competitor: Competitor) -> Observation:
        scores = self.fetch_scores(competitor.name)
        if not scores:
            raise DataSourceUnavailableError(f"榜单无 {competitor.name} 的性能数据")
        lines = [
            f"{s.board_label}: {s.score}{s.unit} @ {s.source_url} (retrieved {s.retrieved_at})"
            for s in scores.values()
        ]
        return _wrap_observation(gap, candidate, "\n".join(lines))
