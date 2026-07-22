"""对线期分析器单元测试"""
import pytest
from unittest.mock import Mock

from post_match_review.analyzers.laning_analyzer import LaningAnalyzer
from post_match_review.domain_types.analysis import AnalysisContext, Conclusion
from post_match_review.domain_types.match_data import MatchData, PlayerData, LaneData
from post_match_review.engines.budget import IterationBudget


class TestLaningAnalyzer:
    """测试对线期分析器"""

    def _create_match_data(self) -> MatchData:
        """创建测试用比赛数据"""
        return MatchData(
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
                    last_hits=85,
                    denies=12,
                    gpm=550,
                    xpm=600,
                    hero_damage=15000,
                    tower_damage=3000,
                    is_radiant=True,
                    is_user=True,
                ),
                PlayerData(
                    account_id="200000000",
                    hero_id=44,
                    hero_name="Phantom Assassin",
                    kills=5,
                    deaths=8,
                    assists=10,
                    last_hits=60,
                    denies=5,
                    gpm=400,
                    xpm=450,
                    hero_damage=10000,
                    tower_damage=1000,
                    is_radiant=False,
                    is_user=False,
                ),
            ],
            picks_bans=[],
            lane_data=LaneData(
                player_lane={
                    "100000000": 1,
                    "200000000": 3,
                },
                lh_at_10={
                    "100000000": 85,
                    "200000000": 60,
                },
                denies_at_10={
                    "100000000": 12,
                    "200000000": 5,
                },
                hero_damage_at_10={
                    "100000000": 1500,
                    "200000000": 800,
                },
                networth_at_10={
                    "100000000": 4500,
                    "200000000": 3200,
                },
            ),
        )

    def _create_mock_llm_client(self, response: str) -> Mock:
        """创建模拟 LLM 客户端"""
        from unittest.mock import AsyncMock
        llm_client = Mock()
        llm_client.chat = AsyncMock(return_value=response)
        return llm_client

    def test_phase_name(self) -> None:
        """测试阶段名称"""
        llm_client = self._create_mock_llm_client("{}")
        analyzer = LaningAnalyzer(llm_client)
        assert analyzer.phase_name == "laning"

    def test_build_prompt_includes_lane_data(self) -> None:
        """测试提示词包含对线期数据"""
        llm_client = self._create_mock_llm_client("{}")
        analyzer = LaningAnalyzer(llm_client)

        match_data = self._create_match_data()
        budget = IterationBudget(max_iterations=3, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)

        messages = analyzer.build_prompt(match_data, context)

        assert len(messages) == 3
        # 检查 Context 层包含对线期数据
        context_content = messages[1]["content"]
        assert "对线期数据" in context_content
        assert "85" in context_content  # 补刀数
        assert "12" in context_content  # 反补数
        assert "1500" in context_content  # 英雄伤害

    def test_parse_response_json_format(self) -> None:
        """测试解析 JSON 格式响应"""
        llm_client = self._create_mock_llm_client("{}")
        analyzer = LaningAnalyzer(llm_client)

        response = """
        {
            "conclusions": [
                {
                    "title": "补刀优势",
                    "content": "Juggernaut 补刀数领先 25 个",
                    "evidence": ["85 vs 60 补刀"],
                    "impact": "high"
                },
                {
                    "title": "反补压制",
                    "content": "反补数明显优于对手",
                    "evidence": ["12 vs 5 反补"],
                    "impact": "medium"
                }
            ]
        }
        """

        conclusions = analyzer.parse_response(response)

        assert len(conclusions) == 2
        assert conclusions[0].title == "补刀优势"
        assert conclusions[0].has_evidence is True
        assert conclusions[0].impact == "high"
        assert conclusions[1].title == "反补压制"

    def test_parse_response_text_format(self) -> None:
        """测试解析文本格式响应（fallback）"""
        llm_client = self._create_mock_llm_client("{}")
        analyzer = LaningAnalyzer(llm_client)

        response = """
        对线期表现分析：

        Juggernaut 在补刀方面表现出色，10 分钟达到 85 补刀，领先对手 25 个。

        反补压制也很明显，12 个反补限制了对手的经济发育。

        英雄伤害输出方面，1500 点伤害显示出良好的对线压制能力。
        """

        conclusions = analyzer.parse_response(response)

        # 应该提取出至少 2 条结论
        assert len(conclusions) >= 2
        assert all(isinstance(c, Conclusion) for c in conclusions)

    @pytest.mark.asyncio
    async def test_analyze_end_to_end(self) -> None:
        """测试端到端分析流程"""
        response = """
        {
            "conclusions": [
                {
                    "title": "补刀优势",
                    "content": "补刀数领先 25 个",
                    "evidence": ["85 vs 60"],
                    "impact": "high"
                },
                {
                    "title": "反补压制",
                    "content": "反补数 12 vs 5",
                    "evidence": ["12 vs 5"],
                    "impact": "medium"
                },
                {
                    "title": "经济领先",
                    "content": "净经济领先 1300",
                    "evidence": ["4500 vs 3200"],
                    "impact": "high"
                }
            ]
        }
        """

        llm_client = self._create_mock_llm_client(response)
        analyzer = LaningAnalyzer(llm_client)

        match_data = self._create_match_data()
        budget = IterationBudget(max_iterations=3, max_tokens=10000)
        context = AnalysisContext(phase="laning", budget=budget)

        result = await analyzer.analyze(match_data, context)

        assert result.phase == "laning"
        assert len(result.conclusions) == 3
        assert result.confidence >= 0.6
        assert all(c.has_evidence for c in result.conclusions)

    def test_format_lane_data(self) -> None:
        """测试对线期数据格式化"""
        llm_client = self._create_mock_llm_client("{}")
        analyzer = LaningAnalyzer(llm_client)

        match_data = self._create_match_data()
        lane_data = match_data.lane_data

        formatted = analyzer._format_domain_data(match_data)

        assert "对线期数据" in formatted
        assert "Juggernaut" in formatted
        assert "Phantom Assassin" in formatted
        assert "85" in formatted
        assert "12" in formatted
        assert "1500" in formatted

    def test_get_lane_name(self) -> None:
        """测试分路名称转换"""
        llm_client = self._create_mock_llm_client("{}")
        analyzer = LaningAnalyzer(llm_client)

        assert "安全路" in analyzer._get_lane_name(1)
        assert "中路" in analyzer._get_lane_name(2)
        assert "劣势路" in analyzer._get_lane_name(3)
        assert "野区" in analyzer._get_lane_name(4)
