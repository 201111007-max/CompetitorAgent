"""抓取策略（设计文档 71 §4.2/§5）——隐性失败检测 + 懒触发单跑上限 + URL 去重。

- ``_is_shell``：判「隐性失败」（HTTP 200 但内容空壳）——正文过短（<80 字符）或首 2K
  命中反爬提示词正则 → True，触发降级到下一级；
- ``FetchPolicy``：per-run 实例（一次 run()/analysis 内跨 web_extract 调用共享）——
  同一 URL 只抓一次（去重不重抓、不计上限）；累计有效调用超 ``max_per_run`` 返回
  上限提示（防失控，doc 71 §5.3）。
"""
from __future__ import annotations

import re
import threading
from typing import Any

_ANTI_BOT_PATTERNS = re.compile(
    r"enable\s+javascript|please\s+enable\s+js|verify\s+you\s+are\s+human|"
    r"just\s+a\s+moment|access\s+denied|captcha|cf\.link|challenge",
    re.IGNORECASE,
)

_SHELL_MIN_CHARS = 80
_SHELL_SCAN_CHARS = 2000


def _is_shell(text: str) -> bool:
    """判隐性失败：空/过短/含反爬提示 → True，触发降级（设计文档 71 §4.2）。"""
    t = (text or "").strip()
    if not t:
        return True
    if len(t) < _SHELL_MIN_CHARS:
        return True
    return bool(_ANTI_BOT_PATTERNS.search(t[:_SHELL_SCAN_CHARS]))


_CHAIN_ALIASES = {"trafilatura": "trafilatura", "crawl4ai": "crawl4ai",
                  "jina": "jina_reader", "jina_reader": "jina_reader"}


def _normalize_chain(chain: list[str] | None) -> list[str]:
    """规范化降级链（去重保序、别名收敛、过滤未知级）。"""
    if not chain:
        return ["trafilatura", "jina_reader"]
    out: list[str] = []
    for item in chain:
        name = _CHAIN_ALIASES.get(str(item).strip().lower(), "")
        if name and name not in out:
            out.append(name)
    return out or ["trafilatura", "jina_reader"]


class FetchPolicy:
    """单跑抓取策略（per-run 实例）：懒触发上限 + 同 URL 去重（doc 71 §5.3/§6.1）。

    线程安全：delegate 并行子 Agent / 并行 tool_calls 共享同一 per-run 实例，
    ``get``/``record`` 全程持锁（去重判空 + 计数原子化，防双抓双计突破上限）。
    """

    def __init__(self, max_per_run: int = 6) -> None:
        self._max = max(1, int(max_per_run))
        self._seen: dict[str, Any] = {}
        self._count = 0
        self._lock = threading.Lock()

    @property
    def max_per_run(self) -> int:
        return self._max

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def get(self, url: str) -> tuple[str, Any]:
        """本轮判定，返回 ``(kind, note)``：

        - ``("cached", FetchResult)``：本 run 已抓过 → 不重抓、不计上限（返回上次结果）；
        - ``("limit", 提示)``：超上限 → 不抓，返回「已达上限」可读提示；
        - ``("ok", "")``：允许抓取。
        """
        with self._lock:
            if url in self._seen:
                return "cached", self._seen[url]
            if self._count >= self._max:
                return (
                    "limit",
                    f"抓取次数已达上限（本任务 {self._max} 次），请基于现有摘要作答，剩余疑点记为待核验。",
                )
            return "ok", ""

    def record(self, url: str, result: Any) -> None:
        """成功抓取后登记：存结果供去重回读 + 计数（仅实际抓取才计数）。"""
        with self._lock:
            self._seen[url] = result
            self._count += 1
