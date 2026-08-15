"""L3 技能沉淀（SkillStore）

每次分析成功后，提炼"该竞品哪个数据源对该维度更有效"为技能。
支持：
- 自动抽取：record_success() 记录成功源并累积权重
- 命中：retrieve_skills() 返回可用技能（按权重降序）
- 上限：每个竞品最多保留 skills_max 条
- 失败衰减：record_failure() 降低权重
"""
from __future__ import annotations

import logging
from pathlib import Path

from competitor_agent.interfaces.context import Skill
from competitor_agent.memory.json_store import JsonStore

logger = logging.getLogger("competitor_agent.memory.skill_store")

_MAX_SKILLS_PER_COMPETITOR = 50
_SKILL_BOOST_STEP = 1.0
_SKILL_DECAY_STEP = 0.5


class SkillStore:
    """L3 技能层（键 = competitor_name）"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        max_per_competitor: int = _MAX_SKILLS_PER_COMPETITOR,
    ) -> None:
        self._store = JsonStore("skill_store", data_dir)
        self._max_per_competitor = max_per_competitor

    def record_skill(self, skill: Skill) -> None:
        """写入一条技能（同竞品+缺口+源 合并，权重累加，method 取最新非空）"""
        competitor = skill.competitor_name
        if not competitor:
            raise ValueError("技能沉淀需要 competitor_name")
        skills = self._skills(competitor)
        # 合并：存在同 (gap, source) 则累加权重
        matched = False
        for item in skills:
            if item["gap_field"] == skill.gap_field and item["source_name"] == skill.source_name:
                item["success"] = item.get("success", True) if skill.success else False
                item["weight"] = float(item.get("weight", 0.0)) + _SKILL_BOOST_STEP
                if skill.method:
                    item["method"] = skill.method
                matched = True
                break
        if not matched:
            skills.append(
                {
                    "competitor_name": competitor,
                    "gap_field": skill.gap_field,
                    "source_name": skill.source_name,
                    "success": skill.success,
                    "weight": _SKILL_BOOST_STEP,
                    "method": skill.method,
                }
            )
        # 裁剪
        skills.sort(key=lambda s: float(s.get("weight", 0.0)), reverse=True)
        skills = skills[: self._max_per_competitor]
        self._store.put(competitor, skills)
        self._store.save()

    def record_success(
        self,
        competitor: str,
        gap_field: str,
        source_name: str,
        method: str = "",
    ) -> None:
        """分析成功后自动提炼技能（可携带成功做法 method，设计文档 35）"""
        self.record_skill(
            Skill(
                competitor_name=competitor,
                gap_field=gap_field,
                source_name=source_name,
                success=True,
                method=method,
            )
        )

    def record_failure(self, competitor: str, gap_field: str, source_name: str) -> None:
        """记录某源在该竞品维度失败，衰减权重"""
        skills = self._skills(competitor)
        updated = False
        for item in skills:
            if item["gap_field"] == gap_field and item["source_name"] == source_name:
                item["weight"] = max(0.0, float(item.get("weight", 0.0)) - _SKILL_DECAY_STEP)
                if float(item["weight"]) <= 0:
                    item["weight"] = 0.0
                updated = True
                break
        if not updated:
            skills.append(
                {
                    "competitor_name": competitor,
                    "gap_field": gap_field,
                    "source_name": source_name,
                    "success": False,
                    "weight": 0.0,
                }
            )
        self._store.put(competitor, skills)
        self._store.save()

    def retrieve_skills(self, competitor: str) -> list[Skill]:
        """取回某竞品技能（按权重降序）"""
        skills = self._skills(competitor)
        skills.sort(key=lambda s: float(s.get("weight", 0.0)), reverse=True)
        return [_skill_from_dict(s) for s in skills]

    def _skills(self, competitor: str) -> list[dict]:
        raw = self._store.get(competitor, [])
        return raw if isinstance(raw, list) else []


def _skill_from_dict(data: dict) -> Skill:
    return Skill(
        competitor_name=str(data.get("competitor_name", "")),
        gap_field=str(data.get("gap_field", "")),
        source_name=str(data.get("source_name", "")),
        success=bool(data.get("success", True)),
        weight=float(data.get("weight", 0.0)),
        method=str(data.get("method", "")),
    )