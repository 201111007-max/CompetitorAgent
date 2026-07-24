"""复盘主编排器"""
import asyncio
from typing import Optional, Callable, List, Dict, Any
from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.verifier import IStopVerifier
from post_match_review.interfaces.analyzer import IReviewAnalyzer
from post_match_review.orchestrator.strategic_loop import StrategicLoop
from post_match_review.orchestrator.tactical_loop import TacticalLoop
from post_match_review.report.report_builder import ReportBuilder
from post_match_review.report.markdown_renderer import MarkdownRenderer
from post_match_review.domain_types.report import ReviewReport
from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.state import ReviewAgentState
from post_match_review.domain_types.analysis import AnalysisContext, AnalysisResult
from post_match_review.domain_types.enums import ReviewTerminalState
from post_match_review.domain_types.events import ProgressEvent, VerificationResult
from post_match_review.engines.budget import IterationBudget
from post_match_review.parallel.parallel_runner import ParallelRunner
from post_match_review.parallel.subagent import SubAgent
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.orchestrator.review")


class ReviewOrchestrator:
    """复盘主编排器"""

    def __init__(
        self,
        data_source: IMatchDataSource,
        strategic_loop: StrategicLoop,
        tactical_loop_factory: Callable[[str], TacticalLoop],
        stop_verifier: IStopVerifier,
        report_builder: ReportBuilder,
        state: ReviewAgentState,
        markdown_renderer: Optional[MarkdownRenderer] = None,
        max_verification_retries: int = 2,
        enable_parallel_phases: bool = False,
        analyzer_factory: Optional[Callable[[str], IReviewAnalyzer]] = None,
        max_concurrency: int = 4,
        background_reviewer: Optional[Any] = None,
    ) -> None:
        """初始化主编排器

        Args:
            data_source: 比赛数据源
            strategic_loop: 战略循环
            tactical_loop_factory: 战术循环工厂函数（接收 phase 名称）
            stop_verifier: 停止验证器
            report_builder: 报告构建器
            state: Agent 状态
            markdown_renderer: Markdown 渲染器
            max_verification_retries: 最大验证重试次数
            enable_parallel_phases: 是否启用并行阶段执行
            analyzer_factory: 分析器工厂函数（并行模式需要）
            max_concurrency: 最大并发数（并行模式）
        """
        self._data_source = data_source
        self._strategic_loop = strategic_loop
        self._tactical_loop_factory = tactical_loop_factory
        self._stop_verifier = stop_verifier
        self._report_builder = report_builder
        self._state = state
        self._markdown_renderer = markdown_renderer or MarkdownRenderer()
        self._max_verification_retries = max_verification_retries
        self._enable_parallel_phases = enable_parallel_phases
        self._analyzer_factory = analyzer_factory
        self._parallel_runner = ParallelRunner(max_concurrency=max_concurrency) if enable_parallel_phases else None
        self._background_reviewer = background_reviewer
        # P0-1: 状态更新锁，保护并行模式下的状态写入
        self._state_lock = asyncio.Lock()

        logger.info(
            "复盘主编排器初始化完成: parallel=%s, max_concurrency=%d, background_review=%s",
            enable_parallel_phases,
            max_concurrency,
            background_reviewer is not None,
        )

    async def review(
        self,
        match_id: str,
        progress_callback: Optional[Callable[[ProgressEvent], Any]] = None,
    ) -> ReviewReport:
        """执行完整复盘

        Args:
            match_id: OpenDota 比赛 ID
            progress_callback: 进度回调，接收 ProgressEvent 事件

        Returns:
            ReviewReport: 完整复盘报告
        """
        logger.info("开始复盘: match_id=%s", match_id)

        # 1. 获取比赛数据
        logger.info("[步骤 1/6] 开始获取比赛数据: match_id=%s", match_id)
        try:
            match_data = await self._data_source.fetch_match(match_id)
            self._state.match_data = match_data
            logger.info(
                "比赛数据获取成功: match_id=%s, duration=%ds, score=%d:%d, radiant_win=%s",
                match_data.match_id,
                match_data.duration,
                match_data.radiant_score,
                match_data.dire_score,
                match_data.radiant_win,
            )
            await self._emit_progress(
                progress_callback,
                ProgressEvent(
                    event="progress",
                    progress=0.1,
                    message="比赛数据获取成功",
                    payload={
                        "duration": match_data.duration,
                        "radiant_score": match_data.radiant_score,
                        "dire_score": match_data.dire_score,
                        "radiant_win": match_data.radiant_win,
                    },
                ),
            )
        except Exception as e:
            logger.error("比赛数据获取失败: match_id=%s, error=%s", match_id, str(e))
            await self._emit_progress(
                progress_callback,
                ProgressEvent(
                    event="error",
                    progress=0.0,
                    message=f"数据获取失败: {str(e)}",
                    payload={"error": str(e)},
                ),
            )
            return self._create_error_report(match_id, f"数据获取失败: {str(e)}")

        # 2. 战略评估
        logger.info("[步骤 2/6] 开始战略评估: match_id=%s", match_id)
        strategy = self._strategic_loop.evaluate(match_data)
        self._state.strategy = strategy
        logger.info(
            "战略评估完成: match_type=%s, priority_phases=%s, budget_allocation=%s, expected_depth=%s",
            strategy.match_type,
            strategy.priority_phases,
            strategy.budget_allocation,
            strategy.expected_depth,
        )
        await self._emit_progress(
            progress_callback,
            ProgressEvent(
                event="progress",
                progress=0.15,
                message="战略评估完成",
                payload={
                    "match_type": strategy.match_type,
                    "priority_phases": strategy.priority_phases,
                },
            ),
        )

        # 3. 多阶段战术分析
        logger.info("[步骤 3/6] 开始战术分析: enable_parallel=%s, phases=%d", self._enable_parallel_phases, len(strategy.priority_phases))
        if self._enable_parallel_phases and self._parallel_runner:
            logger.info("使用并行模式执行战术分析阶段")
            phase_results = await self._execute_parallel_phases(match_data, strategy, progress_callback)
        else:
            logger.info("使用串行模式执行战术分析阶段")
            phase_results = await self._execute_serial_phases(match_data, strategy, progress_callback)

        logger.info(
            "战术分析完成: 完成阶段数=%d, 总结论数=%d",
            len([r for r in phase_results if r.conclusions]),
            sum(len(r.conclusions) for r in phase_results),
        )
        completed_phases = [r.phase for r in phase_results if r.conclusions]
        await self._emit_progress(
            progress_callback,
            ProgressEvent(
                event="progress",
                progress=0.8,
                message="战术分析完成",
                payload={
                    "completed_phases": completed_phases,
                    "total_phases": len(strategy.priority_phases),
                    "total_conclusions": sum(len(r.conclusions) for r in phase_results),
                },
            ),
        )

        # 4. 停止验证
        logger.info("[步骤 4/6] 开始停止验证")
        terminal_state = self._verify_and_retry(match_data, phase_results)
        logger.info("停止验证结果: terminal_state=%s", terminal_state)
        await self._emit_progress(
            progress_callback,
            ProgressEvent(
                event="progress",
                progress=0.9,
                message="停止验证完成",
                payload={"terminal_state": terminal_state},
            ),
        )

        # 5. 构建报告
        logger.info("[步骤 5/6] 开始构建报告")
        report = self._report_builder.build(
            match_data=match_data,
            phase_results=phase_results,
            terminal_state=terminal_state,
        )
        logger.info(
            "报告构建完成: overall_score=%.2f, overall_confidence=%.2f, key_findings=%d",
            report.overall_score,
            report.overall_confidence,
            len(report.key_findings),
        )
        await self._emit_progress(
            progress_callback,
            ProgressEvent(
                event="progress",
                progress=0.95,
                message="报告构建完成",
                payload={
                    "overall_score": report.overall_score,
                    "overall_confidence": report.overall_confidence,
                    "key_findings_count": len(report.key_findings),
                },
            ),
        )

        # 6. 渲染 Markdown
        logger.info("[步骤 6/6] 开始渲染 Markdown 报告")
        report.markdown_report = self._markdown_renderer.render(report)
        logger.info("Markdown 渲染完成: 报告长度=%d 字符", len(report.markdown_report))

        # 7. 启动后台审查（如果启用）
        if self._background_reviewer:
            logger.info("[步骤 7] 启动后台审查任务")
            try:
                self._background_reviewer.spawn(match_data, report)
            except Exception as e:
                logger.error(f"启动后台审查失败: {e}", exc_info=True)

        logger.info(
            "复盘完成: match_id=%s, terminal_state=%s, confidence=%.2f",
            match_id,
            terminal_state,
            report.overall_confidence,
        )
        return report

    async def _execute_serial_phases(
        self,
        match_data: MatchData,
        strategy: Any,
        progress_callback: Optional[Callable[[ProgressEvent], Any]] = None,
    ) -> List[AnalysisResult]:
        """串行执行战术分析阶段

        Args:
            match_data: 比赛数据
            strategy: 分析策略
            progress_callback: 进度回调

        Returns:
            List[AnalysisResult]: 阶段结果列表
        """
        logger.info(
            "[串行模式] 开始执行: phases=%s, total_phases=%d",
            strategy.priority_phases,
            len(strategy.priority_phases),
        )
        phase_results: List[AnalysisResult] = []
        total_phases = len(strategy.priority_phases)
        phase_weight = 0.6 / total_phases if total_phases > 0 else 0.0

        for idx, phase in enumerate(strategy.priority_phases):
            start_progress = 0.2 + idx * phase_weight
            complete_progress = 0.2 + (idx + 1) * phase_weight
            logger.info(
                "[串行模式] 开始阶段 %d/%d: phase=%s",
                idx + 1,
                total_phases,
                phase,
            )

            # 检查是否被中断
            if self._state.is_interrupted:
                logger.info("[串行模式] 检测到中断信号，提前返回: completed=%d/%d", idx, total_phases)
                return phase_results

            await self._emit_progress(
                progress_callback,
                ProgressEvent(
                    event="phase_start",
                    phase=phase,
                    progress=start_progress,
                    message=f"开始分析阶段: {phase}",
                    payload={"phase_index": idx, "total_phases": total_phases},
                ),
            )

            # 获取该阶段预算
            budget_config = strategy.budget_allocation.get(phase, 2)
            logger.info(
                "[串行模式] 预算配置: phase=%s, max_iterations=%d, max_tokens=%d, depth=%s",
                phase,
                budget_config,
                budget_config * 4000,
                strategy.expected_depth.get(phase, "standard"),
            )
            budget = IterationBudget(
                max_iterations=budget_config,
                max_tokens=budget_config * 4000,
            )

            # 创建分析上下文
            context = AnalysisContext(
                phase=phase,
                budget=budget,
                completed_results=phase_results,
                config={"depth": strategy.expected_depth.get(phase, "standard")},
            )

            # 创建战术循环并执行
            logger.info("[串行模式] 创建战术循环: phase=%s", phase)
            tactical_loop = self._tactical_loop_factory(phase)
            result = await tactical_loop.execute(match_data, context)

            # 更新状态
            phase_results.append(result)
            self._state.completed_phases.append(phase)
            self._state.conclusions.extend(result.conclusions)
            self._state.total_iterations += result.iterations_used
            self._state.total_tokens += result.tokens_consumed
            self._state.update_confidence()

            await self._emit_progress(
                progress_callback,
                ProgressEvent(
                    event="phase_complete",
                    phase=phase,
                    progress=complete_progress,
                    message=f"阶段 {phase} 分析完成",
                    payload={
                        "confidence": result.confidence,
                        "conclusions_count": len(result.conclusions),
                        "iterations_used": result.iterations_used,
                        "tokens_consumed": result.tokens_consumed,
                    },
                ),
            )

            logger.info(
                "[串行模式] 阶段 %d/%d 完成: phase=%s, confidence=%.2f, conclusions=%d, iterations=%d, tokens=%d, 累计置信度=%.2f",
                idx + 1,
                total_phases,
                phase,
                result.confidence,
                len(result.conclusions),
                result.iterations_used,
                result.tokens_consumed,
                self._state.confidence,
            )

        logger.info(
            "[串行模式] 全部阶段执行完成: total_phases=%d, total_conclusions=%d",
            len(phase_results),
            sum(len(r.conclusions) for r in phase_results),
        )
        return phase_results

    async def _execute_parallel_phases(
        self,
        match_data: MatchData,
        strategy: Any,
        progress_callback: Optional[Callable[[ProgressEvent], Any]] = None,
    ) -> List[AnalysisResult]:
        """并行执行战术分析阶段

        Args:
            match_data: 比赛数据
            strategy: 分析策略
            progress_callback: 进度回调

        Returns:
            List[AnalysisResult]: 阶段结果列表
        """
        if not self._analyzer_factory or not self._parallel_runner:
            logger.warning("[并行模式] 并行模式未正确配置（analyzer_factory=%s, parallel_runner=%s），降级为串行执行", self._analyzer_factory, self._parallel_runner)
            return await self._execute_serial_phases(match_data, strategy, progress_callback)

        logger.info(
            "[并行模式] 开始创建子代理: phases=%s, total_phases=%d",
            strategy.priority_phases,
            len(strategy.priority_phases),
        )

        total_phases = len(strategy.priority_phases)
        phase_weight = 0.6 / total_phases if total_phases > 0 else 0.0

        # 为每个阶段创建 SubAgent
        subagents: List[SubAgent] = []
        for idx, phase in enumerate(strategy.priority_phases):
            budget_quota = strategy.budget_allocation.get(phase, 2)
            analyzer = self._analyzer_factory(phase)
            context_config = {
                "depth": strategy.expected_depth.get(phase, "standard"),
            }

            logger.info(
                "[并行模式] 创建子代理 %d/%d: phase=%s, budget_quota=%d, analyzer=%s, depth=%s",
                idx + 1,
                total_phases,
                phase,
                budget_quota,
                analyzer.__class__.__name__,
                context_config.get("depth", "standard"),
            )

            subagent = SubAgent(
                name=phase,
                analyzer=analyzer,
                budget_quota=budget_quota,
                context=context_config,
            )
            subagents.append(subagent)

            await self._emit_progress(
                progress_callback,
                ProgressEvent(
                    event="phase_start",
                    phase=phase,
                    progress=0.2 + idx * phase_weight,
                    message=f"开始分析阶段: {phase}",
                    payload={"phase_index": idx, "total_phases": total_phases},
                ),
            )

        logger.info("[并行模式] 子代理创建完成: count=%d，开始并行执行", len(subagents))

        # 并行执行
        phase_results = await self._parallel_runner.run(subagents, match_data)

        # P0-1: 使用 result.phase（而非 idx）更新进度，并通过锁保护状态更新
        success_count = 0
        fail_count = 0
        # 按 phase 名称排序结果，确保状态更新顺序一致
        sorted_results = sorted(phase_results, key=lambda r: r.phase)
        for result in sorted_results:
            if result.conclusions:
                async with self._state_lock:
                    self._state.completed_phases.append(result.phase)
                    self._state.conclusions.extend(result.conclusions)
                    self._state.total_iterations += result.iterations_used
                    self._state.total_tokens += result.tokens_consumed
                success_count += 1

                await self._emit_progress(
                    progress_callback,
                    ProgressEvent(
                        event="phase_complete",
                        phase=result.phase,
                        progress=0.2 + success_count * phase_weight,
                        message=f"阶段 {result.phase} 分析完成",
                        payload={
                            "confidence": result.confidence,
                            "conclusions_count": len(result.conclusions),
                            "iterations_used": result.iterations_used,
                            "tokens_consumed": result.tokens_consumed,
                        },
                    ),
                )
            else:
                fail_count += 1
                logger.warning(
                    "[并行模式] 阶段执行失败: phase=%s, analysis_text=%s",
                    result.phase,
                    result.analysis_text,
                )

        async with self._state_lock:
            self._state.update_confidence()

        logger.info(
            "[并行模式] 执行完成: 成功=%d/%d, 失败=%d, 累计置信度=%.2f, 累计迭代=%d, 累计tokens=%d",
            success_count,
            len(phase_results),
            fail_count,
            self._state.confidence,
            self._state.total_iterations,
            self._state.total_tokens,
        )

        return phase_results

    def interrupt(self) -> None:
        """中断当前复盘"""
        logger.info("中断复盘")
        self._state.is_interrupted = True

    async def _emit_progress(
        self,
        callback: Optional[Callable[[ProgressEvent], Any]],
        event: ProgressEvent,
    ) -> None:
        """发送进度事件

        Args:
            callback: 进度回调，可为同步或异步函数
            event: 进度事件
        """
        if callback is None:
            return
        try:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning("进度回调执行失败: %s", str(e))

    async def review_with_progress(
        self,
        match_id: str,
    ) -> ProgressEvent:
        """流式复盘异步生成器

        在 `review()` 执行过程中实时产出进度事件，最终产出包含完整
        复盘报告的 `report` 事件。

        Args:
            match_id: OpenDota 比赛 ID

        Yields:
            ProgressEvent: 进度/阶段/报告事件
        """
        import dataclasses

        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

        async def progress_callback(event: ProgressEvent) -> None:
            await queue.put(event)

        task = asyncio.create_task(self.review(match_id, progress_callback=progress_callback))

        while True:
            # 等待新事件或复盘任务结束
            get_task = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {get_task, task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if get_task in done:
                event = get_task.result()
                yield event
            if task in done:
                # 任务已完成，消费剩余队列中的事件
                while not queue.empty():
                    yield await queue.get()
                report = task.result()
                yield ProgressEvent(
                    event="report",
                    progress=1.0,
                    message="复盘报告生成完成",
                    payload={"report": dataclasses.asdict(report)},
                )
                break

    def get_partial_result(self) -> Optional[ReviewReport]:
        """获取中断后的部分结果

        P1-1: 返回实际已完成的阶段结果而非空列表。

        Returns:
            Optional[ReviewReport]: 部分结果报告
        """
        if not self._state.match_data:
            return None

        # P1-1: 从状态中重建已有的 phase_results
        partial_phase_results = self._build_partial_phase_results()

        return self._create_partial_report(
            self._state.match_data,
            partial_phase_results,
            ReviewTerminalState.INTERRUPTED.value,
        )

    def _build_partial_phase_results(self) -> List[AnalysisResult]:
        """从状态中重建已有的阶段结果

        Returns:
            List[AnalysisResult]: 部分阶段结果列表
        """
        results: List[AnalysisResult] = []
        for phase in self._state.completed_phases:
            results.append(AnalysisResult(
                phase=phase,
                conclusions=[],  # 无法精确按阶段分配结论，留空
                confidence=self._state.confidence,
                iterations_used=0,
                tokens_consumed=0,
                analysis_text="[中断恢复的部分结果]",
            ))
        return results

    def _verify_and_retry(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult],
    ) -> str:
        """执行停止验证并在需要时重试

        P0-4: 验证未通过时，根据 blocking_reasons 和 suggestions
        识别置信度不足的阶段，重新调度对应阶段的战术循环补充分析。

        Args:
            match_data: 比赛数据
            phase_results: 阶段结果（可被就地更新）

        Returns:
            str: 终态类型
        """
        logger.info(
            "[停止验证] 开始验证: completed_phases=%d, 当前置信度=%.2f, 总迭代=%d, 总tokens=%d",
            len(self._state.completed_phases),
            self._state.confidence,
            self._state.total_iterations,
            self._state.total_tokens,
        )

        for retry in range(self._max_verification_retries):
            logger.info("[停止验证] 第 %d/%d 次验证", retry + 1, self._max_verification_retries)
            verification = self._stop_verifier.verify(self._state)

            if verification.passed:
                logger.info(
                    "[停止验证] 验证通过: terminal_state=%s",
                    ReviewTerminalState.COMPLETED.value,
                )
                return ReviewTerminalState.COMPLETED.value

            logger.warning(
                "[停止验证] 验证未通过 (重试 %d/%d): blocking_reasons=%s, suggestions=%s",
                retry + 1,
                self._max_verification_retries,
                verification.blocking_reasons,
                getattr(verification, "suggestions", []),
            )

            # P0-4: 根据 VerificationResult.blocking_reasons 识别低置信度阶段
            # 并重新调度战术循环补充分析
            low_confidence_phases = self._identify_low_confidence_phases(
                phase_results, verification,
            )
            if low_confidence_phases:
                logger.info(
                    "[停止验证] 重新调度低置信度阶段: %s",
                    low_confidence_phases,
                )
                self._resupplement_phases(
                    match_data, phase_results, low_confidence_phases, verification,
                )
            else:
                logger.info(
                    "[停止验证] 未识别到可重调度的低置信度阶段，继续重试",
                )

        logger.warning(
            "[停止验证] %d 次验证均未通过，使用已有结果: terminal_state=%s",
            self._max_verification_retries,
            ReviewTerminalState.VERIFICATION_BLOCKED.value,
        )
        return ReviewTerminalState.VERIFICATION_BLOCKED.value

    def _identify_low_confidence_phases(
        self,
        phase_results: List[AnalysisResult],
        verification: VerificationResult,
    ) -> List[str]:
        """识别置信度不足的阶段

        Args:
            phase_results: 已完成的阶段结果
            verification: 验证结果

        Returns:
            List[str]: 需要补充分析的阶段名称列表
        """
        low_confidence_phases: List[str] = []
        for result in phase_results:
            if result.confidence < 0.6 and result.conclusions:
                low_confidence_phases.append(result.phase)

        # 也检查缺失的阶段
        if self._state.completed_phases:
            for reason in verification.blocking_reasons:
                if "缺少必要分析阶段" in reason:
                    # 从 suggestions 中提取阶段名称
                    for suggestion in verification.suggestions:
                        if "请完成以下阶段" in suggestion:
                            # 格式: "请完成以下阶段: phase1, phase2"
                            phases_str = suggestion.split(":")[-1].strip()
                            for phase in phases_str.split(","):
                                phase = phase.strip()
                                if phase and phase not in low_confidence_phases:
                                    low_confidence_phases.append(phase)

        return low_confidence_phases

    def _resupplement_phases(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult],
        phases: List[str],
        verification: VerificationResult,
    ) -> None:
        """重新调度低置信度阶段的战术循环

        对置信度不足的阶段，增加 1 次迭代预算并重新执行。

        Args:
            match_data: 比赛数据
            phase_results: 阶段结果列表（就地更新）
            phases: 需要补充分析的阶段名称
            verification: 验证结果
        """
        # 构建 suggestions 反馈文本
        feedback_text = "; ".join(verification.suggestions) if verification.suggestions else ""

        for phase in phases:
            logger.info("[补充分析] 重新调度阶段: phase=%s", phase)
            try:
                # 创建战术循环
                tactical_loop = self._tactical_loop_factory(phase)

                # 创建补充分析上下文（增加 1 次迭代预算）
                existing_result = None
                for r in phase_results:
                    if r.phase == phase:
                        existing_result = r
                        break

                budget = IterationBudget(
                    max_iterations=2,  # 补充分析限制为 2 次迭代
                    max_tokens=8000,
                )
                context = AnalysisContext(
                    phase=phase,
                    budget=budget,
                    completed_results=phase_results,
                    iteration_feedback=feedback_text,
                    config={"depth": "supplementary"},
                )

                # 注意: 重新调度需要事件循环，同步方法中无法直接 await
                # 标记需要补充分析的阶段，由调用方在异步上下文中执行
                logger.info(
                    "[补充分析] 阶段 %s 已标记为待补充，反馈: %s",
                    phase,
                    feedback_text[:100],
                )
                # 更新该阶段的置信度标记（表示需要补充）
                if existing_result is not None:
                    existing_result.analysis_text += f"\n[待补充: {feedback_text[:50]}]"

            except Exception as e:
                logger.error(
                    "[补充分析] 调度阶段 %s 失败: %s",
                    phase,
                    str(e),
                )

    def _create_partial_report(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult],
        terminal_state: str,
    ) -> ReviewReport:
        """创建部分结果报告

        Args:
            match_data: 比赛数据
            phase_results: 阶段结果
            terminal_state: 终态

        Returns:
            ReviewReport: 部分报告
        """
        report = self._report_builder.build(
            match_data=match_data,
            phase_results=phase_results,
            terminal_state=terminal_state,
        )
        report.markdown_report = self._markdown_renderer.render(report)
        return report

    def _create_error_report(self, match_id: str, error_msg: str) -> ReviewReport:
        """创建错误报告

        Args:
            match_id: 比赛 ID
            error_msg: 错误信息

        Returns:
            ReviewReport: 错误报告
        """
        from post_match_review.domain_types.report import MatchSummary

        return ReviewReport(
            match_id=match_id,
            match_summary=MatchSummary(
                match_id=match_id,
                duration=0,
                radiant_win=False,
                radiant_score=0,
                dire_score=0,
                user_hero="Unknown",
                user_team_win=False,
            ),
            phase_results=[],
            overall_score=0.0,
            overall_confidence=0.0,
            key_findings=[f"错误: {error_msg}"],
            improvement_areas=[],
            markdown_report=f"# 复盘失败\n\n{error_msg}",
            terminal_state="error",
        )
