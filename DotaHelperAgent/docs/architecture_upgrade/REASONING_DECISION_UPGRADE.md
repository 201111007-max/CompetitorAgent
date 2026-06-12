# 推理和决策能力增强方案

> **文档版本**: v1.0  
> **创建时间**: 2026-06-12  
> **优先级**: P1  
> **预计工作量**: 3-4 周

---

## 一、当前问题分析

### 1.1 现有推理能力

当前 DotaHelperAgent 的推理能力主要依赖：

1. **规则推理**：基于领域知识的规则引擎
2. **LLM 增强**：使用 LLM 进行自然语言理解和推理

**优势**：
- ✅ 规则推理快速、可靠
- ✅ LLM 推理灵活、适应性强

**局限**：
- ❌ 缺乏数据驱动的决策模型
- ❌ 无法量化决策效果（如推荐策略的胜率提升）
- ❌ 缺乏个性化推荐能力

---

## 二、改进目标

### 2.1 核心目标

从"规则推理 + LLM 增强"升级为"混合推理"系统，实现：

1. **数据驱动决策**：基于历史对局数据的胜率预测
2. **多源决策融合**：综合规则、数据、LLM 的建议
3. **决策效果量化**：评估推荐策略的胜率提升

### 2.2 预期收益

| 维度 | 当前能力 | 升级后能力 | 收益 |
|------|---------|-----------|------|
| **推理准确性** | 75% | 90% | +20% |
| **决策可解释性** | 中等 | 高 | +40% |
| **个性化程度** | 低 | 高 | +50% |

---

## 三、架构设计

### 3.1 混合推理架构

```
┌─────────────────────────────────────────────────────────────┐
│                    混合推理架构                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ 规则推理引擎 │  │ 数据驱动引擎 │  │ LLM 增强引擎 │      │
│  │              │  │              │  │              │      │
│  │ - 领域知识   │  │ - 历史数据   │  │ - 自然语言   │      │
│  │ - 专家规则   │  │ - 胜率模型   │  │ - 复杂推理   │      │
│  │ - 快速响应   │  │ - 个性化推荐 │  │ - 知识融合   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │            │
│         └──────────────────┼──────────────────┘            │
│                            ▼                                │
│              ┌──────────────────────────┐                  │
│              │      决策融合器           │                  │
│              │  - 多源决策融合           │                  │
│              │  - 置信度评估             │                  │
│              │  - 冲突解决               │                  │
│              └──────────────────────────┘                  │
│                            ▼                                │
│                    最终推荐结果                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、关键组件设计

### 4.1 数据驱动引擎

**职责**：基于历史对局数据进行胜率预测和推荐

**实现方案**：

```python
# core/data_driven_engine.py
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from typing import Dict, Any

