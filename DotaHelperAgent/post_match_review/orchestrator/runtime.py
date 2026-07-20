"""Runtime 依赖注入容器"""
from typing import Optional, Dict, Any
import yaml
from pathlib import Path

from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.interfaces.verifier import IStopVerifier
from post_match_review.orchestrator.strategic_loop import StrategicLoop
from post_match_review.orchestrator.tactical_loop import TacticalLoop
from post_match_review.orchestrator.review_orchestrator import ReviewOrchestrator
from post_match_review.report.report_builder import ReportBuilder
from post_match_review.report.markdown_renderer import MarkdownRenderer
from post_match_review.types.state import ReviewAgentState
from post_match_review.engines.stop_verifier import StopVerifier
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.analyzers.laning_analyzer import LaningAnalyzer
from post_match_review.analyzers.teamfight_analyzer import TeamfightAnalyzer
from post_match_review.analyzers.economy_analyzer import EconomyAnalyzer
from post_match_review.analyzers.decision_analyzer import DecisionAnalyzer
from post_match_review.analyzers.vision_analyzer import VisionAnalyzer
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.orchestrator.runtime")


class Runtime:
    """依赖注入容器

    从配置文件组装默认的 ReviewOrchestrator，支持替换依赖。
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        data_source: Optional[IMatchDataSource] = None,
        llm_client: Optional[ILLMClient] = None,
    ) -> None:
        """初始化 Runtime

        Args:
            config_path: 配置文件路径，默认为 post_match_review/config/review_config.yaml
            data_source: 比赛数据源，可选
            llm_client: LLM 客户端，可选
        """
        self._config = self._load_config(config_path)
        self._data_source = data_source
        self._llm_client = llm_client

        logger.info("Runtime 初始化完成")

    def build_orchestrator(self, match_id: str) -> ReviewOrchestrator:
        """构建 ReviewOrchestrator 实例

        Args:
            match_id: 比赛 ID（用于初始化状态）

        Returns:
            ReviewOrchestrator: 编排器实例
        """
        logger.info("构建 ReviewOrchestrator: match_id=%s", match_id)

        # 1. 创建数据源（如果未提供）
        if self._data_source is None:
            raise ValueError("data_source 未配置")

        # 2. 创建 LLM 客户端（如果未提供）
        if self._llm_client is None:
            raise ValueError("llm_client 未配置")

        # 3. 创建提示词构建器
        prompt_builder = PromptBuilder()

        # 4. 创建战略循环
        strategic_loop = StrategicLoop(config=self._config)

        # 5. 创建分析器
        analyzers = {
            "laning": LaningAnalyzer(self._llm_client, prompt_builder),
            "teamfight": TeamfightAnalyzer(self._llm_client, prompt_builder),
            "economy": EconomyAnalyzer(self._llm_client, prompt_builder),
            "decisions": DecisionAnalyzer(self._llm_client, prompt_builder),
            "vision": VisionAnalyzer(self._llm_client, prompt_builder),
        }

        # 6. 创建战术循环工厂
        def tactical_loop_factory(phase: str) -> TacticalLoop:
            analyzer = analyzers.get(phase)
            if analyzer is None:
                raise ValueError(f"未知的分析阶段: {phase}")
            max_iterations = self._config.get("max_iterations_per_phase", 3)
            return TacticalLoop(analyzer=analyzer, max_iterations=max_iterations)

        # 7. 创建停止验证器
        required_phases = self._config.get("required_phases", ["laning", "teamfight", "economy", "decisions"])
        min_confidence = self._config.get("min_confidence", 0.6)
        stop_verifier = StopVerifier(
            required_phases=required_phases,
            min_confidence=min_confidence,
        )

        # 8. 创建报告构建器和渲染器
        report_builder = ReportBuilder()
        markdown_renderer = MarkdownRenderer()

        # 9. 创建 Agent 状态
        state = ReviewAgentState(match_id=match_id)

        # 10. 组装编排器
        orchestrator = ReviewOrchestrator(
            data_source=self._data_source,
            strategic_loop=strategic_loop,
            tactical_loop_factory=tactical_loop_factory,
            stop_verifier=stop_verifier,
            report_builder=report_builder,
            state=state,
            markdown_renderer=markdown_renderer,
        )

        logger.info("ReviewOrchestrator 构建完成")
        return orchestrator

    def _load_config(self, config_path: Optional[Path]) -> Dict[str, Any]:
        """加载配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            Dict[str, Any]: 配置字典
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "review_config.yaml"

        if not config_path.exists():
            logger.warning("配置文件不存在: %s，使用默认配置", config_path)
            return self._get_default_config()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.info("加载配置文件: %s", config_path)
            return config
        except Exception as e:
            logger.error("加载配置文件失败: %s，使用默认配置", e)
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置

        Returns:
            Dict[str, Any]: 默认配置字典
        """
        return {
            "max_iterations_per_phase": 3,
            "required_phases": ["laning", "teamfight", "economy", "decisions"],
            "min_confidence": 0.6,
            "default_budgets": {
                "laning": 2,
                "teamfight": 2,
                "economy": 2,
                "decisions": 2,
                "vision": 2,
            },
        }
