"""阶段6集成测试 - 完整链路验证"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from post_match_review.memory import (
    FourLayerMemory,
    PersistentNotes,
    SessionArchive,
    SkillStore,
)
from post_match_review.memory.dream_recap import DreamRecap
from post_match_review.orchestrator.background_reviewer import BackgroundReviewer


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def memory_system(temp_dir):
    """创建完整的记忆系统"""
    db_path = Path(temp_dir) / "test_archive.db"
    notes_path = Path(temp_dir) / "test_notes.json"
    skills_dir = Path(temp_dir) / "skills"

    session_archive = SessionArchive(str(db_path))
    persistent_notes = PersistentNotes(str(notes_path))
    skill_store = SkillStore(str(skills_dir))

    return FourLayerMemory(
        session_archive=session_archive,
        persistent_notes=persistent_notes,
        skill_store=skill_store,
        data_dir=temp_dir,
    )


@pytest.fixture
def mock_llm_with_skill():
    """创建返回技能沉淀的 Mock LLM"""
    mock = AsyncMock()
    mock.chat = AsyncMock(
        side_effect=[
            # 质量评估
            json.dumps({
                "data_support": 0.85,
                "analysis_depth": 0.75,
                "actionability": 0.80,
                "completeness": 0.90,
                "overall_score": 0.82,
                "comments": "分析质量良好",
            }),
            # 模式提取 - 返回高置信度技能
            json.dumps([
                {
                    "name": "against_pa",
                    "type": "skill",
                    "description": "对抗幻影刺客的分析模式",
                    "content": """# 对抗幻影刺客分析要点

## 对线期
- PA 在 6 级前较弱，关注其补刀数和血量消耗比
- 如果 PA 补刀低于理论值 60%，说明对线压制成功

## 关键时间节点
- 6 级: PA 解锁大招，gank 能力质变
- 15-20 分钟: 狂战斧/暴击披风时间节点
- 25 分钟+: 团战威胁峰值期

## 反制策略评估维度
- 是否出了刃甲/绿杖等克制物品
- 团战站位是否避开 PA 跳切路线
- 视野是否覆盖 PA 常见 farm 路线
""",
                    "category": "hero_counter",
                    "confidence": 0.85,
                    "evidence": [
                        "PA 6 级前补刀数低于理论值 60%",
                        "团战站位避开跳切路线",
                        "视野覆盖 farm 路线",
                    ],
                    "tags": ["hero_counter", "pa", "carry"],
                }
            ]),
            # DreamRecap 洞察提取
            json.dumps([
                {
                    "insight": "PA 对线期压制成功，补刀数低于理论值",
                    "category": "laning",
                    "confidence": 0.85,
                    "evidence": ["补刀数低于理论值 60%"],
                }
            ]),
            # DreamRecap 模式识别
            json.dumps([
                {
                    "name": "pa_laning_pressure",
                    "type": "note",
                    "description": "PA 对线期压制策略",
                    "content": "PA 在 6 级前较弱，通过补刀压制可有效限制其发育",
                    "category": "laning",
                    "confidence": 0.80,
                    "evidence": ["补刀数低于理论值 60%"],
                    "tags": ["pa", "laning"],
                }
            ]),
        ]
    )
    return mock


@pytest.fixture
def mock_llm_for_dream_recap():
    """创建专门用于 DreamRecap 测试的 Mock LLM"""
    mock = AsyncMock()
    mock.chat = AsyncMock(
        side_effect=[
            # DreamRecap 洞察提取
            json.dumps([
                {
                    "insight": "PA 对线期压制成功，补刀数低于理论值",
                    "category": "laning",
                    "confidence": 0.85,
                    "evidence": ["补刀数低于理论值 60%"],
                }
            ]),
            # DreamRecap 模式识别
            json.dumps([
                {
                    "name": "pa_laning_pressure",
                    "type": "note",
                    "description": "PA 对线期压制策略",
                    "content": "PA 在 6 级前较弱，通过补刀压制可有效限制其发育",
                    "category": "laning",
                    "confidence": 0.80,
                    "evidence": ["补刀数低于理论值 60%"],
                    "tags": ["pa", "laning"],
                }
            ]),
        ]
    )
    return mock


class TestPhase6Integration:
    """阶段6集成测试"""

    @pytest.mark.asyncio
    async def test_full_pipeline_report_to_skill(
        self,
        memory_system,
        mock_llm_with_skill,
    ):
        """测试完整链路：报告生成 → 后台审查 → 归档 → 技能沉淀"""
        # 创建后台审查器
        reviewer = BackgroundReviewer(
            llm_client=mock_llm_with_skill,
            memory=memory_system,
            config={"confidence_threshold": 0.7},
        )

        # 模拟比赛数据
        match_data = MagicMock()
        match_data.match_id = "8893253595"
        match_data.duration = 2400
        match_data.radiant_win = True
        match_data.radiant_score = 35
        match_data.dire_score = 28

        # 模拟复盘报告
        report = MagicMock()
        report.match_id = "8893253595"
        report.overall_score = 0.78
        report.overall_confidence = 0.82
        report.key_findings = [
            "PA 对线期压制成功，补刀数低于理论值 60%",
            "团战站位合理，避开 PA 跳切路线",
            "视野覆盖 PA 常见 farm 路线",
        ]
        report.markdown_report = """# 复盘报告

