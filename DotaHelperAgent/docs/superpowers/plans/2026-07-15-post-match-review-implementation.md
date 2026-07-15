# 赛后复盘 Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现基于双循环架构的赛后复盘 Agent，支持自主多阶段分析、智能终止、技能自动沉淀

**Architecture:** 采用 Hermes + Loop Agent + Claude Code 融合架构。战略循环负责全局规划和跨阶段协调，战术循环负责单阶段深度分析。通过迭代预算控制、Stop Hooks 验证、四层记忆系统实现自主可靠的复盘分析。

**Tech Stack:** Python 3.10+, FastAPI, SQLite, Vue 3 + TypeScript, OpenDota API, LLM (DeepSeek/Ollama)

**设计文档:** `docs/POST_MATCH_REVIEW_AGENT_DESIGN.md`

---

## 实施路线图概览

| 阶段 | 核心目标 | 预估工作量 | 验收标准 |
|------|---------|-----------|---------|
| **阶段 1: 数据层** | API 扩展 + 数据模型定义 | 2-3 天 | OpenDota 数据获取完整、MatchData 模型验证通过 |
| **阶段 2: 核心骨架** | 预算控制 + 停止验证 + 提示词构建 | 3-4 天 | 单元测试覆盖率 > 80%、接口契约验证通过 |
| **阶段 3: 单阶段分析** | 战术循环 + 对线期分析器 | 3-4 天 | 端到端完成一次对线期分析，输出结构化结论 |
| **阶段 4: 全流程** | 战略循环 + 全部分析器 + 报告生成 | 5-7 天 | 端到端完成一次完整复盘，生成 Markdown 报告 |
| **阶段 5: 并行优化** | 并行子代理 + 上下文压缩 | 4-5 天 | 并行分析性能提升 > 30% |
| **阶段 6: 自我进化** | 后台审查 + 技能沉淀 + 记忆扩展 | 5-7 天 | 复盘后自动生成技能、记忆持久化验证 |
| **阶段 7: 前端集成** | API 端点 + SSE 流式 + 复盘展示 | 5-7 天 | 前端可实时展示分析进度和报告 |

**总预估工作量:** 27-37 天

---

## 阶段 1: 数据层（API 扩展 + 数据模型）

### Task 1.1: 扩展 OpenDota API 客户端

**Files:**
- Modify: `DotaHelperAgent/utils/api_client.py:240-280`
- Test: `DotaHelperAgent/tests/utils/test_api_client_review.py`

- [ ] **Step 1: 编写失败测试**

创建测试文件 `tests/utils/test_api_client_review.py`:

```python
"""OpenDota API 客户端复盘功能测试"""
import pytest
from unittest.mock import Mock, patch
from utils.api_client import OpenDotaClient


class TestOpenDotaClientReviewMethods:
    """测试复盘相关的 API 方法"""

    @pytest.fixture
    def api_client(self):
        """创建测试用 API 客户端"""
        return OpenDotaClient(api_key="test_key")

    def test_get_player_matches_success(self, api_client):
        """测试获取玩家比赛历史成功"""
        mock_response = [
            {
                "match_id": 8893253595,
                "hero_id": 1,
                "kills": 10,
                "deaths": 5,
                "assists": 15,
                "duration": 2922
            }
        ]
        
        with patch.object(api_client, '_make_request', return_value=mock_response):
            result = api_client.get_player_matches(account_id="123456789", limit=5)
            
            assert result is not None
            assert len(result) == 1
            assert result[0]["match_id"] == 8893253595

    def test_get_match_details_success(self, api_client):
        """测试获取比赛详情成功"""
        mock_response = {
            "match_id": 8893253595,
            "duration": 2922,
            "radiant_win": True,
            "players": []
        }
        
        with patch.object(api_client, '_make_request', return_value=mock_response):
            result = api_client.get_match_details(match_id="8893253595")
            
            assert result is not None
            assert result["match_id"] == 8893253595
            assert result["duration"] == 2922

    def test_get_player_matches_api_failure(self, api_client):
        """测试 API 失败时返回 None"""
        with patch.object(api_client, '_make_request', return_value=None):
            result = api_client.get_player_matches(account_id="123456789")
            assert result is None

    def test_get_match_details_api_failure(self, api_client):
        """测试 API 失败时返回 None"""
        with patch.object(api_client, '_make_request', return_value=None):
            result = api_client.get_match_details(match_id="8893253595")
            assert result is None
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd DotaHelperAgent
pytest tests/utils/test_api_client_review.py -v
```

预期输出: `FAILED` - 方法不存在

- [ ] **Step 3: 实现 API 方法**

在 `utils/api_client.py` 的 `get_hero_stats` 方法后添加:

```python
    def get_player_matches(
        self,
        account_id: str,
        limit: int = 20,
        use_cache: bool = True
    ) -> Optional[List[Dict]]:
        """获取玩家比赛历史
        
        Args:
            account_id: 玩家账户 ID
            limit: 返回比赛数量限制，默认 20
            use_cache: 是否使用缓存，默认 True
            
        Returns:
            比赛历史列表，失败返回 None
        """
        cache_key = f"player_matches_{account_id}_{limit}"
        
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        result = self._make_request(
            f"/players/{account_id}/matches",
            params={"limit": limit}
        )
        
        if result is not None and use_cache:
            self.cache.set(cache_key, result)
        
        return result

    def get_match_details(
        self,
        match_id: str,
        use_cache: bool = True
    ) -> Optional[Dict]:
        """获取比赛详情
        
        Args:
            match_id: 比赛 ID
            use_cache: 是否使用缓存，默认 True
            
        Returns:
            比赛详情字典，失败返回 None
        """
        cache_key = f"match_details_{match_id}"
        
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        result = self._make_request(f"/matches/{match_id}")
        
        if result is not None and use_cache:
            self.cache.set(cache_key, result)
        
        return result
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/utils/test_api_client_review.py -v
```

