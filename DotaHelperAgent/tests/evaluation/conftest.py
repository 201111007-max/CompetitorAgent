"""评测系统测试共享 fixtures"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest


@pytest.fixture
def mock_llm_adapter():
    """提供 Mock LLM 适配器（无需真实 LLM）"""
    from evaluation.judges import build_judge_adapter

    return build_judge_adapter(llm_client=None, temperature=0.0)


@pytest.fixture
def sample_judge():
    """提供测试用 7 维评分 Judge"""
    from evaluation.judges import MultiDimensionalJudge, build_judge_adapter

    adapter = build_judge_adapter(llm_client=None, temperature=0.0)
    return MultiDimensionalJudge(llm_adapter=adapter, n_samples=1)


@pytest.fixture
def sample_context():
    """提供测试用 EvaluationContext"""
    from evaluation.base import EvaluationContext

    return EvaluationContext(
        case_id="test_001",
        input_data={"heroes": ["PA", "CM"]},
        expected_output={
            "key_points": ["高爆发组合", "控制强"],
            "must_include_heroes": ["PA"],
        },
        actual_output="PA + CM 是高爆发组合，控制能力强。",
        metadata={"difficulty": "easy"},
    )
