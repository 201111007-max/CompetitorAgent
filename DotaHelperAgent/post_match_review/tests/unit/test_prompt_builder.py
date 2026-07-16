"""提示词构建器单元测试"""
import pytest
from pathlib import Path
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.types.match_data import MatchData, PlayerData, PickBan


class TestPromptBuilder:
    """测试提示词构建器"""

    def test_build_returns_three_layer_messages(self) -> None:
        """测试构建返回三层消息"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="100000000",
                    hero_id=8,
                    hero_name="Juggernaut",
                    kills=10,
                    deaths=2,
                    assists=15,
                    last_hits=250,
                    denies=15,
                    gpm=650,
                    xpm=700,
                    hero_damage=25000,
                    tower_damage=8000,
                    is_radiant=True,
                    is_user=True,
                )
            ],
            picks_bans=[],
        )
        
        messages = builder.build(match_data, phase="laning")
        
        assert len(messages) == 3
        assert messages[0]["role"] == "system"  # Stable layer
        assert messages[1]["role"] == "user"    # Context layer
        assert messages[2]["role"] == "user"    # Volatile layer

    def test_build_stable_layer_contains_role_definition(self) -> None:
        """测试 Stable 层包含角色定义"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )
        
        messages = builder.build(match_data, phase="laning")
        stable_content = messages[0]["content"]
        
        assert "分析师" in stable_content or "Dota 2" in stable_content

    def test_build_context_layer_contains_match_info(self) -> None:
        """测试 Context 层包含比赛信息"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="100000000",
                    hero_id=8,
                    hero_name="Juggernaut",
                    kills=10,
                    deaths=2,
                    assists=15,
                    last_hits=250,
                    denies=15,
                    gpm=650,
                    xpm=700,
                    hero_damage=25000,
                    tower_damage=8000,
                    is_radiant=True,
                    is_user=True,
                )
            ],
            picks_bans=[],
        )
        
        messages = builder.build(match_data, phase="laning")
        context_content = messages[1]["content"]
        
        assert "8893253595" in context_content
        assert "1800" in context_content
        assert "Juggernaut" in context_content

    def test_build_context_layer_includes_completed_results(self) -> None:
        """测试 Context 层包含已完成结果"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )
        
        completed_results = [
            {"phase": "laning", "finding": "对线优势", "confidence": 0.8}
        ]
        
        messages = builder.build(match_data, phase="teamfight", completed_results=completed_results)
        context_content = messages[1]["content"]
        
        assert "对线优势" in context_content
        assert "0.80" in context_content or "0.8" in context_content

    def test_build_volatile_layer_contains_phase_instruction(self) -> None:
        """测试 Volatile 层包含阶段指令"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )
        
        messages = builder.build(match_data, phase="laning")
        volatile_content = messages[2]["content"]
        
        # Volatile 层应该包含分析指令
        assert len(volatile_content) > 0

    def test_build_volatile_layer_includes_iteration_feedback(self) -> None:
        """测试 Volatile 层包含迭代反馈"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )
        
        feedback = "上一轮分析不够深入，请提供更多数据支撑"
        messages = builder.build(match_data, phase="laning", iteration_feedback=feedback)
        volatile_content = messages[2]["content"]
        
        assert feedback in volatile_content or "上一轮" in volatile_content

    def test_build_with_different_phases(self) -> None:
        """测试不同阶段"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )
        
        phases = ["laning", "teamfight", "economy", "decision", "vision"]
        for phase in phases:
            messages = builder.build(match_data, phase=phase)
            assert len(messages) == 3

    def test_build_with_missing_template_uses_default(self) -> None:
        """测试模板缺失时使用默认模板"""
        builder = PromptBuilder()
        
        match_data = MatchData(
            match_id="8893253595",
            duration=1800,
            radiant_win=True,
            radiant_score=35,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
        )
        
        # 使用不存在的阶段
        messages = builder.build(match_data, phase="nonexistent_phase")
        
        # 应该使用默认模板，仍然返回 3 层
        assert len(messages) == 3
        assert len(messages[0]["content"]) > 0