预期输出: `PASSED` - 所有测试通过

- [ ] **Step 5: 提交代码**

```bash
git add utils/api_client.py tests/utils/test_api_client_review.py
git commit -m "feat: add get_player_matches and get_match_details to OpenDota API client"
```

---

### Task 1.2: 定义复盘数据模型

**Files:**
- Create: `DotaHelperAgent/core/review/types.py`
- Test: `DotaHelperAgent/tests/core/review/test_types.py`

- [ ] **Step 1: 编写失败测试**

创建测试文件 `tests/core/review/test_types.py`:

```python
"""复盘数据模型测试"""
import pytest
from core.review.types import (
    MatchData,
    PlayerData,
    AnalysisResult,
    Conclusion,
    ReviewReport,
    BudgetDecision,
    ReviewTerminalState,
    MatchType
)


class TestDataModels:
    """测试数据模型"""

    def test_match_data_creation(self):
        """测试 MatchData 创建"""
        match_data = MatchData(
            match_id="8893253595",
            duration=2922,
            radiant_win=True,
            radiant_score=32,
            dire_score=58,
            game_mode=22,
            players=[],
            picks_bans=[]
        )
        
        assert match_data.match_id == "8893253595"
        assert match_data.duration == 2922
        assert match_data.radiant_win is True

    def test_player_data_creation(self):
        """测试 PlayerData 创建"""
        player = PlayerData(
            account_id="123456789",
            hero_id=1,
            hero_name="Anti-Mage",
            kills=10,
            deaths=5,
            assists=15,
            last_hits=250,
            denies=20,
            gpm=650,
            xpm=700,
            hero_damage=25000,
            tower_damage=8000,
            is_radiant=True,
            is_user=True
        )
        
        assert player.hero_name == "Anti-Mage"
        assert player.kills == 10
        assert player.is_user is True

    def test_conclusion_creation(self):
        """测试 Conclusion 创建"""
        conclusion = Conclusion(
            title="对线期补刀效率低",
            content="前 10 分钟补刀数低于分段位平均值",
            evidence=["last_hits=80", "expected=120"],
            has_evidence=True,
            impact="high",
            suggestion="加强补刀练习"
        )
        
        assert conclusion.title == "对线期补刀效率低"
        assert conclusion.has_evidence is True
        assert conclusion.impact == "high"

    def test_analysis_result_creation(self):
        """测试 AnalysisResult 创建"""
        conclusion = Conclusion(
            title="测试结论",
            content="测试内容",
            evidence=["evidence1"],
            has_evidence=True,
            impact="medium",
            suggestion=None
        )
        
        result = AnalysisResult(
            phase="laning",
            conclusions=[conclusion],
            confidence=0.8,
            iterations_used=2,
            tokens_consumed=1500,
            analysis_text="## 对线期分析\n测试分析内容"
        )
        
        assert result.phase == "laning"
        assert result.confidence == 0.8
        assert len(result.conclusions) == 1


class TestEnums:
    """测试枚举类型"""

    def test_budget_decision_values(self):
        """测试 BudgetDecision 枚举值"""
        assert BudgetDecision.CONTINUE.value == "continue"
        assert BudgetDecision.STOP_BUDGET_USED.value == "stop_budget_used"
        assert BudgetDecision.STOP_DIMINISHING.value == "stop_diminishing"

    def test_review_terminal_state_values(self):
        """测试 ReviewTerminalState 枚举值"""
        assert ReviewTerminalState.COMPLETED.value == "completed"
        assert ReviewTerminalState.MAX_ITERATIONS.value == "max_iterations"
        assert ReviewTerminalState.INTERRUPTED.value == "interrupted"

    def test_match_type_values(self):
        """测试 MatchType 枚举值"""
        assert MatchType.NORMAL.value == "normal"
        assert MatchType.STOMP.value == "stomp"
        assert MatchType.COMEBACK.value == "comeback"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/core/review/test_types.py -v
```

预期输出: `FAILED` - 模块不存在

- [ ] **Step 3: 创建目录结构**

```bash
mkdir -p DotaHelperAgent/core/review
touch DotaHelperAgent/core/review/__init__.py
```

- [ ] **Step 4: 实现数据模型**

创建 `core/review/types.py`:

```python
"""复盘 Agent 类型定义"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


class BudgetDecision(Enum):
    """预算决策"""
    CONTINUE = "continue"
    STOP_BUDGET_USED = "stop_budget_used"
    STOP_TOKEN_LIMIT = "stop_token_limit"
    STOP_DIMINISHING = "stop_diminishing"


class ReviewTerminalState(Enum):
    """复盘终态"""
    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    BUDGET_EXHAUSTED = "budget_exhausted"
    VERIFICATION_BLOCKED = "verification_blocked"
    INTERRUPTED = "interrupted"


class ReviewContinueState(Enum):
    """复盘继续态"""
    NEXT_PHASE = "next_phase"
    LOW_CONFIDENCE = "low_confidence"
    VERIFICATION_RETRY = "verification_retry"
    TOKEN_BUDGET_OK = "token_budget_ok"


class MatchType(Enum):
    """比赛类型"""
    NORMAL = "normal"
    STOMP = "stomp"
    COMEBACK = "comeback"
    QUICK_PUSH = "quick_push"
    CLOSE_GAME = "close_game"


@dataclass
class PlayerData:
    """玩家数据"""
    account_id: str
    hero_id: int
    hero_name: str
    kills: int
    deaths: int
    assists: int
    last_hits: int
    denies: int
    gpm: int
    xpm: int
    hero_damage: int
    tower_damage: int
    is_radiant: bool
    is_user: bool


@dataclass
class MatchData:
    """结构化比赛数据"""
    match_id: str
    duration: int
    radiant_win: bool
    radiant_score: int
    dire_score: int
    game_mode: int
    players: List[PlayerData]
    picks_bans: List[Dict[str, Any]]
    lane_data: Optional[Dict[str, Any]] = None
    teamfight_data: Optional[List[Dict[str, Any]]] = None
    economy_data: Optional[Dict[str, Any]] = None


@dataclass
class Conclusion:
    """单条分析结论"""
    title: str
    content: str
    evidence: List[str]
    has_evidence: bool
    impact: str
    suggestion: Optional[str] = None


@dataclass
class AnalysisResult:
    """单个分析阶段的结果"""
    phase: str
    conclusions: List[Conclusion]
    confidence: float
    iterations_used: int
    tokens_consumed: int
    analysis_text: str


@dataclass
class ReviewReport:
    """完整复盘报告"""
    match_id: str
    match_summary: Dict[str, Any]
    phase_results: List[AnalysisResult]
    overall_score: float
    overall_confidence: float
    key_findings: List[str]
    improvement_areas: List[str]
    markdown_report: str
    terminal_state: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/core/review/test_types.py -v
```

