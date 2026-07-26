"""SkillStore 增强功能单元测试 — 分析技能（YAML 格式）"""
import tempfile
from pathlib import Path

import pytest
import yaml

from dota_helper.memory.skill_store import SkillStore


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def skill_store(temp_dir):
    """创建 SkillStore 实例"""
    skills_dir = Path(temp_dir) / "skills"
    return SkillStore(str(skills_dir))


def _make_analysis_skill_definition(
    phase: str = "roshan_timing",
    name: str = "Roshan时机分析",
) -> dict:
    """构建测试用的分析技能定义"""
    return {
        "phase": phase,
        "name": name,
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


class TestAnalysisSkillStore:
    """IAnalysisSkillStore 协议实现测试"""

    def test_save_and_load_analysis_skill(self, skill_store):
        """测试保存和加载分析技能"""
        definition = _make_analysis_skill_definition()

        skill_store.save_analysis_skill(
            name="roshan_timing",
            skill_definition=definition,
        )

        loaded = skill_store.load_analysis_skill("roshan_timing")
        assert loaded is not None
        assert loaded["phase"] == "roshan_timing"
        assert loaded["name"] == "Roshan时机分析"
        assert loaded["_source"] == "custom"
        assert loaded["_file_name"] == "roshan_timing"

    def test_load_nonexistent_analysis_skill(self, skill_store):
        """测试加载不存在的分析技能"""
        loaded = skill_store.load_analysis_skill("not_found")
        assert loaded is None

    def test_list_analysis_skills(self, skill_store):
        """测试列出所有分析技能"""
        skill_store.save_analysis_skill(
            name="skill_1",
            skill_definition=_make_analysis_skill_definition("phase_1", "技能1"),
        )
        skill_store.save_analysis_skill(
            name="skill_2",
            skill_definition=_make_analysis_skill_definition("phase_2", "技能2"),
        )

        skills = skill_store.list_analysis_skills()
        assert len(skills) == 2
        phases = [s["phase"] for s in skills]
        assert "phase_1" in phases
        assert "phase_2" in phases

    def test_analysis_skills_in_separate_dir(self, skill_store, temp_dir):
        """测试分析技能存储在 analysis/ 子目录"""
        skill_store.save_analysis_skill(
            name="test_skill",
            skill_definition=_make_analysis_skill_definition(),
        )

        # 验证文件存在于 analysis/ 子目录
        analysis_dir = Path(temp_dir) / "skills" / "analysis"
        yaml_file = analysis_dir / "test_skill.yaml"
        assert yaml_file.exists()

        # 验证根目录不存在同名文件
        root_file = Path(temp_dir) / "skills" / "test_skill.yaml"
        assert not root_file.exists()

    def test_overwrite_analysis_skill(self, skill_store):
        """测试覆盖保存分析技能"""
        definition_v1 = _make_analysis_skill_definition(name="V1")
        skill_store.save_analysis_skill("test", definition_v1)

        definition_v2 = _make_analysis_skill_definition(name="V2")
        skill_store.save_analysis_skill("test", definition_v2)

        loaded = skill_store.load_analysis_skill("test")
        assert loaded["name"] == "V2"

    def test_analysis_skill_yaml_format(self, skill_store, temp_dir):
        """测试分析技能以正确 YAML 格式存储"""
        definition = _make_analysis_skill_definition()
        skill_store.save_analysis_skill("format_test", definition)

        # 直接读取 YAML 文件验证格式
        yaml_path = Path(temp_dir) / "skills" / "analysis" / "format_test.yaml"
        with open(yaml_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)

        assert loaded["phase"] == "roshan_timing"
        assert "data_requirements" in loaded
        assert "output_schema" in loaded


class TestBuiltinSkills:
    """内置分析技能（prompts/skills/ 目录）测试"""

    def test_load_builtin_skill_not_found(self, skill_store):
        """测试加载不存在的内置技能"""
        loaded = skill_store.load_builtin_skill("nonexistent_skill")
        assert loaded is None

    def test_list_builtin_skills_empty_dir(self, skill_store):
        """测试 prompts/skills/ 不存在时返回空列表"""
        skills = skill_store.list_builtin_skills()
        # prompts/skills/ 可能尚未创建，应返回空列表
        assert isinstance(skills, list)

    def test_load_builtin_skill_with_metadata(self, skill_store):
        """测试内置技能包含 _source 标记"""
        # 先创建一个内置技能文件用于测试
        prompts_skills_dir = (
            Path(__file__).parent.parent.parent / "prompts" / "skills"
        )
        if not prompts_skills_dir.exists():
            pytest.skip("prompts/skills/ 目录尚未创建")

        yaml_files = list(prompts_skills_dir.glob("*.yaml"))
        if not yaml_files:
            pytest.skip("prompts/skills/ 目录中无 YAML 文件")

        # 尝试加载第一个内置技能
        first_name = yaml_files[0].stem
        loaded = skill_store.load_builtin_skill(first_name)
        if loaded is not None:
            assert loaded["_source"] == "builtin"


class TestExperienceSkillsUnaffected:
    """回归测试：经验技能功能不受影响"""

    def test_save_and_load_experience_skill(self, skill_store):
        """测试原有经验技能保存加载仍然正常"""
        content = "# 对抗幻影刺客分析要点\n\n## 对线期\n- PA 在 6 级前较弱"
        metadata = {
            "description": "对抗幻影刺客的分析模式",
            "confidence": 0.75,
        }

        skill_store.save_skill(
            name="against_pa",
            content=content,
            metadata=metadata,
        )

        loaded = skill_store.load_skill("against_pa")
        assert loaded is not None
        assert loaded["name"] == "against_pa"
        assert loaded["version"] == 1
        assert "PA" in loaded["content"]

    def test_list_experience_skills(self, skill_store):
        """测试列出经验技能不影响分析技能"""
        skill_store.save_skill(
            name="exp_1",
            content="Content 1",
            metadata={"description": "Exp 1"},
        )
        skill_store.save_analysis_skill(
            name="analysis_1",
            skill_definition=_make_analysis_skill_definition(),
        )

        # list_skills 仅返回经验技能
        exp_skills = skill_store.list_skills()
        assert len(exp_skills) == 1
        assert exp_skills[0]["name"] == "exp_1"

        # list_analysis_skills 仅返回分析技能
        analysis_skills = skill_store.list_analysis_skills()
        assert len(analysis_skills) == 1
        assert analysis_skills[0]["phase"] == "roshan_timing"

    def test_dual_format_coexistence(self, skill_store):
        """测试同名经验技能和分析技能共存"""
        # 经验技能
        skill_store.save_skill(
            name="roshan",
            content="Roshan 经验知识",
            metadata={"description": "经验"},
        )
        # 分析技能
        skill_store.save_analysis_skill(
            name="roshan",
            skill_definition=_make_analysis_skill_definition("roshan", "Roshan分析"),
        )

        # 两者独立加载
        exp = skill_store.load_skill("roshan")
        analysis = skill_store.load_analysis_skill("roshan")

        assert exp is not None
        assert analysis is not None
        assert "经验知识" in exp["content"]
        assert analysis["phase"] == "roshan"
