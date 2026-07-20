"""对线期分析器"""
import json
from typing import List, Dict, Any, Optional

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer, parse_json_response
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.types.analysis import AnalysisContext, Conclusion
from post_match_review.types.match_data import MatchData, LaneData
from post_match_review.observability.logger import get_logger

logger = get_logger("analyzers.laning")


class LaningAnalyzer(BaseLLMReviewAnalyzer):
    """对线期分析器

    分析 0-10 分钟的对线期表现，包括：
    - 补刀效率（last hits/denies）
    - 英雄消耗换血（hero damage）
    - 净经济差距（net worth delta）
    - 神符利用率（如果有数据）
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
    ) -> None:
        """初始化对线期分析器

        Args:
            llm_client: LLM 客户端实例
            prompt_builder: 提示词构建器，默认使用内置构建器
        """
        super().__init__(llm_client)
        self._prompt_builder = prompt_builder or PromptBuilder()
        logger.info("对线期分析器初始化完成")

    @property
    def phase_name(self) -> str:
        """分析阶段名称"""
        return "laning"

    def build_prompt(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> List[Dict[str, str]]:
        """构建对线期分析提示词

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文

        Returns:
            List[Dict[str, str]]: OpenAI 风格消息列表
        """
        logger.debug("构建对线期分析提示词")

        # 使用 PromptBuilder 构建基础提示词
        messages = self._prompt_builder.build(
            match_data=match_data,
            phase=self.phase_name,
            completed_results=context.completed_results,
            iteration_feedback=context.iteration_feedback,
        )

        # 在 Context 层之后插入对线期特定数据
        if match_data.lane_data:
            lane_data_text = self._format_lane_data(match_data.lane_data, match_data)
            # 在 Context 层（第 2 条消息）后追加对线期数据
            messages[1]["content"] += "\n\n" + lane_data_text

        logger.debug("提示词构建完成，消息数: %d", len(messages))
        return messages

    def parse_response(self, response: str) -> List[Conclusion]:
        """解析 LLM 响应为结论列表

        Args:
            response: LLM 原始响应文本

        Returns:
            List[Conclusion]: 解析后的结论列表
        """
        logger.debug("解析对线期分析响应，长度: %d", len(response))

        conclusions: List[Conclusion] = []

        # 尝试解析 JSON 响应
        parsed = parse_json_response(response)

        if parsed:
            # 优先查找 conclusions 键
            if "conclusions" in parsed:
                for item in parsed["conclusions"]:
                    try:
                        conclusion = self._parse_conclusion_from_dict(item)
                        conclusions.append(conclusion)
                    except Exception as e:
                        logger.warning("解析结论失败: %s, 数据: %s", str(e), item)
            # 尝试从 analysis 键中提取结论
            elif "analysis" in parsed:
                analysis_data = parsed["analysis"]
                # 从 analysis 中提取关键发现
                for key, value in analysis_data.items():
                    if isinstance(value, dict) and "conclusion" in value:
                        evidence = []
                        if "evidence" in value:
                            if isinstance(value["evidence"], list):
                                evidence = [str(e) for e in value["evidence"]]
                            else:
                                evidence = [str(value["evidence"])]
                        conclusions.append(Conclusion(
                            title=key.replace("_", " ").title(),
                            content=value.get("conclusion", ""),
                            evidence=evidence,
                            has_evidence=len(evidence) > 0,
                            impact="medium",
                        ))
                # 如果没有找到结构化的 conclusion，尝试将整个 analysis 作为单条结论
                if not conclusions:
                    evidence = []
                    if "evidence" in analysis_data:
                        if isinstance(analysis_data["evidence"], list):
                            evidence = [str(e) for e in analysis_data["evidence"]]
                    conclusions.append(Conclusion(
                        title="对线期分析",
                        content=str(analysis_data.get("conclusion", analysis_data)),
                        evidence=evidence,
                        has_evidence=len(evidence) > 0,
                        impact="medium",
                    ))
            else:
                # 尝试将整个 JSON 作为单条结论
                evidence = []
                if "evidence" in parsed:
                    if isinstance(parsed["evidence"], list):
                        evidence = [str(e) for e in parsed["evidence"]]
                conclusions.append(Conclusion(
                    title="分析结果",
                    content=str(parsed),
                    evidence=evidence,
                    has_evidence=len(evidence) > 0,
                    impact="medium",
                ))
        else:
            # Fallback: 尝试从文本中提取结论
            conclusions = self._parse_conclusions_from_text(response)

        logger.info("解析出 %d 条结论", len(conclusions))
        return conclusions

    def _parse_conclusion_from_dict(self, data: Dict[str, Any]) -> Conclusion:
        """从字典解析单条结论

        Args:
            data: 结论字典数据

        Returns:
            Conclusion: 解析后的结论
        """
        title = data.get("title", "未命名结论")
        content = data.get("content", data.get("finding", ""))
        evidence_list = data.get("evidence", [])
        
        # 处理 evidence 字段（可能是列表或字典）
        if isinstance(evidence_list, dict):
            evidence = [str(v) for v in evidence_list.values()]
        elif isinstance(evidence_list, list):
            evidence = [str(e) for e in evidence_list]
        else:
            evidence = []

        has_evidence = len(evidence) > 0
        impact = data.get("impact", "medium")
        suggestion = data.get("suggestion")

        return Conclusion(
            title=title,
            content=content,
            evidence=evidence,
            has_evidence=has_evidence,
            impact=impact,
            suggestion=suggestion,
        )

    def _parse_conclusions_from_text(self, text: str) -> List[Conclusion]:
        """从文本中提取结论（fallback 方案）

        Args:
            text: LLM 响应文本

        Returns:
            List[Conclusion]: 提取的结论列表
        """
        conclusions: List[Conclusion] = []

        # 简单的启发式提取：按段落分割，每个非空段落作为一条结论
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        for i, para in enumerate(paragraphs[:5]):  # 最多提取 5 条
            # 跳过系统提示或元信息
            if len(para) < 20:
                continue

            # 提取标题（如果有）
            lines = para.split("\n")
            title = lines[0][:50] if lines else f"结论 {i+1}"
            content = "\n".join(lines[1:]) if len(lines) > 1 else para

            conclusions.append(
                Conclusion(
                    title=title,
                    content=content,
                    evidence=[],
                    has_evidence=False,
                    impact="medium",
                )
            )

        return conclusions

    def _format_lane_data(
        self,
        lane_data: LaneData,
        match_data: MatchData,
    ) -> str:
        """格式化对线期数据为可读文本

        Args:
            lane_data: 对线期数据
            match_data: 完整比赛数据（用于获取玩家信息）

        Returns:
            str: 格式化的对线期数据文本
        """
        logger.debug("格式化对线期数据")

        parts: List[str] = []
        parts.append("## 对线期数据（0-10 分钟）")
        parts.append("")

        # 构建玩家 ID 到名称的映射
        player_map: Dict[str, str] = {}
        for player in match_data.players:
            if player.account_id:
                player_map[player.account_id] = player.hero_name

        # 10 分钟补刀数据
        parts.append("### 10 分钟补刀数")
        for account_id, lh in lane_data.lh_at_10.items():
            hero_name = player_map.get(account_id, account_id)
            denies = lane_data.denies_at_10.get(account_id, 0)
            parts.append(f"- {hero_name}: 补刀 {lh}, 反补 {denies}")
        parts.append("")

        # 10 分钟英雄伤害
        parts.append("### 10 分钟英雄伤害")
        for account_id, damage in lane_data.hero_damage_at_10.items():
            hero_name = player_map.get(account_id, account_id)
            parts.append(f"- {hero_name}: {damage} 伤害")
        parts.append("")

        # 10 分钟净经济
        parts.append("### 10 分钟净经济")
        for account_id, networth in lane_data.networth_at_10.items():
            hero_name = player_map.get(account_id, account_id)
            parts.append(f"- {hero_name}: {networth} 金币")
        parts.append("")

        # 分路信息
        if lane_data.player_lane:
            parts.append("### 分路分配")
            for account_id, lane in lane_data.player_lane.items():
                hero_name = player_map.get(account_id, account_id)
                lane_name = self._get_lane_name(lane)
                parts.append(f"- {hero_name}: {lane_name}")
            parts.append("")

        return "\n".join(parts)

    def _get_lane_name(self, lane: int) -> str:
        """将分路编号转换为名称

        Args:
            lane: 分路编号 (1-5)

        Returns:
            str: 分路名称
        """
        lane_names = {
            1: "安全路（优势路）",
            2: "中路",
            3: "劣势路",
            4: "野区辅助",
            5: "游走辅助",
        }
        return lane_names.get(lane, f"未知分路 ({lane})")