预期输出: `PASSED` - 所有测试通过

- [ ] **Step 6: 提交代码**

```bash
git add core/review/ tests/core/review/
git commit -m "feat: add review data models and enums"
```

---

### Task 1.3: 实现比赛数据解析器

**Files:**
- Create: `DotaHelperAgent/core/review/data_parser.py`
- Test: `DotaHelperAgent/tests/core/review/test_data_parser.py`

- [ ] **Step 1: 编写失败测试**

创建测试文件 `tests/core/review/test_data_parser.py`:

```python
"""比赛数据解析器测试"""
import pytest
from core.review.data_parser import MatchDataParser
from core.review.types import MatchData, PlayerData


class TestMatchDataParser:
    """测试比赛数据解析器"""

    @pytest.fixture
    def parser(self):
        """创建解析器实例"""
        return MatchDataParser()

    @pytest.fixture
    def sample_match_data(self):
        """示例比赛数据"""
        return {
            "match_id": 8893253595,
            "duration": 2922,
            "radiant_win": True,
            "radiant_score": 32,
            "dire_score": 58,
            "game_mode": 22,
            "players": [
                {
                    "account_id": 123456789,
                    "hero_id": 1,
                    "kills": 10,
                    "deaths": 5,
                    "assists": 15,
                    "last_hits": 250,
                    "denies": 20,
                    "gold_per_min": 650,
                    "xp_per_min": 700,
                    "hero_damage": 25000,
                    "tower_damage": 8000,
                    "isRadiant": True,
                    "account_id": 123456789
                }
            ],
            "picks_bans": []
        }

    def test_parse_match_data_success(self, parser, sample_match_data):
        """测试解析比赛数据成功"""
        result = parser.parse(sample_match_data, user_account_id="123456789")
        
        assert result is not None
        assert isinstance(result, MatchData)
        assert result.match_id == "8893253595"
        assert result.duration == 2922
        assert result.radiant_win is True
        assert len(result.players) == 1

    def test_parse_player_data(self, parser, sample_match_data):
        """测试解析玩家数据"""
        result = parser.parse(sample_match_data, user_account_id="123456789")
        
        player = result.players[0]
        assert isinstance(player, PlayerData)
        assert player.hero_id == 1
        assert player.kills == 10
        assert player.gpm == 650
        assert player.is_user is True

    def test_parse_match_data_invalid_input(self, parser):
        """测试解析无效输入"""
        result = parser.parse(None, user_account_id="123456789")
        assert result is None

    def test_parse_match_data_missing_fields(self, parser):
        """测试解析缺失字段的比赛数据"""
        invalid_data = {"match_id": 123}
        result = parser.parse(invalid_data, user_account_id="123456789")
        assert result is None
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/core/review/test_data_parser.py -v
```

预期输出: `FAILED` - 模块不存在

- [ ] **Step 3: 实现数据解析器**

创建 `core/review/data_parser.py`:

```python
"""比赛数据解析器"""
from typing import Dict, Any, Optional, List
from .types import MatchData, PlayerData
from utils.log_config import get_logger

logger = get_logger("data_parser", component="review")


class MatchDataParser:
    """比赛数据解析器
    
    将 OpenDota API 返回的原始数据解析为结构化的 MatchData 对象
    """

    def parse(
        self,
        raw_data: Optional[Dict[str, Any]],
        user_account_id: str
    ) -> Optional[MatchData]:
        """解析比赛数据
        
        Args:
            raw_data: OpenDota API 返回的原始数据
            user_account_id: 目标用户的账户 ID
            
        Returns:
            解析后的 MatchData，失败返回 None
        """
        if not raw_data:
            logger.warning("比赛数据为空")
            return None
        
        try:
            # 验证必要字段
            required_fields = ["match_id", "duration", "radiant_win", "players"]
            for field in required_fields:
                if field not in raw_data:
                    logger.error(f"比赛数据缺少必要字段: {field}")
                    return None
            
            # 解析玩家数据
            players = self._parse_players(
                raw_data.get("players", []),
                user_account_id
            )
            
            # 构建 MatchData
            match_data = MatchData(
                match_id=str(raw_data["match_id"]),
                duration=raw_data["duration"],
                radiant_win=raw_data["radiant_win"],
                radiant_score=raw_data.get("radiant_score", 0),
                dire_score=raw_data.get("dire_score", 0),
                game_mode=raw_data.get("game_mode", 0),
                players=players,
                picks_bans=raw_data.get("picks_bans", []),
                lane_data=raw_data.get("lane_data"),
                teamfight_data=raw_data.get("teamfight_data"),
                economy_data=raw_data.get("economy_data")
            )
            
            logger.info(f"比赛数据解析成功: match_id={match_data.match_id}")
            return match_data
            
        except Exception as e:
            logger.error(f"比赛数据解析失败: {e}")
            return None

    def _parse_players(
        self,
        raw_players: List[Dict[str, Any]],
        user_account_id: str
    ) -> List[PlayerData]:
        """解析玩家数据
        
        Args:
            raw_players: 原始玩家数据列表
            user_account_id: 目标用户账户 ID
            
        Returns:
            解析后的 PlayerData 列表
        """
        players = []
        
        for raw_player in raw_players:
            try:
                player = PlayerData(
                    account_id=str(raw_player.get("account_id", "")),
                    hero_id=raw_player.get("hero_id", 0),
                    hero_name=raw_player.get("hero_name", "Unknown"),
                    kills=raw_player.get("kills", 0),
                    deaths=raw_player.get("deaths", 0),
                    assists=raw_player.get("assists", 0),
                    last_hits=raw_player.get("last_hits", 0),
                    denies=raw_player.get("denies", 0),
                    gpm=raw_player.get("gold_per_min", 0),
                    xpm=raw_player.get("xp_per_min", 0),
                    hero_damage=raw_player.get("hero_damage", 0),
                    tower_damage=raw_player.get("tower_damage", 0),
                    is_radiant=raw_player.get("isRadiant", False),
                    is_user=str(raw_player.get("account_id")) == user_account_id
                )
                players.append(player)
            except Exception as e:
                logger.warning(f"解析玩家数据失败: {e}")
                continue
        
        return players
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/core/review/test_data_parser.py -v
```

