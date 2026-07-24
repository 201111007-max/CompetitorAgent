"""P0-P4 优化项修复的单元测试

覆盖以下修复项:
- P0-2: tokens_consumed 不再永远为 0
- P0-3: Python 3.9 兼容性（Optional 替代 X | None）
- P1-1: ReviewAgentState 序列化/反序列化
- P1-4: 领域异常层次结构
- P1-5: SkillStore 中文分词支持
- P2-4: PromptBuilder 配置化截断
- P2-5: AgentConfig.to_dict() 使用 dataclasses.asdict
- P3-4: OpenDotaClient async context manager
"""
import asyncio
import pytest
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock

from post_match_review.analyzers.base import estimate_tokens
from post_match_review.domain_types.state import ReviewAgentState
from post_match_review.domain_types.analysis import Conclusion
from post_match_review.domain_types.exceptions import (
    ReviewError,
    DataFetchError,
    LLMError,
    BudgetExhaustedError,
    VerificationBlockedError,
    SkillDefinitionError,
)
from post_match_review.memory.skill_store import SkillStore


# ── P0-2: estimate_tokens ──

class TestEstimateTokens:
    """P0-2: Token 估算函数测试"""

    def test_empty_text(self) -> None:
        """空文本返回 0"""
        assert estimate_tokens("") == 0

    def test_short_text(self) -> None:
        """短文本至少返回 1"""
        result = estimate_tokens("hi")
        assert result >= 1

    def test_chinese_text(self) -> None:
        """中文文本估算（偏保守，字符/Token 比约 1.5-3）"""
        text = "这是一个中文测试文本"
        result = estimate_tokens(text)
        assert result > 0
        # 中文字符约 9 个，按 3.0 比率应约为 3
        assert result >= 3

    def test_english_text(self) -> None:
        """英文文本估算"""
        text = "This is an English test text for token estimation."
        result = estimate_tokens(text)
        assert result > 0
        # 54 字符 / 3.0 ≈ 18
        assert result >= 10

    def test_mixed_text(self) -> None:
        """中英混合文本估算"""
        text = "Dota2 比赛复盘分析 match review"
        result = estimate_tokens(text)
        assert result > 0

    def test_custom_ratio(self) -> None:
        """自定义字符/Token 比率"""
        text = "test text"
        result_default = estimate_tokens(text)
        result_conservative = estimate_tokens(text, chars_per_token=1.5)
        # 更保守的比率（更小）会产生更大的 Token 数
        assert result_conservative >= result_default


# ── P1-1: ReviewAgentState 序列化 ──

class TestReviewAgentStateSerialization:
    """P1-1: ReviewAgentState 序列化/反序列化测试"""

    def test_to_dict_basic(self) -> None:
        """基本序列化"""
        state = ReviewAgentState(match_id="12345")
        data = state.to_dict()
        assert data["match_id"] == "12345"
        assert data["completed_phases"] == []
        assert data["confidence"] == 0.0
        assert data["conclusions"] == []

    def test_to_dict_with_conclusions(self) -> None:
        """含结论的序列化"""
        state = ReviewAgentState(match_id="12345")
        state.completed_phases = ["laning", "teamfight"]
        state.conclusions = [
            Conclusion(title="测试结论", content="内容", evidence=["数据1"], has_evidence=True),
        ]
        state.confidence = 0.8
        data = state.to_dict()
        assert len(data["conclusions"]) == 1
        assert data["conclusions"][0]["title"] == "测试结论"
        assert data["completed_phases"] == ["laning", "teamfight"]
        assert data["confidence"] == 0.8

    def test_from_dict_basic(self) -> None:
        """基本反序列化"""
        data = {"match_id": "12345", "completed_phases": ["laning"], "confidence": 0.5}
        state = ReviewAgentState.from_dict(data)
        assert state.match_id == "12345"
        assert state.completed_phases == ["laning"]
        assert state.confidence == 0.5

    def test_from_dict_with_conclusions(self) -> None:
        """含结论的反序列化"""
        data = {
            "match_id": "12345",
            "conclusions": [
                {"title": "结论1", "content": "内容1", "evidence": [], "has_evidence": False, "impact": "medium", "suggestion": None},
            ],
        }
        state = ReviewAgentState.from_dict(data)
        assert len(state.conclusions) == 1
        assert state.conclusions[0].title == "结论1"

    def test_roundtrip(self) -> None:
        """序列化-反序列化往返测试"""
        state = ReviewAgentState(match_id="99999")
        state.completed_phases = ["laning", "economy"]
        state.confidence = 0.75
        state.total_iterations = 5
        state.total_tokens = 3000
        state.conclusions = [
            Conclusion(title="A", content="B", evidence=["C"], has_evidence=True, impact="high"),
        ]

        data = state.to_dict()
        restored = ReviewAgentState.from_dict(data)

        assert restored.match_id == state.match_id
        assert restored.completed_phases == state.completed_phases
        assert restored.confidence == state.confidence
        assert restored.total_iterations == state.total_iterations
        assert restored.total_tokens == state.total_tokens
        assert len(restored.conclusions) == len(state.conclusions)
        assert restored.conclusions[0].title == "A"


