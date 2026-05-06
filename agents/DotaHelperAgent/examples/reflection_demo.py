"""反思机制使用示例

演示如何使用 Agent 的反思机制来提升推荐质量
"""

import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.agent_controller import AgentController
from core.tool_registry import ToolRegistry
from core.config import ReflectionConfig
from core.reflection_evaluator import EvaluationDimension, ReflectionAction


def demo_basic_reflection():
    """演示基础反思功能"""
    print("=" * 60)
    print("示例 1: 基础反思功能")
    print("=" * 60)
    
    # 创建工具注册表（简化示例，使用空注册表）
    registry = ToolRegistry()
    
    # 创建带反思的控制器
    controller = AgentController(
        tool_registry=registry,
        enable_reflection=True,
        max_turns=3
    )
    
    # 模拟查询（由于没有实际工具，会返回失败结果）
    # 实际使用时会注册真实的工具
    print("\n查询：推荐克制敌方的英雄")
    print("\n反思过程:")
    
    # 注意：这个示例主要用于演示 API 使用
    # 实际使用时需要注册真实的工具才能看到完整的反思过程
    try:
        result = controller.solve("推荐克制敌方的英雄")
        print(f"状态：{result.get('state', 'unknown')}")
        print(f"成功：{result.get('success', False)}")
        
        if 'reflections' in result and result['reflections']:
            print("\n反思记录:")
            for ref in result['reflections']:
                print(f"  - {ref}")
    except Exception as e:
        print(f"执行失败（预期）：{e}")
        print("说明：需要注册实际工具才能正常运行")


def demo_custom_weights():
    """演示自定义权重配置"""
    print("\n" + "=" * 60)
    print("示例 2: 自定义反思权重")
    print("=" * 60)
    
    # 自定义权重：更看重完整性
    custom_weights = {
        EvaluationDimension.COMPLETENESS: 0.40,  # 40% 权重
        EvaluationDimension.CONSISTENCY: 0.15,   # 15%
        EvaluationDimension.CREDIBILITY: 0.25,   # 25%
        EvaluationDimension.RELEVANCE: 0.15,     # 15%
        EvaluationDimension.ACTIONABILITY: 0.05  # 5%
    }
    
    print("\n自定义权重配置:")
    for dim, weight in custom_weights.items():
        print(f"  {dim.value}: {weight:.0%}")
    
    registry = ToolRegistry()
    controller = AgentController(
        tool_registry=registry,
        enable_reflection=True,
        reflection_weights=custom_weights
    )
    
    print(f"\n控制器已创建，使用自定义权重配置")
    print(f"反思评估器权重：{controller.reflection_evaluator.weights}")


def demo_reflection_config():
    """演示使用配置类"""
    print("\n" + "=" * 60)
    print("示例 3: 使用 ReflectionConfig 配置类")
    print("=" * 60)
    
    # 创建反思配置
    config = ReflectionConfig(
        enabled=True,
        enable_llm=False,  # 暂不启用 LLM
        completeness_weight=0.30,
        consistency_weight=0.20,
        credibility_weight=0.20,
        relevance_weight=0.20,
        actionability_weight=0.10,
        finalize_threshold=0.75,  # 结束阈值
        adjust_threshold=0.60,    # 调整阈值
        continue_threshold=0.40   # 继续阈值
    )
    
    print("\n配置参数:")
    print(f"  启用反思：{config.enabled}")
    print(f"  启用 LLM: {config.enable_llm}")
    print(f"  结束阈值：{config.finalize_threshold}")
    print(f"  调整阈值：{config.adjust_threshold}")
    print(f"  继续阈值：{config.continue_threshold}")
    
    # 验证权重
    if config.validate_weights():
        print(f"\n[OK] 权重验证通过：总和为 1.0")
    
    # 转换为字典
    weights_dict = config.get_weights_dict()
    print(f"\n权重字典:")
    for dim, weight in weights_dict.items():
        print(f"  {dim.value}: {weight:.2f}")


