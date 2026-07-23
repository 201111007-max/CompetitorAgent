"""Skill 驱动分析器 — 从 YAML 技能定义动态生成分析能力

不硬编码 phase_name 或 _format_domain_data()，
全部由外部 YAML 技能定义文件驱动。

组件：
- SkillDrivenPromptBuilder: 从技能定义加载模板的提示词构建器
- SkillDrivenAnalyzer: Skill 驱动分析器主类
- _validate_skill_definition: 技能定义验证函数
"""
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.engines.data_formatter import DataFormatter
from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.analysis import AnalysisResult
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.skill_driven")


class SkillDrivenPromptBuilder(PromptBuilder):
    """从 YAML 技能定义加载模板的提示词构建器

    与标准 PromptBuilder 不同，模板直接从 skill_definition 字典获取，
    不依赖 prompts/tactical_{phase}.yaml 文件。
    复用父类的 _build_stable_layer / _build_context_layer / _build_volatile_layer。
    """

    def __init__(
        self,
        skill_definition: Dict[str, Any],
    ) -> None:
        """初始化技能驱动提示词构建器

        Args:
            skill_definition: YAML 技能定义字典（已加载的完整 YAML 内容）
        """
        # 不调用 super().__init__()，因为不需要 prompts_dir
        # 直接设置父类需要的属性
        self._skill_definition = skill_definition
        self._prompts_dir = None  # type: ignore[assignment]
        self._template_cache: Dict[str, Dict[str, Any]] = {}
        logger.info(
            "SkillDrivenPromptBuilder 初始化: skill=%s",
            skill_definition.get("name", "unknown"),
        )

    def _load_template(self, phase: str) -> Dict[str, Any]:
        """直接返回技能定义作为模板

        Args:
            phase: 分析阶段名称（应与 skill_definition 中的 phase 一致）

        Returns:
            Dict[str, Any]: 技能定义字典
        """
        # 验证 phase 一致性
        skill_phase = self._skill_definition.get("phase", "")
        if skill_phase and skill_phase != phase:
            logger.warning(
                "技能定义 phase=%s 与请求 phase=%s 不一致，使用技能定义",
                skill_phase, phase,
            )

        logger.debug(
            "使用技能定义作为模板: phase=%s, name=%s",
            phase,
            self._skill_definition.get("name", "unknown"),
        )
        return self._skill_definition


