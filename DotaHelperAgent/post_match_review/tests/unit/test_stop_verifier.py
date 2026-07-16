"""停止验证器单元测试"""
import pytest
from post_match_review.engines.stop_verifier import StopVerifier
from post_match_review.types.state import ReviewAgentState
from post_match_review.types.analysis import Conclusion


class TestStopVerifier:
    """测试停止验证器"""

    def test_verify_passes_when_all_conditions_met(self) -> None:
        """测试所有条件满足时验证通过"""
        verifier = StopVerifier(
            required_phases=["laning", "teamfight", "economy"],
            min_confidence=0.6,
        )
        
        state = ReviewAgentState(
            match_id="8893253595",
            completed_phases=["laning", "teamfight", "economy"],
            conclusions=[
                Conclusion(phase="laning", finding="对线优势", confidence=0.8, has_evidence=True),
                Conclusion(phase="teamfight", finding="团战获胜", confidence=0.7, has_evidence=True),
                Conclusion(phase="economy", finding="经济领先", confidence=0.9, has_evidence=True),
            ],
            confidence=0.8,
        )
        
        result = verifier.verify(state)
        assert result.passed is True
        assert len(result.blocking_reasons) == 0
        assert len(result.suggestions) == 0

    def test_verify_blocks_when_required_phases_missing(self) -> None:
        """测试缺少必要阶段时验证阻塞"""
        verifier = StopVerifier(
            required_phases=["laning", "teamfight", "economy"],
            min_confidence=0.6,
        )
        
        state = ReviewAgentState(
            match_id="8893253595",
            completed_phases=["laning", "teamfight"],  # 缺少 economy
            conclusions=[
                Conclusion(phase="laning", finding="对线优势", confidence=0.8, has_evidence=True),
                Conclusion(phase="teamfight", finding="团战获胜", confidence=0.7, has_evidence=True),
            ],
            confidence=0.75,
        )
        
        result = verifier.verify(state)
        assert result.passed is False
        assert len(result.blocking_reasons) > 0
        assert any("economy" in reason for reason in result.blocking_reasons)
        assert len(result.suggestions) > 0

    def test_verify_blocks_when_conclusions_lack_evidence(self) -> None:
        """测试结论缺少证据时验证阻塞"""
        verifier = StopVerifier(
            required_phases=["laning", "teamfight"],
            min_confidence=0.6,
        )
        
        state = ReviewAgentState(
            match_id="8893253595",
            completed_phases=["laning", "teamfight"],
            conclusions=[
                Conclusion(phase="laning", finding="对线优势", confidence=0.8, has_evidence=True),
                Conclusion(phase="teamfight", finding="团战获胜", confidence=0.7, has_evidence=False),  # 缺少证据
            ],
            confidence=0.75,
        )
        
        result = verifier.verify(state)
        assert result.passed is False
        assert len(result.blocking_reasons) > 0
        assert any("数据支撑" in reason for reason in result.blocking_reasons)

    def test_verify_blocks_when_confidence_too_low(self) -> None:
        """测试置信度不足时验证阻塞"""
        verifier = StopVerifier(
            required_phases=["laning"],
            min_confidence=0.6,
        )
        
        state = ReviewAgentState(
            match_id="8893253595",
            completed_phases=["laning"],
            conclusions=[
                Conclusion(phase="laning", finding="对线优势", confidence=0.5, has_evidence=True),
            ],
            confidence=0.5,  # 低于 0.6
        )
        
        result = verifier.verify(state)
        assert result.passed is False
        assert len(result.blocking_reasons) > 0
        assert any("置信度" in reason for reason in result.blocking_reasons)

    def test_verify_with_multiple_blocking_reasons(self) -> None:
        """测试多个阻塞原因同时存在"""
        verifier = StopVerifier(
            required_phases=["laning", "teamfight", "economy"],
            min_confidence=0.6,
        )
        
        state = ReviewAgentState(
            match_id="8893253595",
            completed_phases=["laning"],  # 缺少 teamfight 和 economy
            conclusions=[
                Conclusion(phase="laning", finding="对线优势", confidence=0.5, has_evidence=False),
            ],
            confidence=0.5,  # 置信度不足
        )
        
        result = verifier.verify(state)
        assert result.passed is False
        # 应该有 3 个阻塞原因：缺少阶段、缺少证据、置信度不足
        assert len(result.blocking_reasons) >= 2

    def test_verify_with_empty_conclusions(self) -> None:
        """测试空结论列表"""
        verifier = StopVerifier(
            required_phases=["laning"],
            min_confidence=0.6,
        )
        
        state = ReviewAgentState(
            match_id="8893253595",
            completed_phases=[],
            conclusions=[],
            confidence=0.0,
        )
        
        result = verifier.verify(state)
        assert result.passed is False
        assert len(result.blocking_reasons) > 0

    def test_verify_with_custom_min_confidence(self) -> None:
        """测试自定义最低置信度"""
        verifier = StopVerifier(
            required_phases=["laning"],
            min_confidence=0.8,  # 更高的阈值
        )
        
        state = ReviewAgentState(
            match_id="8893253595",
            completed_phases=["laning"],
            conclusions=[
                Conclusion(phase="laning", finding="对线优势", confidence=0.7, has_evidence=True),
            ],
            confidence=0.7,  # 低于 0.8
        )
        
        result = verifier.verify(state)
        assert result.passed is False
        assert any("置信度" in reason for reason in result.blocking_reasons)
