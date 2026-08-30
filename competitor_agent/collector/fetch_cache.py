"""抓取/搜索分级缓存（设计文档 71 §6.1）——本地磁盘小 JSON 文件。

- 搜索：``{data_dir}/cache/search/{sha256(engine|query|max_results)}.json``，TTL 24h；
- 正文：``{data_dir}/cache/fetch/{sha256(canonical_url)}.json``，TTL 7d（正文 + via + 时间）；
- URL 规范化去 fragment、统一 scheme/host 大小写（同 URL 本任务只抓一次的去重底座）；
- 选型：本地磁盘（无外部依赖、跨进程共享、单文件幂等），预留 ``CacheBackend`` 语义
  备后续量大再上 Redis；写为原子替换（tmp + replace）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any

from competitor_agent.collector.fetch import FetchResult
from competitor_agent.collector.search import SearchHit

logger = logging.getLogger("competitor_agent.collector.fetch_cache")


class FetchCache:
    """分级磁盘缓存（搜索 24h / 正文 7d；TTL 可配）。"""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        search_ttl_hours: int = 24,
        fetch_ttl_days: int = 7,
    ) -> None:
        from competitor_agent.secret_vault import get_data_dir

        base = Path(data_dir) if data_dir else get_data_dir()
        self._search_dir = base / "cache" / "search"
        self._fetch_dir = base / "cache" / "fetch"
        self._search_ttl = max(0, int(search_ttl_hours)) * 3600
        self._fetch_ttl = max(0, int(fetch_ttl_days)) * 86400
        self._search_dir.mkdir(parents=True, exist_ok=True)
        self._fetch_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(seed: str) -> str:
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    @staticmethod
    def canonical_url(url: str) -> str:
        """URL 规范化：去 fragment、统一 scheme/host 大小写、去掉默认端口。

        对畸形端口（非数字/越界）容错：不抛异常（web_extract 契约「不抛」），
        退回仅去 fragment 的原始形式。
        """
        stripped = url.strip()
        parsed = urllib.parse.urlsplit(stripped)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        try:
            port = parsed.port
        except ValueError:
            return urllib.parse.urlunsplit((scheme, host, parsed.path, parsed.query, ""))
        default_port = (80 if scheme == "http" else 443) if scheme in ("http", "https") else None
        netloc = host if (port is None or port == default_port) else f"{host}:{port}"
        return urllib.parse.urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))

    # ---- 搜索缓存（24h） ----
    def get_search(
        self, query: str, max_results: int, engine: str
    ) -> list[SearchHit] | None:
        key = self._key(f"{engine}|{query}|{max_results}")
        data = self._read(self._search_dir / f"{key}.json", self._search_ttl)
        if data is None:
            return None
        try:
            return [
                SearchHit(
                    title=str(h.get("title") or ""),
                    url=str(h.get("url") or ""),
                    snippet=str(h.get("snippet") or ""),
                    source_engine=str(h.get("source_engine") or engine),
                    fetched_at=float(h.get("fetched_at") or 0.0),
                )
                for h in (data.get("hits") or [])
            ]
        except Exception:  # noqa: BLE001 - 缓存损坏视为未命中
            return None

    def set_search(
        self, query: str, max_results: int, engine: str, hits: list[SearchHit]
    ) -> None:
        key = self._key(f"{engine}|{query}|{max_results}")
        payload = {
            "engine": engine,
            "query": query,
            "max_results": max_results,
            "hits": [_hit_to_dict(h) for h in hits],
            "fetched_at": time.time(),
        }
        self._write(self._search_dir / f"{key}.json", payload)

    # ---- 正文缓存（7d） ----
    def get_fetch(self, url: str) -> FetchResult | None:
        key = self._key(self.canonical_url(url))
        data = self._read(self._fetch_dir / f"{key}.json", self._fetch_ttl)
        if data is None:
            return None
        try:
            return FetchResult(
                success=bool(data.get("success")),
                url=str(data.get("url") or url),
                title=str(data.get("title") or ""),
                content=str(data.get("content") or ""),
                provider=str(data.get("provider") or ""),
                reason=str(data.get("reason") or ""),
                fetched_at=float(data.get("fetched_at") or 0.0),
            )
        except Exception:  # noqa: BLE001 - 缓存损坏视为未命中
            return None

    def set_fetch(self, result: FetchResult) -> None:
        if not result.success:
            return
        key = self._key(self.canonical_url(result.url))
        payload = {
            "success": True,
            "url": result.url,
            "title": result.title,
            "content": result.content,
            "provider": result.provider,
            "reason": "",
            "fetched_at": result.fetched_at or time.time(),
        }
        self._write(self._fetch_dir / f"{key}.json", payload)

    # ---- 内部 ----
    def _read(self, path: Path, ttl: float) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏缓存直接忽略
            logger.warning("缓存读取失败（忽略）: %s", path)
            return None
        if time.time() - float(data.get("fetched_at") or 0) > ttl:
            return None
        return data

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)  # 原子替换
        except OSError as exc:
            logger.warning("缓存写入失败（忽略）: %s: %s", path, exc)


def _hit_to_dict(hit: SearchHit) -> dict[str, Any]:
    return {
        "title": hit.title,
        "url": hit.url,
        "snippet": hit.snippet,
        "source_engine": hit.source_engine,
        "fetched_at": hit.fetched_at,
    }