预期输出: `PASSED` - 所有测试通过

- [ ] **Step 5: 提交代码**

```bash
git add core/review/data_parser.py tests/core/review/test_data_parser.py
git commit -m "feat: add match data parser for review agent"
```

---

### Task 1.4: 阶段 1 验收测试

- [ ] **Step 1: 运行所有阶段 1 测试**

```bash
pytest tests/utils/test_api_client_review.py tests/core/review/ -v
```

预期输出: 所有测试通过

- [ ] **Step 2: 验证 API 集成**

创建集成测试脚本 `scripts/test_review_api_integration.py`:

```python
"""复盘 API 集成测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.api_client import OpenDotaClient
from core.review.data_parser import MatchDataParser


def test_api_integration():
    """测试 API 集成"""
    # 创建客户端
    client = OpenDotaClient()
    
    # 测试获取比赛详情（使用已知的比赛 ID）
    match_id = "8893253595"
    print(f"获取比赛详情: {match_id}")
    raw_data = client.get_match_details(match_id)
    
    if raw_data is None:
        print("❌ API 调用失败")
        return False
    
    print(f"✅ API 调用成功，比赛时长: {raw_data.get('duration')}s")
    
    # 测试数据解析
    parser = MatchDataParser()
    match_data = parser.parse(raw_data, user_account_id="123456789")
    
    if match_data is None:
        print("❌ 数据解析失败")
        return False
    
    print(f"✅ 数据解析成功")
    print(f"   - 比赛 ID: {match_data.match_id}")
    print(f"   - 时长: {match_data.duration}s")
    print(f"   - 结果: {'天辉胜利' if match_data.radiant_win else '夜魇胜利'}")
    print(f"   - 玩家数: {len(match_data.players)}")
    
    return True


if __name__ == "__main__":
    success = test_api_integration()
    sys.exit(0 if success else 1)
```

- [ ] **Step 3: 运行集成测试**

```bash
python scripts/test_review_api_integration.py
```

预期输出: 所有步骤成功

- [ ] **Step 4: 提交集成测试**

```bash
git add scripts/test_review_api_integration.py
git commit -m "test: add stage 1 integration test for review API"
```

---

## 阶段 2: 核心骨架（预算控制 + 停止验证 + 提示词构建）

### Task 2.1: 实现迭代预算控制器

**Files:**
- Create: `DotaHelperAgent/core/review/budget.py`
- Test: `DotaHelperAgent/tests/core/review/test_budget.py`

- [ ] **Step 1: 编写失败测试**

创建测试文件 `tests/core/review/test_budget.py`:

```python
"""迭代预算控制器测试"""
import pytest
from core.review.budget import ReviewIterationBudget
from core.review.types import BudgetDecision


class TestReviewIterationBudget:
    """测试迭代预算控制器"""

    def test_budget_creation(self):
        """测试预算控制器创建"""
        budget = ReviewIterationBudget(max_iterations=10, max_tokens=10000)
        
        assert budget.remaining_iterations == 10
        assert budget.remaining_tokens == 10000

    def test_consume_continue(self):
        """测试消费预算 - 继续"""
        budget = ReviewIterationBudget(max_iterations=10, max_tokens=10000)
        
        decision = budget.consume(delta_tokens=500)
        
        assert decision == BudgetDecision.CONTINUE
        assert budget.remaining_iterations == 9

    def test_consume_budget_exhausted(self):
        """测试消费预算 - 迭代次数耗尽"""
        budget = ReviewIterationBudget(max_iterations=2, max_tokens=10000)
        
        budget.consume(delta_tokens=100)
        budget.consume(delta_tokens=100)
        decision = budget.consume(delta_tokens=100)
        
        assert decision == BudgetDecision.STOP_BUDGET_USED

    def test_consume_token_limit(self):
        """测试消费预算 - Token 达到阈值"""
        budget = ReviewIterationBudget(max_iterations=10, max_tokens=1000)
        
        # 消耗 90% Token
        budget.consume(delta_tokens=900)
        decision = budget.consume(delta_tokens=100)
        
        assert decision == BudgetDecision.STOP_TOKEN_LIMIT

    def test_consume_diminishing_returns(self):
        """测试消费预算 - 边际收益递减"""
        budget = ReviewIterationBudget(max_iterations=10, max_tokens=10000)
        
        # 前 3 次正常消耗
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        budget.consume(delta_tokens=1000)
        
        # 连续两次增量 < 500
        budget.consume(delta_tokens=400)
        decision = budget.consume(delta_tokens=300)
        
        assert decision == BudgetDecision.STOP_DIMINISHING

    def test_refund(self):
        """测试退还预算"""
        budget = ReviewIterationBudget(max_iterations=5, max_tokens=10000)
        
        budget.consume(delta_tokens=100)
        budget.consume(delta_tokens=100)
        
        assert budget.remaining_iterations == 3
        
        budget.refund()
        
        assert budget.remaining_iterations == 4

    def test_refund_cannot_go_negative(self):
        """测试退还预算不能为负"""
        budget = ReviewIterationBudget(max_iterations=5, max_tokens=10000)
        
        budget.refund()
        budget.refund()
        
        assert budget.remaining_iterations == 5  # 不能超过最大值
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/core/review/test_budget.py -v
```

