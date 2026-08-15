"""统一编排层 — 单 Agent 缺口执行闭环（设计文档 18 §3）

收敛 single 流水线的缺口级执行（选源→采集→分析→记忆→checkpoint）为单一
`SingleOrchestrator`，实现 `AnalysisOrchestrator` 协议，供 facade 委托调用，
避免 CompetitorAnalysisAPI 膨胀（问题 20：facade 600+ 行混装）。

- `AnalysisOrchestrator`：统一编排协议（single/team 均为"策略 + 预算 → 维度结果"）
- `SingleOrchestrator`：逐缺口闭环，复用 GapExecutor 的采集/分析段；
  并行（execution.mode=parallel）与串行共用 `_run_gap`，共享预算/取消/checkpoint。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from competitor_agent.analyzers.registry import AnalyzerRegistry
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.config.loader import AppConfig
from competitor_agent.core.budget import IterationBudget
from competitor_agent.core.budget_controller import BudgetController
from competitor_agent.core.checkpoint import is_cancelled, save_checkpoint
from competitor_agent.core.tactical_loop import TacticalLoop
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.context import Skill
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.observability.logger import get_logger, set_current_session

logger = get_logger("core.orchestrator")


class AnalysisOrchestrator(Protocol):
    """统一编排协议：策略 + 预算 → 维度结果（single/team 调度形态不同，闭环语义一致）"""

    def run(
        self,
        strategy: CompetitorStrategy,
        iteration_budget: IterationBudget,
        sid: str,
        task: str,
        *,
        event_sink: Any = None,
        memory: IFourLayerMemory | None = None,
        observability: Any = None,
    ) -> list[DimensionResult]: ...


class SingleOrchestrator:
    """single 模式：逐缺口串行/并行执行（复用 GapExecutor 采集分析段）"""

    def __init__(
        self,
        *,
        config: AppConfig,
        budget: BudgetController,
        selector: SourceSelector,
        extractor: Any,
        analyzers: AnalyzerRegistry,
        ingester: Any | None = None,
        retriever: Any | None = None,
        memory: IFourLayerMemory | None = None,
        providers: dict[str, object] | None = None,
    ) -> None:
        self._config = config
        self._budget = budget
        self._selector = selector
        self._extractor = extractor
        self._analyzers = analyzers
        self._ingester = ingester
        self._retriever = retriever
        self._memory = memory
        self._providers = dict(providers or {})

    def run(
        self,
        strategy: CompetitorStrategy,
        iteration_budget: IterationBudget,
        sid: str,
        task: str,
        *,
        event_sink: Any = None,
        memory: IFourLayerMemory | None = None,
        observability: Any = None,
    ) -> list[DimensionResult]:
        """执行全部独立缺口：execution.mode == parallel 时并行，否则串行。"""
        if memory is not None:
            self._memory = memory
        if self._config.execution.mode != "parallel" or len(strategy.gaps) < 2:
            return self._run_gaps_serial(strategy, iteration_budget, sid, task, event_sink)
        return self._run_gaps_parallel(strategy, iteration_budget, sid, task, event_sink)

    def _run_gaps_serial(
        self,
        strategy: CompetitorStrategy,
        iteration_budget: IterationBudget,
        sid: str,
        task: str,
        event_sink: Any,
    ) -> list[DimensionResult]:
        results: list[DimensionResult] = []
        completed_lock = threading.Lock()
        for gap in strategy.gaps:
            self._run_gap(strategy, gap, iteration_budget, results, completed_lock, sid, task, event_sink)
        return results

    def _run_gaps_parallel(
        self,
        strategy: CompetitorStrategy,
        iteration_budget: IterationBudget,
        sid: str,
        task: str,
        event_sink: Any,
    ) -> list[DimensionResult]:
        gaps = list(strategy.gaps)
        workers = min(self._config.execution.max_parallel_subagents, len(gaps))
        if event_sink is not None:
            event_sink(
                ProgressEvent(
                    event="phase_start",
                    phase="execution",
                    message=f"并行执行 {len(gaps)} 个缺口，max_workers={workers}",
                )
            )
        completed: list[DimensionResult] = []
        completed_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gap") as pool:
            futures = {
                pool.submit(
                    self._run_gap, strategy, gap, iteration_budget, completed, completed_lock, sid, task, event_sink
                ): gap
                for gap in gaps
            }
            for future in as_completed(futures):
                gap = futures[future]
                try:
                    future.result()
                except Exception:  # 单缺口异常不影响整体
                    logger.exception("并行缺口 %s 执行失败", gap.field)

        # 按缺口原始顺序稳定返回（与串行路径一致）
        by_field = {r.dimension: r for r in completed}
        return [by_field[g.field] for g in gaps if g.field in by_field]

    def _run_gap(
        self,
        strategy: CompetitorStrategy,
        gap: InfoGap,
        iteration_budget: IterationBudget,
        completed: list[DimensionResult],
        completed_lock: threading.Lock,
        sid: str,
        task: str,
        event_sink: Any,
    ) -> DimensionResult | None:
        """执行单个缺口闭环：预算/取消检查 → TacticalLoop → 结果合并 + 记忆/预算/checkpoint。

        串行与并行共用此实现；并行下多个缺口共享同一迭代预算与取消标志。
        """
        set_current_session(sid)  # 并行 worker 线程的会话上下文（埋点/LLM 日志）
        if self._budget.should_stop(strategy.gaps).should_stop:
            return None
        if is_cancelled(sid):
            logger.info("会话 %s 被取消，停止分析", sid)
            return None
        if event_sink is not None:
            event_sink(
                ProgressEvent(
                    event="phase_start",
                    phase=f"tactical.{gap.field}",
                    progress=0.3,
                    message=f"采集并分析 {gap.field}",
                )
            )
        analyzer = self._analyzers.get(gap.field)
        loop = TacticalLoop(
            selector=self._selector,
            extractor=self._extractor,
            analyzer=analyzer,
            budget=iteration_budget,
            ingester=self._ingester,
            retriever=self._retriever,
            session_id=sid,
            providers=self._providers,
            memory_context_fn=self._memory_context_fn(),
        )
        result = loop.execute(gap, strategy)
        # 每完成一个缺口保存 checkpoint（结果快照 + 共享预算用量）
        with completed_lock:
            if result is not None:
                completed.append(result)
            completion = list(completed)
        if result is not None:
            self._record_memory_success(strategy, gap)
        self._budget.record_iteration(cost=0.01)
        save_checkpoint(
            session_id=sid,
            task=task,
            competitor_name=strategy.competitor.name,
            gaps=strategy.gaps,
            dimension_results=completion,
            iterations_used=iteration_budget.used_iterations,
            max_iterations=self._budget.max_iterations,
            cost_used=iteration_budget.used_cost,
            cost_limit=self._budget.cost_limit,
            sources_tried=[s for g in strategy.gaps for s in g.sources_tried],
        )
        return result

    def _memory_context_fn(self) -> Any:
        """记忆召回回调（设计文档 35）：(competitor, dimension) -> 相关历史经验文本。"""
        if self._memory is None:
            return None
        return lambda comp, dim: "\n".join(
            self._memory.recent_context(comp, top_k=3, query=dim)
        )

    def _record_memory_success(self, strategy: CompetitorStrategy, gap: object) -> None:
        """分析成功后沉淀技能（含做法）+ 记录数据源成功率 + 进化经验（记忆自动进化）"""
        if self._memory is None:
            return
        gap_field = getattr(gap, "field", "")
        competitor = strategy.competitor.name
        tried = getattr(gap, "sources_tried", None) or []
        source = tried[-1] if tried else ""
        if source:
            # 做法：经降级链才命中 → 记录降级路径；直接命中 → 空（默认无需说明）
            method = f"降级链: {' → '.join(tried)}" if len(tried) > 1 else ""
            self._memory.record_skill(
                Skill(
                    competitor_name=competitor,
                    gap_field=gap_field,
                    source_name=source,
                    success=True,
                    method=method,
                )
            )
            self._memory.record_outcome(source, True)
            self._memory.note_pattern(
                competitor,
                gap_field,
                pattern=f"缺口 {gap_field} 由源 {source} 有效",
                outcome="success",
            )


__all__ = ["AnalysisOrchestrator", "SingleOrchestrator"]
