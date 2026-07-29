"""数据持久化测试 — ReviewRepository + ProgressStore + MatchDataCache 集成"""
import asyncio
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from dota_helper.data_path_manager import DataPathManager
from dota_helper.persistence.review_repository import ReviewRepository
from dota_helper.persistence.progress_store import ProgressStore
from dota_helper.domain_types.report import ReviewReport, MatchSummary
from dota_helper.domain_types.analysis import AnalysisResult, Conclusion
from dota_helper.domain_types.state import ReviewAgentState
from dota_helper.domain_types.match_data import MatchData
from dota_helper.data_source.cache import MatchDataCache


# ── ReviewRepository 测试 ──

class TestReviewRepository:
    """复盘报告持久化仓库测试"""

    @pytest.mark.asyncio
    async def test_save_and_load_report(self) -> None:
        """保存并加载报告"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            repo = ReviewRepository(pm)

            report = ReviewReport(
                match_id="123456",
                match_summary=MatchSummary(
                    match_id="123456", duration=2400, radiant_win=True,
                    radiant_score=30, dire_score=28, user_hero="Anti-Mage",
                    user_team_win=True,
                ),
                overall_score=0.75,
                overall_confidence=0.85,
                key_findings=["发现1", "发现2"],
                improvement_areas=["改进1"],
                terminal_state="completed",
            )

            path = await repo.save(report)
            assert path.exists()

            loaded = await repo.load("123456")
            assert loaded is not None
            assert loaded.match_id == "123456"
            assert loaded.overall_score == 0.75
            assert loaded.overall_confidence == 0.85
            assert len(loaded.key_findings) == 2

    @pytest.mark.asyncio
    async def test_load_nonexistent_report(self) -> None:
        """加载不存在的报告返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            repo = ReviewRepository(pm)

            result = await repo.load("nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_exists_check(self) -> None:
        """检查报告是否存在"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            repo = ReviewRepository(pm)

            assert await repo.exists("999") is False

            report = ReviewReport(
                match_id="999",
                match_summary=MatchSummary(
                    match_id="999", duration=1800, radiant_win=False,
                    radiant_score=20, dire_score=25, user_hero="Axe",
                    user_team_win=False,
                ),
            )
            await repo.save(report)

            assert await repo.exists("999") is True

    @pytest.mark.asyncio
    async def test_list_reviews(self) -> None:
        """列出报告摘要"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            repo = ReviewRepository(pm)

            # 保存两个报告
            for mid in ["111", "222"]:
                report = ReviewReport(
                    match_id=mid,
                    match_summary=MatchSummary(
                        match_id=mid, duration=2000, radiant_win=True,
                        radiant_score=30, dire_score=20, user_hero="Sven",
                        user_team_win=True,
                    ),
                    overall_score=0.8,
                    overall_confidence=0.9,
                )
                await repo.save(report)

            summaries = await repo.list_reviews()
            assert len(summaries) == 2
            match_ids = {s["match_id"] for s in summaries}
            assert "111" in match_ids
            assert "222" in match_ids

    @pytest.mark.asyncio
    async def test_list_reviews_with_limit(self) -> None:
        """列出报告摘要带限制"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            repo = ReviewRepository(pm)

            for i in range(5):
                report = ReviewReport(
                    match_id=f"match_{i}",
                    match_summary=MatchSummary(
                        match_id=f"match_{i}", duration=2000, radiant_win=True,
                        radiant_score=30, dire_score=20, user_hero="Sven",
                        user_team_win=True,
                    ),
                )
                await repo.save(report)

            summaries = await repo.list_reviews(limit=3)
            assert len(summaries) == 3


# ── ProgressStore 测试 ──

class TestProgressStore:
    """进度快照持久化测试"""

    @pytest.mark.asyncio
    async def test_save_and_load_snapshot(self) -> None:
        """保存并加载进度快照"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            store = ProgressStore(pm)

            state = ReviewAgentState(match_id="789012")
            state.completed_phases = ["laning", "teamfight"]
            state.confidence = 0.75
            state.total_iterations = 4
            state.total_tokens = 2000

            path = await store.save_snapshot(state)
            assert path.exists()

            loaded = await store.load_snapshot("789012")
            assert loaded is not None
            assert loaded.match_id == "789012"
            assert loaded.completed_phases == ["laning", "teamfight"]
            assert loaded.confidence == 0.75
            assert loaded.total_iterations == 4

    @pytest.mark.asyncio
    async def test_load_nonexistent_snapshot(self) -> None:
        """加载不存在的快照返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            store = ProgressStore(pm)

            result = await store.load_snapshot("nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_clear_snapshot(self) -> None:
        """清除进度快照"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            store = ProgressStore(pm)

            state = ReviewAgentState(match_id="clear_test")
            await store.save_snapshot(state)
            assert await store.has_snapshot("clear_test") is True

            await store.clear_snapshot("clear_test")
            assert await store.has_snapshot("clear_test") is False

    @pytest.mark.asyncio
    async def test_clear_nonexistent_snapshot(self) -> None:
        """清除不存在的快照不报错"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            store = ProgressStore(pm)

            # 不应抛出异常
            await store.clear_snapshot("nonexistent")

    @pytest.mark.asyncio
    async def test_has_snapshot(self) -> None:
        """检查快照是否存在"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = DataPathManager(data_dir=tmpdir)
            store = ProgressStore(pm)

            assert await store.has_snapshot("check_test") is False

            state = ReviewAgentState(match_id="check_test")
            await store.save_snapshot(state)

            assert await store.has_snapshot("check_test") is True


# ── MatchDataCache 集成测试 ──

class TestMatchDataCacheIntegration:
    """MatchDataCache 与 MatchFetcher 集成测试"""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_network(self) -> None:
        """缓存命中时跳过网络请求"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = MatchDataCache(cache_dir=tmpdir, ttl=3600)

            # 预写入缓存
            match_data = MatchData(
                match_id="cached_match", duration=2400, radiant_win=True,
                radiant_score=30, dire_score=28, game_mode=22,
                players=[], picks_bans=[],
            )
            cache.write(match_data)

            # 创建带缓存的 MatchFetcher
            mock_client = AsyncMock()
            fetcher = self._create_fetcher(mock_client, cache)

            result = await fetcher.fetch_and_parse("cached_match")

            # 应返回缓存数据，不调用网络
            assert result.match_id == "cached_match"
            mock_client.get_match_details.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_network(self) -> None:
        """缓存未命中时走网络并写入缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = MatchDataCache(cache_dir=tmpdir, ttl=3600)

            # Mock 网络返回
            mock_client = AsyncMock()
            mock_client.get_match_details.return_value = {
                "match_id": 123, "duration": 1800,
                "radiant_win": True, "radiant_score": 20,
                "dire_score": 15, "game_mode": 22,
                "players": [], "picks_bans": [],
            }

            fetcher = self._create_fetcher(mock_client, cache)

            result = await fetcher.fetch_and_parse("123")

            # 应调用网络
            mock_client.get_match_details.assert_called_once_with("123")
            # 结果应写入缓存
            cached = cache.read("123")
            assert cached is not None

    @pytest.mark.asyncio
    async def test_no_cache_works_normally(self) -> None:
        """无缓存时正常工作"""
        mock_client = AsyncMock()
        mock_client.get_match_details.return_value = {
            "match_id": 456, "duration": 2400,
            "radiant_win": False, "radiant_score": 25,
            "dire_score": 30, "game_mode": 22,
            "players": [], "picks_bans": [],
        }

        fetcher = self._create_fetcher(mock_client, cache=None)
        result = await fetcher.fetch_and_parse("456")
        assert result is not None

    def _create_fetcher(self, client: AsyncMock, cache: Optional[MatchDataCache]) -> Any:
        """创建 MatchFetcher 实例"""
        from dota_helper.data_source.match_fetcher import MatchFetcher
        return MatchFetcher(client=client, cache=cache)
