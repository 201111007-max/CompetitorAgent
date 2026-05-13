"""元认知评估器工厂

职责：
- 根据配置创建合适的评估器实例
- 管理组件依赖注入
- 支持运行时切换实现

使用示例：
```python
from core.metacognition.factory import MetacognitionFactory

# 从配置创建
evaluator = MetacognitionFactory.create_evaluator(
    config={"type": "llm_based"},
    tool_registry=registry,
    memory=memory,
    llm_client=llm_client
)

# 从 YAML 配置文件创建
evaluator = MetacognitionFactory.create_from_yaml("config/metacognition_config.yaml", ...)
```
"""

from typing import Dict, Any, Optional
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.metacognition.interfaces import (
    IKnowledgeBoundary,
    IConfidenceCalculator,
    IClarificationGenerator,
    IMetacognitionEvaluator,
    ConfidenceLevel
)
from core.metacognition.rule_based import (
    WeightedConfidenceCalculator,
    RuleBasedClarificationGenerator,
    RuleBasedMetacognitionEvaluator
)
from utils.log_config import get_logger

logger = get_logger("metacognition_factory", component="core")


class MetacognitionFactory:
    """元认知评估器工厂
    
    职责：
    - 根据配置类型创建对应的评估器实例
    - 管理组件的依赖注入
    - 支持从 YAML 配置文件加载
    
    支持的评估器类型：
    - llm_based: 基于 LLM 的评估器（智能，需要 API）
    
    扩展方式：
    - 在 create_evaluator 中添加新的类型分支
    - 或创建新的工厂方法
    """
    
    @staticmethod
    def create_evaluator(
        config: Dict[str, Any],
        tool_registry=None,
        memory=None,
        api_client=None,
        llm_client=None
    ) -> IMetacognitionEvaluator:
        """创建元认知评估器
        
        Args:
            config: 配置字典，必须包含 "type" 字段
                   示例：{"type": "llm_based"}
            tool_registry: 工具注册表
            memory: 记忆系统
            api_client: API 客户端
            llm_client: LLM 客户端
            
        Returns:
            IMetacognitionEvaluator: 评估器实例
            
        Raises:
            ValueError: 未知的评估器类型或缺少必要依赖
        """
        evaluator_type = config.get("type", "llm_based")
        
        logger.info(f"创建元认知评估器，类型：{evaluator_type}")
        
        if evaluator_type == "llm_based":
            return MetacognitionFactory._create_llm_based(
                config, tool_registry, llm_client
            )
        else:
            raise ValueError(f"未知的评估器类型：{evaluator_type}，支持：llm_based")
    
    @staticmethod
    def create_from_yaml(
        config_path: str,
        tool_registry=None,
        memory=None,
        api_client=None,
        llm_client=None
    ) -> IMetacognitionEvaluator:
        """从 YAML 配置文件创建评估器
        
        Args:
            config_path: YAML 配置文件路径
            tool_registry: 工具注册表
            memory: 记忆系统
            api_client: API 客户端
            llm_client: LLM 客户端
            
        Returns:
            IMetacognitionEvaluator: 评估器实例
        """
        import yaml
        
        config_file = Path(config_path)
        if not config_file.exists():
            logger.warning(f"配置文件不存在：{config_path}，使用默认配置")
            config = {"type": "llm_based"}
        else:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        
        logger.info(f"从配置文件加载元认知评估器：{config_path}")
        
        return MetacognitionFactory.create_evaluator(
            config=config,
            tool_registry=tool_registry,
            memory=memory,
            api_client=api_client,
            llm_client=llm_client
        )
    
    @staticmethod
    def _create_llm_based(
        config: Dict[str, Any],
        tool_registry,
        llm_client
    ) -> IMetacognitionEvaluator:
        """创建 LLM 驱动评估器"""
        if not llm_client:
            raise ValueError("LLM 驱动评估器需要 LLM 客户端")
        
        logger.info("创建基于 LLM 的元认知评估器")
        
        from core.metacognition.llm_based import LLMBasedKnowledgeBoundary
        
        knowledge_boundary = LLMBasedKnowledgeBoundary(
            llm_client=llm_client,
            tool_registry=tool_registry
        )
        
        calculator = WeightedConfidenceCalculator()
        clarification_generator = RuleBasedClarificationGenerator()
        
        threshold_str = config.get("clarification_threshold", "low")
        try:
            threshold = ConfidenceLevel(threshold_str)
        except ValueError:
            logger.warning(f"无效的阈值配置：{threshold_str}，使用默认值 low")
            threshold = ConfidenceLevel.LOW
        
        evaluator = RuleBasedMetacognitionEvaluator(
            knowledge_boundary=knowledge_boundary,
            confidence_calculator=calculator,
            clarification_generator=clarification_generator,
            clarification_threshold=threshold
        )
        
        logger.info("基于 LLM 的元认知评估器创建完成")
        return evaluator
