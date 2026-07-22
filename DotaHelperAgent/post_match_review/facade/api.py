"""PostMatchReviewAPI - 赛后复盘模块统一外部入口

本模块为 post_match_review 包的唯一外部入口。外部调用方应通过
`PostMatchReviewAPI` 发起复盘，而不直接依赖内部编排器或分析器。
"""
import asyncio
import dataclasses
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.orchestrator.runtime import Runtime
from post_match_review.orchestrator.review_orchestrator import ReviewOrchestrator
from post_match_review.domain_types.report import ReviewReport
from post_match_review.domain_types.events import ProgressEvent
from post_match_review.report.progress_emitter import ProgressEmitter
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.facade")


class ReviewTaskState:
    """单个复盘任务的状态"""

    def __init__(self, match_id: str) -> None:
        """初始化任务状态

        Args:
            match_id: 比赛 ID
        """
        self.match_id = match_id
        self.status = "running"
        self.progress = 0.0
        self.current_phase: Optional[str] = None
        self.report: Optional[ReviewReport] = None
        self.error_message: Optional[str] = None
        self.created_at = datetime.now().isoformat()
        self.completed_at: Optional[str] = None
        self.orchestrator: Optional[ReviewOrchestrator] = None


class ReviewStateStore:
    """复盘任务状态与历史存储

    内存实现，用于跟踪正在运行的复盘任务和已完成的复盘历史。
    """

    def __init__(self) -> None:
        """初始化状态存储"""
        self._tasks: Dict[str, ReviewTaskState] = {}
        self._history: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def start(self, match_id: str) -> ReviewTaskState:
        """开始一个新的复盘任务

        Args:
            match_id: 比赛 ID

        Returns:
            ReviewTaskState: 任务状态
        """
        async with self._lock:
            state = ReviewTaskState(match_id=match_id)
            self._tasks[match_id] = state
            logger.info("复盘任务开始: match_id=%s", match_id)
            return state

    async def update_progress(self, match_id: str, event: ProgressEvent) -> None:
        """根据进度事件更新任务状态

        Args:
            match_id: 比赛 ID
            event: 进度事件
        """
        async with self._lock:
            state = self._tasks.get(match_id)
            if state is None:
                return
            state.progress = event.progress
            if event.phase:
                state.current_phase = event.phase
            if event.event == "report":
                state.current_phase = None
            if event.event == "error":
                state.status = "error"
                state.error_message = event.message

    async def set_orchestrator(
        self,
        match_id: str,
        orchestrator: ReviewOrchestrator,
    ) -> None:
        """设置任务对应的编排器实例

        Args:
            match_id: 比赛 ID
            orchestrator: 复盘编排器
        """
        async with self._lock:
            state = self._tasks.get(match_id)
            if state is not None:
                state.orchestrator = orchestrator

    async def complete(self, match_id: str, report: ReviewReport) -> None:
        """标记复盘任务完成

        Args:
            match_id: 比赛 ID
            report: 复盘报告
        """
        async with self._lock:
            state = self._tasks.get(match_id)
            if state is None:
                return
            state.report = report
            state.progress = 1.0
            state.current_phase = None
            state.completed_at = datetime.now().isoformat()
            if report.terminal_state == "error":
                state.status = "error"
            else:
                state.status = "completed"
            self._history.append({
                "match_id": match_id,
                "status": state.status,
                "overall_score": report.overall_score,
                "overall_confidence": report.overall_confidence,
                "terminal_state": report.terminal_state,
                "created_at": state.created_at,
                "completed_at": state.completed_at,
            })
            logger.info(
                "复盘任务完成: match_id=%s, status=%s, score=%.2f, confidence=%.2f",
                match_id,
                state.status,
                report.overall_score,
                report.overall_confidence,
            )

    async def interrupt(self, match_id: str) -> bool:
        """中断复盘任务

        Args:
            match_id: 比赛 ID

        Returns:
            bool: 是否成功触发中断
        """
        async with self._lock:
            state = self._tasks.get(match_id)
            if state is None or state.status != "running":
                return False
            if state.orchestrator is not None:
                state.orchestrator.interrupt()
            state.status = "interrupted"
            state.completed_at = datetime.now().isoformat()
            logger.info("复盘任务已中断: match_id=%s", match_id)
            return True

    async def get_status(self, match_id: str) -> Dict[str, Any]:
        """获取复盘状态

        Args:
            match_id: 比赛 ID

        Returns:
            Dict[str, Any]: 状态字典
        """
        async with self._lock:
            state = self._tasks.get(match_id)
            if state is None:
                return {
                    "match_id": match_id,
                    "status": "not_found",
                    "progress": 0.0,
                    "current_phase": None,
                    "error_message": None,
                }
            return {
                "match_id": state.match_id,
                "status": state.status,
                "progress": state.progress,
                "current_phase": state.current_phase,
                "error_message": state.error_message,
            }

    async def get_report(self, match_id: str) -> Optional[ReviewReport]:
        """获取复盘报告

        Args:
            match_id: 比赛 ID

        Returns:
            Optional[ReviewReport]: 复盘报告（如果存在）
        """
        async with self._lock:
            state = self._tasks.get(match_id)
            return state.report if state is not None else None

    async def list_history(self) -> List[Dict[str, Any]]:
        """获取复盘历史列表

        Returns:
            List[Dict[str, Any]]: 历史记录列表
        """
        async with self._lock:
            return list(self._history)


