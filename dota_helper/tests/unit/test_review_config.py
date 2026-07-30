"""ReviewConfig / MemoryConfig 单元测试（差异4/8 消除验证）"""
import tempfile
from pathlib import Path

import pytest
import yaml

from dota_helper.orchestrator.review_config import (
    MemoryConfig,
    ReviewConfig,
    StrategicLoopConfig,
    TacticalLoopConfig,
)


class TestMemoryConfig:
    """MemoryConfig 测试（差异8 消除：新增 max_persistent_notes / max_skills）"""

    def test_default_values(self) -> None:
        """测试默认值"""
        config = MemoryConfig()
        assert config.enabled is True
        assert config.data_dir is None
        assert config.background_review is True
        assert config.confidence_threshold == 0.7
        assert config.max_persistent_notes == 100
        assert config.max_skills == 50

    def test_custom_values(self) -> None:
        """测试自定义值"""
        config = MemoryConfig(
            enabled=False,
            data_dir="/custom/path",
            background_review=False,
            confidence_threshold=0.8,
            max_persistent_notes=200,
            max_skills=30,
        )
        assert config.enabled is False
        assert config.data_dir == "/custom/path"
        assert config.background_review is False
        assert config.confidence_threshold == 0.8
        assert config.max_persistent_notes == 200
        assert config.max_skills == 30


class TestReviewConfigFromDict:
    """ReviewConfig.from_dict() 测试（差异8 消除：解析新增字段）"""

    def test_from_dict_with_memory_capacity_fields(self) -> None:
        """测试 from_dict 解析 max_persistent_notes 和 max_skills"""
        data = {
            "memory": {
                "enabled": True,
                "data_dir": "/data",
                "background_review": False,
                "confidence_threshold": 0.9,
                "max_persistent_notes": 500,
                "max_skills": 100,
            },
        }
        config = ReviewConfig.from_dict(data)
        assert config.memory.max_persistent_notes == 500
        assert config.memory.max_skills == 100
        assert config.memory.confidence_threshold == 0.9

    def test_from_dict_defaults_memory_capacity(self) -> None:
        """测试 from_dict 使用默认容量值"""
        data = {"memory": {"enabled": True}}
        config = ReviewConfig.from_dict(data)
        assert config.memory.max_persistent_notes == 100
        assert config.memory.max_skills == 50

    def test_from_dict_empty_uses_defaults(self) -> None:
        """测试空字典使用全部默认值"""
        config = ReviewConfig.from_dict({})
        assert config.memory.enabled is True
        assert config.memory.max_persistent_notes == 100
        assert config.memory.max_skills == 50
        assert config.model == "gpt-4o-mini"


class TestEntrypointConfigLoading:
    """entrypoint 配置加载测试（差异4 消除：统一 ReviewConfig 路径）"""

    def test_load_review_config_from_yaml(self) -> None:
        """测试从 YAML 文件加载 ReviewConfig"""
        from dota_helper.facade.entrypoint import _load_review_config

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as f:
            yaml.dump({
                "model": "deepseek-chat",
                "tactical_loop": {"max_iterations_per_phase": 5},
                "stop_verifier": {"min_confidence": 0.8},
                "memory": {
                    "enabled": True,
                    "max_persistent_notes": 200,
                    "max_skills": 30,
                },
            }, f)
            config_path = Path(f.name)

        try:
            config = _load_review_config(config_path)
            assert isinstance(config, ReviewConfig)
            assert config.model == "deepseek-chat"
            assert config.tactical_loop.max_iterations_per_phase == 5
            assert config.stop_verifier.min_confidence == 0.8
            assert config.memory.max_persistent_notes == 200
            assert config.memory.max_skills == 30
        finally:
            config_path.unlink(missing_ok=True)

    def test_load_review_config_missing_file_returns_defaults(self) -> None:
        """测试配置文件不存在时返回默认值"""
        from dota_helper.facade.entrypoint import _load_review_config

        config = _load_review_config(Path("/nonexistent/config.yaml"))
        assert isinstance(config, ReviewConfig)
        assert config.model == "gpt-4o-mini"
        assert config.memory.max_persistent_notes == 100

    def test_load_review_config_invalid_yaml_returns_defaults(self) -> None:
        """测试 YAML 解析失败时返回默认值"""
        from dota_helper.facade.entrypoint import _load_review_config

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as f:
            f.write("invalid: yaml: content: [broken")
            config_path = Path(f.name)

        try:
            config = _load_review_config(config_path)
            assert isinstance(config, ReviewConfig)
            assert config.model == "gpt-4o-mini"
        finally:
            config_path.unlink(missing_ok=True)

    def test_fallback_factory_uses_review_config(self) -> None:
        """测试 fallback 工厂使用 ReviewConfig（不再使用 Dict）"""
        from dota_helper.facade.entrypoint import _create_fallback_orchestrator_factory
        from dota_helper.domain_types.match_data import MatchData
        from dota_helper.data_source.opendota_client import OpenDotaClient
        from dota_helper.data_source.match_fetcher import MatchFetcher

        config = ReviewConfig()
        config = ReviewConfig(
            tactical_loop=TacticalLoopConfig(max_iterations_per_phase=7),
        )

        # 创建一个简单的 data_source mock
        class MockDataSource:
            async def fetch_match(self, match_id: str) -> MatchData:
                return MatchData(match_id=match_id, duration=2400)

        factory = _create_fallback_orchestrator_factory(
            data_source=MockDataSource(),
            config=config,
        )

        # 验证工厂返回 ReviewOrchestrator
        orchestrator = factory("12345")
        from dota_helper.orchestrator.review_orchestrator import ReviewOrchestrator
        assert isinstance(orchestrator, ReviewOrchestrator)