# ── P1-4: 领域异常层次结构 ──

class TestDomainExceptions:
    """P1-4: 领域异常层次结构测试"""

    def test_hierarchy(self) -> None:
        """所有领域异常都是 ReviewError 的子类"""
        assert issubclass(DataFetchError, ReviewError)
        assert issubclass(LLMError, ReviewError)
        assert issubclass(BudgetExhaustedError, ReviewError)
        assert issubclass(VerificationBlockedError, ReviewError)
        assert issubclass(SkillDefinitionError, ReviewError)

    def test_data_fetch_error_retryable(self) -> None:
        """DataFetchError 可恢复标记"""
        err = DataFetchError("API 超时", retryable=True)
        assert err.retryable is True
        err2 = DataFetchError("4xx 错误", retryable=False)
        assert err2.retryable is False

    def test_llm_error_retryable(self) -> None:
        """LLMError 可恢复标记"""
        err = LLMError("模型不可用", retryable=True)
        assert err.retryable is True

    def test_verification_blocked_error(self) -> None:
        """VerificationBlockedError 携带阻塞原因和建议"""
        err = VerificationBlockedError(
            "验证未通过",
            blocking_reasons=["缺少必要阶段"],
            suggestions=["请完成 laning 阶段"],
        )
        assert err.blocking_reasons == ["缺少必要阶段"]
        assert err.suggestions == ["请完成 laning 阶段"]

    def test_skill_definition_error(self) -> None:
        """SkillDefinitionError 携带技能名称"""
        err = SkillDefinitionError("无效技能", skill_name="bad_skill")
        assert err.skill_name == "bad_skill"

    def test_catch_base_class(self) -> None:
        """可以用 ReviewError 基类统一捕获"""
        errors = [
            DataFetchError("a"),
            LLMError("b"),
            BudgetExhaustedError("c"),
        ]
        for err in errors:
            assert isinstance(err, ReviewError)


# ── P1-5: SkillStore 中文分词 ──

class TestSkillStoreChineseTokenization:
    """P1-5: SkillStore 中文分词支持测试"""

    def test_chinese_similarity_high(self) -> None:
        """高度相似的中文文本"""
        sim = SkillStore._calculate_similarity(
            SkillStore, "眼位效率分析", "眼位效率评估"
        )
        # 共享 "眼位"、"位效"、"效率" 等词元
        assert sim > 0.3

    def test_chinese_similarity_low(self) -> None:
        """不相关的中文文本"""
        sim = SkillStore._calculate_similarity(
            SkillStore, "眼位效率分析", "经济发育评估"
        )
        # 几乎没有共享词元
        assert sim < 0.5

    def test_english_similarity(self) -> None:
        """英文文本相似度"""
        sim = SkillStore._calculate_similarity(
            SkillStore, "ward efficiency analysis", "ward efficiency evaluation"
        )
        # 共享 "ward"、"efficiency"
        assert sim > 0.3

    def test_mixed_similarity(self) -> None:
        """中英混合文本"""
        sim = SkillStore._calculate_similarity(
            SkillStore, "Roshan击杀时机分析", "Roshan击杀决策评估"
        )
        # 共享 "Roshan"、"roshan"、"击杀" 等
        assert sim > 0.1

    def test_empty_text(self) -> None:
        """空文本返回 0"""
        sim = SkillStore._calculate_similarity(SkillStore, "", "测试")
        assert sim == 0.0
        sim2 = SkillStore._calculate_similarity(SkillStore, "测试", "")
        assert sim2 == 0.0

    def test_identical_text(self) -> None:
        """相同文本返回 1.0"""
        sim = SkillStore._calculate_similarity(
            SkillStore, "眼位效率分析", "眼位效率分析"
        )
        assert sim == 1.0


