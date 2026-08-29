"""舆情采样源（设计文档 67 §2.2）

``sentiment`` 结论带**样本量与时间窗**（data_sources.md R13 缓解），不靠泛搜索碰运气：
``SentimentProvider`` 策略抽象 + HackerNews（hn.algolia.com 公开免 Key）/ Reddit
（JSON 端点，可配可选凭据）采样，对齐 doc 66 ``SearchProvider`` 模式。平台缺失/
失败 → 降级返回空（不编造，守 doc 47）；主开关关 → None。
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

logger = logging.getLogger("competitor_agent.collector.sentiment_sources")

_DEFAULT_USER_AGENT = "competitor-agent/0.1 (web/sentiment sampling)"
_HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
_REDDIT_SEARCH_URL = "https://www.reddit.com/r/{sub}/search.json"
_DEFAULT_SUBREDDITS = ("MachineLearning", "artificial", "LocalLLaMA")


class SentimentError(RuntimeError):
    """舆情采样失败（网络/非 2xx/响应异常）——上层捕获后降级返回空，不编造。"""


@dataclass
class SentimentSample:
    """一条舆情采样（含平台/样本量/时间窗元数据）"""

    platform: str  # reddit / hn / jike / search
    text: str
    source_url: str
    posted_at: str
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sample_size: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "text": self.text,
            "source_url": self.source_url,
            "posted_at": self.posted_at,
            "fetched_at": self.fetched_at,
            "sample_size": self.sample_size,
        }


class SentimentProvider(ABC):
    """舆情提供方抽象（对齐 doc 66/67 的策略模式）。"""

    @abstractmethod
    def sample(self, competitor: str, max_samples: int = 10) -> list[SentimentSample]:
        """采样竞品相关舆情，返回 ≤max_samples 条；失败抛异常（上层降级不编造）。"""


class HackerNewsProvider(SentimentProvider):
    """hn.algolia.com 公开搜索 API（免 Key）：hits[] → SentimentSample。

    platform="hn"；posted_at 取 ``created_at``；sample_size 记录返回条数。
    非 2xx/网络/解析失败 → 抛可重试异常（上层降级不编造）。
    """

    def __init__(
        self,
        timeout: float = 20.0,
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self._timeout = timeout
        self._user_agent = user_agent
        self._client = client

    def sample(self, competitor: str, max_samples: int = 10) -> list[SentimentSample]:
        params = {
            "query": competitor,
            "tags": "story",
            "hitsPerPage": max(1, min(int(max_samples), 50)),
        }
        try:
            resp = self._get_client().get(
                _HN_SEARCH_URL,
                params=params,
                headers={"User-Agent": self._user_agent},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise SentimentError(f"HackerNews 采样请求失败: {exc}") from exc
        if resp.status_code >= 400:
            raise SentimentError(f"HackerNews 采样 HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SentimentError("HackerNews 采样响应非 JSON") from exc
        hits = data.get("hits") or []
        samples = [
            SentimentSample(
                platform="hn",
                text=str(h.get("title") or h.get("story_title") or "").strip(),
                source_url=str(h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"),
                posted_at=str(h.get("created_at") or ""),
                sample_size=0,
            )
            for h in hits
            if isinstance(h, dict) and (h.get("title") or h.get("story_title") or h.get("url"))
        ]
        for s in samples:
            s.sample_size = len(samples)  # 有效采样条数回填（排除噪声）
        return samples

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client


class RedditProvider(SentimentProvider):
    """Reddit JSON 端点采样（r/<sub>/search.json?q=<competitor>）。

    可配 ``REDDIT_USER_AGENT`` 环境变量（可选，官方要求 UA）；无凭据仍可用公开
    JSON 端点（限制宽松）。platform="reddit"。
    """

    def __init__(
        self,
        subreddits: tuple[str, ...] = _DEFAULT_SUBREDDITS,
        timeout: float = 20.0,
        user_agent: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self._subreddits = subreddits
        self._timeout = timeout
        self._user_agent = user_agent or "competitor-agent/0.1 (by u/competitor_agent)"
        self._client = client

    def sample(self, competitor: str, max_samples: int = 10) -> list[SentimentSample]:
        per_sub = max(1, max(1, int(max_samples)) // max(1, len(self._subreddits)))
        samples: list[SentimentSample] = []
        for sub in self._subreddits:
            try:
                resp = self._get_client().get(
                    _REDDIT_SEARCH_URL.format(sub=sub),
                    params={"q": competitor, "restrict_sr": "1", "limit": per_sub},
                    headers={"User-Agent": self._user_agent},
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                raise SentimentError(f"Reddit 采样请求失败: {exc}") from exc
            if resp.status_code >= 400:
                raise SentimentError(f"Reddit 采样 HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise SentimentError("Reddit 采样响应非 JSON") from exc
            for child in (data.get("data") or {}).get("children") or []:
                post = (child or {}).get("data") or {}
                text = str(post.get("title") or "").strip()
                permalink = str(post.get("permalink") or "")
                url = f"https://www.reddit.com{permalink}" if permalink else ""
                if text and url:
                    samples.append(
                        SentimentSample(
                            platform="reddit",
                            text=text,
                            source_url=url,
                            posted_at=str(post.get("created_utc") or ""),
                            sample_size=0,  # 收尾统一回填总条数
                        )
                    )
                if len(samples) >= max_samples:
                    break
            if len(samples) >= max_samples:
                break
        for s in samples:
            s.sample_size = len(samples)
        return samples

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client


# 配置名 → 提供方工厂（timeout → 实例；让 mypy 对构造签名收敛）
_PROVIDERS: dict[str, Callable[[float], SentimentProvider]] = {
    "hackernews": lambda timeout: HackerNewsProvider(timeout=timeout),
    "reddit": lambda timeout: RedditProvider(timeout=timeout),
}


def build_sentiment_provider(
    cfg: CollectorConfig,
    vault: SecretVault | None = None,
) -> SentimentProvider | None:
    """cfg.sentiment_provider 命中且主开关开启 → 对应舆情提供方；否则 None。

    ``vault`` 为保留参数（HN 公开免 Key；Reddit 可选 UA 经环境变量）。
    """
    if not getattr(cfg, "enable_external_sources", False):
        return None
    name = str(getattr(cfg, "sentiment_provider", "") or "").strip().lower()
    factory = _PROVIDERS.get(name)
    if factory is None:
        return None
    return factory(cfg.timeout_seconds)


def _sample_meta(samples: list[SentimentSample]) -> dict[str, object]:
    """采样元数据：平台/样本量/时间窗（供工具输出头与结论带 sample_size）。"""
    if not samples:
        return {"platform": "", "sample_size": 0, "start": "", "end": ""}
    posted = [s.posted_at for s in samples if s.posted_at]
    return {
        "platform": samples[0].platform,
        "sample_size": len(samples),
        "start": min(posted) if posted else "",
        "end": max(posted) if posted else "",
    }


__all__ = [
    "HackerNewsProvider",
    "RedditProvider",
    "SentimentError",
    "SentimentProvider",
    "SentimentSample",
    "build_sentiment_provider",
]
