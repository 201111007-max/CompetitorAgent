"""本地化工具模块 - 提供 Dota 2 英雄和物品的中英文名称映射"""

import json
import os
from typing import Dict, Optional
from pathlib import Path


class DotaLocalizer:
    """Dota 2 本地化工具类

    提供英雄和物品的中英文名称映射功能。
    数据来源: ModelScope Dota2-Pedia 数据集
    """

    _instance = None
    _heroes_cn: Dict[str, Dict[str, str]] = {}
    _items_cn: Dict[str, Dict[str, str]] = {}

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_data()
        return cls._instance

    def _load_data(self):
        """加载中英文映射数据"""
        # 获取数据文件路径
        data_dir = Path(__file__).parent.parent / "data"

        # 加载英雄中文数据
        heroes_file = data_dir / "heroes_cn.json"
        if heroes_file.exists():
            try:
                with open(heroes_file, 'r', encoding='utf-8') as f:
                    self._heroes_cn = json.load(f)
            except Exception as e:
                print(f"加载英雄中文数据失败: {e}")
                self._heroes_cn = {}
        else:
            print(f"警告: 英雄中文数据文件不存在: {heroes_file}")
            self._heroes_cn = {}

        # 加载物品中文数据
        items_file = data_dir / "items_cn.json"
        if items_file.exists():
            try:
                with open(items_file, 'r', encoding='utf-8') as f:
                    self._items_cn = json.load(f)
            except Exception as e:
                print(f"加载物品中文数据失败: {e}")
                self._items_cn = {}
        else:
            print(f"警告: 物品中文数据文件不存在: {items_file}")
            self._items_cn = {}

    def get_hero_name_cn(self, hero_id: int) -> Optional[str]:
        """获取英雄中文名称

        Args:
            hero_id: 英雄ID

        Returns:
            中文名称，如果没有则返回None
        """
        hero_data = self._heroes_cn.get(str(hero_id))
        return hero_data.get('cn') if hero_data else None

    def get_hero_name_en(self, hero_id: int) -> Optional[str]:
        """获取英雄英文名称

        Args:
            hero_id: 英雄ID

        Returns:
            英文名称，如果没有则返回None
        """
        hero_data = self._heroes_cn.get(str(hero_id))
        return hero_data.get('en') if hero_data else None

    def get_item_name_cn(self, item_id: int) -> Optional[str]:
        """获取物品中文名称

        Args:
            item_id: 物品ID

        Returns:
            中文名称，如果没有则返回None
        """
        item_data = self._items_cn.get(str(item_id))
        return item_data.get('cn') if item_data else None

    def get_item_name_en(self, item_id: int) -> Optional[str]:
        """获取物品英文名称

        Args:
            item_id: 物品ID

        Returns:
            英文名称，如果没有则返回None
        """
        item_data = self._items_cn.get(str(item_id))
        return item_data.get('en') if item_data else None

    def get_all_heroes_cn(self) -> Dict[str, Dict[str, str]]:
        """获取所有英雄的中英文映射

        Returns:
            字典，key为hero_id，value为{'cn': '中文名', 'en': '英文名'}
        """
        return self._heroes_cn.copy()

    def get_all_items_cn(self) -> Dict[str, Dict[str, str]]:
        """获取所有物品的中英文映射

        Returns:
            字典，key为item_id，value为{'cn': '中文名', 'en': '英文名'}
        """
        return self._items_cn.copy()

    def get_hero_count(self) -> int:
        """获取英雄数量"""
        return len(self._heroes_cn)

    def get_item_count(self) -> int:
        """获取物品数量"""
        return len(self._items_cn)


# 全局本地化器实例
_localizer = None


def get_localizer() -> DotaLocalizer:
    """获取全局本地化器实例"""
    global _localizer
    if _localizer is None:
        _localizer = DotaLocalizer()
    return _localizer


# 便捷函数
def get_hero_name_cn(hero_id: int) -> Optional[str]:
    """获取英雄中文名称"""
    return get_localizer().get_hero_name_cn(hero_id)


def get_item_name_cn(item_id: int) -> Optional[str]:
    """获取物品中文名称"""
    return get_localizer().get_item_name_cn(item_id)
