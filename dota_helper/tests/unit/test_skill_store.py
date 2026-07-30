"""技能存储单元测试"""
import tempfile
from pathlib import Path

import pytest

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


class TestSkillStoreCapacityProtection:
    """SkillStore 容量保护测试（差异8 消除）"""

    def test_max_skills_limits_experience_skills(self, temp_dir):
        """测试 max_skills 限制经验技能数量"""
        skills_dir = Path(temp_dir) / "skills_limited"
        store = SkillStore(str(skills_dir), max_skills=3)

        # 保存 3 个技能（达到上限）
        for i in range(3):
            store.save_skill(
                name=f"skill_{i}",
                content=f"Content {i}",
                metadata={"description": f"Skill {i}"},
            )

        assert len(store.list_skills()) == 3

        # 保存第 4 个技能，应触发淘汰
        store.save_skill(
            name="skill_new",
            content="New content",
            metadata={"description": "New skill"},
        )

        # 总数仍为 3（淘汰了最旧的）
        assert len(store.list_skills()) == 3
        names = [s["name"] for s in store.list_skills()]
        assert "skill_new" in names

    def test_update_existing_skill_does_not_trigger_eviction(self, temp_dir):
        """测试更新已有技能不触发淘汰"""
        skills_dir = Path(temp_dir) / "skills_update"
        store = SkillStore(str(skills_dir), max_skills=2)

        store.save_skill(name="skill_a", content="A", metadata={"description": "A"})
        store.save_skill(name="skill_b", content="B", metadata={"description": "B"})

        # 更新已有技能，不应淘汰
        store.save_skill(name="skill_a", content="A updated", metadata={"description": "A2"})

        skills = store.list_skills()
        assert len(skills) == 2

    def test_max_skills_limits_analysis_skills(self, temp_dir):
        """测试 max_skills 限制分析技能数量"""
        skills_dir = Path(temp_dir) / "analysis_limited"
        store = SkillStore(str(skills_dir), max_skills=2)

        store.save_analysis_skill("analy_a", {"name": "A"})
        store.save_analysis_skill("analy_b", {"name": "B"})

        # 保存第 3 个，应触发淘汰
        store.save_analysis_skill("analy_c", {"name": "C"})

        skills = store.list_analysis_skills()
        assert len(skills) == 2
        names = [s["name"] for s in skills]
        assert "C" in names

    def test_default_max_skills_is_50(self, temp_dir):
        """测试默认 max_skills 为 50"""
        skills_dir = Path(temp_dir) / "skills_default"
        store = SkillStore(str(skills_dir))
        assert store._max_skills == 50
