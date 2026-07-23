"""三层提示词构建器

增强版支持从 YAML 加载 analysis_framework、data_requirements、
output_schema，并自动注入到提示词中。旧格式 YAML 完全兼容。
"""
import json
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.analysis import AnalysisResult
from post_match_review.engines.data_formatter import DataFormatter
from post_match_review.observability.logger import get_logger

logger = get_logger("engines.prompt_builder")


class PromptBuilder:
    """三层提示词构建器（Stable/Context/Volatile）

    增强版支持从 YAML 加载 analysis_framework、data_requirements、
    output_schema，并自动注入到提示词中。旧格式 YAML 完全兼容。
    """

    def __init__(self, prompts_dir: Optional[Path] = None) -> None:
        """初始化提示词构建器

        Args:
            prompts_dir: 提示词模板目录，默认为 post_match_review/prompts/
        """
        if prompts_dir is None:
            self._prompts_dir = Path(__file__).parent.parent / "prompts"
        else:
            self._prompts_dir = prompts_dir

        self._template_cache: Dict[str, Dict[str, Any]] = {}
        logger.info("提示词构建器初始化: prompts_dir=%s", self._prompts_dir)

    def build(
        self,
        match_data: MatchData,
        phase: str,
        completed_results: Optional[List[AnalysisResult]] = None,
        iteration_feedback: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """构建完整提示词消息列表

        Args:
            match_data: 结构化比赛数据
            phase: 当前分析阶段
            completed_results: 已完成的阶段结果
            iteration_feedback: 上一轮迭代反馈

        Returns:
            List[Dict[str, str]]: OpenAI 风格消息列表
        """
        messages: List[Dict[str, str]] = []
        template = self._load_template(phase)

        # Layer 1: Stable（稳定层）
        stable_content = self._build_stable_layer(template)
        messages.append({"role": "system", "content": stable_content})

        # Layer 2: Context（上下文层）
        context_content = self._build_context_layer(
            match_data, completed_results, template,
        )
        messages.append({"role": "user", "content": context_content})

        # Layer 3: Volatile（易变层）
        volatile_content = self._build_volatile_layer(
            template, match_data, iteration_feedback,
        )
        messages.append({"role": "user", "content": volatile_content})

        logger.debug(
            "构建提示词: phase=%s, messages=%d",
            phase,
            len(messages),
        )

        return messages

    def _build_stable_layer(self, template: Dict[str, Any]) -> str:
        """构建 Stable 层（系统提示）

        支持从 YAML 注入 analysis_framework 和 output_schema 占位符。

        Args:
            template: YAML 模板内容

        Returns:
            str: Stable 层内容
        """
        stable = template.get("stable_layer", "")

        # 注入 analysis_framework
        if "{analysis_framework}" in stable:
            framework = template.get("analysis_framework", "")
            stable = stable.replace("{analysis_framework}", framework)

        # 注入 output_schema
        if "{output_schema}" in stable:
            schema = template.get("output_schema", {})
            if schema:
                schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
            else:
                schema_str = ""
            stable = stable.replace("{output_schema}", schema_str)

        return stable

    def _build_context_layer(
        self,
        match_data: MatchData,
        completed_results: Optional[List[AnalysisResult]],
        template: Dict[str, Any],
    ) -> str:
        """构建 Context 层（比赛数据 + 已有结论）

        如果 YAML 声明了 data_requirements 且包含非 custom 格式，
        自动使用 DataFormatter 格式化领域数据并追加到 Context 层。

        Args:
            match_data: 结构化比赛数据
            completed_results: 已完成的阶段结果
            template: YAML 模板内容

        Returns:
            str: Context 层内容
        """
        context_parts: List[str] = []

        # 比赛基本信息（保持现有行为）
        context_parts.append("## 比赛基本信息")
        context_parts.append(f"- 比赛 ID: {match_data.match_id}")
        context_parts.append(f"- 时长: {match_data.duration} 秒")
        context_parts.append(f"- 胜利方: {'天辉' if match_data.radiant_win else '夜魇'}")
        context_parts.append(f"- 比分: {match_data.radiant_score} - {match_data.dire_score}")
        context_parts.append(f"- 游戏模式: {match_data.game_mode}")
        context_parts.append("")

        # 玩家数据摘要（保持现有行为）
        context_parts.append("## 玩家数据摘要")
        for i, player in enumerate(match_data.players[:2], 1):  # 只展示前 2 个玩家示例
            context_parts.append(f"### 玩家 {i}")
            context_parts.append(f"- 英雄: {player.hero_name} (ID: {player.hero_id})")
            context_parts.append(f"- KDA: {player.kills}/{player.deaths}/{player.assists}")
            context_parts.append(f"- 补刀/反补: {player.last_hits}/{player.denies}")
            context_parts.append(f"- GPM/XPM: {player.gpm}/{player.xpm}")
            context_parts.append(f"- 阵营: {'天辉' if player.is_radiant else '夜魇'}")
            if player.is_user:
                context_parts.append("- **这是用户**")
            context_parts.append("")

        # YAML 声明的领域数据（新增：DataFormatter 自动格式化）
        data_requirements = template.get("data_requirements", [])
        if data_requirements and DataFormatter.has_declarative_requirements(template):
            formatter = DataFormatter(data_requirements)
            formatted_data = formatter.format_with_secondary(match_data)
            if formatted_data:
                context_parts.append(formatted_data)
                context_parts.append("")

        # 已完成阶段结论（保持现有行为）
        if completed_results:
            context_parts.append("## 已完成的分析阶段")
            for result in completed_results:
                context_parts.append(f"### {result.phase}")
                context_parts.append(f"- 置信度: {result.confidence:.2f}")
                context_parts.append(f"- 迭代次数: {result.iterations_used}")
                if result.conclusions:
                    context_parts.append("- 主要发现:")
                    for conclusion in result.conclusions[:3]:  # 最多展示 3 条结论
                        context_parts.append(f"  - {conclusion.title}")
                context_parts.append("")

        return "\n".join(context_parts)

    def _build_volatile_layer(
        self,
        template: Dict[str, Any],
        match_data: MatchData,
        iteration_feedback: Optional[str],
    ) -> str:
        """构建 Volatile 层（当前阶段指令 + 反馈）

        支持从 YAML 注入 formatted_data 和 iteration_feedback 占位符。

        Args:
            template: YAML 模板内容
            match_data: 结构化比赛数据
            iteration_feedback: 上一轮迭代反馈

        Returns:
            str: Volatile 层内容
        """
        volatile_template = template.get("volatile_layer", "")

        # 注入格式化数据（如果 volatile_layer 引用了 {formatted_data}）
        if "{formatted_data}" in volatile_template:
            data_requirements = template.get("data_requirements", [])
            if data_requirements and DataFormatter.has_declarative_requirements(template):
                formatter = DataFormatter(data_requirements)
                formatted_data = formatter.format_with_secondary(match_data)
            else:
                formatted_data = ""
            volatile_template = volatile_template.replace(
                "{formatted_data}", formatted_data,
            )

        # 注入迭代反馈
        if iteration_feedback:
            feedback_text = f"\n\n上一轮反馈:\n{iteration_feedback}"
        else:
            feedback_text = ""
        volatile_template = volatile_template.replace(
            "{iteration_feedback}", feedback_text,
        )

        return volatile_template

    def _load_template(self, phase: str) -> Dict[str, Any]:
        """加载提示词模板

        Args:
            phase: 分析阶段名称

        Returns:
            Dict[str, Any]: 模板内容
        """
        if phase in self._template_cache:
            return self._template_cache[phase]

        template_file = self._prompts_dir / f"tactical_{phase}.yaml"

        if not template_file.exists():
            logger.warning("模板文件不存在: %s, 使用默认模板", template_file)
            return self._get_default_template()

        try:
            with open(template_file, "r", encoding="utf-8") as f:
                template = yaml.safe_load(f)
            self._template_cache[phase] = template
            logger.debug("加载模板: %s", template_file)
            return template
        except Exception as e:
            logger.error("加载模板失败: %s, 错误: %s", template_file, e)
            return self._get_default_template()

    def _get_default_template(self) -> Dict[str, Any]:
        """获取默认模板

        Returns:
            Dict[str, Any]: 默认模板内容
        """
        return {
            "stable_layer": "你是一位专业的 Dota 2 分析师。请分析比赛数据并提供有价值的洞察。",
            "volatile_layer": "请分析当前阶段的比赛表现。{iteration_feedback}",
        }
