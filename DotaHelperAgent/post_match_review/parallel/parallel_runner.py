"""并行运行器：批量并发执行子代理任务"""
import asyncio
from typing import List, Any

from post_match_review.parallel.subagent import SubAgent
from post_match_review.parallel.task_queue import TaskQueue
from post_match_review.types.match_data import MatchData
from post_match_review.types.analysis import AnalysisResult
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.parallel.parallel_runner")


class ParallelRunner:
    """并行子代理运行器

    使用 asyncio.Semaphore 控制并发数，确保子代理按顺序返回结果。
    单个子代理失败不会中断其他任务。
    """

    def __init__(self, max_concurrency: int = 4) -> None:
        """初始化并行运行器

        Args:
            max_concurrency: 最大并发数，默认 4
        """
        self._max_concurrency = max_concurrency
        logger.info("并行运行器初始化: max_concurrency=%d", max_concurrency)

    async def run(
        self,
        subagents: List[SubAgent],
        match_data: MatchData,
    ) -> List[AnalysisResult]:
        """并发执行子代理任务

        Args:
            subagents: 子代理列表
            match_data: 共享的比赛数据

        Returns:
            List[AnalysisResult]: 按输入顺序返回结果（失败位置返回空结果）
        """
        if not subagents:
            logger.warning("子代理列表为空，跳过执行")
            return []

        logger.info(
            "[并行运行器] 开始执行: 子代理数量=%d, 最大并发数=%d",
            len(subagents),
            self._max_concurrency,
        )

        # 创建信号量控制并发
        semaphore = asyncio.Semaphore(self._max_concurrency)
        task_queue = TaskQueue()

        # 创建异步任务
        async def run_with_semaphore(index: int, subagent: SubAgent) -> None:
            """带信号量控制的子代理执行"""
            logger.info(
                "[并行运行器] 子代理等待执行: index=%d, name=%s",
                index,
                subagent.name,
            )
            async with semaphore:
                logger.info(
                    "[并行运行器] 子代理开始执行: index=%d, name=%s",
                    index,
                    subagent.name,
                )
                try:
                    result = await subagent.run(match_data)
                    logger.info(
                        "[并行运行器] 子代理执行成功: index=%d, name=%s, confidence=%.2f",
                        index,
                        subagent.name,
                        result.confidence,
                    )
                    task_queue.add_result(index, result)
                except Exception as e:
                    logger.error(
                        "[并行运行器] 子代理执行失败: index=%d, name=%s, error=%s",
                        index,
                        subagent.name,
                        str(e),
                    )
                    task_queue.add_error(index, e)

        # 并发执行所有任务
        tasks = [
            asyncio.create_task(run_with_semaphore(i, subagent))
            for i, subagent in enumerate(subagents)
        ]

        logger.info("[并行运行器] 等待所有子代理完成...")
        await asyncio.gather(*tasks, return_exceptions=True)

        # 收集结果
        results = task_queue.get_all_results()

        # 将 None 替换为空结果
        final_results: List[AnalysisResult] = []
        for i, result in enumerate(results):
            if result is None:
                # 该位置执行失败，创建空结果
                phase_name = subagents[i].name if i < len(subagents) else f"unknown_{i}"
                logger.warning(
                    "[并行运行器] 子代理结果为空，创建失败结果: index=%d, phase=%s",
                    i,
                    phase_name,
                )
                final_results.append(
                    AnalysisResult(
                        phase=phase_name,
                        conclusions=[],
                        confidence=0.0,
                        iterations_used=0,
                        tokens_consumed=0,
                        analysis_text="子代理执行失败",
                    )
                )
            else:
                final_results.append(result)

        logger.info(
            "[并行运行器] 执行完成: 成功=%d, 失败=%d, 总计=%d",
            task_queue.success_count,
            task_queue.failure_count,
            len(final_results),
        )

        return final_results
