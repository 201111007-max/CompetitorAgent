"""SkillDrivenPromptBuilder 单元测试"""
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from dota_helper.analyzers.skill_driven import SkillDrivenPromptBuilder
from dota_helper.domain_types.match_data import MatchData, PlayerData
from dota_helper.domain_types.analysis import AnalysisResult


def _make_skill_definition() -> Dict[str, Any]:
    """构建测试用的技能定义"""
    return {
        "phase": "roshan_timing",
        "name": "Roshan时机分析",
        "description": "测试分析技能",
        "analysis_framework": "你是一位专业的 Dota 2 分析师，专注于 Roshan 时机分析。",
        "data_requirements": [
            {"field": "duration", "label": "比赛时长", "format": "simple"},
        ],
        "output_schema": {
            "type": "object",
            "required": ["conclusions"],
            "properties": {
                "conclusions": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
        },
        "metadata": {
            "min_confidence": 0.5,
            "expected_conclusions": 3,
        },
        "stable_layer": "{analysis_framework}\n\n输出格式要求：\n{output_schema}",
        "volatile_layer": "请分析当前比赛。\n\n可用数据：\n{formatted_data}\n\n{iteration_feedback}",
    }


def _make_match_data() -> MatchData:
    """构建测试用 MatchData"""
    return MatchData(
        match_id="12345",
        duration=2400,
        radiant_win=True,
        radiant_score=30,
        dire_score=20,
        game_mode=22,
        players=[
            PlayerData(
                account_id="100",
                hero_name="Axe",
                hero_id=1,
                kills=5,
                deaths=3,
                assists=10,
                last_hits=100,
                denies=20,
                gpm=400,
                xpm=500,
                hero_damage=5000,
                tower_damage=1000,
                is_radiant=True,
                is_user=True,
            ),
        ],
        picks_bans=[],
    )


class TestSkillDrivenPromptBuilder:
    """SkillDrivenPromptBuilder 核心功能测试"""

    def test_load_template_returns_skill_definition(self):
        """_load_template 直接返回技能定义"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)

        template = builder._load_template("roshan_timing")
        assert template is definition
        assert template["phase"] == "roshan_timing"

    def test_build_three_layer_messages(self):
        """构建三层消息列表"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)
        match_data = _make_match_data()

        messages = builder.build(
            match_data=match_data,
            phase="roshan_timing",
        )

        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "user"

    def test_stable_layer_injects_analysis_framework(self):
        """Stable 层注入 analysis_framework"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)
        match_data = _make_match_data()

        messages = builder.build(
            match_data=match_data,
            phase="roshan_timing",
        )

        stable = messages[0]["content"]
        # 应包含分析框架内容
        assert "Roshan 时机分析" in stable

    def test_stable_layer_injects_output_schema(self):
        """Stable 层注入 output_schema"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)
        match_data = _make_match_data()

        messages = builder.build(
            match_data=match_data,
            phase="roshan_timing",
        )

        stable = messages[0]["content"]
        # 应包含 JSON Schema 内容
        assert "conclusions" in stable

    def test_context_layer_includes_formatted_data(self):
        """Context 层包含 DataFormatter 输出"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)
        match_data = _make_match_data()

        messages = builder.build(
            match_data=match_data,
            phase="roshan_timing",
        )

        context = messages[1]["content"]
        # Context 层应包含比赛基本信息
        assert "比赛基本信息" in context
        # DataFormatter 应格式化了 duration 字段
        assert "比赛时长" in context

    def test_volatile_layer_injects_formatted_data(self):
        """Volatile 层注入 formatted_data"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)
        match_data = _make_match_data()

        messages = builder.build(
            match_data=match_data,
            phase="roshan_timing",
        )

        volatile = messages[2]["content"]
        # 应包含分析指令
        assert "请分析" in volatile

    def test_build_with_iteration_feedback(self):
        """构建包含迭代反馈的提示词"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)
        match_data = _make_match_data()

        messages = builder.build(
            match_data=match_data,
            phase="roshan_timing",
            iteration_feedback="上一轮置信度偏低，请加强证据支撑",
        )

        volatile = messages[2]["content"]
        assert "上一轮反馈" in volatile

    def test_build_with_completed_results(self):
        """构建包含已完成阶段结果的提示词"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)
        match_data = _make_match_data()

        completed = [
            AnalysisResult(
                phase="laning",
                conclusions=[],
                confidence=0.8,
                iterations_used=1,
                tokens_consumed=0,
                analysis_text="",
            ),
        ]

        messages = builder.build(
            match_data=match_data,
            phase="roshan_timing",
            completed_results=completed,
        )

        context = messages[1]["content"]
        assert "已完成的分析阶段" in context
        assert "laning" in context

    def test_phase_mismatch_warning(self):
        """请求 phase 与技能定义 phase 不一致时记录警告"""
        definition = _make_skill_definition()
        builder = SkillDrivenPromptBuilder(definition)

        # 请求不同 phase，应仍返回技能定义但记录警告
        template = builder._load_template("different_phase")
        assert template["phase"] == "roshan_timing"
