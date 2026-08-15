"""L4 进化记录（EvolutionMemory）

统计每个数据源（source）的成功率，驱动 SourceSelector 优选：
- SPA 站点 → Playwright 优先（成功率自动积累）
- record_outcome(source, success) 累积计数
- source_success_rates() 返回成功率字典（含默认值 0.5 平滑）

设计文档 35：新增经验/反例归纳（note_pattern / retrieve_patterns），
按竞品记录可检索的模式清单（独立 JsonStore，不污染成功率统计），供规划与失败归因联动。
设计文档 45：L4 消费接线——retrieve_patterns_with_outcome（规划提权/降权按 outcome 判定）
+ failure_patterns_for（源选择把失败反例命中源排后）。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from competitor_agent.memory.json_store import JsonStore, now_iso

logger = logging.getLogger("competitor_agent.memory.evolution_memory")

_SMOOTHING_PRIOR = 0.5
_SMOOTHING_ALPHA = 1.0
_MAX_PATTERNS_PER_COMPETITOR = 50

# 失败/降级 outcome 集（供 failure_patterns_for 判定反例）
_FAILURE_OUTCOMES = frozenset({"failure", "degraded"})
# 从 pattern 文本提取源名（"由源 X 有效" / "源 X 无数据" 等）；源名即 source_name（ASCII 标识符）
_PATTERN_SOURCE_RE = re.compile(r"源\s*([A-Za-z_][A-Za-z0-9_]*)")


class EvolutionMemory:
    """L4 进化层：数据源成功率统计 + 经验/反例归纳"""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._store = JsonStore("evolution_memory", data_dir)
        self._pattern_store = JsonStore("evolution_patterns", data_dir)

    def note_pattern(
        self,
        competitor: str,
        dimension: str,
        pattern: str,
        outcome: str,
    ) -> None:
        """记录一条可检索经验/反例（跨竞品归纳），outcome ∈ {success, degraded, failure}。

        同 (dimension, pattern, outcome) 去重并刷新时间戳；每竞品最多保留
        ``_MAX_PATTERNS_PER_COMPETITOR`` 条（先进先出裁剪）。
        """
        if not competitor or not pattern:
            return
        patterns = self._patterns(competitor)
        for item in patterns:
            if (
                item.get("dimension") == dimension
                and item.get("pattern") == pattern
                and item.get("outcome") == outcome
            ):
                item["created_at"] = now_iso()
                self._persist_patterns(competitor, patterns)
                return
        patterns.append(
            {
                "dimension": dimension,
                "pattern": pattern,
                "outcome": outcome,
                "created_at": now_iso(),
            }
        )
        patterns = patterns[-_MAX_PATTERNS_PER_COMPETITOR:]
        self._persist_patterns(competitor, patterns)

    def retrieve_patterns(self, competitor: str, dimension: str) -> list[str]:
        """取回某竞品该维度的经验/反例（供规划与失败归因联动读取）。"""
        return [
            str(item["pattern"])
            for item in self._patterns(competitor)
            if item.get("dimension") == dimension
        ]

    def retrieve_patterns_with_outcome(
        self, competitor: str, dimension: str
    ) -> list[tuple[str, str]]:
        """取回某竞品该维度的 (pattern, outcome) 列表（设计文档 45）。

        供规划提权/降权按 outcome 可靠判定（区别于仅文本的 retrieve_patterns）。
        """
        return [
            (str(item["pattern"]), str(item.get("outcome", "")))
            for item in self._patterns(competitor)
            if item.get("dimension") == dimension
        ]

    def failure_patterns_for(self, competitor: str) -> list[str]:
        """取回某竞品失败/降级反例涉及的源名清单（设计文档 45 §3.1）。

        从 outcome ∈ {failure, degraded} 的 pattern 文本提取源名（"由源 X 有效" 等格式），
        供 SourceSelector.set_failure_penalties 把记录 failures 的源排后；提取不到源名则跳过。
        """
        sources: set[str] = set()
        for item in self._patterns(competitor):
            if item.get("outcome") not in _FAILURE_OUTCOMES:
                continue
            match = _PATTERN_SOURCE_RE.search(str(item.get("pattern", "")))
            if match:
                sources.add(match.group(1))
        return sorted(sources)

    def record_outcome(self, source: str, success: bool) -> None:
        """记录一次数据源采集成败"""
        if not source:
            return
        record = self._record(source)
        record["success"] = int(record.get("success", 0)) + (1 if success else 0)
        record["total"] = int(record.get("total", 0)) + 1
        record["last_success"] = bool(success)
        self._store.put(source, record)
        self._store.save()

    def source_success_rates(self) -> dict[str, float]:
        """返回每个数据源的成功率（0.0~1.0，带平滑）"""
        rates: dict[str, float] = {}
        for source in self._store:
            record = self._record(source)
            total = int(record.get("total", 0))
            if total == 0:
                rates[source] = _SMOOTHING_PRIOR
                continue
            success = int(record.get("success", 0))
            # 平滑： (success + alpha*prior) / (total + alpha)
            rates[source] = (success + _SMOOTHING_ALPHA * _SMOOTHING_PRIOR) / (
                total + _SMOOTHING_ALPHA
            )
        return rates

    def top_sources(self, n: int = 5) -> list[tuple[str, float]]:
        """按成功率取前 N 个数据源"""
        rates = self.source_success_rates()
        return sorted(rates.items(), key=lambda kv: kv[1], reverse=True)[:n]

    def _record(self, source: str) -> dict:
        raw = self._store.get(source)
        if not isinstance(raw, dict):
            return {}
        return raw

    def _patterns(self, competitor: str) -> list[dict]:
        raw = self._pattern_store.get(competitor, [])
        return raw if isinstance(raw, list) else []

    def _persist_patterns(self, competitor: str, patterns: list[dict]) -> None:
        self._pattern_store.put(competitor, patterns)
        self._pattern_store.save()