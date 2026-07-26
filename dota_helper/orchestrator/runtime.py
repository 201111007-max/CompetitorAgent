"""Runtime 依赖注入容器"""
from typing import Optional, Dict, Any, List
import yaml
from pathlib import Path

from dota_helper.interfaces.data_source import IMatchDataSource
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.interfaces.verifier import IStopVerifier
from dota_helper.orchestrator.strategic_loop import StrategicLoop
from dota_helper.orchestrator.tactical_loop import TacticalLoop
from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
from dota_helper.orchestrator.review_config import ReviewConfig
from dota_helper.report.report_builder import ReportBuilder
from dota_helper.report.markdown_renderer import MarkdownRenderer
from dota_helper.domain_types.state import ReviewAgentState
from dota_helper.engines.stop_verifier import StopVerifier
from dota_helper.engines.prompt_builder import PromptBuilder
from dota_helper.analyzers.laning_analyzer import LaningAnalyzer
from dota_helper.analyzers.teamfight_analyzer import TeamfightAnalyzer
from dota_helper.analyzers.economy_analyzer import EconomyAnalyzer
from dota_helper.analyzers.decision_analyzer import DecisionAnalyzer
from dota_helper.analyzers.vision_analyzer import VisionAnalyzer
from dota_helper.analyzers.skill_driven import SkillDrivenAnalyzer
from dota_helper.observability.logger import get_logger

logger = get_logger("orchestrator.runtime")


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
            config_path: 配置文件路径，默认为 dota_helper/config/review_config.yaml
            data_source: 比赛数据源，可选
            llm_client: LLM 客户端，可选
        """
        # P1-3: 使用类型安全的 ReviewConfig 替代 Dict[str, Any]
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

        # 5.1 加载自定义分析技能
        custom_skills = self._load_custom_skills()
        for skill in custom_skills:
            phase = skill.get("phase")
            if phase and phase not in analyzers:  # 不覆盖内置阶段
                analyzers[phase] = SkillDrivenAnalyzer(
                    llm_client=self._llm_client,
                    skill_definition=skill,
                )
                logger.info(
                    "注册自定义分析技能: phase=%s, name=%s",
                    phase, skill.get("name", "unknown"),
                )

        # 6. 创建战术循环工厂
        def tactical_loop_factory(phase: str) -> TacticalLoop:
            analyzer = analyzers.get(phase)
            if analyzer is None:
                raise ValueError(f"未知的分析阶段: {phase}")
            max_iterations = self._config.tactical_loop.max_iterations_per_phase
            return TacticalLoop(analyzer=analyzer, max_iterations=max_iterations)

        # 7. 创建停止验证器
        required_phases = self._config.stop_verifier.required_phases
        min_confidence = self._config.stop_verifier.min_confidence
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

    def _load_config(self, config_path: Optional[Path]) -> ReviewConfig:
        """加载配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            ReviewConfig: 类型安全的配置实例
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "review_config.yaml"

        if not config_path.exists():
            logger.warning("配置文件不存在: %s，使用默认配置", config_path)
            return ReviewConfig()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.info("加载配置文件: %s", config_path)
            return ReviewConfig.from_dict(config)
        except Exception as e:
            logger.error("加载配置文件失败: %s，使用默认配置", e)
            return ReviewConfig()

    def _get_default_config(self) -> ReviewConfig:
        """获取默认配置

        Returns:
            ReviewConfig: 默认配置实例
        """
        return ReviewConfig()

    def _load_custom_skills(self) -> List[Dict[str, Any]]:
        """加载自定义分析技能

        从配置的 skills_dir 加载用户自定义的分析技能 YAML 文件。

        Returns:
            List[Dict[str, Any]]: 自定义分析技能定义列表
        """
        skills_dir = self._config.skills_dir
        if not skills_dir:
            return []

        try:
            from dota_helper.memory.skill_store import SkillStore
            skill_store = SkillStore(skills_dir)
            skills = skill_store.list_analysis_skills()
            if skills:
                logger.info("加载 %d 个自定义分析技能", len(skills))
            return skills
        except Exception as e:
            logger.error("加载自定义技能失败: %s", e)
            return []

    # P2-3: 公共方法，避免外部直接访问 _config
    def get_skills_dir(self) -> Optional[str]:
        """获取技能存储目录

        Returns:
            Optional[str]: 技能目录路径
        """
        return self._config.skills_dir

    def get_analysis_skills_dir(self) -> Optional[str]:
        """获取分析技能目录

        Returns:
            Optional[str]: 分析技能目录路径
        """
        skills_dir = self._config.skills_dir
        if not skills_dir:
            return None
        return str(Path(skills_dir) / "analysis")
