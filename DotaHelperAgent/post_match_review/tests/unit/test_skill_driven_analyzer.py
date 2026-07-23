"""SkillDrivenAnalyzer 单元测试"""
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from post_match_review.analyzers.skill_driven import (
    SkillDrivenAnalyzer,
    SkillDrivenPromptBuilder,
    _validate_skill_definition,
)
from post_match_review.domain_types.analysis import (
    AnalysisContext,
    AnalysisResult,
    Conclusion,
)
from post_match_review.domain_types.match_data import MatchData


def _make_skill_definition(**overrides: Any) -> Dict[str, Any]:
    """构建测试用的技能定义"""
    base = {
        "phase": "roshan_timing",
        "name": "Roshan时机分析",
        "description": "测试分析技能",
        "analysis_framework": "你是一位专业的 Dota 2 分析师。",
        "data_requirements": [
            {"field": "duration", "label": "比赛时长", "format": "simple"},
        ],
        "output_schema": {
            "type": "object",
            "required": ["conclusions"],
        },
        "metadata": {
            "min_confidence": 0.5,
            "expected_conclusions": 3,
        },
        "stable_layer": "{analysis_framework}\n\n{output_schema}",
        "volatile_layer": "请分析 {formatted_data} {iteration_feedback}",
    }
    base.update(overrides)
    return base


def _make_match_data() -> MatchData:
    """构建测试用 MatchData"""
    from post_match_review.domain_types.match_data import PlayerData
    return MatchData(
        match_id="12345",
        duration=2400,
        radiant_win=True,
        radiant_score=30,
        dire_score=20,
        game_mode=22,
        players=[
            PlayerData(
                account_id="100",
                hero_name="Axe",
                hero_id=1,
                kills=5,
                deaths=3,
                assists=10,
                last_hits=100,
                denies=20,
                gpm=400,
                xpm=500,
                hero_damage=5000,
                tower_damage=1000,
                is_radiant=True,
                is_user=True,
            ),
        ],
        picks_bans=[],
    )


@pytest.fixture
def mock_llm_client():
    """创建 Mock LLM 客户端"""
    client = MagicMock()
    client.chat = AsyncMock(return_value='{"conclusions": []}')
    return client


class TestSkillDrivenAnalyzerInit:
    """初始化和属性测试"""

    def test_phase_name_from_yaml_definition(self, mock_llm_client):
        """验证 phase_name 来自 YAML 技能定义"""
        definition = _make_skill_definition(phase="custom_phase")
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )
        assert analyzer.phase_name == "custom_phase"

    def test_skill_name_property(self, mock_llm_client):
        """验证 skill_name 属性来自 YAML"""
        definition = _make_skill_definition(name="自定义技能")
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )
        assert analyzer.skill_name == "自定义技能"

    def test_skill_name_defaults_to_phase(self, mock_llm_client):
        """验证 skill_name 在无 name 时回退到 phase"""
        definition = _make_skill_definition()
        del definition["name"]
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )
        assert analyzer.skill_name == "roshan_timing"

    def test_skill_definition_property(self, mock_llm_client):
        """验证 skill_definition 属性可获取完整定义"""
        definition = _make_skill_definition()
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )
        assert analyzer.skill_definition is definition


class TestFromYaml:
    """from_yaml 类方法测试"""

    def test_from_yaml_creates_analyzer(self, mock_llm_client, tmp_path):
        """从 YAML 文件创建分析器"""
        definition = _make_skill_definition()
        yaml_path = tmp_path / "test_skill.yaml"
        import yaml
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(definition, f, allow_unicode=True)

        analyzer = SkillDrivenAnalyzer.from_yaml(
            llm_client=mock_llm_client,
            yaml_path=yaml_path,
        )
        assert analyzer.phase_name == "roshan_timing"
        assert analyzer.skill_name == "Roshan时机分析"

    def test_from_yaml_invalid_raises(self, mock_llm_client, tmp_path):
        """缺少必要字段时抛 ValueError"""
        definition = {"phase": "test"}  # 缺少 name, stable_layer, volatile_layer
        yaml_path = tmp_path / "invalid.yaml"
        import yaml
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(definition, f, allow_unicode=True)

        with pytest.raises(ValueError, match="缺少必要字段"):
            SkillDrivenAnalyzer.from_yaml(
                llm_client=mock_llm_client,
                yaml_path=yaml_path,
            )

    def test_from_yaml_empty_file_raises(self, mock_llm_client, tmp_path):
        """空 YAML 文件时抛 ValueError"""
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="内容为空"):
            SkillDrivenAnalyzer.from_yaml(
                llm_client=mock_llm_client,
                yaml_path=yaml_path,
            )


