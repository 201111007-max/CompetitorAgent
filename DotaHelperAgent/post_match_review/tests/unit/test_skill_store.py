"""技能存储单元测试"""
import tempfile
from pathlib import Path

import pytest

from post_match_review.memory.skill_store import SkillStore


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


class TestSkillStore:
    """SkillStore 测试"""

    def test_save_and_load_skill(self, skill_store):
        """测试保存和加载技能"""
        content = """# 对抗幻影刺客分析要点

## 对线期
- PA 在 6 级前较弱

## 关键时间节点
- 6 级: 解锁大招
"""
        metadata = {
            "description": "对抗幻影刺客的分析模式",
            "confidence": 0.75,
            "source_match": "8893253595",
            "tags": ["hero_counter", "pa"],
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
        assert loaded["confidence"] == 0.75
        assert "PA" in loaded["content"]

    def test_version_increment(self, skill_store):
        """测试版本号自增"""
        content_v1 = "Version 1 content"
        skill_store.save_skill(
            name="test_skill",
            content=content_v1,
            metadata={"description": "Test"},
        )

        content_v2 = "Version 2 content"
        skill_store.save_skill(
            name="test_skill",
            content=content_v2,
            metadata={"description": "Test updated"},
        )

        loaded = skill_store.load_skill("test_skill")
        assert loaded is not None
        assert loaded["version"] == 2
        assert "Version 2" in loaded["content"]

    def test_list_skills(self, skill_store):
        """测试列出所有技能"""
        skill_store.save_skill(
            name="skill_1",
            content="Content 1",
            metadata={"description": "Skill 1"},
        )
        skill_store.save_skill(
            name="skill_2",
            content="Content 2",
            metadata={"description": "Skill 2"},
        )

        skills = skill_store.list_skills()
        assert len(skills) == 2
        names = [s["name"] for s in skills]
        assert "skill_1" in names
        assert "skill_2" in names

    def test_check_conflict(self, skill_store):
        """测试冲突检测"""
        content = "对抗幻影刺客的分析模式，PA 在 6 级前较弱"
        skill_store.save_skill(
            name="against_pa",
            content=content,
            metadata={"description": "Test"},
        )

        similar_content = "对抗幻影刺客的分析模式，PA 在 6 级前较弱，需要压制补刀"
        conflict = skill_store.check_conflict("against_pa", similar_content)

        assert conflict is not None
        assert conflict["conflict"] is True
        assert conflict["similarity"] > 0.5
        assert conflict["recommendation"] in ["update", "merge"]

    def test_check_conflict_no_existing(self, skill_store):
        """测试不存在技能时的冲突检测"""
        conflict = skill_store.check_conflict("non_existent", "任意内容")
        assert conflict is None

    def test_load_nonexistent_skill(self, skill_store):
        """测试加载不存在的技能"""
        loaded = skill_store.load_skill("not_found")
        assert loaded is None
