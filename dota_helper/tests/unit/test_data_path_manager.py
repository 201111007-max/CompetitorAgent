"""DataPathManager 统一数据路径管理测试"""
import tempfile
from pathlib import Path

import pytest

from dota_helper.data_path_manager import DataPathManager, DEFAULT_DATA_DIR


class TestDataPathManager:
    """DataPathManager 核心功能测试"""

    def test_default_data_dir(self) -> None:
        """默认数据目录为 ~/.dota_helper/data/"""
        manager = DataPathManager()
        assert manager.data_dir == DEFAULT_DATA_DIR
        assert manager.data_dir == Path.home() / ".dota_helper" / "data"

    def test_custom_data_dir(self) -> None:
        """自定义数据目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            assert manager.data_dir == Path(tmpdir)

    def test_subdir_properties(self) -> None:
        """子目录属性返回正确路径"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            base = Path(tmpdir)

            assert manager.memory_dir == base / "memory"
            assert manager.skills_dir == base / "skills"
            assert manager.sessions_dir == base / "sessions"
            assert manager.reviews_dir == base / "reviews"
            assert manager.progress_dir == base / "progress"
            assert manager.cache_dir == base / "cache"
            assert manager.ward_analysis_dir == base / "ward_analysis"

    def test_ensure_dirs_creates_all(self) -> None:
        """ensure_dirs 创建所有必要目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            manager.ensure_dirs()

            assert manager.memory_dir.exists()
            assert manager.skills_dir.exists()
            assert manager.sessions_dir.exists()
            assert manager.reviews_dir.exists()
            assert manager.progress_dir.exists()
            assert manager.cache_dir.exists()
            assert manager.ward_analysis_dir.exists()

    def test_ensure_dirs_idempotent(self) -> None:
        """ensure_dirs 多次调用不报错"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            manager.ensure_dirs()
            manager.ensure_dirs()  # 第二次调用不应报错
            assert manager.memory_dir.exists()

    def test_get_review_path(self) -> None:
        """复盘报告路径生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            path = manager.get_review_path("123456")
            assert path == Path(tmpdir) / "reviews" / "123456.json"

    def test_get_progress_path(self) -> None:
        """进度快照路径生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            path = manager.get_progress_path("789012")
            assert path == Path(tmpdir) / "progress" / "789012.json"

    def test_get_cache_path(self) -> None:
        """缓存文件路径生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            path = manager.get_cache_path("345678")
            assert path == Path(tmpdir) / "cache" / "345678.json"

    def test_get_session_path(self) -> None:
        """会话文件路径生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DataPathManager(data_dir=tmpdir)
            path = manager.get_session_path("sess_abc123")
            assert path == Path(tmpdir) / "sessions" / "sess_abc123.json"

    def test_none_data_dir_uses_default(self) -> None:
        """data_dir=None 时使用默认路径"""
        manager = DataPathManager(data_dir=None)
        assert manager.data_dir == DEFAULT_DATA_DIR