class PostMatchReviewAPI:
    """赛后复盘公共 API 门面（外部唯一入口）"""

    def __init__(
        self,
        orchestrator_factory: Optional[Callable[[str], ReviewOrchestrator]] = None,
        runtime: Optional[Runtime] = None,
        config_path: Optional[Path] = None,
        data_source: Optional[IMatchDataSource] = None,
        llm_client: Optional[ILLMClient] = None,
    ) -> None:
        """初始化复盘 API 门面

        Args:
            orchestrator_factory: 编排器工厂函数（接收 match_id）
            runtime: 已配置的 Runtime 实例
            config_path: 复盘模块配置文件路径
            data_source: 比赛数据源
            llm_client: LLM 客户端
        """
        if orchestrator_factory is not None:
            self._orchestrator_factory = orchestrator_factory
        elif runtime is not None:
            self._orchestrator_factory = runtime.build_orchestrator
        else:
            self._runtime = Runtime(
                config_path=config_path,
                data_source=data_source,
                llm_client=llm_client,
            )
            self._orchestrator_factory = self._runtime.build_orchestrator

        self._store = ReviewStateStore()
        logger.info("PostMatchReviewAPI 初始化完成")

    async def review(self, match_id: str) -> ReviewReport:
        """执行完整复盘

        Args:
            match_id: 比赛 ID

        Returns:
            ReviewReport: 完整复盘报告
        """
        logger.info("API 收到复盘请求: match_id=%s", match_id)
        await self._store.start(match_id)
        orchestrator = self._orchestrator_factory(match_id)
        await self._store.set_orchestrator(match_id, orchestrator)

        async def progress_callback(event: ProgressEvent) -> None:
            await self._store.update_progress(match_id, event)

        report = await orchestrator.review(match_id, progress_callback=progress_callback)
        await self._store.complete(match_id, report)
        logger.info("API 复盘完成: match_id=%s, confidence=%.2f", match_id, report.overall_confidence)
        return report

    async def review_stream(
        self,
        match_id: str,
    ) -> AsyncGenerator[str, None]:
        """SSE 流式复盘

        Args:
            match_id: 比赛 ID

        Yields:
            str: SSE 格式事件行
        """
        logger.info("API 收到流式复盘请求: match_id=%s", match_id)
        await self._store.start(match_id)
        orchestrator = self._orchestrator_factory(match_id)
        await self._store.set_orchestrator(match_id, orchestrator)
        emitter = ProgressEmitter()

        async def _run_review() -> None:
            """在后台运行复盘并推送事件到发射器"""
            try:
                report = await orchestrator.review(
                    match_id,
                    progress_callback=emitter.emit,
                )
                await self._store.complete(match_id, report)
                await emitter.emit(
                    ProgressEvent(
                        event="report",
                        progress=1.0,
                        message="复盘报告生成完成",
                        payload={"report": dataclasses.asdict(report)},
                    )
                )
            except Exception as e:
                logger.error("流式复盘执行失败: match_id=%s, error=%s", match_id, str(e))
                await self._store.update_progress(
                    match_id,
                    ProgressEvent(
                        event="error",
                        progress=0.0,
                        message=f"复盘执行失败: {str(e)}",
                        payload={"error": str(e)},
                    ),
                )
                await emitter.emit(
                    ProgressEvent(
                        event="error",
                        progress=0.0,
                        message=f"复盘执行失败: {str(e)}",
                        payload={"error": str(e)},
                    )
                )
            finally:
                emitter.close()

        task = asyncio.create_task(_run_review())

        try:
            async for event in emitter.stream():
                await self._store.update_progress(match_id, event)
                yield event.to_sse()
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def get_status(self, match_id: str) -> Dict[str, Any]:
        """获取复盘状态

        Args:
            match_id: 比赛 ID

        Returns:
            Dict[str, Any]: 复盘状态
        """
        return await self._store.get_status(match_id)

    async def get_report(self, match_id: str) -> Optional[ReviewReport]:
        """获取复盘报告

        Args:
            match_id: 比赛 ID

        Returns:
            Optional[ReviewReport]: 复盘报告（如果存在）
        """
        return await self._store.get_report(match_id)

    async def interrupt(self, match_id: str) -> Dict[str, Any]:
        """中断复盘

        Args:
            match_id: 比赛 ID

        Returns:
            Dict[str, Any]: 中断结果
        """
        success = await self._store.interrupt(match_id)
        return {
            "match_id": match_id,
            "success": success,
            "status": (await self._store.get_status(match_id))["status"],
        }

    async def list_history(self) -> List[Dict[str, Any]]:
        """获取复盘历史列表

        Returns:
            List[Dict[str, Any]]: 历史记录列表
        """
        return await self._store.list_history()