预期输出: `FAILED` - 模块不存在

- [ ] **Step 3: 实现预算控制器**

创建 `core/review/budget.py`:

```python
"""迭代预算控制器"""
from threading import Lock
from typing import Optional
from .types import BudgetDecision
from utils.log_config import get_logger

logger = get_logger("budget", component="review")


class ReviewIterationBudget:
    """复盘迭代预算控制器
    
    融合 Hermes 令牌桶 + Claude Code 边际递减检测
    """

    COMPLETION_THRESHOLD = 0.9
    DIMINISHING_THRESHOLD = 500
    MIN_CONTINUATIONS = 3

    def __init__(self, max_iterations: int, max_tokens: int = 100_000):
        """初始化预算控制器
        
        Args:
            max_iterations: 最大迭代次数
            max_tokens: 最大 Token 消耗
        """
        self._max_iterations = max_iterations
        self._used_iterations = 0
        self._lock = Lock()
        
        self._max_tokens = max_tokens
        self._used_tokens = 0
        self._continuation_count = 0
        self._last_delta_tokens = 0

    def consume(self, delta_tokens: int = 0) -> BudgetDecision:
        """消费一个迭代配额
        
        Args:
            delta_tokens: 本轮消耗的 token 数
            
        Returns:
            BudgetDecision: 预算决策
        """
        with self._lock:
            # 1. 检查迭代次数上限
            if self._used_iterations >= self._max_iterations:
                logger.debug("预算耗尽: 迭代次数达到上限")
                return BudgetDecision.STOP_BUDGET_USED
            
            # 2. 检查 Token 完成阈值
            self._used_tokens += delta_tokens
            if self._used_tokens >= self._max_tokens * self.COMPLETION_THRESHOLD:
                logger.debug(f"预算耗尽: Token 达到阈值 {self.COMPLETION_THRESHOLD}")
                return BudgetDecision.STOP_TOKEN_LIMIT
            
            # 3. 边际收益递减检测
            if (self._continuation_count >= self.MIN_CONTINUATIONS and
                delta_tokens < self.DIMINISHING_THRESHOLD and
                self._last_delta_tokens < self.DIMINISHING_THRESHOLD):
                logger.debug("边际收益递减: 连续两次增量低于阈值")
                return BudgetDecision.STOP_DIMINISHING
            
            # 4. 通过，记录状态
            self._used_iterations += 1
            self._continuation_count += 1
            self._last_delta_tokens = delta_tokens
            
            logger.debug(
                f"预算消费: iterations={self._used_iterations}/{self._max_iterations}, "
                f"tokens={self._used_tokens}/{self._max_tokens}"
            )
            
            return BudgetDecision.CONTINUE

    def refund(self) -> None:
        """退还一个迭代配额"""
        with self._lock:
            if self._used_iterations > 0:
                self._used_iterations -= 1
                logger.debug(f"预算退还: remaining={self._used_iterations}")

    @property
    def remaining_iterations(self) -> int:
        """剩余迭代次数"""
        return self._max_iterations - self._used_iterations

    @property
    def remaining_tokens(self) -> int:
        """剩余 token 配额"""
        return self._max_tokens - self._used_tokens
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/core/review/test_budget.py -v
```

预期输出: `PASSED` - 所有测试通过

- [ ] **Step 5: 提交代码**

```bash
git add core/review/budget.py tests/core/review/test_budget.py
git commit -m "feat: add iteration budget controller with diminishing returns detection"
```

---

### Task 2.2: 实现停止验证器

**Files:**
- Create: `DotaHelperAgent/core/review/stop_verifier.py`
- Test: `DotaHelperAgent/tests/core/review/test_stop_verifier.py`

- [ ] **Step 1: 编写失败测试**

创建测试文件 `tests/core/review/test_stop_verifier.py`:

