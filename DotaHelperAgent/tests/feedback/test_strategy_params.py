"""
策略参数管理测试
"""

import pytest
import tempfile
import time
from pathlib import Path

from feedback.strategy_params import StrategyParams


class TestStrategyParams:
    """测试策略参数管理"""

    @pytest.fixture
    def temp_config(self):
        """创建临时配置文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "learned_strategy.yaml"
            params = StrategyParams(config_path=str(config_path))
            yield params

    def test_default_engine_weights(self, temp_config):
        """测试默认引擎权重"""
        weights = temp_config.get_engine_weights()
        
        assert "rule" in weights
        assert "data" in weights
        assert "llm" in weights
        assert weights["rule"] == 0.3
        assert weights["data"] == 0.4
        assert weights["llm"] == 0.3

    def test_update_engine_weight(self, temp_config):
        """测试更新引擎权重"""
        temp_config.update_engine_weight("rule", 0.35)
        
        weights = temp_config.get_engine_weights()
        assert weights["rule"] == 0.35

    def test_get_rule_param_default(self, temp_config):
        """测试获取规则参数默认值"""
        threshold = temp_config.get_rule_param("low_health_threshold")
        assert threshold == 0.3
        
        cooldown = temp_config.get_rule_param("recommendation_cooldown")
        assert cooldown == 10

    def test_update_rule_param(self, temp_config):
        """测试更新规则参数"""
        temp_config.update_rule_param("low_health_threshold", 0.25)
        
        threshold = temp_config.get_rule_param("low_health_threshold")
        assert threshold == 0.25

    def test_save_and_load(self, temp_config):
        """测试保存和加载配置"""
        # 更新参数
        temp_config.update_engine_weight("rule", 0.35)
        temp_config.update_rule_param("low_health_threshold", 0.25)
        
        # 保存
        temp_config.save()
        
        # 创建新实例加载配置
        new_params = StrategyParams(config_path=str(temp_config.config_path))
        
        # 验证加载的参数
        assert new_params.get_engine_weights()["rule"] == 0.35
        assert new_params.get_rule_param("low_health_threshold") == 0.25

    def test_reset(self, temp_config):
        """测试重置为默认值"""
        # 更新参数
        temp_config.update_engine_weight("rule", 0.5)
        temp_config.update_rule_param("low_health_threshold", 0.2)
        
        # 重置
        temp_config.reset()
        
        # 验证恢复默认值
        assert temp_config.get_engine_weights()["rule"] == 0.3
        assert temp_config.get_rule_param("low_health_threshold") == 0.3

    def test_update_stats(self, temp_config):
        """测试更新统计信息"""
        temp_config.update_stats({
            "total_feedback_count": 100,
            "avg_score": 0.65,
            "positive_rate": 0.72
        })
        
        stats = temp_config.get_stats()
        assert stats["total_feedback_count"] == 100
        assert stats["avg_score"] == 0.65
        assert stats["positive_rate"] == 0.72