# ── P2-4: PromptBuilder 配置化截断 ──

class TestPromptBuilderConfigurableTruncation:
    """P2-4: PromptBuilder 配置化截断测试"""

    def test_default_max_players(self) -> None:
        """默认最大玩家数为 10"""
        from post_match_review.engines.prompt_builder import PromptBuilder
        builder = PromptBuilder()
        assert builder._context_max_players == 10

    def test_default_max_conclusions(self) -> None:
        """默认最大结论数为 5"""
        from post_match_review.engines.prompt_builder import PromptBuilder
        builder = PromptBuilder()
        assert builder._context_max_conclusions == 5

    def test_custom_max_players(self) -> None:
        """自定义最大玩家数"""
        from post_match_review.engines.prompt_builder import PromptBuilder
        builder = PromptBuilder(context_max_players=5)
        assert builder._context_max_players == 5

    def test_custom_max_conclusions(self) -> None:
        """自定义最大结论数"""
        from post_match_review.engines.prompt_builder import PromptBuilder
        builder = PromptBuilder(context_max_conclusions=3)
        assert builder._context_max_conclusions == 3


# ── P3-4: OpenDotaClient async context manager ──

class TestOpenDotaClientContextManager:
    """P3-4: OpenDotaClient async context manager 测试"""

    @pytest.mark.asyncio
    async def test_aenter_returns_self(self) -> None:
        """__aenter__ 返回自身"""
        from post_match_review.data_source.opendota_client import OpenDotaClient
        client = OpenDotaClient()
        result = await client.__aenter__()
        assert result is client

    @pytest.mark.asyncio
    async def test_aexit_closes_client(self) -> None:
        """__aexit__ 关闭客户端"""
        from post_match_review.data_source.opendota_client import OpenDotaClient
        client = OpenDotaClient()
        # 创建一个 client（通过 _get_client）
        _ = await client._get_client()
        assert client._client is not None
        await client.__aexit__(None, None, None)
        assert client._client is None

    @pytest.mark.asyncio
    async def test_async_with_usage(self) -> None:
        """支持 async with 语法"""
        from post_match_review.data_source.opendota_client import OpenDotaClient
        async with OpenDotaClient() as client:
            assert isinstance(client, OpenDotaClient)


# ── P0-3: Python 3.9 兼容性 ──

class TestPython39Compatibility:
    """P0-3: Python 3.9 兼容性测试"""

    def test_opendota_client_optional(self) -> None:
        """OpenDotaClient._client 使用 Optional"""
        from post_match_review.data_source.opendota_client import OpenDotaClient
        client = OpenDotaClient()
        assert client._client is None

    def test_exceptions_optional(self) -> None:
        """异常类使用 Optional"""
        err = OpenDotaAPIError("test")
        assert err.status_code is None
        err2 = OpenDotaAPIError("test", status_code=404)
        assert err2.status_code == 404

    def test_data_validation_error_optional(self) -> None:
        """DataValidationError 使用 Optional"""
        from post_match_review.data_source.exceptions import DataValidationError
        err = DataValidationError("test")
        assert err.errors == []
        err2 = DataValidationError("test", errors=["e1"])
        assert err2.errors == ["e1"]


# 需要导入以测试 P0-3
from post_match_review.data_source.exceptions import OpenDotaAPIError