def demo_reflection_result():
    """演示反思结果的处理"""
    print("\n" + "=" * 60)
    print("示例 4: 反思结果处理")
    print("=" * 60)
    
    from core.reflection_evaluator import ReflectionEvaluator, QualityScore
    
    # 创建评估器
    evaluator = ReflectionEvaluator()
    
    # 模拟数据
    observations = [{
        "recommendations": [
            {"hero_name": "pudge", "score": 0.8, "reason": "高胜率"},
            {"hero_name": "axe", "score": 0.7, "reason": "克制关系"},
            {"hero_name": "lion", "score": 0.6, "reason": "控制能力"}
        ]
    }]
    
    actions = [
        {
            "tool_name": "analyze_counter_picks",
            "result": {"status": "success", "data": observations[0]}
        }
    ]
    
    # 执行评估
    result = evaluator.evaluate(
        query="推荐克制敌方的英雄",
        observations=observations,
        actions=actions,
        context={}
    )
    
    print("\n评估结果:")
    print(f"  总体评分：{result.overall_score:.2f}/1.00")
    print(f"  置信度：{result.confidence:.2f}")
    print(f"  采取行动：{result.action.value}")
    print(f"  推理：{result.reasoning}")
    
    print("\n各维度评分:")
    for dim_score in result.dimension_scores:
        print(f"  {dim_score.dimension.value}:")
        print(f"    评分：{dim_score.score:.2f}")
        print(f"    理由：{', '.join(dim_score.reasons[:2])}")  # 只显示前 2 个理由
    
    if result.strategy_adjustments:
        print("\n策略调整建议:")
        for adj in result.strategy_adjustments:
            print(f"  - {adj}")
    
    if result.missing_information:
        print("\n缺失信息:")
        for missing in result.missing_information:
            print(f"  - {missing}")
    
    # 转换为字典
    result_dict = result.to_dict()
    print(f"\n序列化结果:")
    print(f"  类型：{type(result_dict)}")
    print(f"  键：{list(result_dict.keys())}")


def demo_decision_making():
    """演示决策逻辑"""
    print("\n" + "=" * 60)
    print("示例 5: 反思决策逻辑")
    print("=" * 60)
    
    from core.reflection_evaluator import ReflectionEvaluator
    
    evaluator = ReflectionEvaluator()
    
    # 测试不同质量的场景
    scenarios = [
        ("高质量", [{
            "recommendations": [
                {"hero_name": "pudge", "score": 0.9, "reason": "test", "win_rate": 0.6},
                {"hero_name": "axe", "score": 0.8, "reason": "test", "games": 1000},
                {"hero_name": "lion", "score": 0.7, "reason": "test"}
            ]
        }]),
        ("中等质量", [{"recommendations": [{"hero_name": "pudge"}]}]),
        ("低质量", [{"partial": "data"}]),
    ]
    
    for quality_name, observations in scenarios:
        result = evaluator.evaluate(
            query="测试查询",
            observations=observations,
            actions=[{"tool_name": "test", "result": {"status": "success"}}],
            context={}
        )
        
        action_symbol = {
            ReflectionAction.FINALIZE: "[OK]",
            ReflectionAction.ADJUST_STRATEGY: "[WARN]",
            ReflectionAction.CONTINUE: "[FAIL]",
            ReflectionAction.REQUEST_CLARIFICATION: "[?]"
        }
        
        print(f"\n{quality_name}:")
        print(f"  评分：{result.overall_score:.2f}")
        print(f"  行动：{action_symbol.get(result.action, '?')} {result.action.value}")
        print(f"  结论：{result.reasoning[:50]}...")


def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("Agent 反思机制使用示例")
    print("=" * 60)
    
    # 运行示例
    demo_basic_reflection()
    demo_custom_weights()
    demo_reflection_config()
    demo_reflection_result()
    demo_decision_making()
    
    print("\n" + "=" * 60)
    print("所有示例运行完成！")
    print("=" * 60)
    print("\n提示：")
    print("  - 示例 1 需要实际工具才能完整运行")
    print("  - 其他示例都是独立的，可以直接运行")
    print("  - 查看 docs/REFLECTION_GUIDE.md 获取详细文档")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
