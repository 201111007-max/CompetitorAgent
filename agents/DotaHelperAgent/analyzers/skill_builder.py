"""技能加点建议模块 - LLM 优先，数据驱动兜底"""

from typing import Dict, List, Optional, Any

# 支持两种导入方式：包导入和直接运行
try:
    from ..utils.api_client import OpenDotaClient
    from ..core.hybrid_base import HybridAnalyzer, ExecutionSource
except ImportError:
    from utils.api_client import OpenDotaClient
    from core.hybrid_base import HybridAnalyzer, ExecutionSource


class HybridSkillBuilder(HybridAnalyzer):
    """混合模式技能加点建议器
    
    LLM 优先策略：
    1. 优先使用 LLM 根据局势和定位智能推荐加点
    2. LLM 失败时回退到基于规则的加点建议
    """
    
    def __init__(self, client: OpenDotaClient, llm_enabled: bool = False):
        """初始化混合建议器
        
        Args:
            client: OpenDota API 客户端
            llm_enabled: 是否启用 LLM
        """
        super().__init__(llm_enabled)
        self.set_data_client(client)
        self.client = client
    
    def recommend_skill_build(
        self,
        hero_name: str,
        role: str = "core",
        enemy_heroes: Optional[List[str]] = None,
        use_llm: Optional[bool] = None
    ) -> Dict[str, Any]:
        """推荐技能加点
        
        Args:
            hero_name: 英雄名称
            role: 角色定位 (core/support/offlane)
            enemy_heroes: 敌方英雄列表（用于 LLM 分析）
            use_llm: 是否使用 LLM（可选）
            
        Returns:
            Dict: 技能加点建议，包含 source 字段标识来源
        """
        input_data = {
            "hero_name": hero_name,
            "role": role,
            "enemy_heroes": enemy_heroes or []
        }
        
        return self.analyze(input_data, use_llm)
    
    def _execute_llm(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 推荐技能加点
        
        Args:
            input_data: 包含 hero_name, role, enemy_heroes
            
        Returns:
            LLM 生成的加点建议
        """
        if not self._llm_analyzer:
            raise Exception("LLM 分析器未初始化")
        
        hero_name = input_data["hero_name"]
        role = input_data["role"]
        enemy_heroes = input_data.get("enemy_heroes", [])
        
        prompt = f"""作为 Dota 2 技能加点专家，为 {hero_name}（定位：{role}）推荐技能加点顺序。

敌方阵容：{', '.join(enemy_heroes) if enemy_heroes else '未知'}

请分析：
1. 对线期应该优先加什么技能来压制/发育
2. 中期团战应该主升什么技能
3. 后期技能加点优先级
4. 天赋选择建议

请严格按照以下 JSON 格式返回：
{{
    "early_game": {{
        "priority": ["技能 1", "技能 2"],
        "notes": "前期加点理由"
    }},
    "mid_game": {{
        "priority": ["主升技能"],
        "notes": "中期加点理由"
    }},
    "late_game": {{
        "priority": ["后期技能"],
        "notes": "后期加点理由"
    }},
    "talents": {{
        "level_10": "10 级天赋选择",
        "level_15": "15 级天赋选择",
        "level_20": "20 级天赋选择",
        "level_25": "25 级天赋选择"
    }},
    "strategy_notes": "整体加点策略说明"
}}
"""
        
        response = self._llm_analyzer.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=800
        )
        
        if "error" in response:
            raise Exception(f"LLM 生成失败：{response['error']}")
        
        try:
            import json
            content = response['choices'][0]['message']['content']
            llm_build = json.loads(content)
            
            return {
                "hero": hero_name,
                "role": role,
                "build": llm_build,
                "source_detail": "llm"
            }
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            raise Exception(f"解析 LLM 响应失败：{e}")
    
    def _execute_data(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """数据驱动的技能加点建议
        
        Args:
            input_data: 包含 hero_name, role
            
        Returns:
            基于规则的技能加点
        """
        hero_name = input_data["hero_name"]
        role = input_data["role"]
        
        hero_id = self.client.hero_name_to_id(hero_name)
        if not hero_id:
            return {"hero": hero_name, "error": "英雄 ID 转换失败"}
        
        hero_stats = self.client.get_hero_stats()
        if not hero_stats:
            return {"hero": hero_name, "error": "未获取到英雄数据"}
        
        hero_stat = None
        for stat in hero_stats:
            if stat.get("id") == hero_id:
                hero_stat = stat
                break
        
        if not hero_stat:
            return {"hero": hero_name, "error": "未找到英雄数据"}
        
        attack_type = hero_stat.get("attack_type", "")
        primary_attr = hero_stat.get("primary_attr", "")
        roles = hero_stat.get("roles", [])
        
        build = self._generate_build(
            hero_name=hero_name,
            attack_type=attack_type,
            primary_attr=primary_attr,
            roles=roles,
            role=role
        )
        
        build["source_detail"] = "data"
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
        
        if "Carry" in roles or role == "core":
            build["early_game"]["notes"] = "优先提升 farm 能力和生存技能"
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
        """分析技能加点优先级"""
        if not skill_build:
            return {}
        
        skill_counts = {}
        for skill in skill_build:
            skill_counts[skill] = skill_counts.get(skill, 0) + 1
        
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


SkillBuilder = HybridSkillBuilder
