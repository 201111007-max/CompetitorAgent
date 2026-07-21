"""三层提示词构建器"""
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.analysis import AnalysisResult
from post_match_review.observability.logger import get_logger

logger = get_logger("engines.prompt_builder")


class PromptBuilder:
    """三层提示词构建器（Stable/Context/Volatile）"""

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

        # Layer 1: Stable（稳定层）
        stable_content = self._build_stable_layer(phase)
        messages.append({"role": "system", "content": stable_content})

        # Layer 2: Context（上下文层）
        context_content = self._build_context_layer(match_data, completed_results)
        messages.append({"role": "user", "content": context_content})

        # Layer 3: Volatile（易变层）
        volatile_content = self._build_volatile_layer(phase, iteration_feedback)
        messages.append({"role": "user", "content": volatile_content})

        logger.debug(
            "构建提示词: phase=%s, messages=%d",
            phase,
            len(messages),
        )

        return messages

    def _build_stable_layer(self, phase: str) -> str:
        """构建 Stable 层（系统提示）

        Args:
            phase: 当前分析阶段

        Returns:
            str: Stable 层内容
        """
        template = self._load_template(phase)
        return template.get("stable_layer", "")

    def _build_context_layer(
        self,
        match_data: MatchData,
        completed_results: Optional[List[AnalysisResult]],
    ) -> str:
        """构建 Context 层（比赛数据 + 已有结论）

        Args:
            match_data: 结构化比赛数据
            completed_results: 已完成的阶段结果

        Returns:
            str: Context 层内容
        """
        context_parts: List[str] = []

        # 比赛基本信息
        context_parts.append("## 比赛基本信息")
        context_parts.append(f"- 比赛 ID: {match_data.match_id}")
        context_parts.append(f"- 时长: {match_data.duration} 秒")
        context_parts.append(f"- 胜利方: {'天辉' if match_data.radiant_win else '夜魇'}")
        context_parts.append(f"- 比分: {match_data.radiant_score} - {match_data.dire_score}")
        context_parts.append(f"- 游戏模式: {match_data.game_mode}")
        context_parts.append("")

        # 玩家数据摘要
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

        # 已完成阶段结论
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
        phase: str,
        iteration_feedback: Optional[str],
    ) -> str:
        """构建 Volatile 层（当前阶段指令 + 反馈）

        Args:
            phase: 当前分析阶段
            iteration_feedback: 上一轮迭代反馈

        Returns:
            str: Volatile 层内容
        """
        template = self._load_template(phase)
        volatile_template = template.get("volatile_layer", "")

        # 注入迭代反馈
        if iteration_feedback:
            feedback_text = f"\n\n上一轮反馈:\n{iteration_feedback}"
        else:
            feedback_text = ""

        return volatile_template.format(iteration_feedback=feedback_text)

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