## 比赛概况
- 比赛 ID: 8893253595
- 比赛时长: 40 分钟
- 胜方: 天辉

## 关键发现
- PA 对线期压制成功，补刀数低于理论值 60%
- 团战站位合理，避开 PA 跳切路线
- 视野覆盖 PA 常见 farm 路线

## 改进建议
- 继续保持对线期压制
- 注意 PA 6 级后的 gank 节奏
"""

        # 启动后台审查
        reviewer.spawn(match_data, report)

        # 等待后台审查完成
        await reviewer.wait_for_completion()

        # 验证会话归档
        archived = await memory_system.session_archive.query_by_match_id("8893253595")
        assert len(archived) == 1
        assert archived[0]["quality_score"] == 0.82
        assert archived[0]["metadata"]["quality_dimensions"]["data_support"] == 0.85

        # 验证技能沉淀
        skills = await memory_system.load_skills()
        assert len(skills) >= 1
        pa_skill = next((s for s in skills if s["name"] == "against_pa"), None)
        assert pa_skill is not None
        assert pa_skill["confidence"] == 0.85
        assert pa_skill["version"] == 1
        assert "PA" in pa_skill["content"]
        assert "hero_counter" in pa_skill["tags"]

        # 验证持久笔记
        notes = await memory_system.query_persistent_notes("PA 对线", top_k=5)
        assert len(notes) >= 1

    @pytest.mark.asyncio
    async def test_skill_version_increment(
        self,
        memory_system,
        mock_llm_with_skill,
    ):
        """测试技能版本自增"""
        # 第一次沉淀
        skill_store = memory_system.skill_store
        skill_store.save_skill(
            name="against_pa",
            content="Version 1 content",
            metadata={
                "description": "对抗 PA 模式",
                "confidence": 0.75,
                "source_match": "match_001",
                "tags": ["pa"],
            },
        )

        skill_v1 = skill_store.load_skill("against_pa")
        assert skill_v1["version"] == 1

        # 第二次沉淀（更新）
        skill_store.save_skill(
            name="against_pa",
            content="Version 2 content with more details",
            metadata={
                "description": "对抗 PA 模式（更新）",
                "confidence": 0.85,
                "source_match": "match_002",
                "tags": ["pa", "carry"],
            },
        )

        skill_v2 = skill_store.load_skill("against_pa")
        assert skill_v2["version"] == 2
        assert skill_v2["confidence"] == 0.85
        assert "Version 2" in skill_v2["content"]

    @pytest.mark.asyncio
    async def test_conflict_detection(
        self,
        memory_system,
    ):
        """测试冲突检测"""
        skill_store = memory_system.skill_store

        # 保存初始技能
        skill_store.save_skill(
            name="test_skill",
            content="对抗幻影刺客的分析模式，PA 在 6 级前较弱",
            metadata={"description": "Test"},
        )

        # 检查相似内容的冲突
        similar_content = "对抗幻影刺客的分析模式，PA 在 6 级前较弱，需要压制补刀"
        conflict = skill_store.check_conflict("test_skill", similar_content)

        assert conflict is not None
        assert conflict["conflict"] is True
        assert conflict["similarity"] > 0.5
        assert conflict["recommendation"] in ["update", "merge"]

    @pytest.mark.asyncio
    async def test_background_review_failure_isolation(
        self,
        memory_system,
    ):
        """测试后台审查失败不影响主流程"""
        # 创建会失败的 LLM
        failing_llm = AsyncMock()
        failing_llm.chat = AsyncMock(side_effect=Exception("LLM service unavailable"))

        reviewer = BackgroundReviewer(
            llm_client=failing_llm,
            memory=memory_system,
        )

        match_data = MagicMock()
        match_data.match_id = "test_match_fail"
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.match_id = "test_match_fail"
        report.overall_score = 0.75
        report.overall_confidence = 0.80
        report.key_findings = ["发现1"]
        report.markdown_report = "# 测试报告"

        # 启动后台审查（应该不抛异常）
        reviewer.spawn(match_data, report)

        # 等待完成
        await reviewer.wait_for_completion()

        # 验证会话仍然被归档（使用默认质量分数）
        archived = await memory_system.session_archive.query_by_match_id("test_match_fail")
        assert len(archived) == 1
        assert archived[0]["quality_score"] == 0.5  # 默认分数

    @pytest.mark.asyncio
    async def test_memory_query_by_hero(
        self,
        memory_system,
    ):
        """测试按英雄查询"""
        # 归档包含英雄信息的会话
        await memory_system.archive_session(
            match_id="match_hero_001",
            report={"findings": ["test"]},
            metadata={
                "quality_score": 0.8,
                "heroes": ["PA", "Invoker"],
            },
        )

        await memory_system.archive_session(
            match_id="match_hero_002",
            report={"findings": ["test"]},
            metadata={
                "quality_score": 0.75,
                "heroes": ["Juggernaut", "Crystal Maiden"],
            },
        )

        # 按英雄查询
        pa_matches = await memory_system.session_archive.query_by_hero("PA")
        assert len(pa_matches) == 1
        assert pa_matches[0]["match_id"] == "match_hero_001"

        jugg_matches = await memory_system.session_archive.query_by_hero("Juggernaut")
        assert len(jugg_matches) == 1
        assert jugg_matches[0]["match_id"] == "match_hero_002"

    @pytest.mark.asyncio
    async def test_dream_recap_integration(
        self,
        memory_system,
        mock_llm_for_dream_recap,
    ):
        """测试 DreamRecap 整合功能"""
        dream_recap = DreamRecap(
            llm_client=mock_llm_for_dream_recap,
            persistent_notes=memory_system.persistent_notes,
            skill_store=memory_system.skill_store,
        )

        match_data = MagicMock()
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.summary = "PA 对线期压制成功，团战站位合理"

        result = await dream_recap.integrate(match_data, report)

        # 验证整合结果
        assert "insights" in result
        assert "patterns" in result
        assert result["persisted_notes"] >= 1 or result["persisted_skills"] >= 1

        # 验证笔记或技能被持久化
        notes = await memory_system.query_persistent_notes("PA", top_k=5)
        skills = await memory_system.load_skills()

        # 至少有一个被持久化
        assert len(notes) >= 1 or len(skills) >= 1
