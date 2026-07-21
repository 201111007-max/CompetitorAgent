"""后台审查器单元测试"""
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
from post_match_review.orchestrator.background_reviewer import BackgroundReviewer


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    # 手动清理，忽略文件锁定错误
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
def mock_llm():
    """创建 Mock LLM 客户端"""
    mock = AsyncMock()
    mock.chat = AsyncMock(
        side_effect=[
            # 质量评估响应
            json.dumps({
                "data_support": 0.8,
                "analysis_depth": 0.7,
                "actionability": 0.6,
                "completeness": 0.9,
                "overall_score": 0.75,
                "comments": "分析质量良好",
            }),
            # 模式提取响应
            json.dumps([
                {
                    "name": "test_pattern",
                    "type": "note",
                    "description": "测试模式",
                    "content": "这是一个测试模式",
                    "category": "general",
                    "confidence": 0.8,
                    "evidence": ["证据1", "证据2"],
                    "tags": ["test"],
                }
            ]),
        ]
    )
    return mock


class TestBackgroundReviewer:
    """BackgroundReviewer 测试"""

    @pytest.mark.asyncio
    async def test_spawn_creates_task(self, mock_llm, memory_system):
        """测试 spawn 创建后台任务"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
            config={"confidence_threshold": 0.7},
        )

        match_data = MagicMock()
        match_data.match_id = "test_match_001"
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.markdown_report = "# 测试报告\n\n## 关键发现\n- 发现1"
        report.key_findings = ["发现1", "发现2"]

        reviewer.spawn(match_data, report)

        assert reviewer._task is not None
        assert not reviewer._task.done()

        await reviewer.wait_for_completion()

        assert reviewer._task.done()

    @pytest.mark.asyncio
    async def test_review_worker_archives_session(self, mock_llm, memory_system):
        """测试审查工作流归档会话"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        match_data = MagicMock()
        match_data.match_id = "test_match_002"
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.markdown_report = "# 测试报告"
        report.key_findings = ["发现1"]

        reviewer.spawn(match_data, report)
        await reviewer.wait_for_completion()

        archived = await memory_system.session_archive.query_by_match_id("test_match_002")
        assert len(archived) == 1
        assert archived[0]["quality_score"] is not None

    @pytest.mark.asyncio
    async def test_review_worker_handles_llm_failure(self, memory_system):
        """测试 LLM 失败时的降级处理"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM error"))

        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        match_data = MagicMock()
        match_data.match_id = "test_match_003"
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.markdown_report = "# 测试报告"
        report.key_findings = ["发现1"]

        reviewer.spawn(match_data, report)
        await reviewer.wait_for_completion()

        archived = await memory_system.session_archive.query_by_match_id("test_match_003")
        assert len(archived) == 1
        assert archived[0]["quality_score"] is not None

    @pytest.mark.asyncio
    async def test_assess_quality(self, mock_llm, memory_system):
        """测试质量评估"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        report = MagicMock()
        report.markdown_report = "# 测试报告\n\n## 关键发现\n- 发现1"
        report.key_findings = ["发现1", "发现2"]

        quality = await reviewer._assess_quality(report)

        assert "data_support" in quality
        assert "analysis_depth" in quality
        assert "actionability" in quality
        assert "completeness" in quality
        assert "overall_score" in quality
        assert quality["overall_score"] == 0.75

    @pytest.mark.asyncio
    async def test_extract_patterns(self, memory_system):
        """测试模式提取"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            return_value=json.dumps([
                {
                    "name": "test_pattern",
                    "type": "note",
                    "description": "测试模式",
                    "content": "这是一个测试模式",
                    "category": "general",
                    "confidence": 0.8,
                    "evidence": ["证据1", "证据2"],
                    "tags": ["test"],
                }
            ])
        )

        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        match_data = MagicMock()
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.markdown_report = "# 测试报告"
        report.key_findings = ["发现1"]

        patterns = await reviewer._extract_patterns(match_data, report)

        assert len(patterns) >= 1
        assert patterns[0]["name"] == "test_pattern"
        assert patterns[0]["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_spawn_does_not_block(self, mock_llm, memory_system):
        """测试 spawn 不阻塞主流程"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        match_data = MagicMock()
        match_data.match_id = "test_match_004"
        match_data.duration = 2400
        match_data.radiant_win = True

        report = MagicMock()
        report.markdown_report = "# 测试报告"
        report.key_findings = ["发现1"]

        reviewer.spawn(match_data, report)

        task_created = reviewer._task is not None
        assert task_created

        task_done_immediately = reviewer._task.done()
        assert not task_done_immediately

        await reviewer.wait_for_completion()

    def test_serialize_report(self, mock_llm, memory_system):
        """测试报告序列化"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        report = MagicMock()
        report.match_id = "test_match"
        report.overall_score = 0.8
        report.key_findings = ["发现1", "发现2"]

        serialized = reviewer._serialize_report(report)

        assert "match_id" in serialized
        assert "overall_score" in serialized
        assert serialized["match_id"] == "test_match"

    def test_parse_quality_response_valid_json(self, mock_llm, memory_system):
        """测试解析有效的 JSON 响应"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        response = json.dumps({
            "data_support": 0.8,
            "analysis_depth": 0.7,
            "actionability": 0.6,
            "completeness": 0.9,
            "overall_score": 0.75,
        })

        result = reviewer._parse_quality_response(response)

        assert result["overall_score"] == 0.75

    def test_parse_quality_response_with_markdown(self, mock_llm, memory_system):
        """测试解析带 Markdown 代码块的响应"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        response = """```json
{
  "data_support": 0.8,
  "analysis_depth": 0.7,
  "actionability": 0.6,
  "completeness": 0.9,
  "overall_score": 0.75
}
```"""

        result = reviewer._parse_quality_response(response)

        assert result["overall_score"] == 0.75

    def test_parse_quality_response_invalid_json(self, mock_llm, memory_system):
        """测试解析无效的 JSON 响应"""
        reviewer = BackgroundReviewer(
            llm_client=mock_llm,
            memory=memory_system,
        )

        response = "invalid json"

        result = reviewer._parse_quality_response(response)

        assert result["overall_score"] == 0.5
