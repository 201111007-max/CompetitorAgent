"""榜单结构化直连（设计文档 67 §2.1）

``performance`` 维度结论的数字来自**结构化榜单数据源**而非 LLM 读网页：
``BenchmarkSourceProvider`` 策略抽象 + SWE-bench / Terminal-Bench / Aider
官方榜单页 HTML 表解析（复用 bs4/lxml，无新依赖，对齐 doc 66 ``SearchProvider``
模式）。解析失败返回可读提示不抛（守 doc 47 降级不编造）；无网/主开关关 → None。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import httpx

from competitor_agent.config.loader import CollectorConfig
from competitor_agent.secret_vault import SecretVault

logger = logging.getLogger("competitor_agent.collector.benchmark_sources")

_DEFAULT_USER_AGENT = "competitor-agent/0.1"

# 官方榜单端点（可注入 client 供测试 / 配置 base_url 覆盖）
SWEBENCH_URL = "https://www.swebench.com/results/"
TERMINALBENCH_URL = "https://www.terminal-bench.com/"
AIDER_URL = "https://aider.chat/docs/leaderboards/"

# 表头别名 → BenchmarkHit 字段（大小写/空格归一后匹配）
_HEADER_ALIASES: dict[str, str] = {
    "model": "model",
    "agent": "model",
    "name": "model",
    "score": "score",
    "pass@1": "score",
    "resolved": "score",
    "accuracy": "score",
    "% resolved": "score",
    "% solved": "score",
    "eval": "score",
    "rank": "rank",
    "#": "rank",
    "pos": "rank",
    "date": "date",
    "updated": "date",
    "last updated": "date",
    "timestamp": "date",
}


class BenchmarkError(RuntimeError):
    """榜单抓取失败（网络/非 2xx/解析失败）——上层捕获后返回可读提示，不编造。"""


@dataclass
class BenchmarkHit:
    """一条榜单记录（结构化数字，替代 LLM 读网页解析）"""

    benchmark: str  # swe-bench / terminal-bench / aider
    rank: str
    model: str
    score: str
    date: str
    source_url: str
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark": self.benchmark,
            "rank": self.rank,
            "model": self.model,
            "score": self.score,
            "date": self.date,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
        }


class BenchmarkSourceProvider(ABC):
    """榜单提供方抽象（对齐 doc 66/67 的策略模式）。"""

    @abstractmethod
    def fetch(self, benchmark: str) -> list[BenchmarkHit]:
        """抓取指定榜单，返回 ≤ 全量命中；失败抛异常（上层降级不编造）。"""


def _normalize_header(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _parse_score(raw: str) -> str:
    """分数清洗：去 %/空格/括号，保留可读数值串（解析失败原样返回）。"""
    text = " ".join(str(raw or "").strip().split())
    for token in ("%", "(", ")"):
        text = text.replace(token, "")
    return text


def _parse_leaderboard_table(
    html: str,
    benchmark: str,
    source_url: str,
) -> list[BenchmarkHit]:
    """从榜单 HTML 解析 ``<table>`` 为 BenchmarkHit 列表。

    表头别名映射字段（model/score/rank/date）；无表头或无可识别列 → 返回空
    （不编造）。字段缺失容错：缺失列给空串。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    hits: list[BenchmarkHit] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        col_map: dict[int, str] = {}
        for i, cell in enumerate(header_cells):
            mapped = _HEADER_ALIASES.get(_normalize_header(cell.get_text(" ", strip=True)))
            if mapped:
                col_map[i] = mapped
        if "model" not in col_map.values():
            continue  # 无可识别列，非目标榜单表
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            model = ""
            score = ""
            rank = ""
            date = ""
            for i, cell in enumerate(cells):
                field = col_map.get(i)
                if field is None:
                    continue
                value = " ".join(cell.get_text(" ", strip=True).split())
                if field == "model":
                    model = value
                elif field == "score":
                    score = _parse_score(value)
                elif field == "rank":
                    rank = value
                elif field == "date":
                    date = value
            if not model and not score:
                continue
            hits.append(
                BenchmarkHit(
                    benchmark=benchmark,
                    rank=rank,
                    model=model,
                    score=score,
                    date=date,
                    source_url=source_url,
                )
            )
    return hits


class TableBenchmarkProvider(BenchmarkSourceProvider):
    """通用官方榜单 HTML 表提供方（可注入 client 供测试）。"""

    def __init__(
        self,
        benchmark: str,
        base_url: str = "",
        timeout: float = 20.0,
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self._benchmark = benchmark
        self._base_url = base_url
        self._timeout = timeout
        self._user_agent = user_agent
        self._client = client

    def fetch(self, benchmark: str) -> list[BenchmarkHit]:
        url = self._base_url or benchmark
        try:
            resp = self._get_client().get(
                url,
                headers={"User-Agent": self._user_agent},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise BenchmarkError(f"榜单请求失败: {exc}") from exc
        if resp.status_code >= 400:
            raise BenchmarkError(f"榜单 HTTP {resp.status_code}: {resp.text[:200]}")
        hits = _parse_leaderboard_table(resp.text, self._benchmark, url)
        if not hits:
            raise BenchmarkError("榜单页面无可解析的表行（数据可能已改版）")
        return hits

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client


class SweBenchProvider(TableBenchmarkProvider):
    """SWE-bench 官方 leaderboard（swebench.com/results/）。"""

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("base_url", SWEBENCH_URL)
        kwargs.setdefault("benchmark", "swe-bench")
        super().__init__(**kwargs)  # type: ignore[arg-type]


class TerminalBenchProvider(TableBenchmarkProvider):
    """Terminal-Bench 公开结果表（terminal-bench.com）。"""

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("base_url", TERMINALBENCH_URL)
        kwargs.setdefault("benchmark", "terminal-bench")
        super().__init__(**kwargs)  # type: ignore[arg-type]


class AiderProvider(TableBenchmarkProvider):
    """Aider leaderboard 列表（aider.chat/docs/leaderboards/）。"""

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("base_url", AIDER_URL)
        kwargs.setdefault("benchmark", "aider")
        super().__init__(**kwargs)  # type: ignore[arg-type]


# 配置名 → 提供方工厂（timeout → 实例；让 mypy 对构造签名收敛）
_PROVIDERS: dict[str, Callable[[float], BenchmarkSourceProvider]] = {
    "swebench": lambda timeout: SweBenchProvider(timeout=timeout),
    "terminalbench": lambda timeout: TerminalBenchProvider(timeout=timeout),
    "aider": lambda timeout: AiderProvider(timeout=timeout),
}


def build_benchmark_provider(
    cfg: CollectorConfig,
    vault: SecretVault | None = None,
) -> BenchmarkSourceProvider | None:
    """cfg.benchmark_provider 命中且主开关开启 → 对应榜单提供方；否则 None。

    无网/未启用/未知名 → None（不启用，保持现状——performance 走 LLM 读网页
    降级路径）。``vault`` 为保留参数（榜单端点公开无 Key；供未来鉴权源扩展）。
    """
    if not (getattr(cfg, "enable_external_sources", False) and getattr(cfg, "enable_benchmark", True)):
        return None
    name = str(getattr(cfg, "benchmark_provider", "") or "").strip().lower()
    factory = _PROVIDERS.get(name)
    if factory is None:
        return None
    return factory(cfg.timeout_seconds)


__all__ = [
    "AiderProvider",
    "BenchmarkError",
    "BenchmarkHit",
    "BenchmarkSourceProvider",
    "SweBenchProvider",
    "TableBenchmarkProvider",
    "TerminalBenchProvider",
    "build_benchmark_provider",
]