```python
"""停止验证器测试"""
import pytest
from core.review.stop_verifier import ReviewStopVerifier
from core.review.state import ReviewAgentState
from core.review.types import Conclusion, VerificationResult


class TestReviewStopVerifier:
    """测试停止验证器"""

    @pytest.fixture
    def verifier(self):
        """创建验证器实例"""
        return ReviewStopVerifier()

    @pytest.fixture
    def complete_state(self):
        """创建完整的 Agent 状态"""
        state = ReviewAgentState(match_id="8893253595")
        state.completed_phases = ["laning", "teamfight", "economy", "decisions"]
        state.conclusions = [
            Conclusion(
                title="测试结论",
                content="测试内容",
                evidence=["evidence1"],
                has_evidence=True,
                impact="medium",
                suggestion=None
            )
        ]
        state.confidence = 0.8
        return state

    def test_verify_all_checks_pass(self, verifier, complete_state):
        """测试所有检查通过"""
        result = verifier.verify(complete_state)
        
        assert result.passed is True
        assert len(result.blocking_reasons) == 0

    def test_verify_missing_phases(self, verifier):
        """测试缺少分析阶段"""
        state = ReviewAgentState(match_id="8893253595")
        state.completed_phases = ["laning"]  # 缺少其他阶段
        
        result = verifier.verify(state)
        
        assert result.passed is False
        assert any("缺少分析阶段" in reason for reason in result.blocking_reasons)

    def test_verify_no_evidence(self, verifier):
        """测试结论缺少数据支撑"""
        state = ReviewAgentState(match_id="8893253595")
        state.completed_phases = ["laning", "teamfight", "economy", "decisions"]
        state.conclusions = [
            Conclusion(
                title="测试结论",
                content="测试内容",
                evidence=[],
                has_evidence=False,  # 无数据支撑
                impact="medium",
                suggestion=None
            )
        ]
        state.confidence = 0.8
        
        result = verifier.verify(state)
        
        assert result.passed is False
        assert any("缺少数据支撑" in reason for reason in result.blocking_reasons)

    def test_verify_low_confidence(self, verifier):
        """测试置信度不足"""
        state = ReviewAgentState(match_id="8893253595")
        state.completed_phases = ["laning", "teamfight", "economy", "decisions"]
        state.conclusions = []
        state.confidence = 0.4  # 低于阈值 0.6
        
        result = verifier.verify(state)
        
        assert result.passed is False
        assert any("置信度" in reason for reason in result.blocking_reasons)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/core/review/test_stop_verifier.py -v
```

预期输出: `FAILED` - 模块不存在

- [ ] **Step 3: 创建状态管理模块**

创建 `core/review/state.py`:

```python
"""复盘 Agent 状态管理"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .types import MatchData, AnalysisResult, Conclusion


@dataclass
class ReviewAgentState:
    """复盘 Agent 状态"""
    match_id: str
    match_data: Optional[MatchData] = None
    completed_phases: List[str] = field(default_factory=list)
    conclusions: List[Conclusion] = field(default_factory=list)
    confidence: float = 0.0
    is_interrupted: bool = False
    total_iterations: int = 0
    total_tokens: int = 0

    def add_phase_result(self, result: AnalysisResult) -> None:
        """添加阶段分析结果"""
        self.completed_phases.append(result.phase)
        self.conclusions.extend(result.conclusions)
        self.total_iterations += result.iterations_used
        self.total_tokens += result.tokens_consumed
        
        # 更新整体置信度（加权平均）
        if self.completed_phases:
            total_confidence = sum(
                r.confidence for r in [result]
            )
            self.confidence = total_confidence / len(self.completed_phases)
```

- [ ] **Step 4: 实现停止验证器**

创建 `core/review/stop_verifier.py`:

```python
"""停止验证器"""
from typing import List
from dataclasses import dataclass, field
from .state import ReviewAgentState
from utils.log_config import get_logger

logger = get_logger("stop_verifier", component="review")


@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool
    blocking_reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class ReviewStopVerifier:
    """复盘停止验证器
    
    融合 Claude Code Stop Hooks + Hermes verification_stop
    """

    REQUIRED_PHASES = ["laning", "teamfight", "economy", "decisions"]
    MIN_CONFIDENCE = 0.6

    def verify(self, state: ReviewAgentState) -> VerificationResult:
        """验证是否满足终止条件
        
        Args:
            state: 当前 Agent 状态
            
        Returns:
            VerificationResult: 验证结果
        """
        blocking = []
        suggestions = []
        
        # 检查 1: 必要分析阶段是否完成
        missing_phases = [
            p for p in self.REQUIRED_PHASES
            if p not in state.completed_phases
        ]
        if missing_phases:
            blocking.append(f"缺少分析阶段: {missing_phases}")
            suggestions.append(f"请补充分析: {', '.join(missing_phases)}")
        
        # 检查 2: 结论是否有数据支撑
        for conclusion in state.conclusions:
            if not conclusion.has_evidence:
                blocking.append(f"结论 '{conclusion.title}' 缺少数据支撑")
                suggestions.append(f"请为 '{conclusion.title}' 提供具体数据引用")
        
        # 检查 3: 置信度是否达标
        if state.confidence < self.MIN_CONFIDENCE:
            blocking.append(
                f"整体置信度 {state.confidence:.2f} 低于阈值 {self.MIN_CONFIDENCE}"
            )
            suggestions.append("请补充关键数据或降低分析粒度")
        
        passed = len(blocking) == 0
        
        if passed:
            logger.info("停止验证通过")
        else:
            logger.warning(f"停止验证未通过: {blocking}")
        
        return VerificationResult(
            passed=passed,
            blocking_reasons=blocking,
            suggestions=suggestions
        )
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/core/review/test_stop_verifier.py -v
```

预期输出: `PASSED` - 所有测试通过

- [ ] **Step 6: 提交代码**

```bash
git add core/review/stop_verifier.py core/review/state.py tests/core/review/test_stop_verifier.py
git commit -m "feat: add stop verifier with phase, evidence, and confidence checks"
```

---

### Task 2.3: 实现提示词构建器

**Files:**
- Create: `DotaHelperAgent/core/review/prompt_builder.py`
- Test: `DotaHelperAgent/tests/core/review/test_prompt_builder.py`

- [ ] **Step 1: 编写失败测试**

创建测试文件 `tests/core/review/test_prompt_builder.py`:

