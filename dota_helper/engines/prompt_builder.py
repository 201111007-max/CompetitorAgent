"""三层提示词构建器

增强版支持从 YAML 加载 analysis_framework、data_requirements、
output_schema，并自动注入到提示词中。旧格式 YAML 完全兼容。

模板加载统一委托给 PromptLoader，使用 mtime 自动失效缓存。
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from dota_helper.domain_types.match_data import MatchData
from dota_helper.domain_types.analysis import AnalysisResult
from dota_helper.engines.data_formatter import DataFormatter
from dota_helper.prompt.loader import PromptLoader, get_prompt_loader
from dota_helper.observability.logger import get_logger

logger = get_logger("engines.prompt_builder")


class PromptBuilder:
    """三层提示词构建器（Stable/Context/Volatile）

    增强版支持从 YAML 加载 analysis_framework、data_requirements、
    output_schema，并自动注入到提示词中。旧格式 YAML 完全兼容。
    """

    def __init__(
        self,
        prompts_dir: Optional[Path] = None,
        context_max_players: int = 10,
        context_max_conclusions: int = 5,
        prompt_loader: Optional[PromptLoader] = None,
    ) -> None:
        """初始化提示词构建器

        Args:
            prompts_dir: 提示词模板目录（已委托给 PromptLoader，保留参数向后兼容）
            context_max_players: P2-4: 上下文层最大展示玩家数（默认 10，覆盖旧值 2）
            context_max_conclusions: P2-4: 上下文层最大展示结论数（默认 5，覆盖旧值 3）
            prompt_loader: 统一提示词加载器（None 时使用全局单例）
        """
        self._context_max_players = context_max_players
        self._context_max_conclusions = context_max_conclusions

        # 使用注入的 PromptLoader 或全局单例
        if prompt_loader is not None:
            self._prompt_loader = prompt_loader
        else:
            self._prompt_loader = get_prompt_loader()

        # P3-2: DataFormatter 缓存（按 phase 名称）
        self._formatter_cache: Dict[str, DataFormatter] = {}
        logger.info(
            "提示词构建器初始化: prompt_loader=%s",
            type(self._prompt_loader).__name__,
        )

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
            match_data, completed_results, template, phase,
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
        phase: str = "",
    ) -> str:
        """构建 Context 层（比赛数据 + 已有结论）

        如果 YAML 声明了 data_requirements 且包含非 custom 格式，
        自动使用 DataFormatter 格式化领域数据并追加到 Context 层。

        Args:
            match_data: 结构化比赛数据
            completed_results: 已完成的阶段结果
            template: YAML 模板内容
            phase: 当前分析阶段名称

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

        # 玩家数据摘要（P2-4: 使用可配置的最大玩家数）
        context_parts.append("## 玩家数据摘要")
        for i, player in enumerate(match_data.players[:self._context_max_players], 1):
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
            # P3-2: 复用 DataFormatter 实例（按 phase 缓存）
            if phase not in self._formatter_cache:
                self._formatter_cache[phase] = DataFormatter(data_requirements)
            formatted_data = self._formatter_cache[phase].format_with_secondary(match_data)
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
                    for conclusion in result.conclusions[:self._context_max_conclusions]:
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
        """加载提示词模板（委托给 PromptLoader）

        使用 PromptLoader 的 mtime 自动失效缓存，消除内置永久缓存。

        Args:
            phase: 分析阶段名称

        Returns:
            Dict[str, Any]: 模板内容
        """
        template = self._prompt_loader.load_tactical(phase)

        if not template:
            logger.warning("模板加载失败: phase=%s, 使用默认模板", phase)
            return self._get_default_template()

        return template

    def _get_default_template(self) -> Dict[str, Any]:
        """获取默认模板

        Returns:
            Dict[str, Any]: 默认模板内容
        """
        return {
            "stable_layer": "你是一位专业的 Dota 2 分析师。请分析比赛数据并提供有价值的洞察。",
            "volatile_layer": "请分析当前阶段的比赛表现。{iteration_feedback}",
        }
