"""PostMatchReviewAPI 工厂入口

提供零配置创建 `PostMatchReviewAPI` 的能力：
- 自动组装 OpenDota 数据源
- 自动检测 LLM 密钥，未配置时降级为规则驱动的 FallbackAnalyzer
- 外部调用方保持 `from post_match_review import create_default_api`
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional

from post_match_review.facade.api import PostMatchReviewAPI
from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.orchestrator.review_orchestrator import ReviewOrchestrator
from post_match_review.orchestrator.strategic_loop import StrategicLoop
from post_match_review.orchestrator.tactical_loop import TacticalLoop
from post_match_review.engines.stop_verifier import StopVerifier
from post_match_review.engines.budget import IterationBudget
from post_match_review.report.report_builder import ReportBuilder
from post_match_review.report.markdown_renderer import MarkdownRenderer
from post_match_review.domain_types.state import ReviewAgentState
from post_match_review.domain_types.analysis import AnalysisContext
from post_match_review.domain_types.match_data import MatchData
from post_match_review.data_source.opendota_client import OpenDotaClient
from post_match_review.data_source.match_fetcher import MatchFetcher
from post_match_review.analyzers.fallback_analyzer import FallbackAnalyzer
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.facade.entrypoint")


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


def _load_strategic_config(config_path: Path) -> Dict[str, Any]:
    """加载战略循环相关配置

    Args:
        config_path: 配置文件路径

    Returns:
        Dict[str, Any]: 战略配置字典
    """
    import yaml

    if not config_path.exists():
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return {
            "max_iterations_per_phase": 3,
            "required_phases": ["laning", "teamfight", "economy", "decisions"],
            "min_confidence": 0.6,
            "default_budgets": {
                "laning": 3,
                "teamfight": 3,
                "economy": 2,
                "decisions": 2,
                "vision": 1,
            },
        }

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("读取配置文件失败: %s，使用默认配置", e)
        return {
            "max_iterations_per_phase": 3,
            "required_phases": ["laning", "teamfight", "economy", "decisions"],
            "min_confidence": 0.6,
            "default_budgets": {
                "laning": 3,
                "teamfight": 3,
                "economy": 2,
                "decisions": 2,
                "vision": 1,
            },
        }

    tactical = raw.get("tactical_loop", {})
    verifier = raw.get("stop_verifier", {})
    return {
        "max_iterations_per_phase": tactical.get("max_iterations_per_phase", 3),
        "required_phases": verifier.get(
            "required_phases", ["laning", "teamfight", "economy", "decisions"]
        ),
        "min_confidence": verifier.get("min_confidence", 0.6),
        "default_budgets": tactical.get(
            "default_budgets",
            {
                "laning": 3,
                "teamfight": 3,
                "economy": 2,
                "decisions": 2,
                "vision": 1,
            },
        ),
    }


def _create_fallback_orchestrator_factory(
    data_source: IMatchDataSource,
    config_path: Path,
) -> Any:
    """创建使用 FallbackAnalyzer 的编排器工厂

    当未配置 LLM 密钥时使用，确保复盘流程仍可运行。

    Args:
        data_source: 比赛数据源
        config_path: 配置文件路径

    Returns:
        Callable[[str], ReviewOrchestrator]: 编排器工厂函数
    """
    config = _load_strategic_config(config_path)
    strategic_loop = StrategicLoop(config=config)
    stop_verifier = StopVerifier(
        required_phases=config["required_phases"],
        min_confidence=config["min_confidence"],
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
                max_iterations=config["max_iterations_per_phase"],
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
) -> PostMatchReviewAPI:
    """创建默认配置的 PostMatchReviewAPI 实例

    自动完成以下装配：
    1. OpenDota 数据源（未提供时）
    2. LLM 客户端（未提供时）
    3. 未配置 LLM 密钥时，自动降级为 FallbackAnalyzer 规则分析

    Args:
        config_path: 复盘模块配置文件路径
        data_source: 比赛数据源（可选，覆盖默认）
        llm_client: LLM 客户端（可选，覆盖默认）

    Returns:
        PostMatchReviewAPI: 默认 API 实例
    """
    if config_path is None:
        config_path = _default_config_path()

    # 1. 创建数据源
    if data_source is None:
        opendota_client = OpenDotaClient(timeout=30.0, max_retries=3)
        match_fetcher = MatchFetcher(client=opendota_client)
        data_source = MatchFetcherAdapter(match_fetcher)
        logger.info("使用默认 OpenDota 数据源")

    # 2. 判断是否有 LLM 能力
    use_llm = _has_llm_key()
    if not use_llm:
        logger.warning(
            "未检测到 LLM API 密钥（OPENAI_API_KEY/DEEPSEEK_API_KEY/LLM_API_KEY），"
            "复盘将使用 FallbackAnalyzer 规则分析降级运行"
        )

    # 3. 无 LLM 时直接使用自定义工厂，避免 Runtime 创建 LLM 驱动分析器
    if not use_llm:
        factory = _create_fallback_orchestrator_factory(data_source, config_path)
        return PostMatchReviewAPI(orchestrator_factory=factory)

    # 4. 有 LLM 密钥时尝试 LLM 驱动；若 openai 不可用则降级
    try:
        from post_match_review.llm.client import LLMClient
    except ImportError as e:
        logger.warning(
            "openai 模块未安装或导入失败 (%s)，复盘将使用 FallbackAnalyzer 规则分析降级运行",
            e,
        )
        factory = _create_fallback_orchestrator_factory(data_source, config_path)
        return PostMatchReviewAPI(orchestrator_factory=factory)

    if llm_client is None:
        llm_client = LLMClient()

    logger.info("创建默认 PostMatchReviewAPI 实例（LLM 驱动）")
    return PostMatchReviewAPI(
        config_path=config_path,
        data_source=data_source,
        llm_client=llm_client,
    )
