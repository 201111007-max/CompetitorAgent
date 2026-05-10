"""反思评估器 - ReAct Agent 反思机制核心组件

提供高质量的结果评估、策略调整和决策优化功能

特性：
- 多维度结果质量评估（完整性、一致性、可信度、相关性）
- LLM 增强的智能评估
- 基于规则的快速评估
- 策略调整建议生成
- 置信度计算

架构设计原则：
- 高可读性：清晰的类结构、详细的文档字符串、直观的命名
- 高可靠性：多层容错、数据验证、降级方案
- 可扩展性：模块化设计、策略模式、易于添加新评估维度
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import sys
from pathlib import Path
from abc import ABC, abstractmethod

# 确保可以导入项目模块
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class EvaluationDimension(Enum):
    """评估维度枚举"""
    COMPLETENESS = "completeness"      # 完整性：是否回答了所有问题
    CONSISTENCY = "consistency"        # 一致性：结果内部是否一致
    CREDIBILITY = "credibility"        # 可信度：数据来源是否可靠
    RELEVANCE = "relevance"           # 相关性：结果是否与查询相关
    ACTIONABILITY = "actionability"   # 可操作性：建议是否具体可行


class ReflectionAction(Enum):
    """反思后采取的行动"""
    CONTINUE = "continue"              # 继续收集更多信息
    ADJUST_STRATEGY = "adjust_strategy"  # 调整策略
    FINALIZE = "finalize"             # 结束并输出结果
    REQUEST_CLARIFICATION = "request_clarification"  # 请求用户澄清


@dataclass
class QualityScore:
    """质量评分"""
    dimension: EvaluationDimension
    score: float  # 0.0 - 1.0
    reasons: List[str] = field(default_factory=list)
    confidence: float = 1.0  # 评分置信度

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "confidence": round(self.confidence, 3)
        }


@dataclass
class ReflectionResult:
    """反思结果"""
    action: ReflectionAction
    overall_score: float
    dimension_scores: List[QualityScore]
    reasoning: str
    strategy_adjustments: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "overall_score": round(self.overall_score, 3),
            "dimension_scores": [s.to_dict() for s in self.dimension_scores],
            "reasoning": self.reasoning,
            "strategy_adjustments": self.strategy_adjustments,
            "missing_information": self.missing_information,
            "confidence": round(self.confidence, 3)
        }


class IEvaluationStrategy(ABC):
    """评估策略接口"""

    @abstractmethod
    def evaluate(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> QualityScore:
        """评估结果质量

        Args:
            query: 用户查询
            observations: 观察结果列表
            actions: 行动记录列表
            context: 上下文信息

        Returns:
            QualityScore: 质量评分
        """
        pass


class CompletenessStrategy(IEvaluationStrategy):
    """完整性评估策略

    评估结果是否完整回答了用户的问题
    """

    def evaluate(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> QualityScore:
        reasons = []
        score = 0.0

        # 检查是否有观察结果
        if not observations:
            return QualityScore(
                dimension=EvaluationDimension.COMPLETENESS,
                score=0.0,
                reasons=["没有任何观察结果"],
                confidence=1.0
            )

        # 检查观察结果的数量
        obs_count = len(observations)
        if obs_count >= 3:
            score += 0.4
            reasons.append(f"收集到充足的观察结果 ({obs_count} 条)")
        elif obs_count >= 1:
            score += 0.2
            reasons.append(f"收集到基本的观察结果 ({obs_count} 条)")
        else:
            reasons.append("观察结果不足")

        # 检查是否包含关键信息
        for obs in observations:
            if isinstance(obs, dict):
                # 检查是否有推荐结果
                if 'recommendations' in obs:
                    recs = obs['recommendations']
                    if isinstance(recs, list) and len(recs) >= 3:
                        score += 0.3
                        reasons.append(f"包含充足的推荐项 ({len(recs)} 项)")
                    elif isinstance(recs, list) and len(recs) >= 1:
                        score += 0.15
                        reasons.append(f"包含基本的推荐项 ({len(recs)} 项)")
                    else:
                        reasons.append("推荐项数量不足")

                # 检查是否有答案
                if 'answer' in obs and obs['answer']:
                    score += 0.3
                    reasons.append("包含明确的答案")

        return QualityScore(
            dimension=EvaluationDimension.COMPLETENESS,
            score=min(1.0, score),
            reasons=reasons,
            confidence=0.9
        )


class ConsistencyStrategy(IEvaluationStrategy):
    """一致性评估策略

    评估结果内部是否一致，是否存在矛盾
    """

    def evaluate(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> QualityScore:
        reasons = []
        score = 1.0  # 初始为满分，发现问题扣分

        if not observations:
            return QualityScore(
                dimension=EvaluationDimension.CONSISTENCY,
                score=0.0,
                reasons=["没有观察结果，无法评估一致性"],
                confidence=0.5
            )

        # 检查多个观察结果之间是否一致
        if len(observations) > 1:
            # 简单检查：比较数据结构是否相似
            first_type = type(observations[0])
            same_type_count = sum(1 for obs in observations if type(obs) == first_type)

            if same_type_count == len(observations):
                reasons.append("所有观察结果数据结构一致")
            else:
                score -= 0.2
                reasons.append(f"观察结果数据结构不一致 ({same_type_count}/{len(observations)})")

        # 检查推荐结果中的评分是否合理
        for obs in observations:
            if isinstance(obs, dict) and 'recommendations' in obs:
                recs = obs['recommendations']
                if isinstance(recs, list):
                    scores = []
                    for rec in recs:
                        if isinstance(rec, dict):
                            if 'score' in rec:
                                scores.append(rec['score'])
                            elif 'win_rate' in rec:
                                scores.append(rec['win_rate'])

                    if scores:
                        # 检查分数是否在合理范围内
                        if all(0 <= s <= 1 for s in scores):
                            reasons.append("推荐评分在合理范围内")
                        else:
                            score -= 0.3
                            reasons.append("部分推荐评分超出合理范围")

                        # 检查分数是否有明显差异（前几名应该明显更好）
                        if len(scores) >= 2:
                            sorted_scores = sorted(scores, reverse=True)
                            if sorted_scores[0] - sorted_scores[-1] > 0.1:
                                reasons.append("推荐项之间有明显的优劣区分")
                            else:
                                reasons.append("推荐项之间区分度不高")

        return QualityScore(
            dimension=EvaluationDimension.CONSISTENCY,
            score=max(0.0, min(1.0, score)),
            reasons=reasons,
            confidence=0.85
        )


class CredibilityStrategy(IEvaluationStrategy):
    """可信度评估策略

    评估数据来源的可信度
    """

    def evaluate(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> QualityScore:
        reasons = []
        score = 0.0

        if not actions:
            return QualityScore(
                dimension=EvaluationDimension.CREDIBILITY,
                score=0.0,
                reasons=["没有执行任何行动，数据来源不明"],
                confidence=1.0
            )

        # 检查工具执行成功率
        successful_actions = sum(
            1 for action in actions
            if action.get('result', {}).get('status') == 'success'
        )

        success_rate = successful_actions / len(actions) if actions else 0
        if success_rate == 1.0:
            score += 0.5
            reasons.append("所有工具执行成功")
        elif success_rate >= 0.5:
            score += 0.3
            reasons.append(f"部分工具执行成功 ({success_rate:.0%})")
        else:
            reasons.append(f"工具执行成功率低 ({success_rate:.0%})")

        # 检查数据来源
        data_sources = context.get('data_sources', [])
        if data_sources:
            # 检查是否使用了权威数据源（如 OpenDota API）
            authoritative_sources = ['opendota', 'official', 'verified']
            has_authoritative = any(
                any(source.lower() in src for source in authoritative_sources)
                for src in data_sources
            )

            if has_authoritative:
                score += 0.5
                reasons.append("使用了权威数据源")
            else:
                score += 0.3
                reasons.append("使用了普通数据源")
        else:
            # 默认给中等分数
            score += 0.4
            reasons.append("数据来源未知")

        return QualityScore(
            dimension=EvaluationDimension.CREDIBILITY,
            score=min(1.0, score),
            reasons=reasons,
            confidence=0.8
        )


class RelevanceStrategy(IEvaluationStrategy):
    """相关性评估策略

    评估结果与查询的相关程度
    """

    def evaluate(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> QualityScore:
        reasons = []
        score = 0.0

        query_lower = query.lower()

        # 检查是否针对查询类型采取了正确的行动
        query_keywords = {
            'hero': ['英雄', 'hero', '克制', 'counter', '推荐'],
            'item': ['出装', '装备', 'item', 'build'],
            'skill': ['技能', '加点', 'skill', 'ability'],
            'composition': ['阵容', 'composition', 'balance']
        }

        # 检测查询主题
        detected_topics = []
        for topic, keywords in query_keywords.items():
            if any(kw in query_lower for kw in keywords):
                detected_topics.append(topic)

        if not detected_topics:
            detected_topics.append('general')

        # 检查工具调用是否与查询相关
        if actions:
            tool_names = [action.get('tool_name', '') for action in actions]
            relevant_tools = 0

            for tool_name in tool_names:
                tool_lower = tool_name.lower()
                if any(topic in tool_lower for topic in detected_topics):
                    relevant_tools += 1

            relevance_rate = relevant_tools / len(actions)
            if relevance_rate >= 0.8:
                score += 0.5
                reasons.append(f"工具调用高度相关 ({relevance_rate:.0%})")
            elif relevance_rate >= 0.5:
                score += 0.3
                reasons.append(f"工具调用部分相关 ({relevance_rate:.0%})")
            else:
                reasons.append(f"工具调用相关性低 ({relevance_rate:.0%})")

        # 检查观察结果是否包含查询相关的信息
        for obs in observations:
            if isinstance(obs, dict):
                # 检查是否包含推荐或答案
                if any(key in obs for key in ['recommendations', 'answer', 'result']):
                    score += 0.3
                    reasons.append("包含直接相关的结果")
                    break
        else:
            reasons.append("结果相关性不明确")

        return QualityScore(
            dimension=EvaluationDimension.RELEVANCE,
            score=min(1.0, score),
            reasons=reasons,
            confidence=0.85
        )


class ActionabilityStrategy(IEvaluationStrategy):
    """可操作性评估策略

    评估建议是否具体、可行
    """

    def evaluate(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> QualityScore:
        reasons = []
        score = 0.0

        if not observations:
            return QualityScore(
                dimension=EvaluationDimension.ACTIONABILITY,
                score=0.0,
                reasons=["没有观察结果，无法评估可操作性"],
                confidence=1.0
            )

        # 检查推荐是否包含具体信息
        actionable_count = 0
        total_count = 0

        for obs in observations:
            if isinstance(obs, dict) and 'recommendations' in obs:
                recs = obs['recommendations']
                if isinstance(recs, list):
                    for rec in recs:
                        if isinstance(rec, dict):
                            total_count += 1
                            # 检查是否包含必要的详细信息
                            detail_fields = ['hero_name', 'item_name', 'reason', 'description']
                            has_details = any(field in rec for field in detail_fields)

                            # 检查是否有评分或数据支持
                            has_support = any(
                                key in rec for key in ['score', 'win_rate', 'games', 'data']
                            )

                            if has_details and has_support:
                                actionable_count += 1

        if total_count > 0:
            actionability_rate = actionable_count / total_count
            if actionability_rate >= 0.8:
                score += 0.6
                reasons.append(f"推荐高度可操作 ({actionability_rate:.0%} 包含详细信息)")
            elif actionability_rate >= 0.5:
                score += 0.4
                reasons.append(f"推荐基本可操作 ({actionability_rate:.0%} 包含详细信息)")
            else:
                reasons.append(f"推荐可操作性不足 ({actionability_rate:.0%} 包含详细信息)")
        else:
            reasons.append("没有具体的推荐项")

        return QualityScore(
            dimension=EvaluationDimension.ACTIONABILITY,
            score=min(1.0, score),
            reasons=reasons,
            confidence=0.85
        )


class ReflectionEvaluator:
    """反思评估器

    综合多个评估维度，对 Agent 的执行结果进行全面评估

    使用方式：
    1. 创建评估器实例（可选择是否启用 LLM 增强）
    2. 调用 evaluate() 方法进行评估
    3. 根据返回的 ReflectionResult 决定下一步行动

    示例：
    ```python
    evaluator = ReflectionEvaluator()
    result = evaluator.evaluate(
        query="推荐克制帕吉的英雄",
        observations=[...],
        actions=[...],
        context={}
    )

    if result.action == ReflectionAction.CONTINUE:
        # 继续收集更多信息
    elif result.action == ReflectionAction.ADJUST_STRATEGY:
        # 调整策略
    else:
        # 结束并输出结果
    ```
    """

    # 维度权重配置
    DEFAULT_WEIGHTS = {
        EvaluationDimension.COMPLETENESS: 0.30,    # 完整性最重要
        EvaluationDimension.CONSISTENCY: 0.20,     # 一致性
        EvaluationDimension.CREDIBILITY: 0.20,     # 可信度
        EvaluationDimension.RELEVANCE: 0.20,       # 相关性
        EvaluationDimension.ACTIONABILITY: 0.10    # 可操作性
    }

    # 质量阈值配置
    CONTINUE_THRESHOLD = 0.4      # 低于此值需要继续收集信息
    ADJUST_THRESHOLD = 0.6        # 低于此值需要调整策略
    FINALIZE_THRESHOLD = 0.75     # 高于此值可以结束

    def __init__(
        self,
        weights: Optional[Dict[EvaluationDimension, float]] = None,
        enable_llm: bool = False,
        llm_client: Optional[Any] = None
    ):
        """初始化反思评估器

        Args:
            weights: 各维度权重配置（可选，默认使用 DEFAULT_WEIGHTS）
            enable_llm: 是否启用 LLM 增强评估
            llm_client: LLM 客户端实例（可选）
        """
        self.weights = weights or self.DEFAULT_WEIGHTS
        self.enable_llm = enable_llm and llm_client is not None
        self.llm_client = llm_client

        # 初始化评估策略
        self.strategies: Dict[EvaluationDimension, IEvaluationStrategy] = {
            EvaluationDimension.COMPLETENESS: CompletenessStrategy(),
            EvaluationDimension.CONSISTENCY: ConsistencyStrategy(),
            EvaluationDimension.CREDIBILITY: CredibilityStrategy(),
            EvaluationDimension.RELEVANCE: RelevanceStrategy(),
            EvaluationDimension.ACTIONABILITY: ActionabilityStrategy()
        }

        # 验证权重和为 1
        total_weight = sum(self.weights.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"维度权重之和必须为 1.0，当前为 {total_weight}")

    def evaluate(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> ReflectionResult:
        """评估结果质量并决定下一步行动

        Args:
            query: 用户查询
            observations: 观察结果列表
            actions: 行动记录列表
            context: 上下文信息

        Returns:
            ReflectionResult: 反思结果
        """
        # 1. 对每个维度进行评估
        dimension_scores: List[QualityScore] = []
        weighted_sum = 0.0

        for dimension, strategy in self.strategies.items():
            try:
                score = strategy.evaluate(query, observations, actions, context)
                dimension_scores.append(score)
                weighted_sum += score.score * self.weights[dimension]
            except Exception as e:
                # 单个策略失败不影响整体评估
                dimension_scores.append(QualityScore(
                    dimension=dimension,
                    score=0.5,  # 默认中等分数
                    reasons=[f"评估失败：{str(e)}"],
                    confidence=0.3
                ))
                weighted_sum += 0.5 * self.weights[dimension]

        # 2. 计算总体评分
        overall_score = weighted_sum

        # 3. 决定采取的行动
        action, reasoning = self._decide_action(overall_score, dimension_scores)

        # 4. 生成策略调整建议
        strategy_adjustments = self._generate_adjustments(dimension_scores)

        # 5. 识别缺失的信息
        missing_information = self._identify_missing_info(dimension_scores, actions)

        # 6. 计算置信度
        confidence = self._calculate_confidence(dimension_scores)

        return ReflectionResult(
            action=action,
            overall_score=round(overall_score, 3),
            dimension_scores=dimension_scores,
            reasoning=reasoning,
            strategy_adjustments=strategy_adjustments,
            missing_information=missing_information,
            confidence=confidence
        )

    def _decide_action(
        self,
        overall_score: float,
        dimension_scores: List[QualityScore]
    ) -> Tuple[ReflectionAction, str]:
        """根据评分决定采取的行动

        Args:
            overall_score: 总体评分
            dimension_scores: 各维度评分

        Returns:
            (行动类型，推理说明)
        """
        # 检查是否有维度评分极低
        min_score = min(s.score for s in dimension_scores)

        if overall_score >= self.FINALIZE_THRESHOLD and min_score >= 0.5:
            return ReflectionAction.FINALIZE, (
                f"结果质量优秀 (总体：{overall_score:.2f}, 最低维度：{min_score:.2f}), "
                f"可以结束并输出结果"
            )
        elif overall_score >= self.ADJUST_THRESHOLD:
            return ReflectionAction.FINALIZE, (
                f"结果质量良好 (总体：{overall_score:.2f}), "
                f"可以结束并输出结果"
            )
        elif overall_score >= self.CONTINUE_THRESHOLD:
            return ReflectionAction.ADJUST_STRATEGY, (
                f"结果质量一般 (总体：{overall_score:.2f}), "
                f"需要调整策略后继续"
            )
        else:
            return ReflectionAction.CONTINUE, (
                f"结果质量不足 (总体：{overall_score:.2f}), "
                f"需要收集更多信息"
            )

    def _generate_adjustments(
        self,
        dimension_scores: List[QualityScore]
    ) -> List[str]:
        """生成策略调整建议

        Args:
            dimension_scores: 各维度评分

        Returns:
            调整建议列表
        """
        adjustments = []

        for score in dimension_scores:
            if score.score < 0.6:
                if score.dimension == EvaluationDimension.COMPLETENESS:
                    adjustments.append("收集更多观察结果或推荐项")
                elif score.dimension == EvaluationDimension.CONSISTENCY:
                    adjustments.append("检查数据一致性，排除矛盾信息")
                elif score.dimension == EvaluationDimension.CREDIBILITY:
                    adjustments.append("使用更权威的数据源")
                elif score.dimension == EvaluationDimension.RELEVANCE:
                    adjustments.append("调整工具选择，更聚焦于查询主题")
                elif score.dimension == EvaluationDimension.ACTIONABILITY:
                    adjustments.append("提供更详细的信息和数据支持")

        return adjustments

    def _identify_missing_info(
        self,
        dimension_scores: List[QualityScore],
        actions: List[Dict[str, Any]]
    ) -> List[str]:
        """识别缺失的信息

        Args:
            dimension_scores: 各维度评分
            actions: 行动记录

        Returns:
            缺失信息列表
        """
        missing = []

        # 检查是否缺少关键维度的信息
        for score in dimension_scores:
            if score.score < 0.5:
                for reason in score.reasons:
                    if "不足" in reason or "没有" in reason:
                        missing.append(f"{score.dimension.value}: {reason}")

        # 检查是否有未尝试的工具
        if len(actions) < 2:
            missing.append("可以尝试更多工具来获取信息")

        return missing

    def _calculate_confidence(
        self,
        dimension_scores: List[QualityScore]
    ) -> float:
        """计算评估结果的置信度

        Args:
            dimension_scores: 各维度评分

        Returns:
            置信度 (0.0 - 1.0)
        """
        if not dimension_scores:
            return 0.0

        # 基于各维度评分的置信度计算加权平均
        total_confidence = sum(
            s.confidence * self.weights.get(s.dimension, 0)
            for s in dimension_scores
        )

        return min(1.0, max(0.0, total_confidence))

    def evaluate_with_llm(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> ReflectionResult:
        """使用 LLM 增强评估（可选）

        通过 LLM 对结果进行自然语言评估，提供更智能的判断

        Args:
            query: 用户查询
            observations: 观察结果列表
            actions: 行动记录列表
            context: 上下文信息

        Returns:
            ReflectionResult: 反思结果
        """
        if not self.enable_llm or self.llm_client is None:
            # 降级到普通评估
            return self.evaluate(query, observations, actions, context)

        try:
            # 构造评估 Prompt
            prompt = self._build_llm_prompt(query, observations, actions, context)

            # 调用 LLM
            messages = [{"role": "user", "content": prompt}]
            response = self.llm_client.chat(messages, max_tokens=512, temperature=0.3)

            if "error" in response:
                # LLM 失败，降级到普通评估
                return self.evaluate(query, observations, actions, context)

            # 解析 LLM 返回
            llm_evaluation = self._parse_llm_response(response)

            # 结合 LLM 评估和规则评估
            rule_result = self.evaluate(query, observations, actions, context)
            return self._merge_evaluations(llm_evaluation, rule_result)

        except Exception as e:
            # 任何异常都降级到普通评估
            return self.evaluate(query, observations, actions, context)

    def _build_llm_prompt(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> str:
        """构造 LLM 评估 Prompt"""
        return f"""你是一个 ReAct Agent 的质量评估专家。请评估以下 Agent 执行结果的质量。

