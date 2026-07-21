"""战术循环：单阶段深度分析"""
from typing import Optional
from post_match_review.interfaces.analyzer import IReviewAnalyzer
from post_match_review.interfaces.budget import IIterationBudget
from post_match_review.interfaces.compressor import IContextCompressor
from post_match_review.domain_types.analysis import AnalysisContext, AnalysisResult
from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.enums import BudgetDecision
from post_match_review.observability.logger import get_logger

logger = get_logger("orchestrator.tactical")


class TacticalLoop:
    """战术循环：单阶段深度分析

    在预算控制下迭代执行分析器，直到质量达标或预算耗尽。
    """

    def __init__(
        self,
        analyzer: IReviewAnalyzer,
        max_iterations: int = 3,
        compressor: Optional[IContextCompressor] = None,
    ) -> None:
        """初始化战术循环

        Args:
            analyzer: 分析器实例
            max_iterations: 最大迭代次数
            compressor: 上下文压缩器（可选）
        """
        self._analyzer = analyzer
        self._max_iterations = max_iterations
        self._compressor = compressor
        logger.info(
            "战术循环初始化: phase=%s, max_iterations=%d, compressor=%s",
            analyzer.phase_name,
            max_iterations,
            "enabled" if compressor else "disabled",
        )

    async def execute(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> AnalysisResult:
        """执行战术循环

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文

        Returns:
            AnalysisResult: 阶段分析结果
        """
        logger.info(
            "开始战术循环: phase=%s, max_iterations=%d, budget_remaining=%d",
            context.phase,
            self._max_iterations,
            context.budget.remaining_iterations,
        )

        budget = context.budget
        best_result: AnalysisResult | None = None
        iterations_used = 0
        tokens_consumed = 0

        for iteration in range(self._max_iterations):
            logger.info(
                "[迭代 %d/%d] 开始执行: phase=%s",
                iteration + 1,
                self._max_iterations,
                context.phase,
            )

            # 1. 消费预算
            decision = budget.consume(delta_tokens=0)
            logger.info(
                "[迭代 %d/%d] 预算决策: %s, remaining_iterations=%d, remaining_tokens=%d",
                iteration + 1,
                self._max_iterations,
                decision.value,
                budget.remaining_iterations,
                budget.remaining_tokens,
            )

            # 2. 检查是否应该停止
            if decision != BudgetDecision.CONTINUE:
                logger.info(
                    "[迭代 %d/%d] 预算决策为 %s，停止迭代",
                    iteration + 1,
                    self._max_iterations,
                    decision.value,
                )
                break

            # 3. 执行分析
            logger.info("[迭代 %d/%d] 调用分析器: %s", iteration + 1, self._max_iterations, self._analyzer.phase_name)
            result = await self._analyzer.analyze(match_data, context)
            iterations_used += 1
            tokens_consumed += result.tokens_consumed

            logger.info(
                "[迭代 %d/%d] 分析完成: confidence=%.2f, conclusions=%d, tokens=%d",
                iteration + 1,
                self._max_iterations,
                result.confidence,
                len(result.conclusions),
                result.tokens_consumed,
            )

            # 4. 更新最佳结果
            if best_result is None or result.confidence > best_result.confidence:
                logger.info(
                    "[迭代 %d/%d] 更新最佳结果: confidence %.2f -> %.2f",
                    iteration + 1,
                    self._max_iterations,
                    best_result.confidence if best_result else 0.0,
                    result.confidence,
                )
                best_result = result

            # 5. 验证结果质量
            logger.info("[迭代 %d/%d] 验证结果质量", iteration + 1, self._max_iterations)
            if self._analyzer.validate_result(result):
                logger.info(
                    "[迭代 %d/%d] 结果验证通过 (confidence=%.2f)，退还剩余预算",
                    iteration + 1,
                    self._max_iterations,
                    result.confidence,
                )
                # 退还当前迭代配额
                budget.refund()
                break
            else:
                logger.info(
                    "[迭代 %d/%d] 结果验证未通过: confidence=%.2f, conclusions=%d",
                    iteration + 1,
                    self._max_iterations,
                    result.confidence,
                    len(result.conclusions),
                )

            # 6. 上下文压缩（如果配置了压缩器）
            if self._compressor and context.messages:
                from post_match_review.llm.token_counter import TokenCounter
                token_counter = TokenCounter()
                current_tokens = token_counter.count_messages(context.messages)
                
                if self._compressor.should_compress(current_tokens):
                    logger.info(
                        "[迭代 %d/%d] 触发上下文压缩: current_tokens=%d",
                        iteration + 1,
                        self._max_iterations,
                        current_tokens,
                    )
                    context.messages = await self._compressor.compress(
                        context.messages,
                        current_tokens,
                    )
                    compressed_tokens = token_counter.count_messages(context.messages)
                    logger.info(
                        "[迭代 %d/%d] 压缩完成: %d -> %d tokens (节省 %d)",
                        iteration + 1,
                        self._max_iterations,
                        current_tokens,
                        compressed_tokens,
                        current_tokens - compressed_tokens,
                    )

            # 7. 生成反馈用于下一轮迭代
            if iteration < self._max_iterations - 1:
                feedback = self._generate_feedback(result)
                context.iteration_feedback = feedback
                logger.info(
                    "[迭代 %d/%d] 生成迭代反馈: length=%d, preview=%s",
                    iteration + 1,
                    self._max_iterations,
                    len(feedback),
                    feedback[:100],
                )

        # 7. 构建最终结果
        if best_result is None:
            logger.warning("战术循环未产生任何分析结果: phase=%s", context.phase)
            return AnalysisResult(
                phase=context.phase,
                conclusions=[],
                confidence=0.0,
                iterations_used=0,
                tokens_consumed=0,
                analysis_text="战术循环未产生分析结果",
            )

        # 更新迭代统计
        best_result.iterations_used = iterations_used
        best_result.tokens_consumed = tokens_consumed

        logger.info(
            "战术循环完成: phase=%s, iterations=%d/%d, confidence=%.2f, tokens=%d",
            context.phase,
            iterations_used,
            self._max_iterations,
            best_result.confidence,
            tokens_consumed,
        )

        return best_result

    def _generate_feedback(self, result: AnalysisResult) -> str:
        """基于当前结果生成改进反馈

        Args:
            result: 当前分析结果

        Returns:
            str: 反馈文本
        """
        feedback_parts = []

        # 置信度过低
        if result.confidence < 0.6:
            feedback_parts.append(
                f"当前置信度较低 ({result.confidence:.2f})，请提供更多数据支撑。"
            )

        # 结论数量不足
        if len(result.conclusions) < 2:
            feedback_parts.append(
                "结论数量不足，请从更多维度进行分析。"
            )

        # 缺乏证据支撑
        evidence_count = sum(1 for c in result.conclusions if c.has_evidence)
        if evidence_count == 0:
            feedback_parts.append(
                "所有结论均缺乏证据支撑，请引用具体数据。"
            )

        if not feedback_parts:
            feedback_parts.append("请进一步深化分析，提供更多洞察。")

        return " ".join(feedback_parts)