class SkillDrivenAnalyzer(BaseLLMReviewAnalyzer):
    """Skill 驱动分析器

    从 YAML 技能定义文件动态创建分析能力，无需编写 Python 子类。
    继承基类的 parse_response() 和 build_prompt() 模板方法，
    通过 SkillDrivenPromptBuilder 自动注入 DataFormatter 格式化。

    使用方式：
        # 方式1：从文件路径加载
        analyzer = SkillDrivenAnalyzer.from_yaml(
            llm_client=client,
            yaml_path=Path("prompts/skills/roshan_timing.yaml"),
        )

        # 方式2：从字典创建
        analyzer = SkillDrivenAnalyzer(
            llm_client=client,
            skill_definition=skill_dict,
        )

        # 方式3：从 SkillStore 加载
        analyzer = SkillDrivenAnalyzer.from_skill_store(
            llm_client=client,
            skill_store=store,
            skill_name="roshan_timing",
        )
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        skill_definition: Dict[str, Any],
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        """初始化技能驱动分析器

        Args:
            llm_client: LLM 客户端实例
            skill_definition: YAML 技能定义字典
            prompt_builder: 提示词构建器（可选，默认使用 SkillDrivenPromptBuilder）
        """
        self._skill_definition = skill_definition
        self._phase_name: str = skill_definition.get("phase", "custom")

        # 创建 SkillDrivenPromptBuilder（如果未提供自定义 builder）
        if prompt_builder is None:
            prompt_builder = SkillDrivenPromptBuilder(skill_definition)

        super().__init__(llm_client, prompt_builder)

        # 从 metadata 提取配置
        metadata = skill_definition.get("metadata", {})
        self._min_confidence: float = metadata.get("min_confidence", 0.6)
        self._expected_conclusions: int = metadata.get("expected_conclusions", 3)

        logger.info(
            "技能驱动分析器初始化: phase=%s, name=%s, min_confidence=%.2f",
            self._phase_name,
            skill_definition.get("name", "unknown"),
            self._min_confidence,
        )

    @classmethod
    def from_yaml(
        cls,
        llm_client: ILLMClient,
        yaml_path: Path,
    ) -> "SkillDrivenAnalyzer":
        """从 YAML 文件创建分析器

        Args:
            llm_client: LLM 客户端实例
            yaml_path: YAML 技能定义文件路径

        Returns:
            SkillDrivenAnalyzer: 分析器实例

        Raises:
            ValueError: YAML 文件内容为空或定义无效
        """
        logger.info("从 YAML 文件加载技能定义: %s", yaml_path)
        with open(yaml_path, "r", encoding="utf-8") as f:
            skill_definition = yaml.safe_load(f)

        if not skill_definition:
            raise ValueError(f"YAML 文件内容为空: {yaml_path}")

        _validate_skill_definition(skill_definition, yaml_path)

        return cls(llm_client=llm_client, skill_definition=skill_definition)

    @classmethod
    def from_skill_store(
        cls,
        llm_client: ILLMClient,
        skill_store: Any,
        skill_name: str,
        use_builtin: bool = False,
    ) -> "SkillDrivenAnalyzer":
        """从 SkillStore 加载技能定义并创建分析器

        Args:
            llm_client: LLM 客户端实例
            skill_store: 技能存储实例（需实现 IAnalysisSkillStore）
            skill_name: 技能名称
            use_builtin: 是否从内置目录加载

        Returns:
            SkillDrivenAnalyzer: 分析器实例

        Raises:
            ValueError: 技能不存在或定义无效
        """
        if use_builtin:
            definition = skill_store.load_builtin_skill(skill_name)
        else:
            definition = skill_store.load_analysis_skill(skill_name)

        if definition is None:
            raise ValueError(f"分析技能不存在: {skill_name}")

        _validate_skill_definition(definition, skill_name)

        return cls(llm_client=llm_client, skill_definition=definition)

    @property
    def phase_name(self) -> str:
        """分析阶段名称（来自 YAML 技能定义）

        Returns:
            str: 阶段名称
        """
        return self._phase_name

    @property
    def skill_definition(self) -> Dict[str, Any]:
        """获取技能定义

        Returns:
            Dict[str, Any]: 技能定义字典
        """
        return self._skill_definition

    @property
    def skill_name(self) -> str:
        """获取技能名称

        Returns:
            str: 技能名称
        """
        return self._skill_definition.get("name", self._phase_name)

    def _format_domain_data(self, match_data: MatchData) -> str:
        """格式化领域数据

        由于 SkillDrivenPromptBuilder 已通过 DataFormatter 自动处理
        data_requirements 声明（注入到 Context 层和 Volatile 层），
        此方法默认返回空字符串。

        但如果 YAML 技能定义中存在 custom 格式的 data_requirements，
        则记录日志提示需自定义处理。

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的领域数据文本
        """
        data_requirements = self._skill_definition.get("data_requirements", [])

        # 检查是否有 custom 格式的需求
        custom_reqs = [
            req for req in data_requirements
            if req.get("format") == "custom"
        ]

        if not custom_reqs:
            return ""

        # custom 格式的数据处理逻辑
        # 用户可在子类化 SkillDrivenAnalyzer 时覆盖此方法
        logger.debug(
            "[%s] 存在 %d 个 custom 格式需求，默认跳过"
            "（可通过子类 _format_domain_data() 自定义处理）",
            self.phase_name, len(custom_reqs),
        )
        return ""

    def validate_result(self, result: AnalysisResult) -> bool:
        """验证分析结果（使用技能定义中的 min_confidence）

        Args:
            result: 待验证的分析结果

        Returns:
            bool: 结果是否有效
        """
        if result.confidence < self._min_confidence:
            logger.warning(
                "[%s] 置信度 %.2f < 技能定义阈值 %.2f",
                self.phase_name, result.confidence, self._min_confidence,
            )
            return False

        has_evidence_count = sum(
            1 for c in result.conclusions if c.has_evidence
        )
        if has_evidence_count == 0:
            logger.warning(
                "[%s] 无结论包含证据支撑", self.phase_name,
            )
            return False

        logger.debug("[%s] 结果验证通过", self.phase_name)
        return True


def _validate_skill_definition(
    definition: Dict[str, Any],
    source: Any = None,
) -> None:
    """验证 YAML 技能定义的必要字段

    Args:
        definition: 技能定义字典
        source: 来源标识（文件路径或名称，用于错误提示）

    Raises:
        ValueError: 定义缺少必要字段
    """
    required_fields = ["phase", "name", "stable_layer", "volatile_layer"]
    missing = [f for f in required_fields if f not in definition]

    if missing:
        raise ValueError(
            f"技能定义缺少必要字段: {missing}, 来源: {source}"
        )

    # 验证 phase 名称合法（建议小写字母+下划线，避免与内置阶段冲突）
    phase = definition["phase"]
    if not phase.replace("_", "").isalpha() or not phase.islower():
        logger.warning(
            "技能定义 phase=%s 建议使用小写字母+下划线格式, 来源: %s",
            phase, source,
        )

    logger.debug(
        "技能定义验证通过: phase=%s, name=%s",
        phase, definition["name"],
    )
