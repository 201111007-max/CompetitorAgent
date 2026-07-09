"""测试 Judge 模块"""

import json

import pytest

from evaluation.base import (
    EvaluationContext,
    EvaluationStatus,
    ScoreDimension,
)
from evaluation.judges import (
    LLMJudgeAdapter,
    MultiDimensionalJudge,
    build_judge_adapter,
)


class TestLLMJudgeAdapter:
    """测试 LLM 适配器"""

    def test_mock_mode(self):
        """测试 Mock 模式"""
        adapter = LLMJudgeAdapter(llm_client=None)
        assert adapter.is_mock() is True
        response = adapter.generate("test prompt")
        assert isinstance(response, str)
        # Mock 返回 JSON 格式
        data = json.loads(response)
        assert "correctness" in data
        assert "total_score" in data

    def test_extract_text_from_dict(self):
        """测试从 dict 提取文本"""
        adapter = LLMJudgeAdapter(llm_client=None)
        result = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        text = adapter._extract_text(result)
        assert text == "Hello world"

    def test_extract_text_nested(self):
        """测试嵌套字段提取"""
        adapter = LLMJudgeAdapter(llm_client=None)
        assert adapter._extract_text({"content": "abc"}) == "abc"
        assert adapter._extract_text({"text": "xyz"}) == "xyz"
        assert adapter._extract_text("plain string") == "plain string"

    def test_with_mock_client_complete(self):
        """测试带 mock 客户端（complete 接口）"""

        class MockClient:
            def complete(self, prompt, temperature=0.0):
                return {"content": f"Response to: {prompt[:20]}"}

        adapter = LLMJudgeAdapter(llm_client=MockClient())
        assert not adapter.is_mock()
        response = adapter.generate("Hello world this is a test")
        assert "Hello world" in response

    def test_with_mock_client_chat(self):
        """测试带 mock 客户端（chat 接口）"""

        class MockClient:
            def chat(self, messages, temperature=0.0):
                return {
                    "choices": [
                        {"message": {"content": f"Got {len(messages)} messages"}}
                    ]
                }

        adapter = LLMJudgeAdapter(llm_client=MockClient())
        assert not adapter.is_mock()
        response = adapter.generate("test")
        assert "Got 1 messages" in response

    def test_client_failure_falls_back_to_mock(self):
        """测试客户端失败时降级到 Mock"""

        class FailingClient:
            def chat(self, messages, **kwargs):
                raise ConnectionError("Network down")

            def complete(self, prompt, **kwargs):
                raise ConnectionError("Network down")

        adapter = LLMJudgeAdapter(llm_client=FailingClient())
        response = adapter.generate("test")
        # 应降级到 Mock 返回
        assert "correctness" in response

    def test_build_judge_adapter_factory(self):
        """测试工厂函数"""
        adapter = build_judge_adapter(llm_client=None)
        assert isinstance(adapter, LLMJudgeAdapter)
        assert adapter.is_mock()


class TestMultiDimensionalJudge:
    """测试 7 维评分 Judge"""

    def test_evaluate_with_mock(self, sample_judge, sample_context):
        """使用 Mock 评估"""
        result = sample_judge.run(sample_context)
        assert result.status == EvaluationStatus.COMPLETED
        # Mock 模式应返回 7 个维度评分
        assert len(result.dimension_scores) == 7
        # 验证每个维度都有评分
        for dim in ScoreDimension:
            assert dim in result.dimension_scores
            assert 1.0 <= result.dimension_scores[dim] <= 5.0

    def test_evaluate_empty_input(self, mock_llm_adapter):
        """测试空输入处理"""
        judge = MultiDimensionalJudge(llm_adapter=mock_llm_adapter, n_samples=1)
        ctx = EvaluationContext(case_id="empty", input_data={})
        result = judge.run(ctx)
        assert result.status == EvaluationStatus.COMPLETED

    def test_parse_valid_json(self, sample_judge):
        """测试解析有效 JSON"""
        response = """```json
{
  "correctness": 5,
  "completeness": 4,
  "relevance": 4,
  "tool_selection": 4,
  "efficiency": 3,
  "robustness": 3,
  "personalization": 3,
  "total_score": 4.0,
  "reasoning": "Good"
}
```"""
        scores = sample_judge.parse_response(response)
        assert scores[ScoreDimension.CORRECTNESS] == 5.0
        assert scores[ScoreDimension.COMPLETENESS] == 4.0

    def test_parse_invalid_json_fallback(self, sample_judge):
        """测试解析无效 JSON 降级"""
        response = "This is not JSON"
        scores = sample_judge.parse_response(response)
        # 降级为 3.0
        assert all(v == 3.0 for v in scores.values())

    def test_score_clamping(self, sample_judge):
        """测试分数范围限制（1-5）"""
        response = json.dumps({
            "correctness": 10,  # 超出 5
            "completeness": -1,  # 低于 1
        })
        scores = sample_judge.parse_response(response)
        assert scores[ScoreDimension.CORRECTNESS] == 5.0
        assert scores[ScoreDimension.COMPLETENESS] == 1.0

    def test_module_name_in_evaluator_name(self, mock_llm_adapter):
        """测试模块名包含在评估器名称中"""
        judge = MultiDimensionalJudge(
            llm_adapter=mock_llm_adapter, module_name="lineup_analyzer"
        )
        assert "lineup_analyzer" in judge.name

    def test_evaluate_with_expected_dict(self, sample_judge):
        """测试期望输出为字典时"""
        ctx = EvaluationContext(
            case_id="c1",
            input_data={"heroes": ["PA"]},
            expected_output={"key_points": ["要点1", "要点2"]},
            actual_output="输出文本",
        )
        result = sample_judge.run(ctx)
        assert result.status == EvaluationStatus.COMPLETED
