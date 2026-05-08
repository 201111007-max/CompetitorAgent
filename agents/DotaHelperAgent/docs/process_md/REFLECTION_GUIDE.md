# Agent 反思机制使用指南

## 概述

反思机制是 ReAct Agent 的核心组件，它使 Agent 能够：
- **自我评估**：评估执行结果的质量
- **自主决策**：根据评估结果决定下一步行动
- **策略调整**：识别问题并调整执行策略
- **质量保障**：确保输出结果达到一定标准

## 核心组件

### 1. ReflectionEvaluator（反思评估器）

反思评估器负责全面评估 Agent 的执行结果，包含 5 个评估维度：

| 维度 | 权重 | 说明 |
|------|------|------|
| **完整性** (Completeness) | 30% | 是否完整回答了用户的问题 |
| **一致性** (Consistency) | 20% | 结果内部是否一致，有无矛盾 |
| **可信度** (Credibility) | 20% | 数据来源是否可靠 |
| **相关性** (Relevance) | 20% | 结果是否与查询高度相关 |
| **可操作性** (Actionability) | 10% | 建议是否具体可行 |

### 2. ReflectionAction（反思维度）

根据评估结果，反思机制会决定采取以下行动之一：

| 行动 | 触发条件 | 说明 |
|------|---------|------|
| **FINALIZE** (结束) | 总体评分 ≥ 0.75 | 结果质量优秀，输出最终答案 |
| **ADJUST_STRATEGY** (调整) | 0.6 ≤ 评分 < 0.75 | 结果质量一般，调整策略后继续 |
| **CONTINUE** (继续) | 评分 < 0.6 | 结果质量不足，收集更多信息 |
| **REQUEST_CLARIFICATION** (澄清) | 无法理解查询 | 需要用户澄清意图 |

## 基本使用

### 1. 创建带反思机制的 Agent Controller

```python
from core.agent_controller import AgentController
from core.tool_registry import ToolRegistry
from core.config import ReflectionConfig

# 创建工具注册表
registry = ToolRegistry()

# 创建 Agent Controller（默认启用反思）
controller = AgentController(
    tool_registry=registry,
    enable_reflection=True,      # 启用反思
    max_turns=5,                 # 最大循环 5 轮
)

# 执行查询
result = controller.solve("推荐克制敌方帕吉和斧王的英雄")

# 查看反思结果
if 'reflections' in result:
    print("反思过程：")
    for reflection in result['reflections']:
        print(f"  - {reflection}")
```

### 2. 自定义反思权重

```python
from core.reflection_evaluator import EvaluationDimension

# 自定义权重（总和必须为 1.0）
custom_weights = {
    EvaluationDimension.COMPLETENESS: 0.40,  # 更看重完整性
    EvaluationDimension.CONSISTENCY: 0.15,
    EvaluationDimension.CREDIBILITY: 0.25,
    EvaluationDimension.RELEVANCE: 0.15,
    EvaluationDimension.ACTIONABILITY: 0.05
}

controller = AgentController(
    tool_registry=registry,
    enable_reflection=True,
    reflection_weights=custom_weights
)
```

### 3. 使用配置类

```python
from core.config import AgentConfig, ReflectionConfig

# 创建反思配置
reflection_config = ReflectionConfig(
    enabled=True,
    enable_llm=False,  # 暂不启用 LLM 增强反思
    completeness_weight=0.30,
    consistency_weight=0.20,
    credibility_weight=0.20,
    relevance_weight=0.20,
    actionability_weight=0.10,
    finalize_threshold=0.75,  # 结束阈值
    adjust_threshold=0.60,    # 调整阈值
    continue_threshold=0.40   # 继续阈值
)

# 验证权重
assert reflection_config.validate_weights() is True

# 创建 Agent 配置
agent_config = AgentConfig(
    reflection=reflection_config,
    # ... 其他配置
)

# 使用配置创建控制器
controller = AgentController(
    tool_registry=registry,
    reflection_weights=reflection_config.get_weights_dict()
)
```

## 反思过程详解

### 示例：英雄推荐查询

**用户查询**："推荐克制敌方帕吉和斧王的英雄"

**Agent 执行过程**：

```
第 1 轮循环：
  Think: 分析用户查询，识别为英雄克制分析
  Plan: 计划使用 analyze_counter_picks 工具
  Execute: 执行工具调用
  Observe: 收集到 3 个推荐结果
  Reflect: 
    - 总体质量评分：0.72/1.00 (置信度：0.85)
    - 完整性：0.80 (包含充足的推荐项)
    - 一致性：0.90 (数据结构一致，评分合理)
    - 可信度：0.75 (工具执行成功)
    - 相关性：0.85 (工具与查询高度相关)
    - 可操作性：0.60 (部分推荐缺少详细信息)
    - 反思结论：结果质量良好，可以结束并输出结果
    - 行动：FINALIZE

第 2 轮循环（如果需要）：
  ...
```

### 查看详细反思报告

```python
# 获取最后一次反思结果
reflection = controller.last_reflection

if reflection:
    print(f"总体评分：{reflection.overall_score:.2f}")
    print(f"采取行动：{reflection.action.value}")
    print(f"置信度：{reflection.confidence:.2f}")
    print("\n各维度评分:")
    for dim_score in reflection.dimension_scores:
        print(f"  {dim_score.dimension.value}: {dim_score.score:.2f}")
        print(f"    理由：{', '.join(dim_score.reasons)}")
    
    if reflection.strategy_adjustments:
        print("\n策略调整建议:")
        for adj in reflection.strategy_adjustments:
            print(f"  - {adj}")
    
    if reflection.missing_information:
        print("\n缺失信息:")
        for missing in reflection.missing_information:
            print(f"  - {missing}")
```

