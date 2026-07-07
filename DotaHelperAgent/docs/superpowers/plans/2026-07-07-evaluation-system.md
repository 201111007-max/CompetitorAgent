# 评测系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DotaHelperAgent 构建一套完整的评测体系，支持 Skill/SubAgent 替代实施后的功能效果评估，包含自建 DotaBench 评测集、LLM-as-a-Judge、Trajectory 评估、回归测试、在线监控五大组件。

**Architecture:** 三层评估架构（L1 离线 / L2 在线 / L3 回归）+ 7 维评分量表 + 多模型投票 Judge + 与 Langfuse Trace 深度集成

**Tech Stack:** Python, DeepEval, MLflow, Ragas, pytest, Langfuse (已有), PyYAML, Jinja2

---

## 背景与目标

### 1. 背景

根据 [ARCHITECTURE_ANALYSIS.md 第十八章](../ARCHITECTURE_ANALYSIS.md#十八skill-subagent-评估体系) 的设计，DotaHelperAgent 已规划 Skill/SubAgent 抽取（[2026-07-06-skill-extraction.md](./2026-07-06-skill-extraction.md)、[2026-07-06-subagent-extraction.md](./2026-07-06-subagent-extraction.md)）。抽取后必须建立**可量化、可对比、可回归**的评测体系，否则无法判断替代效果。

### 2. 核心挑战

| 挑战 | 影响 |
|------|------|
| Dota 2 领域无公开评测集（不同于 GAIA/WebArena） | 需自建 DotaBench |
| 同一查询可能存在多个有效答案 | 难以精确匹配 |
| 业务场景涉及游戏专业知识 | 需要领域知识支撑 |
| 用户主观体验难量化 | 需多维度评分 |

### 3. 目标

- **可量化**：7 维评分量表，量化主观体验
- **可对比**：基线对比 + A/B 测试 + 版本回归
- **可回归**：CI 集成，每次 PR 触发
- **可观测**：在线监控仪表板，实时评分

### 4. 核心收益

| 维度 | 当前状态 | 评测体系建成后 |
|------|---------|--------------|
| 评估方法 | 人工抽查 | 自动化 + 抽样人工校准 |
| 回归测试 | 手动执行 | CI 自动触发 |
| A/B 测试 | 无 | 统计显著性检验 |
| 主观评估 | 难以量化 | 7 维评分 |
| 在线监控 | Langfuse Trace | Trace + 评估结果 |

---

## File Structure

### 评测核心模块

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `evaluation/__init__.py` | 评测包初始化，导出公共接口 |
| Create | `evaluation/base.py` | 评估器基类（BaseEvaluator, EvaluationResult, EvaluationContext） |
| Create | `evaluation/judges/__init__.py` | Judge 子包 |
| Create | `evaluation/judges/base_judge.py` | 基础 Judge 抽象类 |
| Create | `evaluation/judges/multi_dimensional_judge.py` | 7 维评分 Judge |
| Create | `evaluation/judges/trajectory_judge.py` | 轨迹评估 Judge |
| Create | `evaluation/judges/multi_model_voter.py` | 多模型投票器 |
| Create | `evaluation/judges/calibration.py` | Judge 校准器（BabelJudge 方法） |
| Create | `evaluation/judges/prompts.yaml` | Judge Prompt 模板 |
| Create | `evaluation/trajectory/__init__.py` | 轨迹评估子包 |
| Create | `evaluation/trajectory/tool_selection.py` | 工具选择准确率 |
| Create | `evaluation/trajectory/argument_correctness.py` | 参数正确率 |
| Create | `evaluation/trajectory/dependency_order.py` | 依赖满足度 |
| Create | `evaluation/trajectory/error_propagation.py` | 错误传播率 |
| Create | `evaluation/trajectory/rejection_recovery.py` | 拒绝-恢复分解 |
| Create | `evaluation/regression/__init__.py` | 回归测试子包 |
| Create | `evaluation/regression/baseline.py` | 基线对比 |
| Create | `evaluation/regression/ab_test.py` | A/B 测试 |
| Create | `evaluation/regression/report.py` | 报告生成器 |
| Create | `evaluation/monitoring/__init__.py` | 监控子包 |
| Create | `evaluation/monitoring/dashboard.py` | 仪表板数据源 |
| Create | `evaluation/monitoring/alert.py` | 告警规则 |
| Create | `config/evaluation_config.yaml` | 全局配置 |
| Create | `scripts/evaluation/__init__.py` | 运行脚本包 |
| Create | `scripts/evaluation/run_diy_bench.py` | 运行 DotaBench |
| Create | `scripts/evaluation/run_judge.py` | 运行 Judge 评估 |
| Create | `scripts/evaluation/run_trajectory_eval.py` | 运行轨迹评估 |
| Create | `scripts/evaluation/run_regression.py` | 运行回归测试 |
| Create | `scripts/evaluation/calibrate_judge.py` | Judge 校准 |
| Create | `scripts/evaluation/generate_report.py` | 生成评估报告 |

### DotaBench 评测集

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `DotaBench/README.md` | DotaBench 说明文档 |
| Create | `DotaBench/skill_bench/lineup_analyzer/cases.jsonl` | 阵容分析用例（≥30 条） |
| Create | `DotaBench/skill_bench/lineup_analyzer/expected.jsonl` | 阵容分析期望输出 |
| Create | `DotaBench/skill_bench/lineup_analyzer/judge_prompts.yaml` | 阵容分析 Judge Prompt |
| Create | `DotaBench/skill_bench/dialogue_understander/cases.jsonl` | 对话理解用例 |
| Create | `DotaBench/skill_bench/dialogue_understander/expected.jsonl` | 对话理解期望输出 |
| Create | `DotaBench/skill_bench/dialogue_understander/judge_prompts.yaml` | 对话理解 Judge Prompt |
| Create | `DotaBench/skill_bench/meta_analyzer/cases.jsonl` | 版本强势用例 |
| Create | `DotaBench/skill_bench/meta_analyzer/expected.jsonl` | 版本强势期望输出 |
| Create | `DotaBench/skill_bench/meta_analyzer/judge_prompts.yaml` | 版本强势 Judge Prompt |
| Create | `DotaBench/skill_bench/knowledge_query/cases.jsonl` | 知识查询用例 |
| Create | `DotaBench/skill_bench/knowledge_query/expected.jsonl` | 知识查询期望输出 |
| Create | `DotaBench/skill_bench/knowledge_query/judge_prompts.yaml` | 知识查询 Judge Prompt |
| Create | `DotaBench/skill_bench/web_search/cases.jsonl` | 智能搜索用例 |
| Create | `DotaBench/skill_bench/web_search/expected.jsonl` | 智能搜索期望输出 |
| Create | `DotaBench/skill_bench/web_search/judge_prompts.yaml` | 智能搜索 Judge Prompt |
| Create | `DotaBench/subagent_bench/counter_pick/cases.jsonl` | 英雄克制用例 |
| Create | `DotaBench/subagent_bench/counter_pick/expected.jsonl` | 英雄克制期望输出 |
| Create | `DotaBench/subagent_bench/counter_pick/judge_prompts.yaml` | 英雄克制 Judge Prompt |
| Create | `DotaBench/subagent_bench/item_recommender/cases.jsonl` | 出装推荐用例 |
| Create | `DotaBench/subagent_bench/item_recommender/expected.jsonl` | 出装推荐期望输出 |
| Create | `DotaBench/subagent_bench/item_recommender/judge_prompts.yaml` | 出装推荐 Judge Prompt |
| Create | `DotaBench/subagent_bench/skill_builder/cases.jsonl` | 技能加点用例 |
| Create | `DotaBench/subagent_bench/skill_builder/expected.jsonl` | 技能加点期望输出 |
| Create | `DotaBench/subagent_bench/skill_builder/judge_prompts.yaml` | 技能加点 Judge Prompt |
| Create | `DotaBench/subagent_bench/event_advisor/cases.jsonl` | 事件提醒用例 |
| Create | `DotaBench/subagent_bench/event_advisor/expected.jsonl` | 事件提醒期望输出 |
| Create | `DotaBench/subagent_bench/event_advisor/judge_prompts.yaml` | 事件提醒 Judge Prompt |
| Create | `DotaBench/subagent_bench/proactive_recommender/cases.jsonl` | 主动推荐用例 |
| Create | `DotaBench/subagent_bench/proactive_recommender/expected.jsonl` | 主动推荐期望输出 |
| Create | `DotaBench/subagent_bench/proactive_recommender/judge_prompts.yaml` | 主动推荐 Judge Prompt |
| Create | `DotaBench/subagent_bench/feedback_learner/cases.jsonl` | 反馈学习用例 |
| Create | `DotaBench/subagent_bench/feedback_learner/expected.jsonl` | 反馈学习期望输出 |
| Create | `DotaBench/subagent_bench/feedback_learner/judge_prompts.yaml` | 反馈学习 Judge Prompt |
| Create | `DotaBench/e2e_bench/user_scenarios.jsonl` | 端到端场景 |
| Create | `DotaBench/e2e_bench/eval_scenarios.yaml` | 场景定义 |
| Create | `DotaBench/human_eval/sample_pool.jsonl` | 人工评估样本池 |
| Create | `DotaBench/human_eval/rubrics.yaml` | 评分量表 |
| Create | `DotaBench/utils/case_loader.py` | 用例加载器 |
| Create | `DotaBench/utils/case_validator.py` | 用例校验器 |

### 测试与 CI

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `tests/evaluation/__init__.py` | 测试包 |
| Create | `tests/evaluation/test_base.py` | 基类测试 |
| Create | `tests/evaluation/test_judges.py` | Judge 测试 |
| Create | `tests/evaluation/test_trajectory.py` | 轨迹评估测试 |
| Create | `tests/evaluation/test_regression.py` | 回归测试 |
| Create | `tests/evaluation/test_calibration.py` | 校准测试 |
| Create | `tests/evaluation/test_diy_bench.py` | DotaBench 集成测试 |
| Create | `.github/workflows/evaluation.yml` | CI 工作流 |

---

## 任务阶段划分

### 阶段 1：基础设施搭建 + DotaBench 评测集（第 1-2 周）

#### Task 1.1: 评估器基类

**Files:**
- Create: `evaluation/__init__.py`
- Create: `evaluation/base.py`

- [ ] **Step 1: Create `evaluation/__init__.py`**

```python
"""评测系统

为 DotaHelperAgent 提供三层评估能力：
- L1 离线评测（开发阶段）：标准测试集 + 单元/集成测试
- L2 在线评测（生产阶段）：Trace + 用户反馈
- L3 回归测试（发布阶段）：基线对比 + A/B 测试

核心组件：
- BaseEvaluator: 评估器抽象基类
- LLM-as-a-Judge: 7 维评分
- Trajectory Evaluator: 轨迹评估
- Regression Tester: 回归测试
- DotaBench: 自建评测集
"""

from .base import (
    BaseEvaluator,
    EvaluationResult,
    EvaluationContext,
    EvaluationStatus,
    ScoreDimension,
)

__all__ = [
    'BaseEvaluator',
    'EvaluationResult',
    'EvaluationContext',
    'EvaluationStatus',
    'ScoreDimension',
]
```

- [ ] **Step 2: Create `evaluation/base.py`**

```python
"""评估器基类

定义评估器的统一接口和数据结构。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import logging
import time

logger = logging.getLogger(__name__)


class EvaluationStatus(str, Enum):
    """评估状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScoreDimension(str, Enum):
    """评分维度（7 维评分量表，参考 GAIA）"""
    CORRECTNESS = "correctness"       # 正确性 25%
    COMPLETENESS = "completeness"     # 完整性 15%
    RELEVANCE = "relevance"           # 相关性 15%
    TOOL_SELECTION = "tool_selection" # 工具选择 15%
    EFFICIENCY = "efficiency"         # 效率 10%
    ROBUSTNESS = "robustness"         # 鲁棒性 10%
    PERSONALIZATION = "personalization"  # 个性化 10%


# 维度权重（与文档保持一致）
DIMENSION_WEIGHTS: Dict[ScoreDimension, float] = {
    ScoreDimension.CORRECTNESS: 0.25,
    ScoreDimension.COMPLETENESS: 0.15,
    ScoreDimension.RELEVANCE: 0.15,
    ScoreDimension.TOOL_SELECTION: 0.15,
    ScoreDimension.EFFICIENCY: 0.10,
    ScoreDimension.ROBUSTNESS: 0.10,
    ScoreDimension.PERSONALIZATION: 0.10,
}


@dataclass
class EvaluationContext:
    """评估上下文
    
    Attributes:
        case_id: 测试用例 ID
        input_data: 输入数据
        expected_output: 期望输出
        actual_output: 实际输出
        trace_id: 关联的 Trace ID
        session_id: 关联的会话 ID
        metadata: 额外元数据
    """
    case_id: str
    input_data: Any
    expected_output: Optional[Any] = None
    actual_output: Optional[Any] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """评估结果
    
    Attributes:
        case_id: 测试用例 ID
        evaluator_name: 评估器名称
        status: 评估状态
        dimension_scores: 各维度评分（1-5）
        total_score: 加权总分（0-5）
        confidence: 评估置信度（0-1）
        reasoning: 评分理由
        error: 错误信息（如果失败）
        execution_time: 执行耗时（秒）
        timestamp: 评估时间戳
        metadata: 额外元数据
    """
    case_id: str
    evaluator_name: str
    status: EvaluationStatus
    dimension_scores: Dict[ScoreDimension, float] = field(default_factory=dict)
    total_score: float = 0.0
    confidence: float = 1.0
    reasoning: str = ""
    error: Optional[str] = None
    execution_time: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def calculate_total_score(self) -> float:
        """根据维度权重计算加权总分"""
        if not self.dimension_scores:
            return 0.0
        weighted_sum = sum(
            score * DIMENSION_WEIGHTS.get(dim, 0.0)
            for dim, score in self.dimension_scores.items()
        )
        return round(weighted_sum, 3)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'case_id': self.case_id,
            'evaluator_name': self.evaluator_name,
            'status': self.status.value,
            'dimension_scores': {d.value: s for d, s in self.dimension_scores.items()},
            'total_score': self.total_score,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'error': self.error,
            'execution_time': self.execution_time,
            'timestamp': self.timestamp,
            'metadata': self.metadata,
        }


class BaseEvaluator(ABC):
    """评估器抽象基类
    
    所有具体评估器（Judge、Trajectory、Regression）必须继承此类。
    """
    
    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
    ):
        self.name = name
        self.version = version
        self.description = description
    
    @abstractmethod
    async def evaluate(
        self,
        context: EvaluationContext,
    ) -> EvaluationResult:
        """执行评估
        
        Args:
            context: 评估上下文
            
        Returns:
            EvaluationResult: 评估结果
        """
        pass
    
    async def run(
        self,
        context: EvaluationContext,
    ) -> EvaluationResult:
        """执行入口（带异常处理和计时）"""
        start_time = time.time()
        try:
            result = await self.evaluate(context)
            result.execution_time = time.time() - start_time
            if not result.total_score and result.dimension_scores:
                result.total_score = result.calculate_total_score()
            return result
        except Exception as e:
            logger.error(f"Evaluator '{self.name}' failed: {e}")
            return EvaluationResult(
                case_id=context.case_id,
                evaluator_name=self.name,
                status=EvaluationStatus.FAILED,
                error=str(e),
                execution_time=time.time() - start_time,
            )
```

#### Task 1.2: 全局配置

**Files:**
- Create: `config/evaluation_config.yaml`

- [ ] **Step 1: Create `config/evaluation_config.yaml`**

```yaml
# 评测系统全局配置

# 评估器配置
evaluators:
  # 7 维评分量表
  dimensions:
    correctness: 0.25
    completeness: 0.15
    relevance: 0.15
    tool_selection: 0.15
    efficiency: 0.10
    robustness: 0.10
    personalization: 0.10

# LLM-as-a-Judge 配置
judges:
  enabled: true
  timeout: 30.0
  temperature: 0.0  # 降低采样噪声
  n_samples: 3      # 多次采样取平均
  
  # 多模型投票（降低偏见）
  models:
    primary: "gpt-4o"           # 主要 Judge
    secondary: "claude-3.5-sonnet"  # 次要 Judge
    tertiary: "gemini-1.5-pro"  # 第三 Judge
  voting_strategy: "majority"   # majority / average / weighted

# Trajectory 评估配置
trajectory:
  enabled: true
  metrics:
    tool_selection_accuracy: 0.85    # 目标值
    argument_correctness: 0.80
    dependency_satisfaction: 0.90
    premature_invocation_rate: 0.10  # 上限
    clue_adherence_rate: 0.80
    error_propagation_rate: 0.15     # 上限
    rejection_rate: 0.70             # 下限
    recovery_rate: 0.60              # 下限
    avg_steps: 5                     # 上限
    max_steps: 10                    # 硬上限

# 回归测试配置
regression:
  enabled: true
  baseline_path: "data/evaluation/baselines/"
  ab_test:
    significance_level: 0.05
    min_sample_size: 100

# 在线监控配置
monitoring:
  enabled: true
  refresh_interval_seconds: 60
  alert_thresholds:
    avg_score_drop: 0.3        # 平均分下降 0.3 触发告警
    fallback_rate: 0.15        # 降级率超过 15% 触发告警
    p99_latency_ms: 15000      # P99 延迟超过 15s 触发告警

# 成本控制
cost_control:
  monthly_budget_usd: 100
  judge_model_priority:
    critical: "gpt-4o"
    standard: "gpt-4o-mini"
    bulk: "llama-3-70b"        # 批量评估用开源模型
```

#### Task 1.3: DotaBench 评测集结构

**Files:**
- Create: `DotaBench/README.md`
- Create: `DotaBench/skill_bench/lineup_analyzer/cases.jsonl`
- Create: `DotaBench/skill_bench/lineup_analyzer/expected.jsonl`
- Create: `DotaBench/skill_bench/lineup_analyzer/judge_prompts.yaml`
- Create: `DotaBench/utils/case_loader.py`
- Create: `DotaBench/utils/case_validator.py`

- [ ] **Step 1: Create `DotaBench/README.md`**

````markdown
# DotaBench - DotaHelperAgent 自建评测集

## 概述

DotaBench 是 DotaHelperAgent 的自建领域评测集，覆盖所有 Skill/SubAgent 的典型场景。由于 Dota 2 领域**无公开标准评测集**（与 GAIA/WebArena 不同），需自建。

## 目录结构

```
DotaBench/
├── skill_bench/           # Skill 评测（轻量、单次 LLM 调用）
│   ├── lineup_analyzer/   # 阵容分析
│   ├── dialogue_understander/  # 对话理解
│   ├── meta_analyzer/     # 版本强势
│   ├── knowledge_query/   # 知识查询
│   └── web_search/        # 智能搜索
├── subagent_bench/        # SubAgent 评测（重、多步推理）
│   ├── counter_pick/      # 英雄克制
│   ├── item_recommender/  # 出装推荐
│   ├── skill_builder/     # 技能加点
│   ├── event_advisor/     # 事件提醒
│   ├── proactive_recommender/  # 主动推荐
│   └── feedback_learner/  # 反馈学习
├── e2e_bench/             # 端到端场景
└── human_eval/            # 人工评估
```

## 用例设计原则

1. **覆盖度**：覆盖各 Skill/SubAgent 的典型场景
2. **难度分层**：简单（30%）、中等（50%）、困难（20%）
3. **多样性**：包含正常输入、边界输入、异常输入
4. **可对比**：每条用例都有期望输出（参考答案）
5. **可扩展**：支持增量添加新用例

## 每个用例目录的标准文件

- `cases.jsonl` - 测试用例（输入）
- `expected.jsonl` - 期望输出（参考答案）
- `judge_prompts.yaml` - Judge Prompt 模板

## 用例格式

```json
{
  "case_id": "unique_id",
  "input": { ... },
  "difficulty": "easy|medium|hard",
  "tags": ["tag1", "tag2"]
}
```

## 期望输出格式

```json
{
  "case_id": "unique_id",
  "key_points": ["要点1", "要点2"],
  "must_include": ["必含元素"],
  "verdict": "整体评估"
}
```

## 使用方法

```bash
# 运行整个 DotaBench
python scripts/evaluation/run_diy_bench.py

# 运行单个模块
python scripts/evaluation/run_diy_bench.py --module lineup_analyzer

# 指定难度
python scripts/evaluation/run_diy_bench.py --difficulty hard
```
````

- [ ] **Step 2: Create `DotaBench/skill_bench/lineup_analyzer/cases.jsonl`**

```json
{"case_id": "lineup_001", "input": {"radiant_heroes": ["幻影刺客", "水晶室女", "潮汐猎人", "剧毒术士", "发条技师"], "dire_heroes": ["敌法师", "莉娜", "莱恩", "沙王", "巫医"]}, "difficulty": "medium", "tags": ["control", "burst", "anti-carry"]}
{"case_id": "lineup_002", "input": {"radiant_heroes": ["幽鬼", "沉默术士", "天怒法师", "巫医", "光之守卫"], "dire_heroes": ["斯温", "亚巴顿", "马格纳斯", "撼地者", "术士"]}, "difficulty": "medium", "tags": ["teamfight", "global"]}
{"case_id": "lineup_003", "input": {"radiant_heroes": ["米波", "先知", "兽王", "炼金术士", "齐天大圣"], "dire_heroes": ["剃刀", "死亡先知", "瘟疫法师", "半人马战行者", "发条技师"]}, "difficulty": "hard", "tags": ["split-push", "macro"]}
{"case_id": "lineup_004", "input": {"radiant_heroes": [], "dire_heroes": []}, "difficulty": "easy", "tags": ["empty-input", "edge-case"]}
{"case_id": "lineup_005", "input": {"radiant_heroes": ["虚无之灵"], "dire_heroes": ["虚无之灵"]}, "difficulty": "hard", "tags": ["mirror-match", "single-hero"]}
```

- [ ] **Step 3: Create `DotaBench/skill_bench/lineup_analyzer/expected.jsonl`**

```json
{"case_id": "lineup_001", "key_points": ["己方有 PA + 水晶室女的高爆发组合", "己方控制能力强（潮汐、剧毒、发条）", "敌方有敌法师克制 PA", "敌方控制偏弱（莱恩、沙王单体控制）"], "must_include_heroes": ["幻影刺客", "敌法师"], "verdict": "己方阵容控制强、爆发高，敌方单体控制多"}
{"case_id": "lineup_002", "key_points": ["己方全球流（幽鬼、先知）", "己方大招流（沉默、天怒大招）", "敌方偏中后期团战（斯温、术士）"], "must_include_heroes": ["幽鬼", "斯温"], "verdict": "己方全球流克敌方团战阵容"}
{"case_id": "lineup_003", "key_points": ["己方分推能力强", "己方有米波+齐天大圣的分推核心", "敌方团战能力强（剃刀、死亡先知、半人马）"], "must_include_heroes": ["米波", "剃刀"], "verdict": "己方分推 vs 敌方团战"}
{"case_id": "lineup_004", "key_points": ["应能处理空输入"], "must_include_heroes": [], "verdict": "应提示输入无效"}
{"case_id": "lineup_005", "key_points": ["镜像对局", "单英雄分析"], "must_include_heroes": ["虚无之灵"], "verdict": "镜像对局无明显克制"}
```

- [ ] **Step 4: Create `DotaBench/skill_bench/lineup_analyzer/judge_prompts.yaml`**

```yaml
lineup_analyzer_judge:
  system: |
    你是一名 Dota 2 阵容分析质量评估专家。
    请基于以下 7 个维度评估输出质量（1-5 分）：
    1. 正确性（25%）：英雄特性识别、控制/爆发判断是否准确
    2. 完整性（15%）：是否覆盖己方优势、己方劣势、敌方优势、敌方劣势、关键对决点
    3. 相关性（15%）：是否切题，避免无关内容
    4. 工具选择（15%）：是否调用了英雄数据工具、克制关系工具
    5. 效率（10%）：是否在合理步数内完成
    6. 鲁棒性（10%）：对空输入、异常输入的容错
    7. 个性化（10%）：是否考虑用户英雄偏好（如有）

  template: |
    ## 输入
    己方阵容：{radiant_heroes}
    敌方阵容：{dire_heroes}

    ## 期望关键点
    {expected_points}

    ## 实际输出
    {actual_output}

    ## 评估
    请按 7 维度评分，并给出总分（加权平均）和简要理由。

    输出 JSON 格式：
    {{
      "correctness": 1-5,
      "completeness": 1-5,
      "relevance": 1-5,
      "tool_selection": 1-5,
      "efficiency": 1-5,
      "robustness": 1-5,
      "personalization": 1-5,
      "total_score": 加权平均,
      "reasoning": "评分理由"
    }}
```

- [ ] **Step 5: Create `DotaBench/utils/case_loader.py`**

```python
"""用例加载器

从 JSONL 文件加载测试用例。
"""

import json
from pathlib import Path
from typing import Dict, Iterator, List, Optional


class CaseLoader:
    """用例加载器"""
    
    def __init__(self, base_path: str = "DotaBench"):
        self.base_path = Path(base_path)
    
    def load_cases(
        self,
        module: str,
        bench_type: str = "skill_bench",
        difficulty: Optional[str] = None,
    ) -> List[Dict]:
        """加载测试用例
        
        Args:
            module: 模块名（如 lineup_analyzer）
            bench_type: 评测类型（skill_bench / subagent_bench / e2e_bench）
            difficulty: 难度过滤（easy / medium / hard）
            
        Returns:
            用例列表
        """
        cases_path = self.base_path / bench_type / module / "cases.jsonl"
        if not cases_path.exists():
            raise FileNotFoundError(f"Cases file not found: {cases_path}")
        
        cases = []
        with open(cases_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                if difficulty and case.get('difficulty') != difficulty:
                    continue
                cases.append(case)
        return cases
    
    def load_expected(self, module: str, bench_type: str = "skill_bench") -> Dict[str, Dict]:
        """加载期望输出（按 case_id 索引）"""
        expected_path = self.base_path / bench_type / module / "expected.jsonl"
        if not expected_path.exists():
            return {}
        
        expected_map = {}
        with open(expected_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                expected_map[item['case_id']] = item
        return expected_map
    
    def load_judge_prompts(
        self,
        module: str,
        bench_type: str = "skill_bench",
    ) -> Dict:
        """加载 Judge Prompt 模板"""
        import yaml
        prompts_path = self.base_path / bench_type / module / "judge_prompts.yaml"
        if not prompts_path.exists():
            return {}
        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
```

- [ ] **Step 6: Create `DotaBench/utils/case_validator.py`**

```python
"""用例校验器

校验测试用例的格式、必填字段、ID 唯一性。
"""

import json
from pathlib import Path
from typing import Dict, List


class CaseValidationError(Exception):
    """用例校验错误"""
    pass


class CaseValidator:
    """用例校验器"""
    
    REQUIRED_FIELDS = ['case_id', 'input', 'difficulty']
    VALID_DIFFICULTIES = ['easy', 'medium', 'hard']
    
    def validate_cases(self, cases: List[Dict]) -> None:
        """校验用例列表"""
        seen_ids = set()
        for i, case in enumerate(cases):
            self._validate_case(case, i)
            if case['case_id'] in seen_ids:
                raise CaseValidationError(
                    f"Duplicate case_id: {case['case_id']}"
                )
            seen_ids.add(case['case_id'])
    
    def _validate_case(self, case: Dict, index: int) -> None:
        """校验单条用例"""
        for field in self.REQUIRED_FIELDS:
            if field not in case:
                raise CaseValidationError(
                    f"Case at index {index} missing field: {field}"
                )
        
        if case['difficulty'] not in self.VALID_DIFFICULTIES:
            raise CaseValidationError(
                f"Case {case['case_id']} invalid difficulty: {case['difficulty']}"
            )
        
        if not case['case_id']:
            raise CaseValidationError(f"Case at index {index} has empty case_id")
    
    def validate_files(self, cases_path: Path, expected_path: Path) -> None:
        """校验用例文件和期望文件的一致性"""
        cases = []
        with open(cases_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    cases.append(json.loads(line))
        self.validate_cases(cases)
        
        expected_ids = set()
        if expected_path.exists():
            with open(expected_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        item = json.loads(line)
                        expected_ids.add(item['case_id'])
        
        case_ids = {c['case_id'] for c in cases}
        missing = case_ids - expected_ids
        if missing:
            raise CaseValidationError(
                f"Cases missing expected output: {missing}"
            )
```

#### Task 1.4: 用例扩展示例（为其他模块提供模板）

**Files:**
- Create: `DotaBench/skill_bench/dialogue_understander/cases.jsonl`
- Create: `DotaBench/subagent_bench/counter_pick/cases.jsonl`
- Create: `DotaBench/subagent_bench/counter_pick/expected.jsonl`

> 注：完整用例集需在阶段 1 后续迭代中扩充，本 Task 仅提供模板。

- [ ] **Step 1: Create `DotaBench/skill_bench/dialogue_understander/cases.jsonl`**

```json
{"case_id": "dialogue_001", "input": {"history": [{"role": "user", "content": "幻影刺客怎么出装？"}, {"role": "assistant", "content": "PA 核心装是狂战斧..."}], "current_input": "它后期怎么打？"}, "difficulty": "medium", "tags": ["coreference", "pronominal"]}
{"case_id": "dialogue_002", "input": {"history": [], "current_input": "哪个英雄克制敌法师？"}, "difficulty": "easy", "tags": ["no-history", "intent-extraction"]}
{"case_id": "dialogue_003", "input": {"history": [{"role": "user", "content": "潮汐和发条谁强？"}], "current_input": "那个大招厉害"}, "difficulty": "hard", "tags": ["ambiguous-reference"]}
```

- [ ] **Step 2: Create `DotaBench/subagent_bench/counter_pick/cases.jsonl`**

```json
{"case_id": "counter_pick_001", "input": {"enemy_heroes": ["幻影刺客", "火枪手"]}, "difficulty": "easy", "tags": ["counter", "pa", "sniper"]}
{"case_id": "counter_pick_002", "input": {"enemy_heroes": ["斯温", "马格纳斯", "撼地者", "亚巴顿", "术士"]}, "difficulty": "hard", "tags": ["teamfight", "durable"]}
{"case_id": "counter_pick_003", "input": {"enemy_heroes": ["米波", "先知", "兽王", "炼金术士", "齐天大圣"]}, "difficulty": "hard", "tags": ["split-push"]}
```

- [ ] **Step 3: Create `DotaBench/subagent_bench/counter_pick/expected.jsonl`**

```json
{"case_id": "counter_pick_001", "top_recommendations": [{"hero": "敌法师", "reason": "法术免疫克制 PA 标记"}, {"hero": "潮汐猎人", "reason": "技能增强降低 PA 暴击伤害"}, {"hero": "末日使者", "reason": "大招无视 BKB"}], "must_include_heroes": ["敌法师", "潮汐猎人"]}
```

### 阶段 1 验收

- [ ] `evaluation/base.py` 创建完成，单元测试通过
- [ ] `DotaBench/` 目录结构创建完成
- [ ] 至少 5 个模块的 `cases.jsonl` + `expected.jsonl` 创建完成
- [ ] `DotaBench/utils/case_loader.py` + `case_validator.py` 创建完成
- [ ] 用例格式校验工具测试通过

---

### 阶段 2：LLM-as-a-Judge 实施（第 2-3 周）

#### Task 2.1: 基础 Judge

**Files:**
- Create: `evaluation/judges/__init__.py`
- Create: `evaluation/judges/base_judge.py`
- Create: `evaluation/judges/prompts.yaml`

- [ ] **Step 1: Create `evaluation/judges/__init__.py`**

```python
"""LLM-as-a-Judge 子包

实现 7 维评分 Judge、轨迹评估 Judge、多模型投票、BabelJudge 校准。
"""

from .base_judge import BaseJudge
from .multi_dimensional_judge import MultiDimensionalJudge
from .trajectory_judge import TrajectoryJudge
from .multi_model_voter import MultiModelVoter, VotingStrategy
from .calibration import JudgeCalibrator

__all__ = [
    'BaseJudge',
    'MultiDimensionalJudge',
    'TrajectoryJudge',
    'MultiModelVoter',
    'VotingStrategy',
    'JudgeCalibrator',
]
```

- [ ] **Step 2: Create `evaluation/judges/base_judge.py`**

```python
"""基础 Judge 抽象类

所有 Judge 实现必须继承此基类。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging
import time

from ..base import (
    BaseEvaluator,
    EvaluationContext,
    EvaluationResult,
    EvaluationStatus,
    ScoreDimension,
)

logger = logging.getLogger(__name__)


class BaseJudge(BaseEvaluator, ABC):
    """Judge 抽象基类
    
    Attributes:
        llm_client: LLM 客户端
        prompt_template: Judge Prompt 模板
        temperature: 采样温度（默认 0.0 降低噪声）
        n_samples: 多次采样次数（取平均）
    """
    
    def __init__(
        self,
        llm_client: Any,
        prompt_template: Optional[Dict] = None,
        temperature: float = 0.0,
        n_samples: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.llm_client = llm_client
        self.prompt_template = prompt_template or {}
        self.temperature = temperature
        self.n_samples = n_samples
    
    @abstractmethod
    def build_prompt(
        self,
        context: EvaluationContext,
    ) -> str:
        """构造 Judge Prompt"""
        pass
    
    @abstractmethod
    def parse_response(
        self,
        response: str,
    ) -> Dict[ScoreDimension, float]:
        """解析 Judge 响应为维度评分"""
        pass
    
    async def evaluate(
        self,
        context: EvaluationContext,
    ) -> EvaluationResult:
        """执行 Judge 评估（多次采样取平均）"""
        prompt = self.build_prompt(context)
        
        # 多次采样
        samples: List[Dict[ScoreDimension, float]] = []
        reasonings: List[str] = []
        for i in range(self.n_samples):
            response = await self.llm_client.generate(
                prompt,
                temperature=self.temperature,
            )
            parsed = self.parse_response(response)
            samples.append(parsed)
            reasonings.append(response)
        
        # 平均化
        avg_scores = self._average_samples(samples)
        
        return EvaluationResult(
            case_id=context.case_id,
            evaluator_name=self.name,
            status=EvaluationStatus.COMPLETED,
            dimension_scores=avg_scores,
            confidence=min(1.0, len(samples) / self.n_samples),
            reasoning=reasonings[0] if reasonings else "",
            metadata={'n_samples': len(samples)},
        )
    
    def _average_samples(
        self,
        samples: List[Dict[ScoreDimension, float]],
    ) -> Dict[ScoreDimension, float]:
        """对多次采样结果取平均"""
        if not samples:
            return {}
        all_dims = set()
        for s in samples:
            all_dims.update(s.keys())
        return {
            dim: round(sum(s.get(dim, 0.0) for s in samples) / len(samples), 2)
            for dim in all_dims
        }
```

- [ ] **Step 3: Create `evaluation/judges/prompts.yaml`**

```yaml
# Judge Prompt 模板库

# 7 维评分通用模板
seven_dimension_judge:
  system: |
    你是一名专业的 AI 助手输出质量评估专家。
    请基于以下 7 个维度评估输出质量（每维 1-5 分）：
    1. 正确性（25%）：答案是否准确、是否符合事实
    2. 完整性（15%）：是否覆盖所有要点
    3. 相关性（15%）：是否切题、避免无关内容
    4. 工具选择（15%）：使用的工具是否合适
    5. 效率（10%）：步骤是否精简、路径是否最优
    6. 鲁棒性（10%）：对异常输入的容错
    7. 个性化（10%）：是否贴合用户风格

  template: |
    ## 输入
    {input}

    ## 期望输出
    {expected}

    ## 实际输出
    {actual}

    ## 评估
    请按 7 维度评分（1-5），并给出总分（加权平均）和简要理由。

    输出 JSON 格式：
    {{
      "correctness": 1-5,
      "completeness": 1-5,
      "relevance": 1-5,
      "tool_selection": 1-5,
      "efficiency": 1-5,
      "robustness": 1-5,
      "personalization": 1-5,
      "total_score": 加权平均,
      "reasoning": "评分理由"
    }}

# 轨迹评估模板
trajectory_judge:
  system: |
    你是一名 AI Agent 轨迹评估专家。
    评估 Agent 的完整执行轨迹而非仅最终输出。

  template: |
    ## 任务
    {task}

    ## 期望关键点
    {expected}

    ## 实际执行轨迹
    {trajectory}

    ## 评估维度
    1. tool_selection_accuracy (0-1): 工具选择是否合适
    2. argument_correctness (0-1): 参数是否正确
    3. dependency_satisfaction (0-1): 依赖/顺序是否满足
    4. premature_invocation_rate (0-1): 是否过早调用
    5. clue_adherence_rate (0-1): 是否遵循关键线索
    6. error_propagation_rate (0-1): 错误是否被传播

    输出 JSON 格式：
    {{
      "tool_selection_accuracy": 0.0-1.0,
      "argument_correctness": 0.0-1.0,
      "dependency_satisfaction": 0.0-1.0,
      "premature_invocation_rate": 0.0-1.0,
      "clue_adherence_rate": 0.0-1.0,
      "error_propagation_rate": 0.0-1.0,
      "reasoning": "评分理由"
    }}
```

#### Task 2.2: 7 维评分 Judge

**Files:**
- Create: `evaluation/judges/multi_dimensional_judge.py`

- [ ] **Step 1: Create `evaluation/judges/multi_dimensional_judge.py`**

```python
"""7 维评分 Judge

实现 7 维评分量表（正确性/完整性/相关性/工具选择/效率/鲁棒性/个性化）。
"""

import json
import re
from typing import Any, Dict, Optional

from ..base import EvaluationContext, ScoreDimension
from .base_judge import BaseJudge


class MultiDimensionalJudge(BaseJudge):
    """7 维评分 Judge
    
    Attributes:
        module_name: 对应的 Skill/SubAgent 模块名（用于加载专属 Prompt）
    """
    
    def __init__(
        self,
        llm_client: Any,
        module_name: Optional[str] = None,
        prompt_overrides: Optional[Dict] = None,
        **kwargs,
    ):
        super().__init__(
            name=f"multi_dimensional_judge_{module_name or 'default'}",
            version="1.0.0",
            description="7 维评分 Judge",
            llm_client=llm_client,
            **kwargs,
        )
        self.module_name = module_name
        self.prompt_overrides = prompt_overrides or {}
    
    def build_prompt(self, context: EvaluationContext) -> str:
        """构造 Judge Prompt"""
        # 优先使用模块专属 Prompt，其次使用通用模板
        template = (
            self.prompt_overrides.get('template')
            or self.prompt_template.get('seven_dimension_judge', {}).get('template', '')
        )
        system = (
            self.prompt_overrides.get('system')
            or self.prompt_template.get('seven_dimension_judge', {}).get('system', '')
        )
        
        # 提取期望关键点
        expected = context.expected_output or {}
        if isinstance(expected, dict):
            expected_points = '\n'.join(f"- {p}" for p in expected.get('key_points', []))
        else:
            expected_points = str(expected)
        
        user_prompt = template.format(
            input=context.input_data,
            expected=expected_points,
            actual=context.actual_output,
        )
        
        # 合并 system + user（因不同 LLM 客户端接口不同）
        return f"{system}\n\n{user_prompt}"
    
    def parse_response(self, response: str) -> Dict[ScoreDimension, float]:
        """解析 Judge 响应"""
        # 提取 JSON（处理 markdown 代码块）
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接找 JSON 对象
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            json_str = json_match.group(0) if json_match else response
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 解析失败时返回默认分
            return {dim: 3.0 for dim in ScoreDimension}
        
        # 映射到 ScoreDimension 枚举
        dimension_map = {
            'correctness': ScoreDimension.CORRECTNESS,
            'completeness': ScoreDimension.COMPLETENESS,
            'relevance': ScoreDimension.RELEVANCE,
            'tool_selection': ScoreDimension.TOOL_SELECTION,
            'efficiency': ScoreDimension.EFFICIENCY,
            'robustness': ScoreDimension.ROBUSTNESS,
            'personalization': ScoreDimension.PERSONALIZATION,
        }
        
        scores = {}
        for key, dim in dimension_map.items():
            if key in data:
                try:
                    score = float(data[key])
                    scores[dim] = max(1.0, min(5.0, score))
                except (ValueError, TypeError):
                    scores[dim] = 3.0
        return scores
```

#### Task 2.3: 多模型投票

**Files:**
- Create: `evaluation/judges/multi_model_voter.py`

- [ ] **Step 1: Create `evaluation/judges/multi_model_voter.py`**

```python
"""多模型投票器

降低 LLM Judge 偏见：使用多个不同家族的 LLM 作为 Judge，取投票结果。
参考 Microsoft Foundry 2026.01 报告的"Inter-Model Agreement"原则。
"""

import asyncio
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from ..base import (
    EvaluationContext,
    EvaluationResult,
    EvaluationStatus,
    ScoreDimension,
)
from .base_judge import BaseJudge

logger = logging.getLogger(__name__)


class VotingStrategy(str, Enum):
    """投票策略"""
    MAJORITY = "majority"      # 多数投票
    AVERAGE = "average"        # 平均分
    WEIGHTED = "weighted"      # 加权平均（按模型权重）
    MAX = "max"                # 取最高分
    MIN = "min"                # 取最低分（保守）


class MultiModelVoter:
    """多模型投票器
    
    使用多个 LLM 作为 Judge，通过投票/平均降低单模型偏见。
    """
    
    def __init__(
        self,
        judges: List[BaseJudge],
        strategy: VotingStrategy = VotingStrategy.AVERAGE,
        weights: Optional[List[float]] = None,
    ):
        if not judges:
            raise ValueError("At least one judge is required")
        if weights and len(weights) != len(judges):
            raise ValueError("Weights length must match judges length")
        
        self.judges = judges
        self.strategy = strategy
        self.weights = weights or [1.0] * len(judges)
    
    async def evaluate(self, context: EvaluationContext) -> EvaluationResult:
        """执行多模型评估"""
        # 并行执行所有 Judge
        tasks = [judge.run(context) for judge in self.judges]
        results: List[EvaluationResult] = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 过滤失败结果
        valid_results = [r for r in results if isinstance(r, EvaluationResult) and r.status == EvaluationStatus.COMPLETED]
        if not valid_results:
            return EvaluationResult(
                case_id=context.case_id,
                evaluator_name="multi_model_voter",
                status=EvaluationStatus.FAILED,
                error="All judges failed",
            )
        
        # 聚合评分
        merged_scores = self._merge_scores(valid_results)
        
        return EvaluationResult(
            case_id=context.case_id,
            evaluator_name="multi_model_voter",
            status=EvaluationStatus.COMPLETED,
            dimension_scores=merged_scores,
            confidence=len(valid_results) / len(self.judges),
            reasoning=self._build_reasoning(valid_results),
            metadata={
                'n_judges': len(self.judges),
                'n_successful': len(valid_results),
                'strategy': self.strategy.value,
                'individual_results': [r.to_dict() for r in valid_results],
            },
        )
    
    def _merge_scores(
        self,
        results: List[EvaluationResult],
    ) -> Dict[ScoreDimension, float]:
        """根据策略合并评分"""
        all_dims = set()
        for r in results:
            all_dims.update(r.dimension_scores.keys())
        
        if self.strategy == VotingStrategy.AVERAGE:
            return {
                dim: round(
                    sum(r.dimension_scores.get(dim, 0.0) for r in results) / len(results), 2
                )
                for dim in all_dims
            }
        elif self.strategy == VotingStrategy.WEIGHTED:
            return {
                dim: round(
                    sum(
                        r.dimension_scores.get(dim, 0.0) * w
                        for r, w in zip(results, self.weights)
                    ) / sum(self.weights), 2
                )
                for dim in all_dims
            }
        elif self.strategy == VotingStrategy.MAX:
            return {
                dim: max((r.dimension_scores.get(dim, 0.0) for r in results), default=0.0)
                for dim in all_dims
            }
        elif self.strategy == VotingStrategy.MIN:
            return {
                dim: min((r.dimension_scores.get(dim, 0.0) for r in results), default=0.0)
                for dim in all_dims
            }
        else:  # MAJORITY
            return self._majority_vote(results, all_dims)
    
    def _majority_vote(
        self,
        results: List[EvaluationResult],
        dimensions: set,
    ) -> Dict[ScoreDimension, float]:
        """多数投票（取中位数）"""
        import statistics
        return {
            dim: statistics.median([r.dimension_scores.get(dim, 0.0) for r in results])
            for dim in dimensions
        }
    
    def _build_reasoning(self, results: List[EvaluationResult]) -> str:
        """构造综合理由"""
        return f"Aggregated from {len(results)} judges using {self.strategy.value} strategy"
```

#### Task 2.4: DeepEval 集成

**Files:**
- Modify: `requirements.txt` (添加 deepeval)

- [ ] **Step 1: Add to `requirements.txt`**

```text
# 评测系统
deepeval>=0.20.0
mlflow>=2.10.0
```

- [ ] **Step 2: Create `evaluation/judges/deepeval_wrapper.py`**

```python
"""DeepEval 集成

DeepEval 提供 pytest 风格的 LLM 评估框架，支持 G-Eval / DAG / QAG。
集成 DeepEval 补充自定义 Judge。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DeepEvalWrapper:
    """DeepEval 包装器
    
    集成 DeepEval 的 G-Eval / DAG / QAG 评估方法。
    """
    
    def __init__(self, model: str = "gpt-4o"):
        self.model = model
        self._deepeval_metrics = None
        self._load_deepeval()
    
    def _load_deepeval(self):
        """延迟加载 DeepEval（避免硬依赖）"""
        try:
            from deepeval.metrics import GEval
            from deepeval.test_case import LLMTestCase, LLMTestCaseParams
            self._deepeval_metrics = {
                'GEval': GEval,
                'LLMTestCase': LLMTestCase,
                'LLMTestCaseParams': LLMTestCaseParams,
            }
            logger.info("DeepEval loaded successfully")
        except ImportError:
            logger.warning(
                "DeepEval not installed. "
                "Install with: pip install deepeval"
            )
            self._deepeval_metrics = None
    
    async def g_eval(
        self,
        input_text: str,
        actual_output: str,
        expected_output: str,
        criteria: str,
    ) -> Optional[float]:
        """使用 G-Eval 评估
        
        Args:
            input_text: 输入
            actual_output: 实际输出
            expected_output: 期望输出
            criteria: 评估标准（如 "正确性和完整性"）
            
        Returns:
            评分（0-1），如果 DeepEval 不可用则返回 None
        """
        if not self._deepeval_metrics:
            return None
        
        GEval = self._deepeval_metrics['GEval']
        LLMTestCase = self._deepeval_metrics['LLMTestCase']
        LLMTestCaseParams = self._deepeval_metrics['LLMTestCaseParams']
        
        test_case = LLMTestCase(
            input=input_text,
            actual_output=actual_output,
            expected_output=expected_output,
        )
        metric = GEval(
            name="custom_metric",
            criteria=criteria,
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            model=self.model,
        )
        metric.measure(test_case)
        return metric.score
```

#### Task 2.5: Judge 校准器

**Files:**
- Create: `evaluation/judges/calibration.py`

- [ ] **Step 1: Create `evaluation/judges/calibration.py`**

```python
"""Judge 校准器

参考 BabelJudge 的"Gold-labelling by degradation"方法：
1. 准备参考答案（人工标注）
2. 构造扰动样本（删除、错误、冗余）
3. 测试 Judge 一致性
4. 持续校准
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class JudgeCalibrator:
    """Judge 校准器
    
    通过扰动样本验证 Judge 的评分可靠性。
    """
    
    def __init__(self, judge, human_eval_threshold: float = 0.8):
        """
        Args:
            judge: 待校准的 Judge
            human_eval_threshold: Judge 与人工评分的一致性阈值
        """
        self.judge = judge
        self.human_eval_threshold = human_eval_threshold
    
    def degrade_sample(
        self,
        original_output: str,
        degradation_type: str = "deletion",
    ) -> str:
        """构造扰动样本
        
        Args:
            original_output: 原始输出
            degradation_type: 扰动类型
                - deletion: 删除关键内容
                - corruption: 加入错误信息
                - redundancy: 添加冗余内容
                - irrelevance: 添加无关内容
        """
        if degradation_type == "deletion":
            # 删除后半部分
            midpoint = len(original_output) // 2
            return original_output[:midpoint]
        elif degradation_type == "corruption":
            return f"{original_output}（注意：以上信息有误）"
        elif degradation_type == "redundancy":
            return f"{original_output}\n\n重复内容：{original_output[:100]}"
        elif degradation_type == "irrelevance":
            return f"{original_output}\n\n无关内容：Dota 2 是一款 5v5 团队竞技游戏"
        return original_output
    
    async def calibrate(
        self,
        gold_samples: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """校准 Judge
        
        Args:
            gold_samples: 金标准样本，格式：
                [
                    {
                        "input": ...,
                        "expected": ...,
                        "actual": ...,
                        "human_score": 4.5,  # 人工评分
                    },
                    ...
                ]
                
        Returns:
            校准结果：
                {
                    "agreement_rate": 0.85,  # Judge 与人工评分一致性
                    "pass": True,             # 是否通过校准
                    "details": [...],         # 详细对比
                }
        """
        from ..base import EvaluationContext
        
        agreements = []
        details = []
        
        for sample in gold_samples:
            context = EvaluationContext(
                case_id=sample.get('case_id', ''),
                input_data=sample['input'],
                expected_output=sample['expected'],
                actual_output=sample['actual'],
            )
            
            result = await self.judge.run(context)
            judge_score = result.total_score
            human_score = sample['human_score']
            
            # 一致性：差异 ≤ 0.5 视为一致
            agreement = abs(judge_score - human_score) <= 0.5
            agreements.append(1.0 if agreement else 0.0)
            
            details.append({
                'case_id': context.case_id,
                'judge_score': judge_score,
                'human_score': human_score,
                'diff': abs(judge_score - human_score),
                'agreement': agreement,
            })
        
        agreement_rate = sum(agreements) / len(agreements) if agreements else 0.0
        return {
            'agreement_rate': agreement_rate,
            'pass': agreement_rate >= self.human_eval_threshold,
            'details': details,
        }
    
    async def calibrate_with_degradation(
        self,
        reference_samples: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """通过扰动样本校准 Judge
        
        期望：扰动样本应被 Judge 识别为低分
        """
        agreements = []
        for sample in reference_samples:
            original = sample['actual_output']
            degraded = self.degrade_sample(original, sample.get('degradation_type', 'deletion'))
            
            from ..base import EvaluationContext
            
            ctx_original = EvaluationContext(
                case_id=sample['case_id'],
                input_data=sample['input'],
                expected_output=sample['expected'],
                actual_output=original,
            )
            ctx_degraded = EvaluationContext(
                case_id=sample['case_id'] + '_degraded',
                input_data=sample['input'],
                expected_output=sample['expected'],
                actual_output=degraded,
            )
            
            r_original = await self.judge.run(ctx_original)
            r_degraded = await self.judge.run(ctx_degraded)
            
            # 期望：扰动样本分数应低于原始样本
            agreement = r_degraded.total_score < r_original.total_score
            agreements.append(1.0 if agreement else 0.0)
        
        agreement_rate = sum(agreements) / len(agreements) if agreements else 0.0
        return {
            'degradation_agreement_rate': agreement_rate,
            'pass': agreement_rate >= self.human_eval_threshold,
        }
```

### 阶段 2 验收

- [ ] `BaseJudge` / `MultiDimensionalJudge` / `MultiModelVoter` 创建完成
- [ ] DeepEval 集成完成
- [ ] Judge 校准器实现完成
- [ ] 单元测试通过（`tests/evaluation/test_judges.py`）

---

### 阶段 3：Trajectory 评估（第 3-4 周）

#### Task 3.1: 轨迹评估器

**Files:**
- Create: `evaluation/trajectory/__init__.py`
- Create: `evaluation/trajectory/tool_selection.py`
- Create: `evaluation/trajectory/argument_correctness.py`
- Create: `evaluation/trajectory/dependency_order.py`
- Create: `evaluation/trajectory/error_propagation.py`
- Create: `evaluation/trajectory/rejection_recovery.py`
- Create: `evaluation/trajectory/trajectory_evaluator.py`

- [ ] **Step 1: Create `evaluation/trajectory/__init__.py`**

```python
"""轨迹评估子包

实现 SubAgent 多步推理的轨迹评估，参考 TRAJECT-Bench + AgentProp-Bench。
"""

from .trajectory_evaluator import TrajectoryEvaluator
from .tool_selection import ToolSelectionMetric
from .argument_correctness import ArgumentCorrectnessMetric
from .dependency_order import DependencyOrderMetric
from .error_propagation import ErrorPropagationMetric
from .rejection_recovery import RejectionRecoveryMetric

__all__ = [
    'TrajectoryEvaluator',
    'ToolSelectionMetric',
    'ArgumentCorrectnessMetric',
    'DependencyOrderMetric',
    'ErrorPropagationMetric',
    'RejectionRecoveryMetric',
]
```

- [ ] **Step 2: Create `evaluation/trajectory/tool_selection.py`**

```python
"""工具选择准确率

参考 TRAJECT-Bench：评估每一步的工具选择是否合适。
"""

from typing import Any, Dict, List
from dataclasses import dataclass


@dataclass
class TrajectoryStep:
    """轨迹单步"""
    step_id: int
    tool_name: str
    arguments: Dict[str, Any]
    result: Any = None
    expected_tool: Optional[str] = None
    expected_arguments: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ToolSelectionMetric:
    """工具选择准确率"""
    
    def compute(
        self,
        trajectory: List[TrajectoryStep],
    ) -> Dict[str, float]:
        """计算工具选择准确率
        
        Returns:
            {
                "accuracy": 0.85,
                "total": 10,
                "correct": 8,
                "details": [...]
            }
        """
        if not trajectory:
            return {'accuracy': 0.0, 'total': 0, 'correct': 0}
        
        correct = 0
        total = 0
        details = []
        
        for step in trajectory:
            if step.expected_tool is None:
                continue
            total += 1
            is_correct = step.tool_name == step.expected_tool
            if is_correct:
                correct += 1
            details.append({
                'step_id': step.step_id,
                'expected': step.expected_tool,
                'actual': step.tool_name,
                'correct': is_correct,
            })
        
        return {
            'accuracy': correct / total if total > 0 else 0.0,
            'total': total,
            'correct': correct,
            'details': details,
        }
```

- [ ] **Step 3: Create `evaluation/trajectory/argument_correctness.py`**

```python
"""参数正确率

参考 TRAJECT-Bench：评估工具调用参数是否正确。
"""

from typing import Any, Dict
from .tool_selection import TrajectoryStep


class ArgumentCorrectnessMetric:
    """参数正确率"""
    
    def compute(
        self,
        trajectory: list[TrajectoryStep],
    ) -> Dict[str, float]:
        """计算参数正确率"""
        if not trajectory:
            return {'correctness': 0.0, 'total': 0, 'correct': 0}
        
        correct = 0
        total = 0
        details = []
        
        for step in trajectory:
            if step.expected_arguments is None:
                continue
            total += 1
            is_correct = self._compare_arguments(
                step.arguments, step.expected_arguments
            )
            if is_correct:
                correct += 1
            details.append({
                'step_id': step.step_id,
                'expected': step.expected_arguments,
                'actual': step.arguments,
                'correct': is_correct,
            })
        
        return {
            'correctness': correct / total if total > 0 else 0.0,
            'total': total,
            'correct': correct,
            'details': details,
        }
    
    def _compare_arguments(
        self,
        actual: Dict[str, Any],
        expected: Dict[str, Any],
    ) -> bool:
        """比较参数（允许类型容差）"""
        if set(actual.keys()) != set(expected.keys()):
            return False
        for k, v in expected.items():
            if str(actual.get(k)) != str(v):
                return False
        return True
```

- [ ] **Step 4: Create `evaluation/trajectory/dependency_order.py`**

```python
"""依赖/顺序满足度

参考 TRAJECT-Bench：评估工具调用顺序是否符合依赖关系。
"""

from typing import Dict, List, Set
from .tool_selection import TrajectoryStep


class DependencyOrderMetric:
    """依赖/顺序满足度"""
    
    def compute(
        self,
        trajectory: List[TrajectoryStep],
        dependencies: Dict[str, List[str]] = None,
    ) -> Dict[str, float]:
        """计算依赖满足度
        
        Args:
            trajectory: 执行轨迹
            dependencies: 工具依赖关系，格式：
                {
                    "tool_b": ["tool_a"],  # tool_b 依赖 tool_a
                    ...
                }
        """
        if not trajectory or not dependencies:
            return {'satisfaction': 1.0, 'total': 0, 'satisfied': 0}
        
        # 记录已调用的工具
        called: Set[str] = set()
        satisfied = 0
        total = 0
        details = []
        
        for step in trajectory:
            tool = step.tool_name
            deps = dependencies.get(tool, [])
            
            if not deps:
                called.add(tool)
                continue
            
            total += 1
            all_deps_called = all(dep in called for dep in deps)
            if all_deps_called:
                satisfied += 1
            details.append({
                'step_id': step.step_id,
                'tool': tool,
                'dependencies': deps,
                'satisfied': all_deps_called,
            })
            called.add(tool)
        
        return {
            'satisfaction': satisfied / total if total > 0 else 1.0,
            'total': total,
            'satisfied': satisfied,
            'details': details,
        }
```

- [ ] **Step 5: Create `evaluation/trajectory/error_propagation.py`**

```python
"""错误传播率

参考 AgentProp-Bench：评估错误是否在后续步骤中被传播。
"""

from typing import List
from .tool_selection import TrajectoryStep


class ErrorPropagationMetric:
    """错误传播率"""
    
    def compute(
        self,
        trajectory: List[TrajectoryStep],
    ) -> Dict[str, float]:
        """计算错误传播率"""
        if not trajectory:
            return {'propagation_rate': 0.0, 'error_steps': 0, 'propagated_steps': 0}
        
        error_steps = [s for s in trajectory if s.error]
        error_step_ids = {s.step_id for s in error_steps}
        
        if not error_step_ids:
            return {'propagation_rate': 0.0, 'error_steps': 0, 'propagated_steps': 0}
        
        # 检查错误步骤之后是否有依赖其结果的步骤也出错
        propagated = 0
        for step in trajectory:
            if step.step_id in error_step_ids or step.error:
                continue
            # 启发式：如果错误步骤之后的步骤也出错，视为传播
            earlier_errors = [s for s in error_steps if s.step_id < step.step_id]
            if earlier_errors and step.error:
                propagated += 1
        
        propagation_rate = propagated / len(trajectory)
        return {
            'propagation_rate': propagation_rate,
            'error_steps': len(error_step_ids),
            'propagated_steps': propagated,
        }
```

- [ ] **Step 6: Create `evaluation/trajectory/rejection_recovery.py`**

```python
"""拒绝-恢复分解

参考 AgentProp-Bench：错误检测和错误恢复是相互独立的能力。
"""

from typing import List
from .tool_selection import TrajectoryStep


class RejectionRecoveryMetric:
    """拒绝-恢复分解
    
    - rejection_rate: 应拒绝的错误被主动拒绝的比例
    - recovery_rate: 错误后成功恢复的比例
    """
    
    def compute(
        self,
        trajectory: List[TrajectoryStep],
        error_steps: List[int] = None,
    ) -> Dict[str, float]:
        """计算拒绝率和恢复率"""
        if not trajectory:
            return {'rejection_rate': 0.0, 'recovery_rate': 0.0}
        
        error_step_ids = set(error_steps or [s.step_id for s in trajectory if s.error])
        if not error_step_ids:
            return {'rejection_rate': 0.0, 'recovery_rate': 0.0}
        
        # 拒绝率：错误步骤之后，Agent 主动重新尝试或改变策略
        rejected = 0
        for step_id in error_step_ids:
            # 查找错误步骤之后的步骤
            subsequent = [s for s in trajectory if s.step_id > step_id]
            if any(s.error is None and s.tool_name != trajectory[step_id - 1].tool_name 
                   for s in subsequent[:3]):
                rejected += 1
        
        # 恢复率：错误步骤之后，Agent 成功完成后续步骤
        recovered = 0
        for step_id in error_step_ids:
            subsequent = [s for s in trajectory if s.step_id > step_id]
            if subsequent and all(s.error is None for s in subsequent):
                recovered += 1
        
        return {
            'rejection_rate': rejected / len(error_step_ids),
            'recovery_rate': recovered / len(error_step_ids),
            'total_errors': len(error_step_ids),
        }
```

- [ ] **Step 7: Create `evaluation/trajectory/trajectory_evaluator.py`**

```python
"""Trajectory 评估器

整合所有轨迹指标，对 SubAgent 的完整执行轨迹进行评估。
"""

import logging
from typing import Any, Dict, List, Optional

from ..base import (
    BaseEvaluator,
    EvaluationContext,
    EvaluationResult,
    EvaluationStatus,
)
from .tool_selection import TrajectoryStep, ToolSelectionMetric
from .argument_correctness import ArgumentCorrectnessMetric
from .dependency_order import DependencyOrderMetric
from .error_propagation import ErrorPropagationMetric
from .rejection_recovery import RejectionRecoveryMetric

logger = logging.getLogger(__name__)


class TrajectoryEvaluator(BaseEvaluator):
    """Trajectory 评估器
    
    整合 5 个轨迹指标：
    - tool_selection_accuracy
    - argument_correctness
    - dependency_satisfaction
    - error_propagation_rate
    - rejection_rate / recovery_rate
    """
    
    def __init__(self, **kwargs):
        super().__init__(
            name="trajectory_evaluator",
            version="1.0.0",
            description="SubAgent 轨迹评估器",
            **kwargs,
        )
        self.tool_selection = ToolSelectionMetric()
        self.argument_correctness = ArgumentCorrectnessMetric()
        self.dependency_order = DependencyOrderMetric()
        self.error_propagation = ErrorPropagationMetric()
        self.rejection_recovery = RejectionRecoveryMetric()
    
    async def evaluate(self, context: EvaluationContext) -> EvaluationResult:
        """执行轨迹评估"""
        trajectory_data = context.metadata.get('trajectory', [])
        if not trajectory_data:
            return EvaluationResult(
                case_id=context.case_id,
                evaluator_name=self.name,
                status=EvaluationStatus.SKIPPED,
                error="No trajectory in metadata",
            )
        
        # 转换为 TrajectoryStep
        steps = [
            TrajectoryStep(
                step_id=i,
                tool_name=step.get('tool_name', ''),
                arguments=step.get('arguments', {}),
                result=step.get('result'),
                expected_tool=step.get('expected_tool'),
                expected_arguments=step.get('expected_arguments'),
                error=step.get('error'),
            )
            for i, step in enumerate(trajectory_data)
        ]
        
        # 计算所有指标
        tool_sel = self.tool_selection.compute(steps)
        arg_correct = self.argument_correctness.compute(steps)
        dep_order = self.dependency_order.compute(
            steps, context.metadata.get('dependencies', {})
        )
        err_prop = self.error_propagation.compute(steps)
        rej_rec = self.rejection_recovery.compute(steps)
        
        # 转换为 0-1 评分
        return EvaluationResult(
            case_id=context.case_id,
            evaluator_name=self.name,
            status=EvaluationStatus.COMPLETED,
            total_score=self._calculate_overall({
                'tool_selection_accuracy': tool_sel['accuracy'],
                'argument_correctness': arg_correct['correctness'],
                'dependency_satisfaction': dep_order['satisfaction'],
                'clue_adherence': 1.0 - err_prop['propagation_rate'],
            }),
            metadata={
                'tool_selection': tool_sel,
                'argument_correctness': arg_correct,
                'dependency_order': dep_order,
                'error_propagation': err_prop,
                'rejection_recovery': rej_rec,
                'n_steps': len(steps),
            },
        )
    
    def _calculate_overall(self, metrics: Dict[str, float]) -> float:
        """计算总体评分（0-1 映射到 0-5）"""
        avg = sum(metrics.values()) / len(metrics) if metrics else 0.0
        return round(avg * 5, 2)
```

### 阶段 3 验收

- [ ] 5 个轨迹指标实现完成
- [ ] `TrajectoryEvaluator` 整合完成
- [ ] 单元测试通过（`tests/evaluation/test_trajectory.py`）

---

### 阶段 4：回归测试 + A/B 测试（第 4-5 周）

#### Task 4.1: 回归测试

**Files:**
- Create: `evaluation/regression/__init__.py`
- Create: `evaluation/regression/baseline.py`
- Create: `evaluation/regression/ab_test.py`
- Create: `evaluation/regression/report.py`

- [ ] **Step 1: Create `evaluation/regression/__init__.py`**

```python
"""回归测试子包"""

from .baseline import BaselineComparator
from .ab_test import ABTestRunner
from .report import ReportGenerator

__all__ = [
    'BaselineComparator',
    'ABTestRunner',
    'ReportGenerator',
]
```

- [ ] **Step 2: Create `evaluation/regression/baseline.py`**

```python
"""基线对比

将当前评估结果与基线对比，检测性能回归。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaselineComparator:
    """基线对比器"""
    
    def __init__(self, baseline_path: str = "data/evaluation/baselines/"):
        self.baseline_path = Path(baseline_path)
        self.baseline_path.mkdir(parents=True, exist_ok=True)
    
    def save_baseline(
        self,
        results: List[Dict[str, Any]],
        name: str,
    ) -> str:
        """保存基线"""
        baseline_file = self.baseline_path / f"{name}.json"
        baseline = {
            'name': name,
            'created_at': datetime.utcnow().isoformat(),
            'n_cases': len(results),
            'avg_total_score': sum(r.get('total_score', 0) for r in results) / len(results) if results else 0,
            'results': results,
        }
        with open(baseline_file, 'w', encoding='utf-8') as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        logger.info(f"Baseline saved: {baseline_file}")
        return str(baseline_file)
    
    def load_baseline(self, name: str) -> Optional[Dict]:
        """加载基线"""
        baseline_file = self.baseline_path / f"{name}.json"
        if not baseline_file.exists():
            return None
        with open(baseline_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def compare(
        self,
        current_results: List[Dict[str, Any]],
        baseline_name: str,
        threshold: float = 0.3,
    ) -> Dict[str, Any]:
        """对比当前结果与基线
        
        Args:
            current_results: 当前评估结果
            baseline_name: 基线名称
            threshold: 退化阈值（平均分下降超过此值视为退化）
            
        Returns:
            对比结果
        """
        baseline = self.load_baseline(baseline_name)
        if not baseline:
            return {
                'regression': False,
                'reason': f"Baseline '{baseline_name}' not found",
            }
        
        current_avg = sum(r.get('total_score', 0) for r in current_results) / len(current_results) if current_results else 0
        baseline_avg = baseline['avg_total_score']
        
        diff = current_avg - baseline_avg
        is_regression = diff < -threshold
        
        return {
            'regression': is_regression,
            'current_avg': current_avg,
            'baseline_avg': baseline_avg,
            'diff': diff,
            'threshold': threshold,
            'n_current': len(current_results),
            'n_baseline': baseline['n_cases'],
        }
```

- [ ] **Step 3: Create `evaluation/regression/ab_test.py`**

```python
"""A/B 测试

对两个版本进行统计显著性检验。
"""

import logging
import math
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ABTestRunner:
    """A/B 测试运行器
    
    使用 Welch's t-test 检验两个版本的评分是否存在显著差异。
    """
    
    def __init__(self, significance_level: float = 0.05):
        self.significance_level = significance_level
    
    def run(
        self,
        group_a_scores: List[float],
        group_b_scores: List[float],
    ) -> Dict[str, Any]:
        """执行 A/B 测试
        
        Args:
            group_a_scores: A 组评分
            group_b_scores: B 组评分
            
        Returns:
            {
                'mean_a': 4.2,
                'mean_b': 4.5,
                'diff': 0.3,
                'p_value': 0.03,
                'significant': True,
                'winner': 'B',  # 'A' / 'B' / 'tie'
            }
        """
        if not group_a_scores or not group_b_scores:
            return {'error': 'Empty groups'}
        
        mean_a = sum(group_a_scores) / len(group_a_scores)
        mean_b = sum(group_b_scores) / len(group_b_scores)
        diff = mean_b - mean_a
        
        # Welch's t-test
        t_stat, p_value = self._welch_t_test(group_a_scores, group_b_scores)
        significant = p_value < self.significance_level
        
        if significant:
            winner = 'B' if mean_b > mean_a else 'A'
        else:
            winner = 'tie'
        
        return {
            'mean_a': mean_a,
            'mean_b': mean_b,
            'diff': diff,
            'p_value': p_value,
            't_stat': t_stat,
            'significant': significant,
            'winner': winner,
            'n_a': len(group_a_scores),
            'n_b': len(group_b_scores),
        }
    
    def _welch_t_test(
        self,
        a: List[float],
        b: List[float],
    ) -> tuple:
        """Welch's t-test（不假设等方差）"""
        n_a, n_b = len(a), len(b)
        mean_a, mean_b = sum(a) / n_a, sum(b) / n_b
        var_a = sum((x - mean_a) ** 2 for x in a) / (n_a - 1) if n_a > 1 else 0
        var_b = sum((x - mean_b) ** 2 for x in b) / (n_b - 1) if n_b > 1 else 0
        
        se = math.sqrt(var_a / n_a + var_b / n_b) if (var_a / n_a + var_b / n_b) > 0 else 1e-9
        t_stat = (mean_b - mean_a) / se
        
        # 简化的 p 值估算（实际应使用 scipy）
        p_value = 2 * (1 - min(0.99, abs(t_stat) / 3.0))
        return t_stat, p_value
```

- [ ] **Step 4: Create `evaluation/regression/report.py`**

```python
"""报告生成器

生成多维度的评估报告（Markdown / JSON / HTML）。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class ReportGenerator:
    """报告生成器"""
    
    def generate_markdown(
        self,
        results: List[Dict[str, Any]],
        title: str = "评估报告",
    ) -> str:
        """生成 Markdown 报告"""
        if not results:
            return "# 评估报告\n\n无结果"
        
        avg_score = sum(r.get('total_score', 0) for r in results) / len(results)
        
        lines = [
            f"# {title}",
            "",
            f"**生成时间**: {datetime.utcnow().isoformat()}",
            f"**用例数**: {len(results)}",
            f"**平均分**: {avg_score:.2f} / 5.00",
            "",
            "## 评分分布",
            "",
            "| 分值区间 | 数量 | 占比 |",
            "|---------|------|------|",
        ]
        
        # 分值分布
        buckets = {'0-1': 0, '1-2': 0, '2-3': 0, '3-4': 0, '4-5': 0}
        for r in results:
            score = r.get('total_score', 0)
            if score < 1:
                buckets['0-1'] += 1
            elif score < 2:
                buckets['1-2'] += 1
            elif score < 3:
                buckets['2-3'] += 1
            elif score < 4:
                buckets['3-4'] += 1
            else:
                buckets['4-5'] += 1
        
        for bucket, count in buckets.items():
            pct = count / len(results) * 100
            lines.append(f"| {bucket} | {count} | {pct:.1f}% |")
        
        # 维度平均分
        lines.extend([
            "",
            "## 维度平均分",
            "",
            "| 维度 | 平均分 | 权重 |",
            "|------|--------|------|",
        ])
        
        dim_totals: Dict[str, List[float]] = {}
        for r in results:
            for dim, score in r.get('dimension_scores', {}).items():
                dim_totals.setdefault(dim, []).append(score)
        
        weights = {
            'correctness': '25%', 'completeness': '15%', 'relevance': '15%',
            'tool_selection': '15%', 'efficiency': '10%', 'robustness': '10%',
            'personalization': '10%',
        }
        for dim, scores in sorted(dim_totals.items()):
            avg = sum(scores) / len(scores) if scores else 0
            lines.append(f"| {dim} | {avg:.2f} | {weights.get(dim, '-')} |")
        
        # 失败用例
        failed = [r for r in results if r.get('status') == 'failed' or r.get('total_score', 0) < 3.0]
        if failed:
            lines.extend([
                "",
                f"## 低分用例 (< 3.0): {len(failed)} 条",
                "",
                "| Case ID | 评分 | 状态 |",
                "|---------|------|------|",
            ])
            for r in failed[:20]:  # 最多显示 20 条
                lines.append(
                    f"| {r.get('case_id', '')} | {r.get('total_score', 0):.2f} | "
                    f"{r.get('status', '')} |"
                )
        
        return "\n".join(lines)
    
    def save_report(
        self,
        content: str,
        output_path: str,
    ) -> str:
        """保存报告到文件"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)
        return str(output_file)
```

### 阶段 4 验收

- [ ] `BaselineComparator` / `ABTestRunner` / `ReportGenerator` 创建完成
- [ ] 单元测试通过（`tests/evaluation/test_regression.py`）
- [ ] 能生成 Markdown 报告

---

### 阶段 5：在线监控仪表板 + CI 集成（第 5-6 周）

#### Task 5.1: 在线监控

**Files:**
- Create: `evaluation/monitoring/__init__.py`
- Create: `evaluation/monitoring/dashboard.py`
- Create: `evaluation/monitoring/alert.py`

- [ ] **Step 1: Create `evaluation/monitoring/__init__.py`**

```python
"""在线监控子包"""

from .dashboard import Dashboard
from .alert import AlertRule, AlertManager

__all__ = [
    'Dashboard',
    'AlertRule',
    'AlertManager',
]
```

- [ ] **Step 2: Create `evaluation/monitoring/dashboard.py`**

```python
"""在线监控仪表板

从 Langfuse Trace + 评估结果中聚合数据，生成监控指标。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Dashboard:
    """监控仪表板"""
    
    def __init__(self, langfuse_client=None):
        """
        Args:
            langfuse_client: Langfuse 客户端（用于查询 Trace）
        """
        self.langfuse_client = langfuse_client
    
    def get_metrics(
        self,
        time_range_hours: int = 24,
    ) -> Dict[str, Any]:
        """获取监控指标
        
        Returns:
            {
                'avg_total_score': 4.2,
                'total_evaluations': 1000,
                'fallback_rate': 0.08,
                'p50_latency_ms': 1200,
                'p99_latency_ms': 8500,
                'evaluations_by_module': {...},
                'score_trend': [...],
            }
        """
        if not self.langfuse_client:
            logger.warning("No langfuse_client provided, returning empty metrics")
            return {}
        
        # 实际实现：从 Langfuse 查询 Trace + Score
        return {
            'avg_total_score': 4.2,
            'total_evaluations': 0,
            'fallback_rate': 0.0,
            'p50_latency_ms': 0,
            'p99_latency_ms': 0,
            'evaluations_by_module': {},
            'score_trend': [],
        }
    
    def get_alerts(
        self,
        time_range_hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """获取告警"""
        return []
```

- [ ] **Step 3: Create `evaluation/monitoring/alert.py`**

```python
"""告警规则与管理

基于监控指标触发告警（评分下降、降级率过高等）。
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """告警严重程度"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    metric: str  # e.g., "avg_total_score", "fallback_rate"
    comparator: str  # "lt" / "gt" / "eq"
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    description: str = ""
    enabled: bool = True


class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self.rules: List[AlertRule] = []
        self.triggered: List[Dict[str, Any]] = []
    
    def add_rule(self, rule: AlertRule) -> None:
        """添加告警规则"""
        self.rules.append(rule)
    
    def load_default_rules(self) -> None:
        """加载默认告警规则"""
        self.add_rule(AlertRule(
            name="score_drop",
            metric="avg_total_score",
            comparator="lt",
            threshold=3.5,
            severity=AlertSeverity.CRITICAL,
            description="平均分低于 3.5",
        ))
        self.add_rule(AlertRule(
            name="fallback_rate_high",
            metric="fallback_rate",
            comparator="gt",
            threshold=0.15,
            severity=AlertSeverity.WARNING,
            description="降级率超过 15%",
        ))
        self.add_rule(AlertRule(
            name="p99_latency_high",
            metric="p99_latency_ms",
            comparator="gt",
            threshold=15000,
            severity=AlertSeverity.WARNING,
            description="P99 延迟超过 15s",
        ))
    
    def check(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检查指标并触发告警"""
        triggered = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            value = metrics.get(rule.metric)
            if value is None:
                continue
            
            is_triggered = False
            if rule.comparator == "lt":
                is_triggered = value < rule.threshold
            elif rule.comparator == "gt":
                is_triggered = value > rule.threshold
            elif rule.comparator == "eq":
                is_triggered = value == rule.threshold
            
            if is_triggered:
                alert = {
                    'rule': rule.name,
                    'severity': rule.severity.value,
                    'metric': rule.metric,
                    'value': value,
                    'threshold': rule.threshold,
                    'description': rule.description,
                }
                triggered.append(alert)
                logger.warning(f"Alert triggered: {alert}")
        
        self.triggered.extend(triggered)
        return triggered
```

#### Task 5.2: CI 集成

**Files:**
- Create: `.github/workflows/evaluation.yml`

- [ ] **Step 1: Create `.github/workflows/evaluation.yml`**

```yaml
name: Evaluation

on:
  pull_request:
    branches: [ main, develop ]
  push:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      
      - name: Run evaluation unit tests
        run: |
          pytest tests/evaluation/ -v --tb=short
      
      - name: Run DotaBench (skill_bench)
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          python scripts/evaluation/run_diy_bench.py --bench-type skill_bench --difficulty easy,medium
      
      - name: Generate report
        if: always()
        run: |
          python scripts/evaluation/generate_report.py \
            --input data/evaluation/results/latest.jsonl \
            --output data/evaluation/reports/pr-${{ github.event.pull_request.number }}.md
      
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: evaluation-report
          path: data/evaluation/reports/
      
      - name: Compare with baseline
        if: github.event_name == 'pull_request'
        run: |
          python scripts/evaluation/run_regression.py \
            --baseline main \
            --current data/evaluation/results/latest.jsonl \
            --threshold 0.3
```

#### Task 5.3: 运行脚本

**Files:**
- Create: `scripts/evaluation/run_diy_bench.py`
- Create: `scripts/evaluation/run_judge.py`
- Create: `scripts/evaluation/run_trajectory_eval.py`
- Create: `scripts/evaluation/run_regression.py`
- Create: `scripts/evaluation/calibrate_judge.py`
- Create: `scripts/evaluation/generate_report.py`

- [ ] **Step 1: Create `scripts/evaluation/run_diy_bench.py`**

```python
"""运行 DotaBench 评测集

执行所有 Skill/SubAgent 模块的评测用例，使用 LLM-as-a-Judge 评分。
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from DotaBench.utils.case_loader import CaseLoader
from evaluation.judges import MultiDimensionalJudge
from evaluation.base import EvaluationContext, EvaluationStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_module(
    module: str,
    bench_type: str,
    judge: MultiDimensionalJudge,
    loader: CaseLoader,
    difficulty: str = None,
) -> list:
    """运行单个模块的评测"""
    cases = loader.load_cases(module, bench_type, difficulty)
    expected_map = loader.load_expected(module, bench_type)
    
    logger.info(f"Running {bench_type}/{module}: {len(cases)} cases")
    
    results = []
    for case in cases:
        # 模拟实际执行（实际应调用 Skill/SubAgent）
        # 真实场景：actual_output = await skill.run(case['input'])
        actual_output = f"[模拟输出] case_id={case['case_id']}"
        
        context = EvaluationContext(
            case_id=case['case_id'],
            input_data=case['input'],
            expected_output=expected_map.get(case['case_id']),
            actual_output=actual_output,
            metadata={'difficulty': case.get('difficulty'), 'tags': case.get('tags', [])},
        )
        
        result = await judge.run(context)
        results.append(result)
        logger.info(
            f"  {case['case_id']}: score={result.total_score:.2f}, "
            f"status={result.status.value}"
        )
    
    return results


async def main():
    parser = argparse.ArgumentParser(description="Run DotaBench")
    parser.add_argument('--bench-type', default='skill_bench', help='skill_bench / subagent_bench / e2e_bench')
    parser.add_argument('--module', help='指定模块（不指定则运行所有）')
    parser.add_argument('--difficulty', help='难度过滤（easy/medium/hard）')
    parser.add_argument('--output', default='data/evaluation/results/latest.jsonl')
    args = parser.parse_args()
    
    loader = CaseLoader()
    judge = MultiDimensionalJudge(llm_client=None)  # 实际应传入 LLM 客户端
    
    if args.module:
        modules = [args.module]
    else:
        # 列出所有模块
        bench_path = Path('DotaBench') / args.bench_type
        modules = [d.name for d in bench_path.iterdir() if d.is_dir()] if bench_path.exists() else []
    
    all_results = []
    for module in modules:
        results = await run_module(
            module, args.bench_type, judge, loader, args.difficulty
        )
        all_results.extend(results)
    
    # 保存结果
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for r in all_results:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + '\n')
    
    # 统计
    completed = [r for r in all_results if r.status == EvaluationStatus.COMPLETED]
    avg = sum(r.total_score for r in completed) / len(completed) if completed else 0
    logger.info(f"\n=== 总计 ===")
    logger.info(f"用例数: {len(all_results)}")
    logger.info(f"成功: {len(completed)}")
    logger.info(f"平均分: {avg:.2f} / 5.00")
    logger.info(f"结果已保存: {output_path}")


if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 2: Create `scripts/evaluation/run_judge.py`**

```python
"""运行 Judge 评估

针对单个用例执行 LLM-as-a-Judge 评估。
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.base import EvaluationContext
from evaluation.judges import MultiDimensionalJudge, MultiModelVoter, VotingStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Run Judge evaluation")
    parser.add_argument('--input', required=True, help='输入 JSON')
    parser.add_argument('--expected', help='期望输出 JSON')
    parser.add_argument('--actual', required=True, help='实际输出文本')
    parser.add_argument('--multi-model', action='store_true', help='使用多模型投票')
    args = parser.parse_args()
    
    with open(args.input, 'r', encoding='utf-8') as f:
        input_data = json.load(f) if args.input.endswith('.json') else {'text': args.input}
    
    expected = None
    if args.expected:
        with open(args.expected, 'r', encoding='utf-8') as f:
            expected = json.load(f)
    
    context = EvaluationContext(
        case_id='cli_run',
        input_data=input_data,
        expected_output=expected,
        actual_output=args.actual,
    )
    
    if args.multi_model:
        # 多模型投票
        judges = [
            MultiDimensionalJudge(llm_client=None, name_suffix='_gpt4o'),
            MultiDimensionalJudge(llm_client=None, name_suffix='_claude'),
            MultiDimensionalJudge(llm_client=None, name_suffix='_gemini'),
        ]
        voter = MultiModelVoter(judges, strategy=VotingStrategy.AVERAGE)
        result = await voter.evaluate(context)
    else:
        judge = MultiDimensionalJudge(llm_client=None)
        result = await judge.run(context)
    
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 3: Create `scripts/evaluation/run_trajectory_eval.py`**

```python
"""运行轨迹评估

对 SubAgent 的执行轨迹进行评估。
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.base import EvaluationContext
from evaluation.trajectory import TrajectoryEvaluator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Run trajectory evaluation")
    parser.add_argument('--trajectory', required=True, help='轨迹 JSON 文件')
    parser.add_argument('--dependencies', help='依赖关系 JSON 文件')
    args = parser.parse_args()
    
    with open(args.trajectory, 'r', encoding='utf-8') as f:
        trajectory = json.load(f)
    
    dependencies = {}
    if args.dependencies:
        with open(args.dependencies, 'r', encoding='utf-8') as f:
            dependencies = json.load(f)
    
    context = EvaluationContext(
        case_id='trajectory_run',
        input_data={},
        actual_output=None,
        metadata={'trajectory': trajectory, 'dependencies': dependencies},
    )
    
    evaluator = TrajectoryEvaluator()
    result = await evaluator.run(context)
    
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 4: Create `scripts/evaluation/run_regression.py`**

```python
"""运行回归测试

对比当前结果与基线，检测性能回归。
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.regression import BaselineComparator, ABTestRunner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run regression test")
    parser.add_argument('--current', required=True, help='当前结果 JSONL')
    parser.add_argument('--baseline', required=True, help='基线名称')
    parser.add_argument('--threshold', type=float, default=0.3, help='退化阈值')
    parser.add_argument('--save-baseline', action='store_true', help='保存为基线')
    args = parser.parse_args()
    
    # 加载当前结果
    current_results = []
    with open(args.current, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                current_results.append(json.loads(line))
    
    comparator = BaselineComparator()
    
    if args.save_baseline:
        path = comparator.save_baseline(current_results, args.baseline)
        logger.info(f"Baseline saved: {path}")
        return
    
    comparison = comparator.compare(current_results, args.baseline, args.threshold)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    
    if comparison.get('regression'):
        logger.error("REGRESSION DETECTED!")
        sys.exit(1)
    else:
        logger.info("No regression detected.")


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Create `scripts/evaluation/calibrate_judge.py`**

```python
"""Judge 校准

使用金标准样本和扰动样本验证 Judge 评分可靠性。
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.judges import MultiDimensionalJudge
from evaluation.judges.calibration import JudgeCalibrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Calibrate Judge")
    parser.add_argument('--gold-samples', required=True, help='金标准样本 JSON')
    parser.add_argument('--method', default='gold', choices=['gold', 'degradation'])
    args = parser.parse_args()
    
    with open(args.gold_samples, 'r', encoding='utf-8') as f:
        samples = json.load(f)
    
    judge = MultiDimensionalJudge(llm_client=None)
    calibrator = JudgeCalibrator(judge)
    
    if args.method == 'gold':
        result = await calibrator.calibrate(samples)
    else:
        result = await calibrator.calibrate_with_degradation(samples)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    if not result.get('pass'):
        logger.error("Calibration FAILED")
        sys.exit(1)
    else:
        logger.info("Calibration PASSED")


if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 6: Create `scripts/evaluation/generate_report.py`**

```python
"""生成评估报告

将评估结果生成 Markdown 报告。
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.regression import ReportGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Generate evaluation report")
    parser.add_argument('--input', required=True, help='输入 JSONL 结果')
    parser.add_argument('--output', required=True, help='输出 Markdown 文件')
    parser.add_argument('--title', default='评估报告')
    args = parser.parse_args()
    
    results = []
    with open(args.input, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    
    generator = ReportGenerator()
    markdown = generator.generate_markdown(results, args.title)
    output_path = generator.save_report(markdown, args.output)
    logger.info(f"Report saved: {output_path}")


if __name__ == '__main__':
    main()
```

### 阶段 5 验收

- [ ] `Dashboard` / `AlertManager` 创建完成
- [ ] CI 工作流配置完成（`.github/workflows/evaluation.yml`）
- [ ] 6 个运行脚本创建完成
- [ ] 单元测试通过（`tests/evaluation/test_dashboard.py`）

---

### 阶段 6：持续优化 + Judge 校准（第 6 周+）

#### Task 6.1: 持续校准机制

- [ ] **Step 1: 每月校准 Judge**
  - 收集当月人工评估样本
  - 运行 `scripts/evaluation/calibrate_judge.py`
  - 记录校准结果到 `data/evaluation/calibration_history.jsonl`

- [ ] **Step 2: 扩充 DotaBench 评测集**
  - 每月新增 10-20 条用例
  - 覆盖新场景 + 边缘情况
  - 更新版本映射（`DotaBench/version_mapping.yaml`）

- [ ] **Step 3: A/B 测试新方案**
  - 新功能/优化上线前必须经过 A/B 测试
  - 使用 `evaluation.regression.ABTestRunner`
  - 显著性检验通过后才上线

---

## 分阶段实施计划

| 阶段 | 时间 | 任务 | 验收标准 | 状态 |
|------|------|------|---------|------|
| **阶段 1** | 第 1-2 周 | 基础设施 + DotaBench 评测集 | ≥5 个模块的 `cases.jsonl` + `expected.jsonl` 创建完成 | ⏳ 未开始 |
| **阶段 2** | 第 2-3 周 | LLM-as-a-Judge + DeepEval + 校准 | Judge 单元测试通过，与人工评分一致性 ≥ 80% | ⏳ 未开始 |
| **阶段 3** | 第 3-4 周 | Trajectory 评估（5 指标） | 5 个指标单元测试通过，轨迹评分与专家分析一致 | ⏳ 未开始 |
| **阶段 4** | 第 4-5 周 | 回归测试 + A/B 测试 | 自动化回归报告生成 | ⏳ 未开始 |
| **阶段 5** | 第 5-6 周 | CI 集成 + 监控仪表板 | PR 触发评估，监控上线 | ⏳ 未开始 |
| **阶段 6** | 第 6 周+ | 持续优化 + Judge 校准 | 每月校准 Judge，扩充评测集 | ⏳ 未开始 |

---

## 关键决策与注意事项

### 设计决策

1. **三层分离**：L1 离线（开发）/ L2 在线（生产）/ L3 回归（发布），避免单一方法失效
2. **7 维评分**：参考 GAIA 量表（正确性 25% / 完整性 15% / 相关性 15% / 工具选择 15% / 效率 10% / 鲁棒性 10% / 个性化 10%）
3. **多模型投票**：使用 GPT-4o / Claude / Gemini 多模型投票，降低单模型偏见
4. **降级集成**：与 Langfuse Trace 集成，复用已有基础设施（无需重建可观测性）
5. **延迟加载**：DeepEval / MLflow 等可选依赖未安装时静默降级，不影响核心功能

### 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM Judge 偏见（位置/长度/自我偏好） | 多模型投票 + 盲评 + temperature=0 + 多次采样 |
| 评测集偏差 | 持续扩充用例，覆盖边缘情况 |
| 评估成本高 | 关键场景用 GPT-4o，大规模用 LLaMA 3 70B，月预算 < $100 |
| 评估延迟 | 异步执行 + CI 缓存结果 |
| 主观维度难量化 | 多评估员平均，明确评分标准 |
| 游戏版本变化 | 评测集随版本更新，建立版本映射 |
| Judge 评分不稳定 | 3 次采样取平均 + BabelJudge 校准 |

### 关键设计原则

1. **方法匹配场景**：
   - 规则匹配：单元测试（精确、可重复）
   - LLM Judge：功能测试（开放性答案）
   - 混合方法：轨迹测试（同时评估过程和结果）
2. **可靠性优先**：
   - temperature=0（降低采样噪声）
   - 多次采样（≥3 次取平均）
   - 多模型投票（避免单点偏差）
   - 持续校准（BabelJudge 方法）
3. **成本可控**：
   - 模型分层（GPT-4o / GPT-4o-mini / LLaMA 3 70B）
   - 月预算上限 $100
   - 关键场景 vs 批量场景区分

### 回退方案

- 保留现有 Langfuse Trace 系统作为基础
- 评测系统作为可选层（不启用时不影响主流程）
- 评估失败时降级为基础规则评分

---

## 验收标准

1. **评测集覆盖度**：DotaBench 至少 200 条用例，覆盖所有 Skill/SubAgent
2. **Judge 可靠性**：Judge 评分与人工评分一致性 ≥ 80%
3. **自动化程度**：CI 集成回归测试，每次 PR 触发
4. **可视化**：评估仪表板支持多维筛选、趋势分析
5. **响应时间**：单次评估 < 30s（LLM Judge）
6. **成本控制**：月度评估成本 < $100

### 详细验收指标

| 指标 | 目标值 | 测量方法 |
|------|-------|---------|
| 评测集用例数 | ≥ 200 | `find DotaBench -name cases.jsonl \| xargs wc -l` |
| Skill 覆盖度 | 100% | 5 个 Skill 全部有 cases.jsonl |
| SubAgent 覆盖度 | 100% | 6 个 SubAgent 全部有 cases.jsonl |
| Judge 与人工一致性 | ≥ 80% | `calibrate_judge.py --method gold` |
| CI 触发率 | 100% | 每次 PR 自动触发评估 |
| 单次评估延迟 P99 | < 30s | CI 日志统计 |
| 月度评估成本 | < $100 | OpenAI API 用量统计 |
| 平均评分波动 | < 0.2 | 同一用例 10 次评估的标准差 |

---

## 与现有系统集成

DotaHelperAgent 已有 Langfuse Trace 系统，可直接复用：

| 现有系统 | 复用方式 |
|---------|---------|
| Langfuse Trace | 评估结果记录到 Trace，新增 |
| Langfuse Score | 用户反馈关联 Trace，已有 |
| Langfuse Token 统计 | 评估成本统计，已有 |
| `web/app.py` | 评测结果上报 API，新增 |
| `utils/llm_client.py` | Judge 调用入口，已有 |
| `core/agent_controller.py` | Trace 关联评估，新增 |
| `feedback/` | 显式/隐式反馈作为评估信号，已有 |

---

## 参考资料

- [ARCHITECTURE_ANALYSIS.md 第十八章](../ARCHITECTURE_ANALYSIS.md#十八skill-subagent-评估体系) - 评测体系设计
- [TRAJECT-Bench (ICLR 2026)](https://openreview.net/pdf?id=TZWnWvsQ0X) - 轨迹感知评测
- [AgentProp-Bench](https://arxiv.org/html/2604.16706v1) - 错误传播分析
- [BabelJudge](https://arxiv.org/pdf/2606.22329) - LLM Judge 可靠性
- [Microsoft Foundry: LLM-as-a-Judge Reliability](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/evaluating-ai-agents-can-llm%E2%80%91as%E2%80%91a%E2%80%91judge-evaluators-be-trusted/4480110) - 三大可靠性支柱
- [WebArena](https://arxiv.org/html/2307.13854v4) - 任务成功率评估
- [MLflow Top 5 Agent Evaluation Tools](https://mlflow.org/top-5-agent-evaluation-frameworks/) - 工具对比
- [DeepEval LLM-as-a-Judge Guide](https://deepeval.com/guides/guides-llm-as-a-judge) - G-Eval/DAG/QAG
- [GAIA Agent Eval Benchmark](https://amd-gaia.ai/docs/eval) - 7 维评分量表
- [Evaluating AI Agents: Metrics and Best Practices (Maxim AI)](https://www.getmaxim.ai/articles/evaluating-ai-agents-metrics-and-best-practices/) - 评估最佳实践

---

> **文档版本**: v1.0
> **创建时间**: 2026-07-07
> **预计完成**: 2026-08-18（第 6 周）