class TestFromSkillStore:
    """from_skill_store 类方法测试"""

    def test_from_skill_store_creates_analyzer(self, mock_llm_client):
        """从 SkillStore 创建分析器"""
        from post_match_review.memory.skill_store import SkillStore
        import tempfile
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            store = SkillStore(tmpdir)
            definition = _make_skill_definition()
            store.save_analysis_skill("test_skill", definition)

            analyzer = SkillDrivenAnalyzer.from_skill_store(
                llm_client=mock_llm_client,
                skill_store=store,
                skill_name="test_skill",
            )
            assert analyzer.phase_name == "roshan_timing"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_from_skill_store_not_found_raises(self, mock_llm_client):
        """技能不存在时抛 ValueError"""
        from post_match_review.memory.skill_store import SkillStore
        import tempfile
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            store = SkillStore(tmpdir)
            with pytest.raises(ValueError, match="分析技能不存在"):
                SkillDrivenAnalyzer.from_skill_store(
                    llm_client=mock_llm_client,
                    skill_store=store,
                    skill_name="nonexistent",
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestInheritedMethods:
    """继承自基类的方法测试"""

    def test_parse_response_inherited_from_base(self, mock_llm_client):
        """验证 parse_response 继承自基类"""
        definition = _make_skill_definition()
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )

        # 测试 JSON 响应解析
        response = '{"conclusions": [{"title": "测试", "content": "内容", "evidence": ["e1"], "impact": "high"}]}'
        conclusions = analyzer.parse_response(response)
        assert len(conclusions) == 1
        assert conclusions[0].title == "测试"

    def test_format_domain_data_default_empty(self, mock_llm_client):
        """无 custom 格式时 _format_domain_data 返回空字符串"""
        definition = _make_skill_definition()
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )

        match_data = _make_match_data()
        result = analyzer._format_domain_data(match_data)
        assert result == ""

    def test_format_domain_data_with_custom_format(self, mock_llm_client):
        """有 custom 格式时记录日志但仍返回空字符串"""
        definition = _make_skill_definition(
            data_requirements=[
                {"field": "raw_metadata.objectives", "format": "custom"},
            ],
        )
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )

        match_data = _make_match_data()
        result = analyzer._format_domain_data(match_data)
        # custom 格式默认不处理，返回空字符串
        assert result == ""


class TestValidateResult:
    """validate_result 测试"""

    def test_validate_result_uses_skill_confidence(self, mock_llm_client):
        """验证 validate_result 使用技能定义的 min_confidence"""
        definition = _make_skill_definition(
            metadata={"min_confidence": 0.5, "expected_conclusions": 2},
        )
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )

        # 置信度 0.55 >= 0.5，应通过
        result_pass = AnalysisResult(
            phase="roshan_timing",
            conclusions=[
                Conclusion(
                    title="t1", content="c1",
                    evidence=["e1"], has_evidence=True, impact="medium",
                ),
            ],
            confidence=0.55,
            iterations_used=1,
            tokens_consumed=0,
            analysis_text="",
        )
        assert analyzer.validate_result(result_pass) is True

        # 置信度 0.4 < 0.5，应不通过
        result_fail = AnalysisResult(
            phase="roshan_timing",
            conclusions=[
                Conclusion(
                    title="t1", content="c1",
                    evidence=["e1"], has_evidence=True, impact="medium",
                ),
            ],
            confidence=0.4,
            iterations_used=1,
            tokens_consumed=0,
            analysis_text="",
        )
        assert analyzer.validate_result(result_fail) is False

    def test_validate_result_no_evidence(self, mock_llm_client):
        """无证据支撑时验证不通过"""
        definition = _make_skill_definition()
        analyzer = SkillDrivenAnalyzer(
            llm_client=mock_llm_client,
            skill_definition=definition,
        )

        result = AnalysisResult(
            phase="roshan_timing",
            conclusions=[
                Conclusion(
                    title="t1", content="c1",
                    evidence=[], has_evidence=False, impact="medium",
                ),
            ],
            confidence=0.8,
            iterations_used=1,
            tokens_consumed=0,
            analysis_text="",
        )
        assert analyzer.validate_result(result) is False


class TestSkillDefinitionValidation:
    """_validate_skill_definition 函数测试"""

    def test_valid_definition_passes(self):
        """合法定义通过验证"""
        definition = _make_skill_definition()
        _validate_skill_definition(definition)  # 不抛异常即通过

    def test_missing_phase_raises(self):
        """缺少 phase 字段抛 ValueError"""
        definition = _make_skill_definition()
        del definition["phase"]
        with pytest.raises(ValueError, match="缺少必要字段"):
            _validate_skill_definition(definition)

    def test_missing_stable_layer_raises(self):
        """缺少 stable_layer 抛 ValueError"""
        definition = _make_skill_definition()
        del definition["stable_layer"]
        with pytest.raises(ValueError, match="缺少必要字段"):
            _validate_skill_definition(definition)

    def test_missing_volatile_layer_raises(self):
        """缺少 volatile_layer 抛 ValueError"""
        definition = _make_skill_definition()
        del definition["volatile_layer"]
        with pytest.raises(ValueError, match="缺少必要字段"):
            _validate_skill_definition(definition)

    def test_missing_name_raises(self):
        """缺少 name 抛 ValueError"""
        definition = _make_skill_definition()
        del definition["name"]
        with pytest.raises(ValueError, match="缺少必要字段"):
            _validate_skill_definition(definition)
