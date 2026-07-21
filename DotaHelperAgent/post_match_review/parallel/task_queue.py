"""任务队列：收集并行子代理的执行结果"""
from typing import List, Optional, Any
from post_match_review.domain_types.analysis import AnalysisResult
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.parallel.task_queue")


class TaskQueue:
    """任务结果收集队列

    维护子代理执行结果的顺序，支持部分失败记录。
    """

    def __init__(self) -> None:
        """初始化任务队列"""
        self._results: List[Optional[AnalysisResult]] = []
        self._errors: List[Optional[Exception]] = []
        self._completed_count = 0

        logger.info("任务队列初始化")

    def add_result(self, index: int, result: AnalysisResult) -> None:
        """添加执行结果

        Args:
            index: 结果在队列中的位置索引
            result: 分析结果
        """
        # 扩展列表到足够长度
        while len(self._results) <= index:
            self._results.append(None)
            self._errors.append(None)

        self._results[index] = result
        self._completed_count += 1

        logger.info(
            "任务结果已添加: index=%d, phase=%s, confidence=%.2f",
            index,
            result.phase,
            result.confidence,
        )

    def add_error(self, index: int, error: Exception) -> None:
        """记录执行错误

        Args:
            index: 结果在队列中的位置索引
            error: 执行过程中发生的异常
        """
        # 扩展列表到足够长度
        while len(self._errors) <= index:
            self._results.append(None)
            self._errors.append(None)

        self._errors[index] = error
        self._completed_count += 1

        logger.error("任务执行失败: index=%d, error=%s", index, str(error))

    def get_results(self) -> List[AnalysisResult]:
        """获取所有成功执行的结果

        Returns:
            List[AnalysisResult]: 按索引顺序排列的成功结果列表
        """
        return [r for r in self._results if r is not None]

    def get_all_results(self) -> List[Optional[AnalysisResult]]:
        """获取所有结果（包括失败位置）

        Returns:
            List[Optional[AnalysisResult]]: 完整结果列表，失败位置为 None
        """
        return self._results.copy()

    def get_errors(self) -> List[Optional[Exception]]:
        """获取所有错误记录

        Returns:
            List[Optional[Exception]]: 错误列表，成功位置为 None
        """
        return self._errors.copy()

    @property
    def completed_count(self) -> int:
        """已完成的任务数量（包括成功和失败）"""
        return self._completed_count

    @property
    def success_count(self) -> int:
        """成功执行的任务数量"""
        return sum(1 for r in self._results if r is not None)

    @property
    def failure_count(self) -> int:
        """失败的任务数量"""
        return sum(1 for e in self._errors if e is not None)

    def is_complete(self, expected_count: int) -> bool:
        """检查是否所有任务都已完成

        Args:
            expected_count: 预期的任务总数

        Returns:
            bool: 是否全部完成
        """
        return self._completed_count >= expected_count