```python
"""提示词构建器测试"""
import pytest
from core.review.prompt_builder import ReviewPromptBuilder
from core.review.types import MatchData, PlayerData, AnalysisResult, Conclusion


class TestReviewPromptBuilder:
    """测试提示词构建器"""

    @pytest.fixture
    def builder(self):
        """创建构建器实例"""
        return ReviewPromptBuilder()

    @pytest.fixture
    def sample_match_data(self):
        """示例比赛数据"""
        return MatchData(
            match_id="8893253595",
            duration=2922,
            radiant_win=True,
            radiant_score=32,
            dire_score=58,
            game_mode=22,
            players=[
                PlayerData(
                    account_id="123456789",
                    hero_id=1,
                    hero_name="Anti-Mage",
                    kills=10,
                    deaths=5,
                    assists=15,
                    last_hits=250,
                    denies=20,
                    gpm=650,
                    xpm=700,
                    hero_damage=25000,
                    tower_damage=8000,
                    is_radiant=True,
                    is_user=True
                )
            ],
            picks_bans=[]
        )

    def test_build_stable_layer(self, builder):
        """测试构建稳定层"""
        messages = builder.build_stable_layer()
        
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "分析师" in messages[0]["content"]

    def test_build_context_layer(self, builder, sample_match_data):
        """测试构建上下文层"""
        messages = builder.build_context_layer(sample_match_data, [])
        
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "8893253595" in messages[0]["content"]
        assert "Anti-Mage" in messages[0]["content"]

    def test_build_full_prompt(self, builder, sample_match_data):
        """测试构建完整提示词"""
        messages = builder.build(sample_match_data, [])
        
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_build_with_phase_results(self, builder, sample_match_data):
        """测试包含阶段结果的提示词构建"""
        phase_results = [
            AnalysisResult(
                phase="laning",
                conclusions=[
                    Conclusion(
                        title="对线期表现良好",
                        content="补刀效率高于平均值",
                        evidence=["last_hits=250"],
                        has_evidence=True,
                        impact="medium",
                        suggestion=None
                    )
                ],
                confidence=0.8,
                iterations_used=2,
                tokens_consumed=1500,
                analysis_text="## 对线期分析\n补刀效率良好"
            )
        ]
        
        messages = builder.build(sample_match_data, phase_results)
        
        assert len(messages) == 2
        assert "对线期分析" in messages[1]["content"]
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/core/review/test_prompt_builder.py -v
```

预期输出: `FAILED` - 模块不存在

- [ ] **Step 3: 实现提示词构建器**

创建 `core/review/prompt_builder.py`:

```python
"""提示词构建器"""
from typing import List, Dict, Any, Optional
from .types import MatchData, AnalysisResult
from utils.log_config import get_logger

logger = get_logger("prompt_builder", component="review")


class ReviewPromptBuilder:
    """复盘提示词构建器
    
    融合 Claude Code Dream 整合模式 + Hermes 三层分离
    """

    def build_stable_layer(self) -> List[Dict[str, str]]:
        """构建稳定层: 分析角色和指令
        
        Returns:
            消息列表
        """
        return [{
            "role": "system",
            "content": """你是一位专业的 Dota 2 赛后复盘分析师。

## 分析框架
1. **对线期分析**（0-10 分钟）
   - 补刀效率评估（last_hits/denies vs 理论值）
   - 消耗换血质量
   - 神符利用率

2. **团战执行分析**（10-25 分钟）
   - 团战参与率
   - 技能释放时机评估
   - 走位和站位分析

3. **经济效率分析**
   - GPM/XPM 曲线 vs 分段位均值
   - 装备购买效率（空闲时间占比）
   - 关键装备时间节点

4. **关键决策点分析**
   - Roshan 时机选择
   - 推塔节奏
   - 团战发起/撤退决策

## 输出要求
- 每个结论必须引用具体数据
- 改进建议必须具体可执行
- 使用 Markdown 格式
- 包含评分（1-10）和置信度"""
        }]

    def build_context_layer(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult]
    ) -> List[Dict[str, str]]:
        """构建上下文层: 比赛数据 + 已有分析结果
        
        Args:
            match_data: 比赛数据
            phase_results: 已完成的分析结果
            
        Returns:
            消息列表
        """
        parts = []
        
        # 比赛基本信息
        user_player = next((p for p in match_data.players if p.is_user), None)
        hero_name = user_player.hero_name if user_player else "未知"
        
        parts.append(f"# 比赛基本信息\n"
                     f"- 比赛 ID: {match_data.match_id}\n"
                     f"- 时长: {match_data.duration // 60} 分钟\n"
                     f"- 结果: {'天辉胜利' if match_data.radiant_win else '夜魇胜利'}\n"
                     f"- 比分: {match_data.radiant_score}:{match_data.dire_score}\n"
                     f"- 英雄: {hero_name}")
        
        # 玩家数据
        if user_player:
            parts.append(f"\n# 玩家数据\n"
                         f"- KDA: {user_player.kills}/{user_player.deaths}/{user_player.assists}\n"
                         f"- 补刀: {user_player.last_hits}/{user_player.denies}\n"
                         f"- GPM/XPM: {user_player.gpm}/{user_player.xpm}\n"
                         f"- 英雄伤害: {user_player.hero_damage}\n"
                         f"- 建筑伤害: {user_player.tower_damage}")
        
        # 已有分析结果
        if phase_results:
            parts.append("\n# 已完成的分析\n")
            for pr in phase_results:
                parts.append(f"## {pr.phase}\n{pr.analysis_text}")
        
        return [{
            "role": "user",
            "content": "\n".join(parts)
        }]

    def build(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult]
    ) -> List[Dict[str, str]]:
        """构建完整提示词（三层结构）
        
        Args:
            match_data: 比赛数据
            phase_results: 已完成的分析结果
            
        Returns:
            消息列表
        """
        messages = []
        messages.extend(self.build_stable_layer())
        messages.extend(self.build_context_layer(match_data, phase_results))
        
        logger.debug(f"提示词构建完成: {len(messages)} 条消息")
        return messages
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/core/review/test_prompt_builder.py -v
```

预期输出: `PASSED` - 所有测试通过

- [ ] **Step 5: 提交代码**

