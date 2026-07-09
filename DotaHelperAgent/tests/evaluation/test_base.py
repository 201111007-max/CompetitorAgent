"""测试评估器基类"""

import pytest

from evaluation.base import (
    BaseEvaluator,
    DIMENSION_WEIGHTS,
    EvaluationContext,
    EvaluationResult,
    EvaluationStatus,
    ScoreDimension,
)


class TestScoreDimension:
    """测试评分维度枚举"""

    def test_all_dimensions_defined(self):
        """验证所有 7 个维度都已定义"""
        expected = {
            "correctness",
            "completeness",
            "relevance",
            "tool_selection",
            "efficiency",
            "robustness",
            "personalization",
        }
        actual = {d.value for d in ScoreDimension}
        assert actual == expected

    def test_dimension_weights_sum_to_one(self):
        """验证维度权重之和为 1.0"""
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-6

    def test_correctness_highest_weight(self):
        """验证正确性权重最高（25%）"""
        assert DIMENSION_WEIGHTS[ScoreDimension.CORRECTNESS] == 0.25


class TestEvaluationContext:
    """测试评估上下文"""

    def test_required_fields(self):
        """测试必填字段"""
        ctx = EvaluationContext(
            case_id="c1",
            input_data={"x": 1},
        )
        assert ctx.case_id == "c1"
        assert ctx.input_data == {"x": 1}
        assert ctx.expected_output is None
        assert ctx.actual_output is None
        assert ctx.metadata == {}

    def test_optional_fields(self):
        """测试可选字段"""
        ctx = EvaluationContext(
            case_id="c2",
            input_data="input",
            expected_output="expected",
            actual_output="actual",
            trace_id="trace-123",
            session_id="sess-456",
            metadata={"key": "value"},
        )
        assert ctx.expected_output == "expected"
        assert ctx.trace_id == "trace-123"
        assert ctx.metadata == {"key": "value"}


class TestEvaluationResult:
    """测试评估结果"""

    def test_calculate_total_score(self):
        """测试加权总分计算"""
        result = EvaluationResult(
            case_id="c1",
            evaluator_name="test",
            status=EvaluationStatus.COMPLETED,
            dimension_scores={
                ScoreDimension.CORRECTNESS: 5.0,
                ScoreDimension.COMPLETENESS: 4.0,
                ScoreDimension.RELEVANCE: 4.0,
                ScoreDimension.TOOL_SELECTION: 4.0,
                ScoreDimension.EFFICIENCY: 4.0,
                ScoreDimension.ROBUSTNESS: 4.0,
                ScoreDimension.PERSONALIZATION: 4.0,
            },
        )
        score = result.calculate_total_score()
        # 5*0.25 + 4*0.75 = 1.25 + 3.0 = 4.25
        assert abs(score - 4.25) < 0.01

    def test_to_dict(self):
        """测试转换为字典"""
        result = EvaluationResult(
            case_id="c1",
            evaluator_name="test",
            status=EvaluationStatus.COMPLETED,
            total_score=4.0,
        )
        d = result.to_dict()
        assert d["case_id"] == "c1"
        assert d["status"] == "completed"
        assert d["total_score"] == 4.0
        assert "timestamp" in d


class TestBaseEvaluator:
    """测试评估器基类"""

    def test_concrete_evaluator_works(self):
        """测试具体评估器实现"""

        class SimpleEvaluator(BaseEvaluator):
            def evaluate(self, context):
                return EvaluationResult(
                    case_id=context.case_id,
                    evaluator_name=self.name,
                    status=EvaluationStatus.COMPLETED,
                    total_score=4.0,
                )

        ev = SimpleEvaluator(name="simple")
        ctx = EvaluationContext(case_id="c1", input_data="x")
        result = ev.run(ctx)
        assert result.status == EvaluationStatus.COMPLETED
        assert result.total_score == 4.0
        assert result.execution_time > 0

    def test_evaluator_handles_exception(self):
        """测试评估器异常处理"""

        class FailingEvaluator(BaseEvaluator):
            def evaluate(self, context):
                raise ValueError("Test error")

        ev = FailingEvaluator(name="failing")
        ctx = EvaluationContext(case_id="c1", input_data="x")
        result = ev.run(ctx)
        assert result.status == EvaluationStatus.FAILED
        assert "Test error" in result.error
