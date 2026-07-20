"""复盘主编排器"""
from typing import Optional, Callable, List, Dict, Any
from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.verifier import IStopVerifier
from post_match_review.interfaces.analyzer import IReviewAnalyzer
from post_match_review.orchestrator.strategic_loop import StrategicLoop
from post_match_review.orchestrator.tactical_loop import TacticalLoop
from post_match_review.report.report_builder import ReportBuilder
from post_match_review.report.markdown_renderer import MarkdownRenderer
from post_match_review.types.report import ReviewReport
from post_match_review.types.match_data import MatchData
from post_match_review.types.state import ReviewAgentState
from post_match_review.types.analysis import AnalysisContext, AnalysisResult
from post_match_review.types.enums import ReviewTerminalState
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

        logger.info(
            "复盘主编排器初始化完成: parallel=%s, max_concurrency=%d",
            enable_parallel_phases,
            max_concurrency,
        )

    async def review(self, match_id: str) -> ReviewReport:
        """执行完整复盘

        Args:
            match_id: OpenDota 比赛 ID

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
        except Exception as e:
            logger.error("比赛数据获取失败: match_id=%s, error=%s", match_id, str(e))
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

        # 3. 多阶段战术分析
        logger.info("[步骤 3/6] 开始战术分析: enable_parallel=%s, phases=%d", self._enable_parallel_phases, len(strategy.priority_phases))
        if self._enable_parallel_phases and self._parallel_runner:
            logger.info("使用并行模式执行战术分析阶段")
            phase_results = await self._execute_parallel_phases(match_data, strategy)
        else:
            logger.info("使用串行模式执行战术分析阶段")
            phase_results = await self._execute_serial_phases(match_data, strategy)

        logger.info(
            "战术分析完成: 完成阶段数=%d, 总结论数=%d",
            len([r for r in phase_results if r.conclusions]),
            sum(len(r.conclusions) for r in phase_results),
        )

        # 4. 停止验证
        logger.info("[步骤 4/6] 开始停止验证")
        terminal_state = self._verify_and_retry(match_data, phase_results)
        logger.info("停止验证结果: terminal_state=%s", terminal_state)

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

        # 6. 渲染 Markdown
        logger.info("[步骤 6/6] 开始渲染 Markdown 报告")
        report.markdown_report = self._markdown_renderer.render(report)
        logger.info("Markdown 渲染完成: 报告长度=%d 字符", len(report.markdown_report))

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
    ) -> List[AnalysisResult]:
        """串行执行战术分析阶段

        Args:
            match_data: 比赛数据
            strategy: 分析策略

        Returns:
            List[AnalysisResult]: 阶段结果列表
        """
        logger.info(
            "[串行模式] 开始执行: phases=%s, total_phases=%d",
            strategy.priority_phases,
            len(strategy.priority_phases),
        )
        phase_results: List[AnalysisResult] = []

        for idx, phase in enumerate(strategy.priority_phases):
            logger.info(
                "[串行模式] 开始阶段 %d/%d: phase=%s",
                idx + 1,
                len(strategy.priority_phases),
                phase,
            )

            # 检查是否被中断
            if self._state.is_interrupted:
                logger.info("[串行模式] 检测到中断信号，提前返回: completed=%d/%d", idx, len(strategy.priority_phases))
                return phase_results

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

            logger.info(
                "[串行模式] 阶段 %d/%d 完成: phase=%s, confidence=%.2f, conclusions=%d, iterations=%d, tokens=%d, 累计置信度=%.2f",
                idx + 1,
                len(strategy.priority_phases),
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
    ) -> List[AnalysisResult]:
        """并行执行战术分析阶段

        Args:
            match_data: 比赛数据
            strategy: 分析策略

        Returns:
            List[AnalysisResult]: 阶段结果列表
        """
        if not self._analyzer_factory or not self._parallel_runner:
            logger.warning("[并行模式] 并行模式未正确配置（analyzer_factory=%s, parallel_runner=%s），降级为串行执行", self._analyzer_factory, self._parallel_runner)
            return await self._execute_serial_phases(match_data, strategy)

        logger.info(
            "[并行模式] 开始创建子代理: phases=%s, total_phases=%d",
            strategy.priority_phases,
            len(strategy.priority_phases),
        )

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
                len(strategy.priority_phases),
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

        logger.info("[并行模式] 子代理创建完成: count=%d，开始并行执行", len(subagents))

        # 并行执行
        phase_results = await self._parallel_runner.run(subagents, match_data)

        # 更新状态
        success_count = 0
        fail_count = 0
        for result in phase_results:
            if result.conclusions:
                self._state.completed_phases.append(result.phase)
                self._state.conclusions.extend(result.conclusions)
                self._state.total_iterations += result.iterations_used
                self._state.total_tokens += result.tokens_consumed
                success_count += 1
            else:
                fail_count += 1
                logger.warning(
                    "[并行模式] 阶段执行失败: phase=%s, analysis_text=%s",
                    result.phase,
                    result.analysis_text,
                )

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

    def get_partial_result(self) -> Optional[ReviewReport]:
        """获取中断后的部分结果

        Returns:
            Optional[ReviewReport]: 部分结果报告
        """
        if not self._state.match_data:
            return None

        return self._create_partial_report(
            self._state.match_data,
            [],  # TODO: 从状态中获取已有的 phase_results
            ReviewTerminalState.INTERRUPTED.value,
        )

    def _verify_and_retry(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult],
    ) -> str:
        """执行停止验证并在需要时重试

        Args:
            match_data: 比赛数据
            phase_results: 阶段结果

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

            # TODO: 可以根据 suggestions 进行补充分析
            # 当前简化处理：直接继续

        logger.warning(
            "[停止验证] %d 次验证均未通过，使用已有结果: terminal_state=%s",
            self._max_verification_retries,
            ReviewTerminalState.VERIFICATION_BLOCKED.value,
        )
        return ReviewTerminalState.VERIFICATION_BLOCKED.value

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
        from post_match_review.types.report import MatchSummary

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
