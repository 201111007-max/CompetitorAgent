"""L4 进化记录（EvolutionMemory）

统计每个数据源（source）的成功率，驱动 SourceSelector 优选：
- SPA 站点 → Playwright 优先（成功率自动积累）
- record_outcome(source, success) 累积计数
- source_success_rates() 返回成功率字典（含默认值 0.5 平滑）
"""
from __future__ import annotations

import logging
from pathlib import Path

from competitor_agent.memory.json_store import JsonStore

logger = logging.getLogger("competitor_agent.memory.evolution_memory")

_SMOOTHING_PRIOR = 0.5
_SMOOTHING_ALPHA = 1.0


class EvolutionMemory:
    """L4 进化层：数据源成功率统计"""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._store = JsonStore("evolution_memory", data_dir)

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