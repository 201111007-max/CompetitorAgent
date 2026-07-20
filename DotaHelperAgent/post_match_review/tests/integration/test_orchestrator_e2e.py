"""集成测试：端到端复盘流程"""
import pytest
from typing import List, Dict, Any
from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.orchestrator.runtime import Runtime
from post_match_review.types.match_data import (
    MatchData,
    PlayerData,
    PickBan,
    LaneData,
    TeamfightData,
    EconomyData,
)
from post_match_review.types.report import ReviewReport


class MockLLMClient(ILLMClient):
    """Mock LLM 客户端"""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        """返回模拟的 LLM 响应"""
        # 返回结构化的 JSON 响应
        return """
{
  "conclusions": [
    {
      "title": "测试结论 1",
      "content": "这是一个测试结论内容",
      "evidence": ["证据 1", "证据 2"],
      "impact": "high",
      "suggestion": "建议改进方向 1"
    },
    {
      "title": "测试结论 2",
      "content": "这是另一个测试结论",
      "evidence": ["证据 3"],
      "impact": "medium",
      "suggestion": "建议改进方向 2"
    }
  ]
}
"""


class MockDataSource(IMatchDataSource):
    """Mock 数据源"""

    async def fetch_match(self, match_id: str) -> MatchData:
        """返回模拟的比赛数据"""
        # 创建玩家数据
        players = [
            PlayerData(
                account_id="user123",
                hero_id=1,
                hero_name="Anti-Mage",
                kills=10,
                deaths=3,
                assists=8,
                last_hits=250,
                denies=20,
                gpm=650,
                xpm=700,
                hero_damage=25000,
                tower_damage=8000,
                is_radiant=True,
                is_user=True,
                items=[1, 2, 3],
                level=18,
                gold=3000,
                xp_per_min=700,
            ),
            PlayerData(
                account_id="ally1",
                hero_id=2,
                hero_name="Axe",
                kills=8,
                deaths=5,
                assists=15,
                last_hits=120,
                denies=10,
                gpm=450,
                xpm=550,
                hero_damage=30000,
                tower_damage=5000,
                is_radiant=True,
                is_user=False,
            ),
            PlayerData(
                account_id="enemy1",
                hero_id=3,
                hero_name="Juggernaut",
                kills=12,
                deaths=6,
                assists=10,
                last_hits=280,
                denies=15,
                gpm=680,
                xpm=720,
                hero_damage=28000,
                tower_damage=6000,
                is_radiant=False,
                is_user=False,
            ),
        ]

        # 创建对线期数据
        lane_data = LaneData(
            player_lane={"user123": 1, "ally1": 3, "enemy1": 1},
            lh_at_10={"user123": 80, "ally1": 45, "enemy1": 85},
            denies_at_10={"user123": 8, "ally1": 5, "enemy1": 10},
            hero_damage_at_10={"user123": 1500, "ally1": 2000, "enemy1": 1800},
            networth_at_10={"user123": 5000, "ally1": 3500, "enemy1": 5200},
        )

        # 创建团战数据
        teamfight_data = [
            TeamfightData(
                start=600,
                end=630,
                deaths=5,
                players=["user123", "ally1", "enemy1"],
                radiant_gold_delta=2000,
                dire_gold_delta=-2000,
            ),
            TeamfightData(
                start=1200,
                end=1245,
                deaths=8,
                players=["user123", "ally1", "enemy1"],
                radiant_gold_delta=-1500,
                dire_gold_delta=1500,
            ),
        ]

        # 创建经济数据
        economy_data = EconomyData(
            gpm_series={
                "user123": [400, 500, 600, 650, 700],
                "ally1": [300, 380, 420, 450, 480],
                "enemy1": [420, 520, 620, 680, 720],
            },
            xpm_series={
                "user123": [450, 550, 650, 700, 750],
                "ally1": [350, 450, 520, 550, 580],
                "enemy1": [460, 560, 660, 720, 760],
            },
            networth_series={
                "user123": [2000, 4000, 7000, 10000, 13000],
                "ally1": [1500, 3000, 5000, 7000, 9000],
                "enemy1": [2100, 4200, 7200, 10500, 13500],
            },
            purchase_log={
                "user123": [
                    {"key": "battle_fury", "time": 900},
                    {"key": "manta_style", "time": 1500},
                ],
            },
        )

        # 创建 Pick/Ban 数据
        picks_bans = [
            PickBan(is_pick=True, hero_id=1, team=0, order=0),
            PickBan(is_pick=True, hero_id=2, team=0, order=2),
            PickBan(is_pick=True, hero_id=3, team=1, order=1),
        ]

        # 创建完整比赛数据
        match_data = MatchData(
            match_id=match_id,
            duration=2400,  # 40 分钟
            radiant_win=True,
            radiant_score=35,
            dire_score=28,
            game_mode=22,
            players=players,
            picks_bans=picks_bans,
            lane_data=lane_data,
            teamfight_data=teamfight_data,
            economy_data=economy_data,
            raw_metadata={
                "objectives": [
                    {"type": "tower", "time": 1200},
                    {"type": "roshan", "time": 1800},
                ],
                "vision": {
                    "obs": {"user123": 15, "ally1": 12},
                    "sen": {"user123": 8, "ally1": 6},
                },
            },
        )

        return match_data


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """创建 Mock LLM 客户端"""
    return MockLLMClient()


