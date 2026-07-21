"""并行子代理：独立上下文和执行环境"""
from typing import Any, Dict, List
from post_match_review.interfaces.analyzer import IReviewAnalyzer
from post_match_review.domain_types.analysis import AnalysisContext, AnalysisResult
from post_match_review.domain_types.match_data import MatchData
from post_match_review.engines.budget import IterationBudget
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.parallel.subagent")


class SubAgent:
    """并行子代理

    每个子代理拥有独立的上下文消息列表和预算配额，
    负责执行单个分析阶段的任务。
    """

    def __init__(
        self,
        name: str,
        analyzer: IReviewAnalyzer,
        budget_quota: int,
        context: Dict[str, Any],
    ) -> None:
        """初始化子代理

        Args:
            name: 子代理名称（通常为阶段名称）
            analyzer: 分析器实例
            budget_quota: 分配的预算配额（迭代次数）
            context: 初始上下文配置
        """
        self._name = name
        self._analyzer = analyzer
        self._budget_quota = budget_quota
        self._context = context
        self._messages: List[Dict[str, str]] = []  # 独立上下文消息列表
        self._result: AnalysisResult | None = None
        self._error: Exception | None = None

        logger.info(
            "子代理初始化: name=%s, budget_quota=%d",
            name,
            budget_quota,
        )

    @property
    def name(self) -> str:
        """子代理名称"""
        return self._name

    @property
    def result(self) -> AnalysisResult | None:
        """分析结果"""
        return self._result

    @property
    def error(self) -> Exception | None:
        """执行过程中的错误"""
        return self._error

    @property
    def messages(self) -> List[Dict[str, str]]:
        """独立上下文消息列表"""
        return self._messages

    async def run(self, match_data: MatchData) -> AnalysisResult:
        """执行子代理任务

        Args:
            match_data: 共享的比赛数据

        Returns:
            AnalysisResult: 子代理分析结果

        Raises:
            Exception: 当分析失败时抛出
        """
        logger.info(
            "[子代理] 开始执行: name=%s, budget_quota=%d, context_keys=%s",
            self._name,
            self._budget_quota,
            list(self._context.keys()),
        )

        try:
            # 创建独立的预算控制器
            logger.info(
                "[子代理] 创建预算控制器: max_iterations=%d, max_tokens=%d",
                self._budget_quota,
                self._budget_quota * 4000,
            )
            budget = IterationBudget(
                max_iterations=self._budget_quota,
                max_tokens=self._budget_quota * 4000,  # 假设每次迭代 4000 tokens
            )

            # 创建分析上下文
            logger.info(
                "[子代理] 创建分析上下文: phase=%s, config=%s",
                self._name,
                self._context,
            )
            context = AnalysisContext(
                phase=self._name,
                budget=budget,
                completed_results=[],  # 子代理独立，不共享已完成结果
                config=self._context,
                messages=self._messages,  # 传递独立消息列表
            )

            # 执行分析
            logger.info("[子代理] 调用分析器: %s", self._analyzer.__class__.__name__)
            self._result = await self._analyzer.analyze(match_data, context)

            # 更新独立消息列表（用于后续压缩）
            self._messages = context.messages
            logger.info(
                "[子代理] 分析完成: name=%s, confidence=%.2f, conclusions=%d, messages_count=%d",
                self._name,
                self._result.confidence,
                len(self._result.conclusions),
                len(self._messages),
            )

            return self._result

        except Exception as e:
            self._error = e
            logger.error(
                "[子代理] 执行失败: name=%s, error_type=%s, error=%s",
                self._name,
                type(e).__name__,
                str(e),
                exc_info=True,
            )

            # 返回空结果，标记失败
            self._result = AnalysisResult(
                phase=self._name,
                conclusions=[],
                confidence=0.0,
                iterations_used=0,
                tokens_consumed=0,
                analysis_text=f"子代理执行失败: {str(e)}",
            )

            logger.info(
                "[子代理] 已创建失败结果: name=%s, phase=%s",
                self._name,
                self._name,
            )

            return self._result
