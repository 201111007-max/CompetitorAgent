"""复盘主编排器"""
from typing import Optional, Callable, List
from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.verifier import IStopVerifier
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
        """
        self._data_source = data_source
        self._strategic_loop = strategic_loop
        self._tactical_loop_factory = tactical_loop_factory
        self._stop_verifier = stop_verifier
        self._report_builder = report_builder
        self._state = state
        self._markdown_renderer = markdown_renderer or MarkdownRenderer()
        self._max_verification_retries = max_verification_retries

        logger.info("复盘主编排器初始化完成")

    async def review(self, match_id: str) -> ReviewReport:
        """执行完整复盘

        Args:
            match_id: OpenDota 比赛 ID

        Returns:
            ReviewReport: 完整复盘报告
        """
        logger.info("开始复盘: match_id=%s", match_id)

        # 1. 获取比赛数据
        try:
            match_data = await self._data_source.fetch_match(match_id)
            self._state.match_data = match_data
            logger.info("比赛数据获取成功")
        except Exception as e:
            logger.error("比赛数据获取失败: %s", str(e))
            # 返回空报告
            return self._create_error_report(match_id, f"数据获取失败: {str(e)}")

        # 2. 战略评估
        strategy = self._strategic_loop.evaluate(match_data)
        self._state.strategy = strategy
        logger.info("战略评估完成: match_type=%s", strategy.match_type)

        # 3. 多阶段战术分析
        phase_results: List[AnalysisResult] = []
        for phase in strategy.priority_phases:
            # 检查是否被中断
            if self._state.is_interrupted:
                logger.info("复盘被中断")
                return self._create_partial_report(
                    match_data, phase_results, ReviewTerminalState.INTERRUPTED.value
                )

            # 获取该阶段预算
            budget_config = strategy.budget_allocation.get(phase, 2)
            budget = IterationBudget(
                max_iterations=budget_config,
                max_tokens=budget_config * 4000,  # 假设每次迭代 4000 tokens
            )

            # 创建分析上下文
            context = AnalysisContext(
                phase=phase,
                budget=budget,
                completed_results=phase_results,
                config={"depth": strategy.expected_depth.get(phase, "standard")},
            )

            # 创建战术循环并执行
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
                "阶段 %s 完成: confidence=%.2f, conclusions=%d",
                phase,
                result.confidence,
                len(result.conclusions),
            )

        # 4. 停止验证
        terminal_state = self._verify_and_retry(match_data, phase_results)

        # 5. 构建报告
        report = self._report_builder.build(
            match_data=match_data,
            phase_results=phase_results,
            terminal_state=terminal_state,
        )

        # 6. 渲染 Markdown
        report.markdown_report = self._markdown_renderer.render(report)

        logger.info("复盘完成: match_id=%s", match_id)
        return report

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
        for retry in range(self._max_verification_retries):
            verification = self._stop_verifier.verify(self._state)

            if verification.passed:
                logger.info("停止验证通过")
                return ReviewTerminalState.COMPLETED.value

            logger.warning(
                "停止验证未通过 (重试 %d/%d): %s",
                retry + 1,
                self._max_verification_retries,
                verification.blocking_reasons,
            )

            # TODO: 可以根据 suggestions 进行补充分析
            # 当前简化处理：直接继续

        logger.warning("停止验证多次未通过，使用已有结果")
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
