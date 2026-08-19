"""SourceDedup — 跨竞品同源去重（设计文档 49 §3.4）

进程内 URL → ``Observation`` 缓存（跨竞品共享）：同源 URL 二次抓取直接复用缓存，
``compare`` 多竞品共享官网/榜单时省网络请求，并保证跨竞品引用同一版本数据。

- 缓存键 = 规范化 URL（去掉 fragment / 尾部斜杠 / scheme 大小写）；
- URL 不同但内容相同（``content_hash`` 命中）→ 仅当哈希一致时复用，防"同 URL 不同内容"
  与"不同 URL 相同内容"两种情况误用；不同内容绝不复用。
- 有界缓存（FIFO 淘汰），默认关闭时（未装配）采集行为不变。
"""
from __future__ import annotations

from typing import Callable

from competitor_agent.domain_types.observation import Observation

_DEFAULT_MAX_SIZE = 256


def _normalize_url(url: str) -> str:
    """规范化 URL：去空白、去 fragment、统一 scheme/host 小写、去尾部斜杠（保留根）。"""
    raw = (url or "").strip()
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    scheme, _, rest = raw.partition("://")
    if rest:
        scheme = scheme.lower()
        host, _, tail = rest.partition("/")
        host = host.lower()
        tail = tail.rstrip("/")
        return f"{scheme}://{host}/{tail}".rstrip("/")
    return raw


class SourceDedup:
    """URL → Observation 缓存 + content_hash 同内容复用。"""

    def __init__(self, max_size: int = _DEFAULT_MAX_SIZE) -> None:
        self._max_size = max(1, int(max_size))
        self._by_url: dict[str, Observation] = {}
        self._hits = 0
        self._total = 0

    def get_or_fetch(self, url: str, fetch_fn: Callable[[], Observation]) -> Observation:
        """按 URL 取缓存；未命中则调用 fetch_fn 抓取并缓存。

        - URL 命中 → 直接复用缓存观测（跨竞品共享省抓取）；
        - URL 未命中但抓取结果 content_hash 与已缓存观测一致 → 复用缓存（同内容）；
        - 否则按 URL 缓存新观测。
        """
        self._total += 1
        key = _normalize_url(url)
        cached = self._by_url.get(key)
        if cached is not None:
            self._hits += 1
            return cached
        fetched = fetch_fn()
        if fetched.evidence and fetched.evidence.content_hash:
            for other in self._by_url.values():
                if (
                    other.evidence
                    and other.evidence.content_hash == fetched.evidence.content_hash
                ):
                    self._by_url[key] = other
                    self._hits += 1
                    return other
        if len(self._by_url) >= self._max_size:
            self._by_url.pop(next(iter(self._by_url)), None)  # FIFO 淘汰
        self._by_url[key] = fetched
        return fetched

    @property
    def hit_count(self) -> int:
        """缓存命中次数（测试/集成统计去重收益）。"""
        return self._hits

    @property
    def total_lookups(self) -> int:
        return self._total

    @property
    def cache_size(self) -> int:
        return len(self._by_url)

    def clear(self) -> None:
        self._by_url.clear()
        self._hits = 0
        self._total = 0


__all__ = ["SourceDedup", "_normalize_url"]
