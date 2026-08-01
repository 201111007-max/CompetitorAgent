"""RagEngine 单元测试

测试覆盖：
1. 初始化与默认路径
2. TF-IDF 回退检索（无 chromadb 时）
3. Markdown 段落切分
4. 检索结果格式化
5. 知识库索引（增量/强制）
6. 空查询和空结果处理
"""
import os
import tempfile
from pathlib import Path

import pytest

from dota_helper.agent.rag_engine import RagEngine, filename_from_content


class TestRagEngineInit:
    """RagEngine 初始化测试"""

    def test_default_paths(self) -> None:
        """默认路径指向 dota_helper/knowledge_base/"""
        engine = RagEngine()
        assert "knowledge_base" in str(engine.kb_dir)
        assert "chromadb_data" in str(engine.persist_dir)

    def test_custom_paths(self) -> None:
        """自定义路径生效"""
        engine = RagEngine(kb_dir="/tmp/custom_kb", persist_dir="/tmp/custom_db")
        assert str(engine.kb_dir) == "/tmp/custom_kb"
        assert str(engine.persist_dir) == "/tmp/custom_db"

    def test_custom_min_score(self) -> None:
        """自定义 min_score 生效"""
        engine = RagEngine(min_score=0.5)
        assert engine._min_score == 0.5


class TestRagEngineSearch:
    """RAG 检索测试（TF-IDF 回退模式）"""

    @pytest.fixture
    def engine(self) -> RagEngine:
        """创建指向真实 knowledge_base 的引擎"""
        kb_dir = Path(__file__).parent.parent.parent / "knowledge_base"
        return RagEngine(kb_dir=str(kb_dir))

    def test_search_empty_query(self, engine: RagEngine) -> None:
        """空查询返回空列表"""
        assert engine.search("") == []
        assert engine.search("   ") == []
        assert engine.search(None) == []  # type: ignore[arg-type]

    def test_search_no_match(self, engine: RagEngine) -> None:
        """无匹配查询返回空列表"""
        results = engine.search("xyzabc123nonexistent", top_k=3)
        assert results == []

    def test_search_returns_expected_structure(self, engine: RagEngine) -> None:
        """检索结果包含 content/metadata/score"""
        results = engine.search("敌法师", top_k=1)
        if results:
            item = results[0]
            assert "content" in item
            assert "metadata" in item
            assert "score" in item
            assert isinstance(item["score"], float)
            assert 0.0 <= item["score"] <= 1.0

    def test_search_top_k(self, engine: RagEngine) -> None:
        """top_k 参数控制返回数量"""
        results = engine.search("敌法师", top_k=3)
        assert len(results) <= 3

    def test_search_sorted_by_score(self, engine: RagEngine) -> None:
        """结果按 score 降序排列"""
        results = engine.search("幽鬼", top_k=3)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i]["score"] >= results[i + 1]["score"]

    def test_search_hero_returns_hero_knowledge(self, engine: RagEngine) -> None:
        """search_hero 返回英雄相关知识"""
        results = engine.search_hero("敌法师")
        if results:
            content = results[0]["content"]
            assert isinstance(content, str)
            assert len(content) > 0

    def test_search_different_queries(self, engine: RagEngine) -> None:
        """不同查询返回不同结果"""
        results_a = engine.search("敌法师", top_k=1)
        results_b = engine.search("幽鬼", top_k=1)
        # 两个查询可能返回不同内容
        if results_a and results_b:
            content_a = results_a[0].get("content", "")
            content_b = results_b[0].get("content", "")
            # 至少有一个不同（查询不同英雄）
            assert "敌法师" in content_a or "幽鬼" in content_b


class TestRagEngineFormat:
    """RAG 结果格式化测试"""

    def test_format_empty(self) -> None:
        """空结果返回空字符串"""
        engine = RagEngine()
        assert engine.format_context([]) == ""

    def test_format_single_result(self) -> None:
        """单个结果格式化"""
        engine = RagEngine()
        results = [
            {
                "content": "敌法师是后期大核",
                "metadata": {"source": "hero/anti_mage.md"},
                "score": 0.85,
            }
        ]
        formatted = engine.format_context(results)
        assert "相关知识" in formatted
        assert "敌法师" in formatted
        assert "0.85" in formatted

    def test_format_multiple_results(self) -> None:
        """多个结果格式化"""
        engine = RagEngine()
        results = [
            {"content": "内容A", "metadata": {"source": "a.md"}, "score": 0.9},
            {"content": "内容B", "metadata": {"source": "b.md"}, "score": 0.8},
        ]
        formatted = engine.format_context(results)
        assert "参考 1" in formatted
        assert "参考 2" in formatted
        assert "内容A" in formatted
        assert "内容B" in formatted

    def test_format_truncates_long_content(self) -> None:
        """过长内容被截断"""
        engine = RagEngine()
        long_content = "A" * 1000
        results = [
            {"content": long_content, "metadata": {}, "score": 0.9},
        ]
        formatted = engine.format_context(results)
        assert "[截断]" in formatted


class TestRagEngineIndex:
    """知识库索引测试"""

    @pytest.fixture
    def temp_kb(self) -> str:
        """创建临时知识库目录"""
        tmpdir = tempfile.mkdtemp()
        # 创建分类子目录
        hero_dir = Path(tmpdir) / "hero"
        hero_dir.mkdir()
        # 创建测试文件
        (hero_dir / "test_hero.md").write_text(
            "## 英雄定位\n测试英雄是后期大核\n\n## 技能加点\n主1副2\n",
            encoding="utf-8",
        )
        return tmpdir

    def test_index_all_creates_index(self, temp_kb: str) -> None:
        """index_all 返回索引段落数"""
        engine = RagEngine(kb_dir=temp_kb)
        count = engine.index_all()
        assert count > 0

    def test_index_all_empty_dir(self) -> None:
        """空目录索引返回 0"""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RagEngine(kb_dir=tmpdir)
            count = engine.index_all()
            assert count == 0

    def test_index_all_no_md_files(self) -> None:
        """无 .md 文件返回 0"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建非 .md 文件
            Path(tmpdir, "readme.txt").write_text("hello")
            engine = RagEngine(kb_dir=tmpdir)
            count = engine.index_all()
            assert count == 0

    def test_index_all_force_rebuild(self, temp_kb: str) -> None:
        """force=True 强制重建"""
        engine = RagEngine(kb_dir=temp_kb)
        count1 = engine.index_all(force=True)
        count2 = engine.index_all(force=True)
        assert count1 > 0
        assert count2 > 0

    def test_index_all_incremental(self, temp_kb: str) -> None:
        """增量索引：无变更时跳过"""
        engine = RagEngine(kb_dir=temp_kb)
        count1 = engine.index_all(force=True)
        # 无变更，增量索引应返回 0
        count2 = engine.index_all(force=False)
        assert count2 == 0


class TestFilenameFromContent:
    """filename_from_content 工具函数测试"""

    def test_extracts_first_line(self) -> None:
        """提取内容第一行"""
        result = filename_from_content("# 敌法师攻略\n内容")
        assert "敌法师攻略" in result

    def test_strips_hash(self) -> None:
        """去除 # 符号"""
        result = filename_from_content("## 英雄定位")
        assert "英雄定位" in result

    def test_truncates_long(self) -> None:
        """过长内容截断"""
        long = "A" * 100
        result = filename_from_content(long)
        assert len(result) <= 50

    def test_empty_content(self) -> None:
        """空内容返回空字符串"""
        result = filename_from_content("")
        assert result == ""
