"""技能加点建议模块"""

from typing import Dict, List, Optional
from ..utils.api_client import OpenDotaClient


class SkillBuilder:
    """技能加点建议器"""

    def __init__(self, client: OpenDotaClient):
        self.client = client

    def recommend_skill_build(
        self,
        hero_name: str,
        role: str = "core"
    ) -> Dict:
        """推荐技能加点

        Args:
            hero_name: 英雄名称
            role: 角色定位 (core/support/offlane)

        Returns:
            Dict: 技能加点建议
        """
        hero_id = self.client.hero_name_to_id(hero_name)
        if not hero_id:
            return {}

        # 获取英雄统计数据
        hero_stats = self.client.get_hero_stats()
        if not hero_stats:
            return {}

        # 查找该英雄的统计
        hero_stat = None
        for stat in hero_stats:
            if stat.get("id") == hero_id:
                hero_stat = stat
                break

        if not hero_stat:
            return {}

        # 基于英雄属性生成加点建议
        attack_type = hero_stat.get("attack_type", "")
        primary_attr = hero_stat.get("primary_attr", "")
        roles = hero_stat.get("roles", [])

        # 生成技能加点建议
        build = self._generate_build(
            hero_name=hero_name,
            attack_type=attack_type,
            primary_attr=primary_attr,
            roles=roles,
            role=role
        )

        return build

    def _generate_build(
        self,
        hero_name: str,
        attack_type: str,
        primary_attr: str,
        roles: List[str],
        role: str
    ) -> Dict:
        """生成技能加点方案"""

        build = {
            "hero": hero_name,
            "role": role,
            "primary_attribute": primary_attr,
            "attack_type": attack_type,
            "early_game": {
                "priority": [],
                "notes": ""
            },
            "mid_game": {
                "priority": [],
                "notes": ""
            },
            "late_game": {
                "priority": [],
                "notes": ""
            },
            "talents": {
                "level_10": "",
                "level_15": "",
                "level_20": "",
                "level_25": ""
            }
        }

        # 根据角色定位给出建议
        if "Carry" in roles or role == "core":
            build["early_game"]["notes"] = "优先提升farm能力和生存技能"
            build["mid_game"]["notes"] = "提升输出技能，参与团战"
            build["late_game"]["notes"] = "最大化输出，注意站位"

        elif "Support" in roles or role == "support":
            build["early_game"]["notes"] = "优先控制技能和保命技能"
            build["mid_game"]["notes"] = "提升辅助技能等级，保护核心"
            build["late_game"]["notes"] = "提供控制和团队增益"

        elif "Offlane" in roles or role == "offlane":
            build["early_game"]["notes"] = "提升生存和消耗能力"
            build["mid_game"]["notes"] = "提升控制技能，开团能力"
            build["late_game"]["notes"] = "充当肉盾，提供控制"

        # 根据属性给出一般性建议
        attr_advice = {
            "str": "力量型英雄通常较肉，可以承受更多伤害",
            "agi": "敏捷型英雄通常依赖普攻输出，注意攻击速度",
            "int": "智力型英雄通常技能伤害高，注意蓝量管理"
        }
        build["attribute_advice"] = attr_advice.get(primary_attr, "")

        return build

    def analyze_skill_priority(
        self,
        hero_name: str,
        skill_build: List[int]
    ) -> Dict:
        """分析技能加点优先级

        Args:
            hero_name: 英雄名称
            skill_build: 技能加点顺序列表 (1-4代表QWER)

        Returns:
            Dict: 分析结果
        """
        if not skill_build:
            return {}

        # 统计各技能加点次数
        skill_counts = {}
        for skill in skill_build:
            skill_counts[skill] = skill_counts.get(skill, 0) + 1

        # 排序
        sorted_skills = sorted(
            skill_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )

        skill_names = {1: "Q", 2: "W", 3: "E", 4: "R"}

        return {
            "hero": hero_name,
            "skill_priority": [
                {"skill": skill_names.get(s, f"Skill{s}"), "levels": c}
                for s, c in sorted_skills
            ],
            "build_sequence": [skill_names.get(s, str(s)) for s in skill_build],
            "analysis": f"优先加满 {skill_names.get(sorted_skills[0][0], '主技能')} 技能"
        }
