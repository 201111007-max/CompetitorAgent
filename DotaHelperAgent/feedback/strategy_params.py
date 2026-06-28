"""
策略参数管理 - 管理学习到的策略参数

职责：
- 存储引擎权重和规则参数
- 提供读取和更新接口
- 持久化到 YAML 文件
- 支持重置为默认值
"""

import yaml
import time
import threading
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class EngineWeight:
    """引擎权重"""
    weight: float
    confidence: float = 0.0
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "weight": self.weight,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
        }


@dataclass
class RuleParam:
    """规则参数"""
    value: float
    default: float
    confidence: float = 0.0
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "value": self.value,
            "default": self.default,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
        }


class StrategyParams:
    """策略参数管理"""

    def __init__(self, config_path: str = "config/learned_strategy.yaml"):
        """
        初始化策略参数管理

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        if not self.config_path.is_absolute():
            self.config_path = Path(__file__).parent.parent / config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

        # 默认引擎权重
        self.default_engine_weights = {
            "rule": 0.3,
            "data": 0.4,
            "llm": 0.3,
        }

        # 默认规则参数
        self.default_rule_params = {
            "low_health_threshold": 0.3,
            "recommendation_cooldown": 10,
        }

        # 当前策略参数
        self.engine_weights: Dict[str, EngineWeight] = {}
        self.rule_params: Dict[str, RuleParam] = {}
        self.stats: Dict[str, Any] = {
            "total_feedback_count": 0,
            "avg_score": 0.0,
            "positive_rate": 0.0,
        }

        # 加载配置
        self.load()
        logger.info(f"策略参数管理初始化完成: {self.config_path}")

    def get_engine_weights(self) -> Dict[str, float]:
        """
        获取引擎权重

        Returns:
            引擎权重字典
        """
        with self._lock:
            if not self.engine_weights:
                return self.default_engine_weights.copy()

            return {
                engine: ew.weight
                for engine, ew in self.engine_weights.items()
            }

    def get_rule_param(self, param_name: str, default: Optional[Any] = None) -> Any:
        """
        获取规则参数

        Args:
            param_name: 参数名称
            default: 默认值

        Returns:
            参数值
        """
        with self._lock:
            if param_name in self.rule_params:
                return self.rule_params[param_name].value

            if default is not None:
                return default

            return self.default_rule_params.get(param_name)

    def update_engine_weight(
        self,
        engine: str,
        weight: float,
        confidence: Optional[float] = None
    ) -> None:
        """
        更新引擎权重

        Args:
            engine: 引擎名称
            weight: 权重值
            confidence: 置信度（可选）
        """
        with self._lock:
            if engine not in self.engine_weights:
                self.engine_weights[engine] = EngineWeight(
                    weight=weight,
                    confidence=confidence or 0.0,
                    last_updated=time.time()
                )
            else:
                self.engine_weights[engine].weight = weight
                if confidence is not None:
                    self.engine_weights[engine].confidence = confidence
                self.engine_weights[engine].last_updated = time.time()

            logger.debug(f"更新引擎权重: {engine}={weight:.3f}")

    def update_rule_param(
        self,
        param_name: str,
        value: float,
        confidence: Optional[float] = None
    ) -> None:
        """
        更新规则参数

        Args:
            param_name: 参数名称
            value: 参数值
            confidence: 置信度（可选）
        """
        with self._lock:
            default_value = self.default_rule_params.get(param_name, value)

            if param_name not in self.rule_params:
                self.rule_params[param_name] = RuleParam(
                    value=value,
                    default=default_value,
                    confidence=confidence or 0.0,
                    last_updated=time.time()
                )
            else:
                self.rule_params[param_name].value = value
                if confidence is not None:
                    self.rule_params[param_name].confidence = confidence
                self.rule_params[param_name].last_updated = time.time()

            logger.debug(f"更新规则参数: {param_name}={value}")

    def update_stats(self, stats: Dict[str, Any]) -> None:
        """
        更新统计信息

        Args:
            stats: 统计字典
        """
        with self._lock:
            self.stats.update(stats)

    def save(self) -> None:
        """保存配置到文件"""
        with self._lock:
            config = {
                "version": 1,
                "last_updated": time.time(),
                "engine_weights": {
                    engine: ew.to_dict()
                    for engine, ew in self.engine_weights.items()
                },
                "rule_params": {
                    name: rp.to_dict()
                    for name, rp in self.rule_params.items()
                },
                "stats": self.stats,
            }

            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
                logger.debug(f"保存策略参数: {self.config_path}")
            except Exception as e:
                logger.error(f"保存策略参数失败: {e}")

    def load(self) -> None:
        """从文件加载配置"""
        if not self.config_path.exists():
            logger.info(f"策略参数文件不存在，使用默认值: {self.config_path}")
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            if not config:
                return

            # 加载引擎权重
            engine_weights = config.get("engine_weights", {})
            for engine, data in engine_weights.items():
                self.engine_weights[engine] = EngineWeight(
                    weight=data.get("weight", 0.0),
                    confidence=data.get("confidence", 0.0),
                    last_updated=data.get("last_updated", time.time())
                )

            # 加载规则参数
            rule_params = config.get("rule_params", {})
            for name, data in rule_params.items():
                self.rule_params[name] = RuleParam(
                    value=data.get("value", 0.0),
                    default=data.get("default", 0.0),
                    confidence=data.get("confidence", 0.0),
                    last_updated=data.get("last_updated", time.time())
                )

            # 加载统计
            self.stats = config.get("stats", self.stats)

            logger.info(f"加载策略参数: {len(self.engine_weights)} 个引擎权重, {len(self.rule_params)} 个规则参数")

        except Exception as e:
            logger.error(f"加载策略参数失败: {e}")

    def reset(self) -> None:
        """重置为默认值"""
        with self._lock:
            self.engine_weights.clear()
            self.rule_params.clear()
            self.stats = {
                "total_feedback_count": 0,
                "avg_score": 0.0,
                "positive_rate": 0.0,
            }
            self.save()
            logger.info("重置策略参数为默认值")

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计字典
        """
        with self._lock:
            return self.stats.copy()
