"""PostMatchReviewAPI - 赛后复盘模块统一外部入口

本模块为 dota_helper 包的唯一外部入口。外部调用方应通过
`PostMatchReviewAPI` 发起复盘，而不直接依赖内部编排器或分析器。
"""
import asyncio
import dataclasses
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from dota_helper.interfaces.data_source import IMatchDataSource
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.interfaces.memory import IFourLayerMemory
from dota_helper.memory.four_layer_memory import FourLayerMemory
from dota_helper.memory.persistent_notes import PersistentNotes
from dota_helper.memory.session_archive import SessionArchive
from dota_helper.memory.skill_store import SkillStore
from dota_helper.orchestrator.background_reviewer import BackgroundReviewer
from dota_helper.orchestrator.review_config import MemoryConfig
from dota_helper.orchestrator.runtime import Runtime
from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
from dota_helper.domain_types.report import ReviewReport
from dota_helper.domain_types.events import ProgressEvent
from dota_helper.report.progress_emitter import ProgressEmitter
from dota_helper.observability.logger import get_logger

logger = get_logger("facade")


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
        memory: Optional[IFourLayerMemory] = None,
        enable_background_review: Optional[bool] = None,
        data_dir: Optional[Path] = None,
        background_reviewer_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化复盘 API 门面

        Args:
            orchestrator_factory: 编排器工厂函数（接收 match_id）
            runtime: 已配置的 Runtime 实例
            config_path: 复盘模块配置文件路径
            data_source: 比赛数据源
            llm_client: LLM 客户端
            memory: 四层记忆系统实例（可选）
            enable_background_review: 是否开启后台审查（None 则读取配置）
            data_dir: 记忆数据持久化根目录（可选）
            background_reviewer_config: 后台审查器额外配置（可选）
        """
        self._store = ReviewStateStore()
        self._runtime: Optional[Runtime] = None
        self._memory: Optional[IFourLayerMemory] = memory
        self._background_reviewer: Optional[BackgroundReviewer] = None
        self._llm_client = llm_client

        # 1. 确定编排器来源并保存 Runtime 引用（如果提供）
        if orchestrator_factory is not None:
            self._runtime = None
            self._orchestrator_factory = orchestrator_factory
        elif runtime is not None:
            self._runtime = runtime
            self._orchestrator_factory = runtime.build_orchestrator
        else:
            self._runtime = Runtime(
                config_path=config_path,
                data_source=data_source,
                llm_client=llm_client,
            )
            self._orchestrator_factory = self._runtime.build_orchestrator

        # 2. 读取记忆配置
        memory_config = self._get_memory_config()

        # 3. 解析是否启用记忆系统
        enable_memory = memory is not None or memory_config.enabled

        # 4. 解析是否开启后台审查
        if enable_background_review is None:
            enable_background_review = (
                memory_config.enabled and memory_config.background_review
            )
        # 后台审查依赖记忆系统
        if enable_background_review and not enable_memory:
            logger.warning("后台审查需要记忆系统，自动启用记忆系统")
            enable_memory = True
        self._enable_background_review = enable_background_review

        # 5. 若启用记忆系统，创建或保存实例
        if enable_memory and self._memory is None:
            resolved_data_dir = self._resolve_data_dir(data_dir, memory_config)
            try:
                self._memory = self._create_default_memory(resolved_data_dir)
            except Exception as e:
                logger.error("创建默认记忆系统失败: %s", e)
                self._memory = None
                self._enable_background_review = False

        # 6. 若开启后台审查，组装审查器
        if self._enable_background_review and self._memory is not None:
            self._setup_background_review(
                memory=self._memory,
                memory_config=memory_config,
                background_reviewer_config=background_reviewer_config,
            )

        logger.info("PostMatchReviewAPI 初始化完成")

    def _get_memory_config(self) -> MemoryConfig:
        """获取记忆系统配置

        Returns:
            MemoryConfig: 配置实例
        """
        if self._runtime is not None:
            return self._runtime.get_memory_config()
        return MemoryConfig()

    def _resolve_data_dir(
        self,
        data_dir: Optional[Path],
        memory_config: MemoryConfig,
    ) -> Path:
        """解析最终数据目录

        优先级：参数 > 配置 > 默认用户目录

        Args:
            data_dir: 显式指定的数据目录
            memory_config: 记忆配置

        Returns:
            Path: 数据目录路径
        """
        if data_dir is not None:
            return data_dir
        if memory_config.data_dir is not None:
            return Path(memory_config.data_dir)
        return Path.home() / ".dota_helper" / "data"

    def _create_default_memory(self, data_dir: Path) -> IFourLayerMemory:
        """创建默认四层记忆系统

        Args:
            data_dir: 数据根目录

        Returns:
            IFourLayerMemory: 四层记忆系统实例
        """
        data_dir.mkdir(parents=True, exist_ok=True)
        memory_dir = data_dir / "memory"
        skills_dir = data_dir / "skills"
        memory_dir.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)

        session_archive = SessionArchive(str(memory_dir / "session_archive.db"))
        persistent_notes = PersistentNotes(str(memory_dir / "persistent_notes.json"))
        skill_store = SkillStore(str(skills_dir))

        return FourLayerMemory(
            session_archive=session_archive,
            persistent_notes=persistent_notes,
            skill_store=skill_store,
            data_dir=str(data_dir),
        )

    def _resolve_llm_client(self) -> Optional[ILLMClient]:
        """解析最终 LLM 客户端

        优先级：构造参数 > Runtime

        Returns:
            Optional[ILLMClient]: LLM 客户端（可能为 None）
        """
        if self._llm_client is not None:
            return self._llm_client
        if self._runtime is not None:
            return self._runtime.get_llm_client()
        return None

    def _wrap_factory_with_background_reviewer(
        self,
        background_reviewer: BackgroundReviewer,
    ) -> None:
        """将后台审查器注入编排器工厂

        如果工厂来源于 Runtime，直接调用 build_orchestrator(match_id, reviewer)。
        如果是外部工厂，检测其是否接受 background_reviewer 参数。

        Args:
            background_reviewer: 后台审查器实例
        """
        if self._runtime is not None:
            # 来自 Runtime，直接调用支持透传的方法
            self._orchestrator_factory = lambda match_id: self._runtime.build_orchestrator(
                match_id,
                background_reviewer=background_reviewer,
            )
            return

        # 外部工厂：通过 inspect 检测参数
        factory = self._orchestrator_factory
        sig = inspect.signature(factory)
        if "background_reviewer" in sig.parameters:
            self._orchestrator_factory = lambda match_id: factory(
                match_id,
                background_reviewer=background_reviewer,
            )
        else:
            logger.warning(
                "外部 orchestrator_factory 不接受 background_reviewer 参数，"
                "后台审查器未注入"
            )

    def _setup_background_review(
        self,
        memory: IFourLayerMemory,
        memory_config: MemoryConfig,
        background_reviewer_config: Optional[Dict[str, Any]],
    ) -> None:
        """组装并注入后台审查器

        Args:
            memory: 记忆系统实例
            memory_config: 记忆配置
            background_reviewer_config: 审查器额外配置
        """
        llm_client = self._resolve_llm_client()
        if llm_client is None:
            logger.warning(
                "未配置 LLM 客户端，后台审查器无法启动，记忆系统仅保留实例"
            )
            return

        reviewer_config = background_reviewer_config or {}
        if "confidence_threshold" not in reviewer_config:
            reviewer_config["confidence_threshold"] = memory_config.confidence_threshold

        self._background_reviewer = BackgroundReviewer(
            llm_client=llm_client,
            memory=memory,
            config=reviewer_config,
        )
        self._wrap_factory_with_background_reviewer(self._background_reviewer)
        logger.info("后台审查器已启用")

    @property
    def memory(self) -> Optional[IFourLayerMemory]:
        """获取四层记忆系统实例（如果已创建）"""
        return self._memory

    @property
    def background_reviewer(self) -> Optional[BackgroundReviewer]:
        """获取后台审查器实例（如果已启用）"""
        return self._background_reviewer

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

    # ── 分析技能管理 API ──

    def list_analysis_skills(self) -> List[Dict[str, Any]]:
        """列出所有可用的分析技能（内置 + 用户自定义）

        P2-3: 通过 Runtime 公共方法访问配置，不直接触碰 _runtime._config。

        Returns:
            List[Dict[str, Any]]: 分析技能定义列表
        """
        from dota_helper.memory.skill_store import SkillStore

        skills: List[Dict[str, Any]] = []

        # 尝试加载内置技能
        try:
            # 使用临时 SkillStore 实例访问 prompts/skills/
            temp_store = SkillStore(
                str(Path(__file__).parent.parent / "memory" / "_api_skills"),
            )
            builtin = temp_store.list_builtin_skills()
            skills.extend(builtin)
        except Exception as e:
            logger.warning("加载内置分析技能失败: %s", e)

        # 尝试加载用户自定义技能
        runtime = getattr(self, "_runtime", None)
        if runtime is not None:
            # P2-3: 通过公共方法获取 skills_dir
            skills_dir = runtime.get_skills_dir()
            if skills_dir:
                try:
                    store = SkillStore(skills_dir)
                    custom = store.list_analysis_skills()
                    skills.extend(custom)
                except Exception as e:
                    logger.warning("加载自定义分析技能失败: %s", e)

        return skills

    def register_analysis_skill(
        self,
        name: str,
        skill_definition: Dict[str, Any],
        skills_dir: Optional[str] = None,
    ) -> None:
        """注册自定义分析技能

        P2-3: 通过 Runtime 公共方法访问配置，不直接触碰 _runtime._config。

        Args:
            name: 技能名称
            skill_definition: 技能定义字典
            skills_dir: 技能存储目录（可选，默认从 Runtime 配置获取）

        Raises:
            ValueError: skills_dir 未配置
        """
        from dota_helper.memory.skill_store import SkillStore

        if skills_dir is None:
            runtime = getattr(self, "_runtime", None)
            if runtime is not None:
                # P2-3: 通过公共方法获取 skills_dir
                skills_dir = runtime.get_skills_dir()
            if not skills_dir:
                raise ValueError(
                    "skills_dir 未配置，请在构造 API 时指定或在配置文件中设置"
                )

        store = SkillStore(skills_dir)
        store.save_analysis_skill(name, skill_definition)
        logger.info("注册分析技能: %s", name)
