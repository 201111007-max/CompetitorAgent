"""直接测试第二阶段代码（绕过 pytest 的包导入问题）"""
import sys
from pathlib import Path

# 添加 DotaHelperAgent 到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# 测试导入
print("测试导入...")
from post_match_review.types.enums import BudgetDecision
from post_match_review.types.events import VerificationResult
from post_match_review.types.state import ReviewAgentState
from post_match_review.types.analysis import Conclusion
from post_match_review.engines.budget import IterationBudget
from post_match_review.engines.stop_verifier import StopVerifier
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.types.match_data import MatchData, PlayerData

print("✓ 所有模块导入成功")

# 测试 IterationBudget
print("\n测试 IterationBudget...")
budget = IterationBudget(max_iterations=15, max_tokens=100000)
assert budget.remaining_iterations == 15
assert budget.remaining_tokens == 100000

decision = budget.consume(delta_tokens=1000)
assert decision == BudgetDecision.CONTINUE
assert budget.remaining_iterations == 14
assert budget.remaining_tokens == 99000

budget.refund()
assert budget.remaining_iterations == 15
print("✓ IterationBudget 测试通过")

# 测试 StopVerifier
print("\n测试 StopVerifier...")
verifier = StopVerifier(
    required_phases=["laning", "teamfight"],
    min_confidence=0.6,
)

state = ReviewAgentState(
    match_id="8893253595",
    completed_phases=["laning", "teamfight"],
    conclusions=[
        Conclusion(phase="laning", finding="对线优势", confidence=0.8, has_evidence=True),
        Conclusion(phase="teamfight", finding="团战获胜", confidence=0.7, has_evidence=True),
    ],
    confidence=0.75,
)

result = verifier.verify(state)
assert result.passed is True
print("✓ StopVerifier 测试通过")

# 测试 PromptBuilder
print("\n测试 PromptBuilder...")
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
assert messages[0]["role"] == "system"
assert messages[1]["role"] == "user"
assert messages[2]["role"] == "user"
print("✓ PromptBuilder 测试通过")

print("\n✅ 所有第二阶段测试通过！")