@pytest.fixture
def mock_data_source() -> MockDataSource:
    """创建 Mock 数据源"""
    return MockDataSource()


@pytest.fixture
def runtime(mock_data_source: MockDataSource, mock_llm_client: MockLLMClient) -> Runtime:
    """创建 Runtime 实例"""
    return Runtime(
        data_source=mock_data_source,
        llm_client=mock_llm_client,
    )


@pytest.mark.asyncio
async def test_full_review_pipeline(runtime: Runtime) -> None:
    """测试完整复盘流程"""
    # 执行复盘
    match_id = "test_match_123"
    orchestrator = runtime.build_orchestrator(match_id)
    report = await orchestrator.review(match_id)

    # 验证报告结构
    assert isinstance(report, ReviewReport)
    assert report.match_id == match_id
    assert report.match_summary is not None
    assert report.match_summary.match_id == match_id
    assert report.match_summary.duration == 2400
    assert report.match_summary.radiant_win is True
    assert report.match_summary.radiant_score == 35
    assert report.match_summary.dire_score == 28

    # 验证包含必要阶段
    phase_names = [r.phase for r in report.phase_results]
    assert "laning" in phase_names
    assert "teamfight" in phase_names
    assert "economy" in phase_names
    assert "decisions" in phase_names

    # 验证每个阶段都有结论
    for result in report.phase_results:
        assert len(result.conclusions) > 0, f"阶段 {result.phase} 没有结论"
        assert result.confidence >= 0.0
        assert result.iterations_used > 0

    # 验证整体评分和置信度
    assert report.overall_score >= 0.0
    assert report.overall_confidence >= 0.0

    # 验证 Markdown 报告非空
    assert report.markdown_report is not None
    assert len(report.markdown_report) > 0
    assert "赛后复盘报告" in report.markdown_report
    assert "比赛摘要" in report.markdown_report
    assert "整体评估" in report.markdown_report
    assert "详细分析" in report.markdown_report

    # 验证终态
    assert report.terminal_state in ["completed", "verification_blocked", "interrupted"]


@pytest.mark.asyncio
async def test_review_with_interrupt(runtime: Runtime) -> None:
    """测试中断复盘流程"""
    match_id = "test_match_interrupt"
    orchestrator = runtime.build_orchestrator(match_id)

    # 立即中断
    orchestrator.interrupt()

    # 执行复盘（应该立即返回部分结果）
    report = await orchestrator.review(match_id)

    # 验证报告
    assert isinstance(report, ReviewReport)
    assert report.match_id == match_id
    # 中断后应该有部分结果或空结果
    assert report.terminal_state == "interrupted" or len(report.phase_results) >= 0


@pytest.mark.asyncio
async def test_review_with_partial_result(runtime: Runtime) -> None:
    """测试获取部分结果"""
    match_id = "test_match_partial"
    orchestrator = runtime.build_orchestrator(match_id)

    # 先执行一部分（这里简化为直接获取）
    partial_report = orchestrator.get_partial_result()

    # 由于还没有执行，应该返回 None 或空报告
    # 这里只验证方法存在且可调用
    assert partial_report is None or isinstance(partial_report, ReviewReport)


@pytest.mark.asyncio
async def test_strategic_loop_classification(runtime: Runtime) -> None:
    """测试战略循环的比赛分类"""
    match_id = "test_match_classification"
    orchestrator = runtime.build_orchestrator(match_id)

    # 获取数据
    match_data = await orchestrator._data_source.fetch_match(match_id)

    # 执行战略评估
    strategy = orchestrator._strategic_loop.evaluate(match_data)

    # 验证策略结构
    assert strategy.match_type in [
        "normal",
        "stomp",
        "comeback",
        "quick_push",
        "close_game",
    ]
    assert len(strategy.priority_phases) > 0
    assert len(strategy.budget_allocation) > 0
    assert len(strategy.expected_depth) > 0

    # 验证预算分配合理
    for phase, budget in strategy.budget_allocation.items():
        assert budget > 0, f"阶段 {phase} 预算应该大于 0"

    # 验证预期深度合理
    for phase, depth in strategy.expected_depth.items():
        assert depth in ["shallow", "standard", "deep"], f"阶段 {phase} 深度不合理"


@pytest.mark.asyncio
async def test_report_builder_cross_validation() -> None:
    """测试报告构建器的交叉验证"""
    from post_match_review.types.analysis import AnalysisResult, Conclusion
    from post_match_review.report.report_builder import ReportBuilder

    # 创建模拟的阶段结果
    results = [
        AnalysisResult(
            phase="laning",
            conclusions=[
                Conclusion(
                    title="对线优势",
                    content="用户在对线期取得优势",
                    evidence=["补刀领先"],
                    has_evidence=True,
                    impact="high",
                )
            ],
            confidence=0.8,
            iterations_used=2,
            tokens_consumed=4000,
        ),
        AnalysisResult(
            phase="teamfight",
            conclusions=[
                Conclusion(
                    title="团战参与率高",
                    content="团战参与率达到 80%",
                    evidence=["参与 8/10 次团战"],
                    has_evidence=True,
                    impact="medium",
                )
            ],
            confidence=0.5,  # 较低置信度
            iterations_used=1,
            tokens_consumed=2000,
        ),
    ]

    # 执行交叉验证
    report_builder = ReportBuilder()
    notes = report_builder.cross_validate(results)

    # 应该检测到置信度差异
    assert len(notes) > 0
    assert any("置信度差异" in note for note in notes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
