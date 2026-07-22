"""PostMatchReviewAPI - 赛后复盘模块统一外部入口

本模块为 post_match_review 包的唯一外部入口。外部调用方应通过
PostMatchReviewAPI 发起复盘，而不直接依赖内部编排器或分析器。
"""
from pathlib import Path
from typing import Any, Dict, Optional

from post_match_review.data_source.match_fetcher import MatchFetcher
from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.interfaces.memory import IFourLayerMemory
from post_match_review.memory.four_layer_memory import FourLayerMemory
from post_match_review.memory.persistent_notes import PersistentNotes
from post_match_review.memory.session_archive import SessionArchive
from post_match_review.memory.skill_store import SkillStore
from post_match_review.observability.logger import get_logger
from post_match_review.orchestrator.background_reviewer import BackgroundReviewer
from post_match_review.orchestrator.review_orchestrator import ReviewOrchestrator
from post_match_review.orchestrator.runtime import Runtime
from post_match_review.domain_types.report import ReviewReport

logger = get_logger("pmr.api")


class PostMatchReviewAPI:
    """赛后复盘模块统一 API 入口

    负责组装 ReviewOrchestrator、可选的后台审查器与四层记忆系统，
    并向外部暴露单一的 `review(match_id)` 接口。
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        data_source: Optional[IMatchDataSource] = None,
        llm_client: Optional[ILLMClient] = None,
        memory: Optional[IFourLayerMemory] = None,
        enable_background_review: bool = False,
        data_dir: Optional[Path] = None,
    ) -> None:
        """初始化复盘 API

        Args:
            config_path: 复盘模块配置文件路径
            data_source: 比赛数据源，未提供时默认使用 MatchFetcher
            llm_client: LLM 客户端，未提供时默认使用 LLMClient
            memory: 四层记忆系统，未提供时根据 data_dir 自动创建
            enable_background_review: 是否启用后台自我审查
            data_dir: 记忆/技能数据持久化目录
        """
        self._config_path = config_path
        self._data_source = data_source or self._create_default_data_source()
        self._llm_client = llm_client or self._create_default_llm_client()
        self._data_dir = data_dir or Path(__file__).parent / "data"
        self._memory = memory or self._create_default_memory(self._data_dir)
        self._enable_background_review = enable_background_review
        self._background_reviewer: Optional[BackgroundReviewer] = None

        if self._enable_background_review:
            self._background_reviewer = BackgroundReviewer(
                llm_client=self._llm_client,
                memory=self._memory,
                config={"confidence_threshold": 0.7},
            )
            logger.info("后台自我审查已启用")

        self._runtime = Runtime(
            config_path=self._config_path,
            data_source=self._data_source,
            llm_client=self._llm_client,
        )
        logger.info("PostMatchReviewAPI 初始化完成")

    async def review(self, match_id: str) -> ReviewReport:
        """执行一次完整赛后复盘

        Args:
            match_id: OpenDota 比赛 ID

        Returns:
            ReviewReport: 完整复盘报告
        """
        logger.info("API 收到复盘请求: match_id=%s", match_id)
        orchestrator = self._runtime.build_orchestrator(match_id)

        if self._background_reviewer:
            orchestrator._background_reviewer = self._background_reviewer
            logger.info("已向后备编排器注入后台审查器")

        report = await orchestrator.review(match_id)
        logger.info("API 复盘完成: match_id=%s, confidence=%.2f", match_id, report.overall_confidence)
        return report

    @property
    def memory(self) -> IFourLayerMemory:
        """获取四层记忆系统实例"""
        return self._memory

    @property
    def background_reviewer(self) -> Optional[BackgroundReviewer]:
        """获取后台审查器实例（如果启用）"""
        return self._background_reviewer

    def _create_default_data_source(self) -> IMatchDataSource:
        """创建默认比赛数据源"""
        return MatchFetcher()

    def _create_default_llm_client(self) -> ILLMClient:
        """创建默认 LLM 客户端

        延迟导入 LLMClient，避免在未安装 openai SDK 时导入失败。
        调用方如无法使用默认客户端，可直接传入自定义 llm_client。
        """
        from post_match_review.llm.client import LLMClient
        return LLMClient()

    def _create_default_memory(self, data_dir: Path) -> IFourLayerMemory:
        """创建默认四层记忆系统"""
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
