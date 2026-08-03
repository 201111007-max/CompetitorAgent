"""ParallelRunner — 高优先级独立维度并行采集分析（M3 3.6）

- 把策略中的核心/独立缺口拆分给多个 SubAgent 并发执行
- 共享 ThreadSafe 预算（IterationBudget 有 Lock）
- 收集各子代理的 DimensionResult 合并返回（顺序稳定：按策略 gaps 顺序）
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from competitor_agent.core.subagent import SubAgent
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.observability.logger import get_logger

logger = get_logger("core.parallel_runner")

SubAgentFactory = Callable[[InfoGap, CompetitorStrategy], SubAgent]


class ParallelRunner:
    """并行执行多个独立缺口"""

    def __init__(
        self,
        subagent_factory: SubAgentFactory,
        max_workers: int = 4,
    ) -> None:
        self._factory = subagent_factory
        self._max_workers = max_workers

    def run(
        self,
        strategy: CompetitorStrategy,
        fields: list[str] | None = None,
    ) -> list[DimensionResult]:
        """并行执行指定缺口（默认核心缺口），返回按原顺序合并的结果。"""
        targets = strategy.gaps if fields is None else [g for g in strategy.gaps if g.field in fields]
        if not targets:
            return []

        agents: list[SubAgent] = [self._factory(gap, strategy) for gap in targets]
        results: dict[str, DimensionResult] = {}

        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(agents))) as pool:
            futures = {pool.submit(agent.run): agent.field for agent in agents}
            for future in as_completed(futures):
                field = futures[future]
                try:
                    result = future.result()
                except Exception:
                    logger.exception("子代理 %s 执行失败", field)
                    continue
                if result is not None:
                    results[field] = result

        # 按策略 gaps 顺序稳定返回
        return [results[g.field] for g in targets if g.field in results]


__all__ = ["ParallelRunner"]