"""战略循环：全局评估与策略制定"""
from typing import Dict, Any, List
from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.strategy import AnalysisStrategy
from post_match_review.domain_types.enums import MatchType
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.orchestrator.strategic")


class StrategicLoop:
    """战略循环：全局评估与策略制定"""

    def __init__(self, config: Dict[str, Any]) -> None:
        """初始化战略循环

        Args:
            config: 配置字典，包含各阶段的默认预算和深度设置
        """
        self._config = config
        logger.info("战略循环初始化完成")

    def evaluate(self, match_data: MatchData) -> AnalysisStrategy:
        """评估比赛并制定分析策略

        Args:
            match_data: 结构化比赛数据

        Returns:
            AnalysisStrategy: 分析策略
        """
        logger.info("开始评估比赛: match_id=%s", match_data.match_id)

        # 1. 分类比赛类型
        match_type = self.classify_match(match_data)
        logger.info("比赛类型分类: %s", match_type)

        # 2. 确定分析优先级
        priority_phases = self._determine_priority_phases(match_type, match_data)
        logger.info("分析优先级: %s", priority_phases)

        # 3. 分配预算
        budget_allocation = self.allocate_budget(match_type)
        logger.info("预算分配: %s", budget_allocation)

        # 4. 确定预期深度
        expected_depth = self._determine_expected_depth(match_type)
        logger.info("预期深度: %s", expected_depth)

        strategy = AnalysisStrategy(
            match_type=match_type,
            priority_phases=priority_phases,
            budget_allocation=budget_allocation,
            expected_depth=expected_depth,
        )

        logger.info("战略评估完成")
        return strategy

    def classify_match(self, match_data: MatchData) -> str:
        """比赛类型分类

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: MatchType 枚举值
        """
        duration = match_data.duration
        radiant_score = match_data.radiant_score
        dire_score = match_data.dire_score
        score_diff = abs(radiant_score - dire_score)
        total_score = radiant_score + dire_score

        # 快速推平（< 15 分钟）
        if duration < 900:  # 15 分钟
            return MatchType.QUICK_PUSH.value

        # 碾压局（比分差距 > 30 或时长 < 25 分钟且差距 > 20）
        if score_diff > 30 or (duration < 1500 and score_diff > 20):
            return MatchType.STOMP.value

        # 翻盘局（需要通过经济曲线判断，这里简化为比分接近但时长较长）
        if duration > 2400 and score_diff < 10:  # > 40 分钟且比分接近
            return MatchType.COMEBACK.value

        # 焦灼局（比分差距 < 5）
        if score_diff < 5 and duration > 1800:  # > 30 分钟
            return MatchType.CLOSE_GAME.value

        # 普通局
        return MatchType.NORMAL.value

    def allocate_budget(self, match_type: str) -> Dict[str, int]:
        """为各阶段分配预算

        Args:
            match_type: 比赛类型

        Returns:
            Dict[str, int]: 阶段 -> 迭代次数
        """
        # 从配置中读取默认预算
        default_budgets = self._config.get("default_budgets", {})

        # 根据比赛类型调整预算
        if match_type == MatchType.STOMP.value:
            # 碾压局：重点关注压制效率
            return {
                "laning": default_budgets.get("laning", 2),
                "teamfight": default_budgets.get("teamfight", 1),
                "economy": default_budgets.get("economy", 3),
                "decisions": default_budgets.get("decisions", 2),
                "vision": default_budgets.get("vision", 1),
            }
        elif match_type == MatchType.COMEBACK.value:
            # 翻盘局：重点关注决策和团战
            return {
                "laning": default_budgets.get("laning", 2),
                "teamfight": default_budgets.get("teamfight", 3),
                "economy": default_budgets.get("economy", 2),
                "decisions": default_budgets.get("decisions", 4),
                "vision": default_budgets.get("vision", 2),
            }
        elif match_type == MatchType.CLOSE_GAME.value:
            # 焦灼局：全面分析
            return {
                "laning": default_budgets.get("laning", 3),
                "teamfight": default_budgets.get("teamfight", 3),
                "economy": default_budgets.get("economy", 3),
                "decisions": default_budgets.get("decisions", 3),
                "vision": default_budgets.get("vision", 3),
            }
        elif match_type == MatchType.QUICK_PUSH.value:
            # 快速推平：简化分析
            return {
                "laning": default_budgets.get("laning", 2),
                "teamfight": default_budgets.get("teamfight", 1),
                "economy": default_budgets.get("economy", 1),
                "decisions": default_budgets.get("decisions", 2),
                "vision": default_budgets.get("vision", 1),
            }
        else:
            # 普通局：标准预算
            return {
                "laning": default_budgets.get("laning", 2),
                "teamfight": default_budgets.get("teamfight", 2),
                "economy": default_budgets.get("economy", 2),
                "decisions": default_budgets.get("decisions", 2),
                "vision": default_budgets.get("vision", 2),
            }

    def _determine_priority_phases(
        self,
        match_type: str,
        match_data: MatchData,
    ) -> List[str]:
        """确定分析优先级

        Args:
            match_type: 比赛类型
            match_data: 比赛数据

        Returns:
            List[str]: 优先级排序的阶段列表
        """
        # 基础优先级
        if match_type == MatchType.STOMP.value:
            # 顺风局优先分析压制效率
            return ["economy", "laning", "teamfight", "decisions", "vision"]
        elif match_type == MatchType.COMEBACK.value:
            # 逆风局优先分析失误
            return ["decisions", "teamfight", "economy", "vision", "laning"]
        elif match_type == MatchType.CLOSE_GAME.value:
            # 焦灼局全面分析
            return ["teamfight", "decisions", "economy", "laning", "vision"]
        elif match_type == MatchType.QUICK_PUSH.value:
            # 快速局简化分析
            return ["laning", "decisions", "teamfight", "economy", "vision"]
        else:
            # 普通局标准顺序
            return ["laning", "teamfight", "economy", "decisions", "vision"]

    def _determine_expected_depth(self, match_type: str) -> Dict[str, str]:
        """确定各阶段预期分析深度

        Args:
            match_type: 比赛类型

        Returns:
            Dict[str, str]: 阶段 -> 深度（shallow/standard/deep）
        """
        if match_type == MatchType.STOMP.value:
            return {
                "laning": "standard",
                "teamfight": "shallow",
                "economy": "deep",
                "decisions": "standard",
                "vision": "shallow",
            }
        elif match_type == MatchType.COMEBACK.value:
            return {
                "laning": "standard",
                "teamfight": "deep",
                "economy": "standard",
                "decisions": "deep",
                "vision": "standard",
            }
        elif match_type == MatchType.CLOSE_GAME.value:
            return {
                "laning": "deep",
                "teamfight": "deep",
                "economy": "deep",
                "decisions": "deep",
                "vision": "standard",
            }
        elif match_type == MatchType.QUICK_PUSH.value:
            return {
                "laning": "deep",
                "teamfight": "shallow",
                "economy": "shallow",
                "decisions": "standard",
                "vision": "shallow",
            }
        else:
            return {
                "laning": "standard",
                "teamfight": "standard",
                "economy": "standard",
                "decisions": "standard",
                "vision": "standard",
            }