## 高级功能

### 1. LLM 增强反思（可选）

如果配置了 LLM，可以使用更智能的自然语言评估：

```python
from utils.llm_client import LLMClient, LLMConfig

# 配置 LLM
llm_config = LLMConfig(
    enabled=True,
    base_url="http://127.0.0.1:1234/v1",
    model="qwen3.5-9b"
)
llm_client = LLMClient(llm_config)

# 创建带 LLM 反思的控制器
controller = AgentController(
    tool_registry=registry,
    enable_reflection=True,
    enable_llm_reflection=True,
    llm_client=llm_client
)
```

LLM 反思提供更自然的评估语言，但会增加调用开销。

### 2. 反思结果持久化

```python
import json

# 保存反思结果到文件
reflection_dict = controller.last_reflection.to_dict()
with open("reflection_result.json", "w", encoding="utf-8") as f:
    json.dump(reflection_dict, f, ensure_ascii=False, indent=2)

# 从文件加载
with open("reflection_result.json", "r", encoding="utf-8") as f:
    loaded = json.load(f)
    print(f"加载的反思结果：{loaded['action']}")
```

### 3. 反思统计分析

```python
# 收集多次查询的反思结果
reflections = []

for query in queries:
    result = controller.solve(query)
    if controller.last_reflection:
        reflections.append(controller.last_reflection)

# 统计分析
total = len(reflections)
finalize_count = sum(1 for r in reflections if r.action == ReflectionAction.FINALIZE)
adjust_count = sum(1 for r in reflections if r.action == ReflectionAction.ADJUST_STRATEGY)
continue_count = sum(1 for r in reflections if r.action == ReflectionAction.CONTINUE)

print(f"总查询数：{total}")
print(f"直接结束：{finalize_count} ({finalize_count/total:.1%})")
print(f"调整后结束：{adjust_count} ({adjust_count/total:.1%})")
print(f"继续收集：{continue_count} ({continue_count/total:.1%})")

# 平均质量评分
avg_score = sum(r.overall_score for r in reflections) / total
print(f"平均质量评分：{avg_score:.2f}")
```

## 调试技巧

### 1. 启用详细日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 控制器会输出详细的调试信息
controller = AgentController(
    tool_registry=registry,
    enable_reflection=True
)

result = controller.solve("测试查询")
```

### 2. 检查单维度评分

如果某个维度评分持续偏低，可以针对性优化：

```python
# 检查完整性评分低的原因
for reflection in reflections:
    completeness = next(
        s for s in reflection.dimension_scores 
        if s.dimension == EvaluationDimension.COMPLETENESS
    )
    if completeness.score < 0.6:
        print(f"查询：{reflection.query}")
        print(f"完整性评分：{completeness.score:.2f}")
        print(f"原因：{', '.join(completeness.reasons)}")
        print()
```

### 3. 调整阈值

根据实际效果调整决策阈值：

```python
# 更严格的结束标准（需要更高质量才能结束）
config = ReflectionConfig(
    finalize_threshold=0.85,  # 从 0.75 提高到 0.85
    adjust_threshold=0.65,    # 从 0.60 提高到 0.65
)
```

## 常见问题

### Q1: 反思机制会影响性能吗？

**A**: 会有一定开销，但通常值得：
- 规则评估：非常快（毫秒级）
- LLM 评估：较慢（秒级），建议仅在需要时使用

### Q2: 什么时候应该禁用反思？

**A**: 以下场景可以考虑禁用：
- 简单查询（如查询单个英雄信息）
- 对响应时间要求极高的场景
- 资源受限的环境

### Q3: 如何确定最佳权重配置？

**A**: 建议步骤：
1. 使用默认权重运行一段时间
2. 收集反思统计数据
3. 分析哪些维度与用户满意度相关性最高
4. 针对性调整权重
5. A/B 测试不同配置

### Q4: 反思机制会无限循环吗？

**A**: 不会，有 max_turns 限制：
- 默认最大 5 轮循环
- 达到限制后强制结束
- 每轮都会评估，低质量会调整而非无限继续

## 最佳实践

1. **始终启用反思**：除非有特殊原因，否则应该启用反思机制
2. **监控反思统计**：定期分析反思结果，了解 Agent 表现
3. **调整权重**：根据实际应用场景调整维度权重
4. **设置合理阈值**：平衡质量和响应时间
5. **利用调整建议**：根据反思建议优化数据和工具

## 测试反思机制

运行单元测试验证反思功能：

```bash
cd agents/DotaHelperAgent/tests
python -m pytest core/test_reflection.py -v
```

测试覆盖：
- ✅ 5 个评估策略的独立测试
- ✅ ReflectionEvaluator 综合测试
- ✅ AgentController 集成测试
- ✅ 边界情况和异常处理
- ✅ 配置类测试

## 下一步

反思机制已完成基础实现，未来可以：
1. 实现 LLM 增强反思
2. 添加更多评估维度（如时效性、多样性）
3. 基于历史数据学习最优权重
4. 实现自适应阈值调整