用户查询：{query}

执行的行动：
{json.dumps(actions, ensure_ascii=False, indent=2)}

观察结果：
{json.dumps(observations, ensure_ascii=False, indent=2)}

请从以下维度评估（每个维度 0-1 分）：
1. 完整性：是否完整回答了用户的问题？
2. 一致性：结果内部是否一致，有无矛盾？
3. 可信度：数据来源是否可靠？
4. 相关性：结果是否与查询高度相关？
5. 可操作性：建议是否具体可行？

请返回 JSON 格式：
{{
    "dimension_scores": {{
        "completeness": {{"score": 0.8, "reason": "..."}},
        "consistency": {{"score": 0.9, "reason": "..."}},
        "credibility": {{"score": 0.7, "reason": "..."}},
        "relevance": {{"score": 0.85, "reason": "..."}},
        "actionability": {{"score": 0.75, "reason": "..."}}
    }},
    "overall_score": 0.8,
    "action": "finalize|continue|adjust_strategy",
    "reasoning": "...",
    "suggestions": ["建议 1", "建议 2"]
}}

只返回 JSON，不要其他内容："""

    def _parse_llm_response(self, response: Dict[str, Any]) -> ReflectionResult:
        """解析 LLM 返回的评估结果"""
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        # 提取 JSON
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            raise ValueError("LLM 返回格式不正确")

        data = json.loads(json_match.group())

        # 转换为 ReflectionResult
        dimension_scores = []
        for dim_name, score_data in data.get("dimension_scores", {}).items():
            try:
                dimension = EvaluationDimension(dim_name)
                dimension_scores.append(QualityScore(
                    dimension=dimension,
                    score=float(score_data.get("score", 0.5)),
                    reasons=[score_data.get("reason", "")],
                    confidence=0.9
                ))
            except ValueError:
                continue

        action_map = {
            "finalize": ReflectionAction.FINALIZE,
            "continue": ReflectionAction.CONTINUE,
            "adjust_strategy": ReflectionAction.ADJUST_STRATEGY
        }
        action = action_map.get(data.get("action", "finalize"), ReflectionAction.FINALIZE)

        return ReflectionResult(
            action=action,
            overall_score=float(data.get("overall_score", 0.75)),
            dimension_scores=dimension_scores,
            reasoning=data.get("reasoning", "LLM 评估"),
            strategy_adjustments=data.get("suggestions", []),
            missing_information=[],
            confidence=0.9
        )

    def _merge_evaluations(
        self,
        llm_result: ReflectionResult,
        rule_result: ReflectionResult
    ) -> ReflectionResult:
        """合并 LLM 评估和规则评估结果

        策略：
        - 如果 LLM 和规则评估一致，采用该结果
        - 如果不一致，优先采用规则评估（更可靠）
        - 融合两者的 reasoning 和 suggestions
        """
        # 简单策略：以规则评估为主，LLM 评估作为补充
        merged_reasoning = f"{rule_result.reasoning}\nLLM 观点：{llm_result.reasoning}"
        merged_suggestions = list(set(rule_result.strategy_adjustments + llm_result.strategy_adjustments))

        return ReflectionResult(
            action=rule_result.action,  # 优先采用规则评估的行动
            overall_score=rule_result.overall_score,
            dimension_scores=rule_result.dimension_scores,
            reasoning=merged_reasoning,
            strategy_adjustments=merged_suggestions,
            missing_information=rule_result.missing_information,
            confidence=min(1.0, (rule_result.confidence + llm_result.confidence) / 2)
        )