```bash
git add core/review/prompt_builder.py tests/core/review/test_prompt_builder.py
git commit -m "feat: add prompt builder with three-layer structure"
```

---

### Task 2.4: 阶段 2 验收测试

- [ ] **Step 1: 运行所有阶段 2 测试**

```bash
pytest tests/core/review/test_budget.py tests/core/review/test_stop_verifier.py tests/core/review/test_prompt_builder.py -v
```

预期输出: 所有测试通过

- [ ] **Step 2: 验证组件集成**

创建集成测试脚本 `scripts/test_review_core_integration.py`:

```python
"""复盘核心组件集成测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.review.budget import ReviewIterationBudget
from core.review.stop_verifier import ReviewStopVerifier
from core.review.prompt_builder import ReviewPromptBuilder
from core.review.state import ReviewAgentState
from core.review.types import MatchData, PlayerData, Conclusion, BudgetDecision


def test_core_integration():
    """测试核心组件集成"""
    print("测试核心组件集成...")
    
    # 1. 测试预算控制器
    print("\n1. 测试预算控制器")
    budget = ReviewIterationBudget(max_iterations=5, max_tokens=10000)
    decision = budget.consume(delta_tokens=1000)
    assert decision == BudgetDecision.CONTINUE
    print("   ✅ 预算控制器工作正常")
    
    # 2. 测试提示词构建器
    print("\n2. 测试提示词构建器")
    builder = ReviewPromptBuilder()
    match_data = MatchData(
        match_id="8893253595",
        duration=2922,
        radiant_win=True,
        radiant_score=32,
        dire_score=58,
        game_mode=22,
        players=[
            PlayerData(
                account_id="123456789",
                hero_id=1,
                hero_name="Anti-Mage",
                kills=10,
                deaths=5,
                assists=15,
                last_hits=250,
                denies=20,
                gpm=650,
                xpm=700,
                hero_damage=25000,
                tower_damage=8000,
                is_radiant=True,
                is_user=True
            )
        ],
        picks_bans=[]
    )
    messages = builder.build(match_data, [])
    assert len(messages) == 2
    print("   ✅ 提示词构建器工作正常")
    
    # 3. 测试停止验证器
    print("\n3. 测试停止验证器")
    verifier = ReviewStopVerifier()
    state = ReviewAgentState(match_id="8893253595")
    state.completed_phases = ["laning", "teamfight", "economy", "decisions"]
    state.conclusions = [
        Conclusion(
            title="测试结论",
            content="测试内容",
            evidence=["evidence1"],
            has_evidence=True,
            impact="medium",
            suggestion=None
        )
    ]
    state.confidence = 0.8
    
    result = verifier.verify(state)
    assert result.passed is True
    print("   ✅ 停止验证器工作正常")
    
    print("\n✅ 所有核心组件集成测试通过")
    return True


if __name__ == "__main__":
    success = test_core_integration()
    sys.exit(0 if success else 1)
```

- [ ] **Step 3: 运行集成测试**

```bash
python scripts/test_review_core_integration.py
```

预期输出: 所有步骤成功

- [ ] **Step 4: 提交集成测试**

```bash
git add scripts/test_review_core_integration.py
git commit -m "test: add stage 2 integration test for review core components"
```

---

## 后续阶段（待展开）

由于篇幅限制，阶段 3-7 的详细任务清单将在实施过程中逐步展开。每个阶段将遵循相同的 TDD 模式：

1. **编写失败测试** - 明确验收标准
2. **运行测试验证失败** - 确认测试有效
3. **实现最小代码** - 让测试通过
4. **运行测试验证通过** - 确认实现正确
5. **提交代码** - 保持小步提交

**阶段 3-7 核心任务概览:**

- **阶段 3**: 实现战术循环 + 对线期分析器
- **阶段 4**: 实现战略循环 + 全部分析器 + 报告生成
- **阶段 5**: 实现并行子代理 + 上下文压缩
- **阶段 6**: 实现后台审查 + 技能沉淀 + 记忆扩展
- **阶段 7**: 实现 API 端点 + SSE 流式 + 前端组件

---

## 执行方式

**采用 Subagent-Driven Development（子代理驱动开发）**

每个任务分派一个独立子代理执行，任务间进行两阶段审查（Spec Compliance + Code Quality），快速迭代。

**执行流程:**

```
实施计划 (本文档)
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  Subagent-Driven Development 循环                       │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐   │
│  │ 分派任务  │ ─▶ │ 子代理执行 │ ─▶ │ 两阶段审查        │   │
│  │ Task N   │    │ TDD 模式  │    │ 1. Spec 合规审查   │   │
│  └──────────┘    └──────────┘    │ 2. 代码质量审查    │   │
│       ▲                          └────────┬─────────┘   │
│       │                                   │              │
│       │         ┌──────────┐              │              │
│       └──────── │ 通过审查  │ ◀────────────┘              │
│                 │ 进入下一任务│                             │
│                 └──────────┘                              │
└─────────────────────────────────────────────────────────┘
```

**审查要点:**

| 审查阶段 | 检查内容 |
|---------|---------|
| **Spec Compliance** | 实现是否覆盖设计文档中对应组件的所有要求？接口契约是否匹配？ |
| **Code Quality** | 代码是否遵循项目规范（Type Hints、依赖注入、接口+策略模式）？测试是否充分？ |

**子代理分派规则:**

| 规则 | 说明 |
|------|------|
| 一个任务一个子代理 | 每个 Task 分派独立子代理，避免上下文污染 |
| 提供完整上下文 | 子代理需获得设计文档对应章节 + 实施计划对应 Task 的完整内容 |
| TDD 强制执行 | 子代理必须遵循 编写测试 → 验证失败 → 实现代码 → 验证通过 的流程 |
| 审查后合并 | 通过两阶段审查后才合并代码，进入下一任务 |