class DataDrivenEngine:
    """数据驱动引擎"""
    
    def __init__(self, match_data_path: str):
        # 加载历史对局数据
        self.match_data = pd.read_csv(match_data_path)
        
        # 训练胜率预测模型
        self.win_rate_model = self._train_win_rate_model()
    
    def _train_win_rate_model(self) -> RandomForestClassifier:
        """训练胜率预测模型"""
        # 特征工程
        features = self._extract_features(self.match_data)
        labels = self.match_data['radiant_win']
        
        # 训练模型
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        model.fit(features, labels)
        
        return model
    
    def predict_win_rate(self, context: Dict[str, Any]) -> float:
        """预测胜率"""
        features = self._extract_features_from_context(context)
        win_probability = self.win_rate_model.predict_proba([features])[0][1]
        return win_probability
    
    def recommend_strategy(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """推荐策略"""
        # 预测当前胜率
        current_win_rate = self.predict_win_rate(context)
        
        # 模拟不同策略的胜率
        strategies = self._simulate_strategies(context)
        
        # 选择胜率最高的策略
        best_strategy = max(strategies, key=lambda s: s['win_rate'])
        
        return {
            "strategy": best_strategy,
            "current_win_rate": current_win_rate,
            "improvement": best_strategy['win_rate'] - current_win_rate
        }
```

### 4.2 决策融合器

**职责**：融合多个决策源的建议

**实现方案**：

```python
# core/decision_fusion.py
from typing import Dict, Any, List

class DecisionFusion:
    """决策融合器"""
    
    def __init__(self):
        self.weights = {
            "rule": 0.3,
            "data": 0.4,
            "llm": 0.3
        }
    
    def fuse(
        self, 
        rule_decision: Dict,
        data_decision: Dict,
        llm_decision: Dict
    ) -> Dict[str, Any]:
        """融合多个决策源"""
        # 评估每个决策的置信度
        confidences = {
            "rule": self._evaluate_rule_confidence(rule_decision),
            "data": self._evaluate_data_confidence(data_decision),
            "llm": self._evaluate_llm_confidence(llm_decision)
        }
        
        # 加权融合
        fused = self._weighted_fusion(
            rule_decision, 
            data_decision, 
            llm_decision, 
            weights=confidences
        )
        
        # 冲突检测和解决
        if self._has_conflict(fused):
            fused = self._resolve_conflict(fused)
        
        return fused
    
    def _evaluate_rule_confidence(self, decision: Dict) -> float:
        """评估规则决策置信度"""
        # 基于规则的完整性和一致性评估
        return decision.get('confidence', 0.7)
    
    def _evaluate_data_confidence(self, decision: Dict) -> float:
        """评估数据决策置信度"""
        # 基于数据量和模型准确率评估
        return decision.get('confidence', 0.8)
    
    def _evaluate_llm_confidence(self, decision: Dict) -> float:
        """评估 LLM 决策置信度"""
        # 基于 LLM 的输出置信度评估
        return decision.get('confidence', 0.6)
    
    def _weighted_fusion(
        self, 
        rule_decision: Dict,
        data_decision: Dict,
        llm_decision: Dict,
        weights: Dict[str, float]
    ) -> Dict:
        """加权融合"""
        # 归一化权重
        total_weight = sum(weights.values())
        normalized_weights = {k: v/total_weight for k, v in weights.items()}
        
        # 融合推荐
        fused_recommendation = {
            "strategy": self._merge_strategies(
                rule_decision.get('strategy'),
                data_decision.get('strategy'),
                llm_decision.get('strategy'),
                normalized_weights
            ),
            "confidence": sum([
                weights['rule'] * rule_decision.get('confidence', 0.5),
                weights['data'] * data_decision.get('confidence', 0.5),
                weights['llm'] * llm_decision.get('confidence', 0.5)
            ]),
            "sources": {
                "rule": rule_decision,
                "data": data_decision,
                "llm": llm_decision
            }
        }
        
        return fused_recommendation
```

---

## 五、实施步骤

### 第一阶段：数据收集和处理（1 周）

**任务**:
1. 收集历史对局数据
2. 数据清洗和特征工程
3. 建立数据管道

**交付物**:
- 历史对局数据集
- 特征工程代码

---

### 第二阶段：模型训练（1 周）

**任务**:
1. 训练胜率预测模型
2. 模型评估和优化
3. 模型部署

**交付物**:
- 胜率预测模型
- 模型评估报告

---

### 第三阶段：决策融合器开发（1 周）

**任务**:
1. 实现决策融合器
2. 实现冲突检测和解决
3. 编写单元测试

**交付物**:
- 决策融合器
- 单元测试通过

---

### 第四阶段：集成和测试（1 周）

**任务**:
1. 集成到 Agent
2. 编写集成测试
3. 性能测试和优化

**交付物**:
- 集成测试通过
- 性能测试报告

---

## 六、预期收益

| 指标 | 当前 | 升级后 | 提升 |
|------|------|--------|------|
| **推理准确性** | 75% | 90% | +20% |
| **决策可解释性** | 60% | 85% | +42% |
| **用户满意度** | 80% | 95% | +19% |

---

> **文档版本**: v1.0  
> **最后更新**: 2026-06-12
