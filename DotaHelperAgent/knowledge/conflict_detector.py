"""冲突检测 - 识别知识库中的矛盾建议"""

from typing import List, Dict, Any
from utils.log_config import get_logger

logger = get_logger("conflict_detector", component="knowledge")


class ConflictDetector:
    """冲突检测器

    功能：
    - 检测物品推荐冲突（同一物品，不同推荐）
    - 检测技能加点冲突（同一技能，不同优先级）
    - 检测策略建议冲突（同一场景，不同建议）
    """

    def __init__(self):
        """初始化冲突检测器"""
        logger.info("冲突检测器初始化完成")

    def detect(
        self,
        knowledge_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """检测知识冲突

        Args:
            knowledge_list: 知识列表

        Returns:
            冲突列表
        """
        conflicts = []

        # 按英雄分组
        hero_knowledge = self._group_by_hero(knowledge_list)

        # 检测每个英雄的知识冲突
        for hero, knowledge_items in hero_knowledge.items():
            # 检测物品推荐冲突
            item_conflicts = self._detect_item_conflicts(hero, knowledge_items)
            conflicts.extend(item_conflicts)

            # 检测技能加点冲突
            skill_conflicts = self._detect_skill_conflicts(hero, knowledge_items)
            conflicts.extend(skill_conflicts)

        if conflicts:
            logger.warning(f"检测到 {len(conflicts)} 个知识冲突")

        return conflicts

    def _group_by_hero(
        self,
        knowledge_list: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """按英雄分组"""
        grouped = {}
        for knowledge in knowledge_list:
            hero = knowledge.get("hero", "unknown")
            if hero not in grouped:
                grouped[hero] = []
            grouped[hero].append(knowledge)
        return grouped

    def _detect_item_conflicts(
        self,
        hero: str,
        knowledge_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """检测物品推荐冲突"""
        conflicts = []

        # 提取物品推荐
        item_recommendations = {}
        for item in knowledge_items:
            if "item" in item and "recommendation" in item:
                item_name = item["item"]
                recommendation = item["recommendation"]
                source = item.get("source", "unknown")

                if item_name not in item_recommendations:
                    item_recommendations[item_name] = []

                item_recommendations[item_name].append({
                    "recommendation": recommendation,
                    "source": source
                })

        # 检测冲突
        for item_name, recommendations in item_recommendations.items():
            if len(recommendations) > 1:
                # 检查推荐是否矛盾
                rec_values = [r["recommendation"] for r in recommendations]
                if self._is_contradictory(rec_values):
                    conflicts.append({
                        "type": "item_recommendation_conflict",
                        "hero": hero,
                        "item": item_name,
                        "recommendations": recommendations,
                        "description": f"英雄 {hero} 的物品 {item_name} 存在推荐冲突"
                    })

        return conflicts

    def _detect_skill_conflicts(
        self,
        hero: str,
        knowledge_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """检测技能加点冲突"""
        conflicts = []

        # 提取技能加点
        skill_builds = {}
        for item in knowledge_items:
            if "skill" in item and "priority" in item:
                skill_name = item["skill"]
                priority = item["priority"]
                source = item.get("source", "unknown")

                if skill_name not in skill_builds:
                    skill_builds[skill_name] = []

                skill_builds[skill_name].append({
                    "priority": priority,
                    "source": source
                })

        # 检测冲突
        for skill_name, builds in skill_builds.items():
            if len(builds) > 1:
                # 检查优先级是否矛盾
                priorities = [b["priority"] for b in builds]
                if len(set(priorities)) > 1:
                    conflicts.append({
                        "type": "skill_build_conflict",
                        "hero": hero,
                        "skill": skill_name,
                        "builds": builds,
                        "description": f"英雄 {hero} 的技能 {skill_name} 存在加点冲突"
                    })

        return conflicts

    def _is_contradictory(self, values: List[str]) -> bool:
        """判断值是否矛盾"""
        # 定义矛盾对
        contradictory_pairs = [
            ("必出", "不出"),
            ("推荐", "不推荐"),
            ("优先", "不优先"),
            ("核心", "可选")
        ]

        for pair in contradictory_pairs:
            if pair[0] in values and pair[1] in values:
                return True

        return False
