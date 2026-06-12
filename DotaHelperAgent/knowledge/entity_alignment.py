"""实体对齐 - 统一不同数据源的实体名称"""

from typing import Dict, Optional
from utils.log_config import get_logger

logger = get_logger("entity_alignment", component="knowledge")


class EntityAlignment:
    """实体对齐类

    功能：
    - 统一不同数据源的英雄名称（英文、中文、缩写）
    - 统一不同数据源的物品名称
    - 统一不同数据源的技能名称
    """

    def __init__(self):
        """初始化实体对齐映射"""
        # 英雄名称映射（英文 -> 中文）
        self.hero_mapping = {
            # 英文全称 -> 中文
            "Phantom Assassin": "幻影刺客",
            "Juggernaut": "主宰",
            "Anti-Mage": "敌法师",
            "Sniper": "狙击手",
            "Drow Ranger": "卓尔游侠",
            "Templar Assassin": "圣堂刺客",
            "Luna": "露娜",
            "Spectre": "幽鬼",
            "Medusa": "美杜莎",
            "Terrorblade": "恐怖利刃",
            # 缩写 -> 中文
            "PA": "幻影刺客",
            "JUGG": "主宰",
            "AM": "敌法师",
            "TA": "圣堂刺客",
            "TB": "恐怖利刃",
        }

        # 物品名称映射（英文 -> 中文/缩写）
        self.item_mapping = {
            # 英文全称 -> 缩写
            "Black King Bar": "BKB",
            "Blink Dagger": "跳刀",
            "Divine Rapier": "圣剑",
            "Aghanim's Scepter": "A杖",
            "Aghanim's Shard": "碎片",
            "Observer Ward": "假眼",
            "Sentry Ward": "真眼",
            "Town Portal Scroll": "TP",
            "Magic Stick": "魔棒",
            "Magic Wand": "魔杖",
            "Power Treads": "假腿",
            "Phase Boots": "相位鞋",
            "Arcane Boots": "秘法鞋",
            "Tranquil Boots": "绿鞋",
            "Boots of Travel": "飞鞋",
        }

        # 技能名称映射
        self.ability_mapping = {
            "Coup de Grace": "恩赐解脱",
            "Blade Fury": "剑刃风暴",
            "Mana Break": "法力损毁",
            "Blink": "闪烁",
        }

        logger.info("实体对齐初始化完成")

    def align(
        self,
        entity_name: str,
        entity_type: str = "hero"
    ) -> str:
        """对齐实体名称

        Args:
            entity_name: 实体名称（英文、中文或缩写）
            entity_type: 实体类型（"hero" | "item" | "ability"）

        Returns:
            对齐后的实体名称（统一为中文或常用缩写）
        """
        if entity_type == "hero":
            mapping = self.hero_mapping
        elif entity_type == "item":
            mapping = self.item_mapping
        elif entity_type == "ability":
            mapping = self.ability_mapping
        else:
            logger.warning(f"未知的实体类型: {entity_type}")
            return entity_name

        # 查找映射
        aligned_name = mapping.get(entity_name)

        if aligned_name:
            logger.debug(f"实体对齐: {entity_name} -> {aligned_name}")
            return aligned_name
        else:
            # 如果没有映射，检查是否已经是标准名称
            if entity_name in mapping.values():
                return entity_name
            else:
                logger.warning(f"未找到实体映射: {entity_name}")
                return entity_name

    def add_mapping(
        self,
        entity_name: str,
        standard_name: str,
        entity_type: str = "hero"
    ) -> None:
        """添加实体映射

        Args:
            entity_name: 实体名称
            standard_name: 标准名称
            entity_type: 实体类型
        """
        if entity_type == "hero":
            self.hero_mapping[entity_name] = standard_name
        elif entity_type == "item":
            self.item_mapping[entity_name] = standard_name
        elif entity_type == "ability":
            self.ability_mapping[entity_name] = standard_name

        logger.info(f"添加实体映射: {entity_name} -> {standard_name}")
