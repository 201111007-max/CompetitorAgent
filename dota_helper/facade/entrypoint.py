"""PostMatchReviewAPI 工厂入口

提供零配置创建 `PostMatchReviewAPI` 的能力：
- 自动组装 OpenDota 数据源
- 自动检测 LLM 密钥，未配置时降级为规则驱动的 FallbackAnalyzer
- 默认集成四层记忆系统与后台审查器
- 外部调用方保持 `from dota_helper import create_default_api`
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dota_helper.facade.api import PostMatchReviewAPI
from dota_helper.interfaces.data_source import IMatchDataSource
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.interfaces.memory import IFourLayerMemory
from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
from dota_helper.orchestrator.review_config import ReviewConfig
from dota_helper.orchestrator.strategic_loop import StrategicLoop
from dota_helper.orchestrator.tactical_loop import TacticalLoop
from dota_helper.orchestrator.runtime import Runtime
from dota_helper.engines.stop_verifier import StopVerifier
from dota_helper.engines.budget import IterationBudget
from dota_helper.report.report_builder import ReportBuilder
from dota_helper.report.markdown_renderer import MarkdownRenderer
from dota_helper.domain_types.state import ReviewAgentState
from dota_helper.domain_types.analysis import AnalysisContext
from dota_helper.domain_types.match_data import MatchData
from dota_helper.data_source.opendota_client import OpenDotaClient
from dota_helper.data_source.match_fetcher import MatchFetcher
from dota_helper.data_source.cache import MatchDataCache
from dota_helper.data_path_manager import DataPathManager
from dota_helper.analyzers.fallback_analyzer import FallbackAnalyzer
from dota_helper.observability.logger import get_logger

logger = get_logger("facade.entrypoint")


def _default_config_path() -> Path:
    """默认复盘配置文件路径

    Returns:
        Path: review_config.yaml 绝对路径
    """
    return Path(__file__).parent.parent / "review_config.yaml"


class MatchFetcherAdapter:
    """适配器：将 MatchFetcher 适配为 IMatchDataSource"""

    def __init__(self, fetcher: MatchFetcher) -> None:
        """初始化适配器

        Args:
            fetcher: 比赛数据获取器
        """
        self._fetcher = fetcher

    async def fetch_match(self, match_id: str) -> MatchData:
        """获取并解析比赛数据

        Args:
            match_id: 比赛 ID

        Returns:
            MatchData: 结构化比赛数据
        """
        return await self._fetcher.fetch_and_parse(match_id)


def _has_llm_key() -> bool:
    """检查是否配置了 LLM API 密钥

    Returns:
        bool: 是否可调用 LLM
    """
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("LLM_API_KEY")
    )


def _load_review_config(config_path: Path) -> ReviewConfig:
    """加载类型安全的复盘配置

    统一使用 ReviewConfig dataclass 替代手动 Dict[str, Any] 解析，
    确保 fallback 分支与 Runtime 分支使用完全一致的类型安全路径。

    Args:
        config_path: 配置文件路径

    Returns:
        ReviewConfig: 类型安全的配置实例
    """
    import yaml

    if not config_path.exists():
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return ReviewConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        logger.info("加载配置文件: %s", config_path)
        return ReviewConfig.from_dict(raw)
    except Exception as e:
        logger.error("读取配置文件失败: %s，使用默认配置", e)
        return ReviewConfig()


def _create_fallback_orchestrator_factory(
    data_source: IMatchDataSource,
    config: ReviewConfig,
) -> Any:
    """创建使用 FallbackAnalyzer 的编排器工厂

    当未配置 LLM 密钥时使用，确保复盘流程仍可运行。
    统一使用 ReviewConfig dataclass 替代手动字典配置。

    Args:
        data_source: 比赛数据源
        config: 类型安全的复盘配置

    Returns:
        Callable[[str], ReviewOrchestrator]: 编排器工厂函数
    """
    strategic_loop = StrategicLoop(config=config)
    stop_verifier = StopVerifier(
        required_phases=config.stop_verifier.required_phases,
        min_confidence=config.stop_verifier.min_confidence,
    )
    report_builder = ReportBuilder()
    markdown_renderer = MarkdownRenderer()

    def factory(match_id: str) -> ReviewOrchestrator:
        """构建降级编排器"""
        state = ReviewAgentState(match_id=match_id)

        def tactical_loop_factory(phase: str) -> TacticalLoop:
            analyzer = FallbackAnalyzer(phase=phase)
            return TacticalLoop(
                analyzer=analyzer,
                max_iterations=config.tactical_loop.max_iterations_per_phase,
            )

        return ReviewOrchestrator(
            data_source=data_source,
            strategic_loop=strategic_loop,
            tactical_loop_factory=tactical_loop_factory,
            stop_verifier=stop_verifier,
            report_builder=report_builder,
            state=state,
            markdown_renderer=markdown_renderer,
        )

    return factory


def create_default_api(
    config_path: Optional[Path] = None,
    data_source: Optional[IMatchDataSource] = None,
    llm_client: Optional[ILLMClient] = None,
    memory: Optional[IFourLayerMemory] = None,
    enable_background_review: Optional[bool] = None,
    data_dir: Optional[Path] = None,
    background_reviewer_config: Optional[Dict[str, Any]] = None,
) -> PostMatchReviewAPI:
    """创建默认配置的 PostMatchReviewAPI 实例

    自动完成以下装配：
    1. OpenDota 数据源（未提供时）
    2. LLM 客户端（未提供时）
    3. 四层记忆系统与后台审查器（默认启用）
    4. 未配置 LLM 密钥时，自动降级为 FallbackAnalyzer 规则分析

    Args:
        config_path: 复盘模块配置文件路径
        data_source: 比赛数据源（可选，覆盖默认）
        llm_client: LLM 客户端（可选，覆盖默认）
        memory: 四层记忆系统实例（可选）
        enable_background_review: 是否开启后台审查（None 则读取配置）
        data_dir: 记忆数据持久化根目录（可选）
        background_reviewer_config: 后台审查器额外配置（可选）

    Returns:
        PostMatchReviewAPI: 默认 API 实例
    """
    if config_path is None:
        config_path = _default_config_path()

    # 1. 创建数据源
    if data_source is None:
        # 初始化 DataPathManager 并创建缓存
        path_manager = DataPathManager(
            data_dir=str(data_dir) if data_dir else None,
        )
        path_manager.ensure_dirs()
        cache = MatchDataCache(cache_dir=path_manager.cache_dir)

        opendota_client = OpenDotaClient(timeout=30.0, max_retries=3)
        match_fetcher = MatchFetcher(client=opendota_client, cache=cache)
        data_source = MatchFetcherAdapter(match_fetcher)
        logger.info("使用默认 OpenDota 数据源（缓存已启用）")

    # 2. 判断是否有 LLM 能力
    use_llm = _has_llm_key()
    if not use_llm:
        logger.warning(
            "未检测到 LLM API 密钥（OPENAI_API_KEY/DEEPSEEK_API_KEY/LLM_API_KEY），"
            "复盘将使用 FallbackAnalyzer 规则分析降级运行"
        )

    # 3. 无 LLM 时直接使用自定义工厂，避免 Runtime 创建 LLM 驱动分析器
    if not use_llm:
        # 统一使用 ReviewConfig 加载配置（差异4 消除：不再手动解析 YAML）
        config = _load_review_config(config_path)

        # Fallback 分支无法运行后台审查器（依赖 LLM），强制关闭
        if enable_background_review is True:
            logger.warning(
                "Fallback 模式下不支持后台审查器（依赖 LLM），"
                "enable_background_review 已强制关闭"
            )
        elif enable_background_review is None:
            # 读取配置默认开启时，也需要在 fallback 下关闭
            if config.memory.enabled and config.memory.background_review:
                logger.warning(
                    "Fallback 模式下记忆系统后台审查自动关闭（依赖 LLM），"
                    "FourLayerMemory 实例仍会创建用于后续手动查询"
                )
        enable_background_review = False

        return PostMatchReviewAPI(
            orchestrator_factory=_create_fallback_orchestrator_factory(
                data_source, config
            ),
            config_path=config_path,
            data_source=data_source,
            llm_client=llm_client,
            memory=memory,
            enable_background_review=False,
            data_dir=data_dir,
            background_reviewer_config=background_reviewer_config,
        )

    # 4. 有 LLM 密钥时尝试 LLM 驱动；若 openai 不可用则降级
    try:
        from dota_helper.llm.client import LLMClient
    except ImportError as e:
        logger.warning(
            "openai 模块未安装或导入失败 (%s)，复盘将使用 FallbackAnalyzer 规则分析降级运行",
            e,
        )
        config = _load_review_config(config_path)
        return PostMatchReviewAPI(
            orchestrator_factory=_create_fallback_orchestrator_factory(
                data_source, config
            ),
            config_path=config_path,
            data_source=data_source,
            llm_client=llm_client,
            memory=memory,
            enable_background_review=False,
            data_dir=data_dir,
            background_reviewer_config=background_reviewer_config,
        )

    if llm_client is None:
        llm_client = LLMClient()

    logger.info("创建默认 PostMatchReviewAPI 实例（LLM 驱动）")
    return PostMatchReviewAPI(
        config_path=config_path,
        data_source=data_source,
        llm_client=llm_client,
        memory=memory,
        enable_background_review=enable_background_review,
        data_dir=data_dir,
        background_reviewer_config=background_reviewer_config,
    )
