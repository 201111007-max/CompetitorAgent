"""四层记忆系统单元测试"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from post_match_review.memory import (
    DreamRecap,
    FourLayerMemory,
    PersistentNotes,
    SessionArchive,
    SkillStore,
)


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    # 手动清理，忽略文件锁定错误
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def session_archive(temp_dir):
    """创建 SessionArchive 实例"""
    db_path = Path(temp_dir) / "test_archive.db"
    return SessionArchive(str(db_path), max_entries=10)


@pytest.fixture
def persistent_notes(temp_dir):
    """创建 PersistentNotes 实例"""
    json_path = Path(temp_dir) / "test_notes.json"
    return PersistentNotes(str(json_path), max_entries=10)


@pytest.fixture
def skill_store(temp_dir):
    """创建 SkillStore 实例"""
    skills_dir = Path(temp_dir) / "skills"
    return SkillStore(str(skills_dir))


@pytest.fixture
def four_layer_memory(session_archive, persistent_notes, skill_store, temp_dir):
    """创建 FourLayerMemory 实例"""
    return FourLayerMemory(
        session_archive=session_archive,
        persistent_notes=persistent_notes,
        skill_store=skill_store,
        data_dir=temp_dir,
    )


class TestSessionArchive:
    """SessionArchive 测试"""

    @pytest.mark.asyncio
    async def test_archive_and_query(self, session_archive):
        """测试归档和查询"""
        report = {"key_findings": ["发现1", "发现2"], "overall_score": 0.8}
        metadata = {"quality_score": 0.85, "heroes": ["PA", "Juggernaut"]}

        await session_archive.archive(
            match_id="test_match_001",
            report=report,
            quality_score=0.85,
            metadata=metadata,
        )

        results = await session_archive.query_by_match_id("test_match_001")
        assert len(results) == 1
        assert results[0]["match_id"] == "test_match_001"
        assert results[0]["quality_score"] == 0.85
        assert results[0]["report"]["key_findings"] == ["发现1", "发现2"]

    @pytest.mark.asyncio
    async def test_query_by_hero(self, session_archive):
        """测试按英雄查询"""
        report = {"findings": ["test"]}
        metadata = {"heroes": ["PA", "Invoker"]}

        await session_archive.archive(
            match_id="match_001",
            report=report,
            metadata=metadata,
        )

        results = await session_archive.query_by_hero("PA")
        assert len(results) == 1
        assert results[0]["match_id"] == "match_001"

    @pytest.mark.asyncio
    async def test_cleanup_old_entries(self, temp_dir):
        """测试清理旧条目"""
        db_path = Path(temp_dir) / "cleanup_test.db"
        archive = SessionArchive(str(db_path), max_entries=3)

        for i in range(5):
            await archive.archive(
                match_id=f"match_{i}",
                report={"index": i},
            )

        count = await archive.get_count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_query_by_time_range(self, session_archive):
        """测试按时间范围查询"""
        await session_archive.archive(
            match_id="match_001",
            report={"test": 1},
        )

        from datetime import datetime, timedelta

        start = (datetime.now() - timedelta(hours=1)).isoformat()
        end = (datetime.now() + timedelta(hours=1)).isoformat()

        results = await session_archive.query_by_time_range(start, end)
        assert len(results) >= 1


class TestPersistentNotes:
    """PersistentNotes 测试"""

    @pytest.mark.asyncio
    async def test_add_and_query(self, persistent_notes):
        """测试添加和查询笔记"""
        await persistent_notes.add_note(
            category="laning",
            content="PA 对线期较弱，需要关注补刀压制",
            evidence=["补刀数低于理论值 60%", "血量消耗比劣势"],
        )

        results = await persistent_notes.query("PA 对线", top_k=5)
        assert len(results) >= 1
        assert results[0]["category"] == "laning"
        assert "PA" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_query_by_category(self, persistent_notes):
        """测试按类别查询"""
        await persistent_notes.add_note(
            category="laning",
            content="对线期要点",
            evidence=["evidence1"],
        )
        await persistent_notes.add_note(
            category="teamfight",
            content="团战要点",
            evidence=["evidence2"],
        )

        results = await persistent_notes.get_by_category("laning")
        assert len(results) == 1
        assert results[0]["category"] == "laning"

    @pytest.mark.asyncio
    async def test_cleanup_old_notes(self, temp_dir):
        """测试清理旧笔记"""
        json_path = Path(temp_dir) / "cleanup_notes.json"
        notes = PersistentNotes(str(json_path), max_entries=3)

        for i in range(5):
            await notes.add_note(
                category="test",
                content=f"Note {i}",
                evidence=[f"evidence_{i}"],
            )

        count = await notes.get_count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_delete_note(self, persistent_notes):
        """测试删除笔记"""
        await persistent_notes.add_note(
            category="test",
            content="Test note",
            evidence=["evidence"],
        )

        notes = await persistent_notes.get_by_category("test")
        assert len(notes) == 1

        note_id = notes[0]["id"]
        deleted = await persistent_notes.delete_note(note_id)
        assert deleted is True

        count = await persistent_notes.get_count()
        assert count == 0


class TestFourLayerMemory:
    """FourLayerMemory 测试"""

    @pytest.mark.asyncio
    async def test_archive_session(self, four_layer_memory):
        """测试归档会话"""
        report = {"findings": ["test"]}
        metadata = {"quality_score": 0.8}

        await four_layer_memory.archive_session(
            match_id="test_match",
            report=report,
            metadata=metadata,
        )

        results = await four_layer_memory.session_archive.query_by_match_id("test_match")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_add_and_query_notes(self, four_layer_memory):
        """测试添加和查询笔记"""
        await four_layer_memory.add_persistent_note(
            category="laning",
            content="对线期要点",
            evidence=["evidence1"],
        )

        results = await four_layer_memory.query_persistent_notes("对线", top_k=5)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_load_skills(self, four_layer_memory):
        """测试加载技能"""
        four_layer_memory.skill_store.save_skill(
            name="test_skill",
            content="Test content",
            metadata={"description": "Test"},
        )

        skills = await four_layer_memory.load_skills()
        assert len(skills) >= 1


class TestDreamRecap:
    """DreamRecap 测试"""

    @pytest.mark.asyncio
    async def test_integrate_with_mock_llm(self, persistent_notes, skill_store):
        """测试整合功能（使用 Mock LLM）"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            side_effect=[
                # 第一次调用：提取洞察
                json.dumps([
                    {
                        "insight": "PA 对线期较弱",
                        "category": "laning",
                        "confidence": 0.8,
                        "evidence": ["补刀数低"],
                    }
                ]),
                # 第二次调用：识别模式
                json.dumps([
                    {
                        "name": "against_pa",
                        "type": "skill",
                        "description": "对抗 PA 模式",
                        "content": "PA 对线期压制要点",
                        "category": "hero_counter",
                        "confidence": 0.75,
                        "evidence": ["证据"],
                        "tags": ["pa"],
                    }
                ]),
            ]
        )

        dream_recap = DreamRecap(
            llm_client=mock_llm,
            persistent_notes=persistent_notes,
            skill_store=skill_store,
        )

        match_data = MagicMock()
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.summary = "测试报告摘要"

        result = await dream_recap.integrate(match_data, report)

        assert result["persisted_skills"] >= 1 or result["persisted_notes"] >= 1
        assert mock_llm.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_integrate_handles_llm_failure(self, persistent_notes, skill_store):
        """测试 LLM 失败时的降级处理"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM error"))

        dream_recap = DreamRecap(
            llm_client=mock_llm,
            persistent_notes=persistent_notes,
            skill_store=skill_store,
        )

        match_data = MagicMock()
        report = MagicMock()

        result = await dream_recap.integrate(match_data, report)

        assert "error" in result
        assert result["persisted_notes"] == 0
        assert result["persisted_skills"] == 0
