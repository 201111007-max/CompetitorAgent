"""基于规则的元认知评估器（默认实现）

特点：
- 快速、可预测
- 易于调试和测试
- 不依赖外部 API
- 可作为降级方案

架构：
- RuleBasedKnowledgeBoundary: 知识边界评估
- WeightedConfidenceCalculator: 加权置信度计算
- RuleBasedClarificationGenerator: 澄清请求生成
- RuleBasedMetacognitionEvaluator: 主协调器
"""

from typing import Dict, List, Any, Optional
import time
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
    KnowledgeAssessment,
    ClarificationRequest,
    ConfidenceLevel
)
from utils.log_config import get_logger
from utils.trace_context import TraceSpan, get_current_trace

logger = get_logger("rule_based_metacognition", component="core")


class RuleBasedKnowledgeBoundary(IKnowledgeBoundary):
    """基于规则的知识边界评估
    
    评估维度：
    1. 查询关键词匹配度
    2. 数据源覆盖度
    3. 工具可用性
    4. 记忆相关性
    
    扩展方式：
    - 继承此类并重写评估方法
    - 或实现 IKnowledgeBoundary 接口创建全新实现
    """
    
    DOMAIN_KEYWORDS = {
        "hero_counter": ["克制", "counter", "克制谁", "counter pick"],
        "item_build": ["出装", "装备", "item", "build", "出什么"],
        "skill_build": ["技能", "加点", "skill", "ability"],
        "hero_info": ["英雄", "hero", "属性", "stats"],
    }
    
    def __init__(
        self,
        tool_registry=None,
        memory=None,
        api_client=None
    ):
        """初始化
        
        Args:
            tool_registry: 工具注册表（用于检查可用工具）
            memory: 记忆系统（用于检查历史经验）
            api_client: API 客户端（用于检查数据可用性）
        """
        self.tool_registry = tool_registry
        self.memory = memory
        self.api_client = api_client
    
    def assess(self, query: str, context: Dict[str, Any]) -> KnowledgeAssessment:
        """评估知识掌握程度"""
        trace_ctx = get_current_trace()
        
        with TraceSpan("knowledge_boundary_assess"):
            logger.info_ctx(
                "开始知识边界评估",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={"query": query}
            )
            
            detected_domains = self._detect_domains(query)
            logger.debug_ctx(
                "检测到查询领域",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={"domains": detected_domains}
            )
            
            coverage_score = self._evaluate_coverage(query, detected_domains, context)
            quality_score = self._evaluate_data_quality(context)
            tool_score = self._evaluate_tool_match(query)
            memory_score = self._evaluate_memory_relevance(query)
            
            overall_score = (
                coverage_score * 0.35 +
                quality_score * 0.25 +
                tool_score * 0.20 +
                memory_score * 0.20
            )
            
            limitations = self._identify_limitations(query, detected_domains)
            data_sources = self._identify_data_sources(context)
            reasoning = self._build_reasoning(coverage_score, quality_score, tool_score, memory_score)
            
            assessment = KnowledgeAssessment(
                confidence_score=overall_score,
                confidence_level=self._score_to_level(overall_score),
                knowledge_coverage=coverage_score,
                data_quality_score=quality_score,
                reasoning=reasoning,
                limitations=limitations,
                data_sources=data_sources
            )
            
            logger.info_ctx(
                "知识边界评估完成",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={
                    "confidence_score": round(overall_score, 3),
                    "confidence_level": assessment.confidence_level.value,
                    "coverage": round(coverage_score, 3),
                    "quality": round(quality_score, 3)
                }
            )
            
            return assessment
    
    def _detect_domains(self, query: str) -> List[str]:
        """检测查询涉及的领域"""
        query_lower = query.lower()
        domains = []
        
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                domains.append(domain)
        
        return domains if domains else ["general"]
    
    def _evaluate_coverage(
        self,
        query: str,
        domains: List[str],
        context: Dict[str, Any]
    ) -> float:
        """评估数据覆盖度"""
        score = 0.0
        
        has_entities = bool(
            context.get("our_heroes") or
            context.get("enemy_heroes") or
            context.get("items")
        )
        
        if has_entities:
            score += 0.6
            
            hero_count = (
                len(context.get("our_heroes", [])) +
                len(context.get("enemy_heroes", []))
            )
            
            if hero_count >= 2:
                score += 0.4
            elif hero_count == 1:
                score += 0.2
        else:
            score = 0.3
        
        return min(1.0, score)
    
    def _evaluate_data_quality(self, context: Dict[str, Any]) -> float:
        """评估数据质量"""
        score = 0.7
        
        data_sources = context.get("data_sources", [])
        if "opendota" in data_sources:
            score += 0.2
        
        data_age = context.get("data_age_days", 30)
        if data_age < 7:
            score += 0.1
        elif data_age > 90:
            score -= 0.2
        
        return max(0.0, min(1.0, score))
    
    def _evaluate_tool_match(self, query: str) -> float:
        """评估工具匹配度"""
        if not self.tool_registry:
            return 0.5
        
        available_tools = self.tool_registry.list_tools()
        query_lower = query.lower()
        matched_tools = 0
        
        for tool_name in available_tools:
            if any(kw in tool_name.lower() for kw in query_lower.split()):
                matched_tools += 1
        
        if available_tools:
            return min(1.0, matched_tools / len(available_tools) * 2)
        
        return 0.5
    
    def _evaluate_memory_relevance(self, query: str) -> float:
        """评估记忆相关性"""
        if not self.memory:
            return 0.5
        
        try:
            relevant_memories = self.memory.get_relevant_context(query, limit=3)
            
            if relevant_memories:
                return min(1.0, 0.5 + len(relevant_memories) * 0.15)
            
            return 0.5
        except Exception as e:
            logger.warning_ctx(
                "记忆检索失败",
                session_id=None,
                extra_data={"error": str(e)}
            )
            return 0.5
    
    def _identify_limitations(
        self,
        query: str,
        domains: List[str]
    ) -> List[str]:
        """识别知识限制"""
        limitations = []
        
        if "版本" in query or "patch" in query.lower():
            limitations.append("游戏版本可能已更新，数据可能不是最新")
        
        if "职业" in query or "professional" in query.lower():
            limitations.append("职业比赛数据可能与普通对局不同")
        
        if not self.api_client:
            limitations.append("无法访问实时 API 数据")
        
        return limitations
    
    def _identify_data_sources(self, context: Dict[str, Any]) -> List[str]:
        """识别使用的数据源"""
        sources = []
        
        if context.get("data_sources"):
            sources.extend(context["data_sources"])
        
        if self.memory:
            sources.append("memory")
        
        return sources if sources else ["local_knowledge"]
    
    def _score_to_level(self, score: float) -> ConfidenceLevel:
        """分数转等级"""
        if score >= 0.9:
            return ConfidenceLevel.VERY_HIGH
        elif score >= 0.7:
            return ConfidenceLevel.HIGH
        elif score >= 0.5:
            return ConfidenceLevel.MEDIUM
        elif score >= 0.3:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW
    
    def _build_reasoning(
        self,
        coverage: float,
        quality: float,
        tool_match: float,
        memory: float
    ) -> str:
        """构建评估理由"""
        reasons = []
        
        if coverage >= 0.8:
            reasons.append("数据覆盖充分")
        elif coverage < 0.5:
            reasons.append("数据覆盖不足")
        
        if quality >= 0.8:
            reasons.append("数据质量良好")
        
        if tool_match >= 0.7:
            reasons.append("工具匹配度高")
        
        if memory >= 0.7:
            reasons.append("有相关历史经验")
        
        return "；".join(reasons) if reasons else "基于现有知识评估"


class WeightedConfidenceCalculator(IConfidenceCalculator):
    """加权置信度计算器
    
    特点：
    - 支持自定义权重配置
    - 支持动态权重调整
    - 易于替换为其他计算策略
    
    扩展方式：
    - 继承此类并重写 calculate 方法
    - 或实现 IConfidenceCalculator 接口创建全新实现（如 ML 模型）
    """
    
    DEFAULT_WEIGHTS = {
        "knowledge_coverage": 0.35,
        "data_quality": 0.25,
        "tool_match": 0.20,
        "memory_relevance": 0.20
    }
    
    LEVEL_THRESHOLDS = {
        ConfidenceLevel.VERY_HIGH: 0.9,
        ConfidenceLevel.HIGH: 0.7,
        ConfidenceLevel.MEDIUM: 0.5,
        ConfidenceLevel.LOW: 0.3,
        ConfidenceLevel.VERY_LOW: 0.0
    }
    
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        thresholds: Optional[Dict[ConfidenceLevel, float]] = None
    ):
        """初始化
        
        Args:
            weights: 自定义权重配置
            thresholds: 自定义等级阈值
        """
        self.weights = weights or self.DEFAULT_WEIGHTS
        self.thresholds = thresholds or self.LEVEL_THRESHOLDS
    
    def calculate(
        self,
        factors: Dict[str, float],
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """计算加权置信度"""
        trace_ctx = get_current_trace()
        
        active_weights = weights or self.weights
        
        weighted_sum = 0.0
        total_weight = 0.0
        
        for factor_name, weight in active_weights.items():
            if factor_name in factors:
                weighted_sum += factors[factor_name] * weight
                total_weight += weight
        
        if total_weight > 0:
            result = weighted_sum / total_weight
        else:
            result = 0.0
        
        logger.debug_ctx(
            "置信度计算完成",
            session_id=trace_ctx.session_id if trace_ctx else None,
            extra_data={
                "factors": {k: round(v, 3) for k, v in factors.items()},
                "weights": {k: round(v, 3) for k, v in active_weights.items()},
                "result": round(result, 3)
            }
        )
        
        return result
    
    def get_level(self, score: float) -> ConfidenceLevel:
        """根据分数获取等级"""
        for level in [
            ConfidenceLevel.VERY_HIGH,
            ConfidenceLevel.HIGH,
            ConfidenceLevel.MEDIUM,
            ConfidenceLevel.LOW
        ]:
            if score >= self.thresholds[level]:
                return level
        
        return ConfidenceLevel.VERY_LOW


class RuleBasedClarificationGenerator(IClarificationGenerator):
    """基于规则的澄清请求生成器
    
    特点：
    - 根据知识缺口类型生成针对性问题
    - 支持模板化配置
    - 易于扩展新的澄清策略
    
    扩展方式：
    - 继承此类并重写 generate 方法
    - 或实现 IClarificationGenerator 接口创建全新实现（如 LLM 生成）
    """
    
    CLARIFICATION_TEMPLATES = {
        "missing_hero": "请问您指的是哪个英雄？可以提供英雄名称或描述。",
        "missing_context": "能否提供更多对局信息？例如游戏阶段、双方阵容等。",
        "ambiguous_intent": "请问您具体想了解什么？例如：克制关系、出装建议、技能加点等。",
        "version_dependent": "请问您询问的是哪个游戏版本？不同版本可能有不同答案。",
        "insufficient_data": "当前数据可能不够充分，您能否提供更多细节？"
    }
    
    def generate(
        self,
        query: str,
        assessment: KnowledgeAssessment,
        missing_info: List[str]
    ) -> ClarificationRequest:
        """生成澄清请求"""
        trace_ctx = get_current_trace()
        
        logger.info_ctx(
            "生成澄清请求",
            session_id=trace_ctx.session_id if trace_ctx else None,
            extra_data={
                "query": query,
                "confidence_level": assessment.confidence_level.value,
                "missing_info_count": len(missing_info)
            }
        )
        
        clarification_type = self._determine_type(missing_info, assessment)
        questions = self._generate_questions(missing_info, clarification_type)
        suggestions = self._generate_suggestions(clarification_type)
        partial_answer = self._build_partial_answer(assessment)
        
        request = ClarificationRequest(
            type=clarification_type,
            original_query=query,
            confidence_level=assessment.confidence_level,
            missing_info=missing_info,
            questions=questions,
            suggestions=suggestions,
            partial_answer=partial_answer
        )
        
        logger.info_ctx(
            "澄清请求生成完成",
            session_id=trace_ctx.session_id if trace_ctx else None,
            extra_data={
                "type": clarification_type,
                "questions_count": len(questions)
            }
        )
        
        return request
    
    def _determine_type(
        self,
        missing_info: List[str],
        assessment: KnowledgeAssessment
    ) -> str:
        """确定澄清类型"""
        missing_text = " ".join(missing_info).lower()
        
        if "英雄" in missing_text or "hero" in missing_text:
            return "missing_hero"
        elif "版本" in missing_text or "version" in missing_text:
            return "version_dependent"
        elif "意图" in missing_text or "intent" in missing_text:
            return "ambiguous_intent"
        elif "数据" in missing_text or "data" in missing_text:
            return "insufficient_data"
        else:
            return "missing_context"
    
    def _generate_questions(
        self,
        missing_info: List[str],
        clarification_type: str
    ) -> List[str]:
        """生成澄清问题"""
        questions = []
        
        template = self.CLARIFICATION_TEMPLATES.get(clarification_type)
        if template:
            questions.append(template)
        
        for info in missing_info[:2]:
            questions.append(f"关于「{info}」，您能提供更多细节吗？")
        
        return questions[:3]
    
    def _generate_suggestions(self, clarification_type: str) -> List[str]:
        """生成建议操作"""
        suggestion_map = {
            "missing_hero": ["提供英雄名称（中文或英文）", "描述英雄特征"],
            "missing_context": ["说明游戏阶段（对线期/中期/后期）", "提供双方阵容信息"],
            "ambiguous_intent": ["明确您的需求（克制/出装/技能）", "提供具体场景"],
            "version_dependent": ["说明游戏版本号", "说明是否为测试服"],
            "insufficient_data": ["提供更多对局细节", "说明具体需求场景"]
        }
        
        return suggestion_map.get(clarification_type, ["提供更多详细信息"])
    
    def _build_partial_answer(self, assessment: KnowledgeAssessment) -> Optional[str]:
        """构建部分答案"""
        if assessment.confidence_level not in [ConfidenceLevel.VERY_LOW]:
            return (
                f"基于现有数据（置信度：{assessment.confidence_score:.0%}），"
                f"我可以提供一般性建议。但为了更准确的答案，建议您补充上述信息。"
            )
        
        return None


class RuleBasedMetacognitionEvaluator(IMetacognitionEvaluator):
    """基于规则的元认知评估器（主协调器）
    
    职责：
    - 协调各个组件完成完整评估流程
    - 提供统一的评估接口
    - 支持组件替换（通过依赖注入）
    
    扩展方式：
    - 通过构造函数注入不同的组件实现
    - 或继承此类并重写方法
    - 或实现 IMetacognitionEvaluator 接口创建全新实现
    """
    
    def __init__(
        self,
        knowledge_boundary: IKnowledgeBoundary,
        confidence_calculator: IConfidenceCalculator,
        clarification_generator: IClarificationGenerator,
        clarification_threshold: ConfidenceLevel = ConfidenceLevel.LOW
    ):
        """初始化
        
        Args:
            knowledge_boundary: 知识边界评估器
            confidence_calculator: 置信度计算器
            clarification_generator: 澄清请求生成器
            clarification_threshold: 请求澄清的阈值
        """
        self.knowledge_boundary = knowledge_boundary
        self.confidence_calculator = confidence_calculator
        self.clarification_generator = clarification_generator
        self.clarification_threshold = clarification_threshold
        
        logger.info("基于规则的元认知评估器已初始化")
    
    def assess_before_execution(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> KnowledgeAssessment:
        """执行前评估"""
        trace_ctx = get_current_trace()
        
        with TraceSpan("metacognition_assess_before"):
            logger.info_ctx(
                "执行前元认知评估",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={"query": query}
            )
            
            assessment = self.knowledge_boundary.assess(query, context)
            
            logger.info_ctx(
                "执行前评估完成",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={
                    "confidence_level": assessment.confidence_level.value,
                    "confidence_score": round(assessment.confidence_score, 3)
                }
            )
            
            return assessment
    
    def assess_during_execution(
        self,
        query: str,
        observations: List[Any],
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> KnowledgeAssessment:
        """执行中评估"""
        trace_ctx = get_current_trace()
        
        with TraceSpan("metacognition_assess_during"):
            logger.info_ctx(
                "执行中元认知评估",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={
                    "observations_count": len(observations),
                    "actions_count": len(actions)
                }
            )
            
            base_assessment = self.knowledge_boundary.assess(query, context)
            
            if actions:
                success_rate = sum(
                    1 for a in actions
                    if a.get("result", {}).get("status") == "success"
                ) / len(actions)
                
                base_assessment.confidence_score = min(
                    1.0,
                    base_assessment.confidence_score * (0.7 + success_rate * 0.3)
                )
                
                logger.debug_ctx(
                    "根据工具执行成功率调整置信度",
                    session_id=trace_ctx.session_id if trace_ctx else None,
                    extra_data={"success_rate": round(success_rate, 3)}
                )
            
            if observations:
                obs_bonus = min(0.2, len(observations) * 0.05)
                base_assessment.confidence_score = min(
                    1.0,
                    base_assessment.confidence_score + obs_bonus
                )
                
                logger.debug_ctx(
                    "根据观察结果数量调整置信度",
                    session_id=trace_ctx.session_id if trace_ctx else None,
                    extra_data={"observations_bonus": round(obs_bonus, 3)}
                )
            
            base_assessment.confidence_level = self.confidence_calculator.get_level(
                base_assessment.confidence_score
            )
            
            logger.info_ctx(
                "执行中评估完成",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={
                    "confidence_level": base_assessment.confidence_level.value,
                    "confidence_score": round(base_assessment.confidence_score, 3)
                }
            )
            
            return base_assessment
    
    def assess_after_execution(
        self,
        query: str,
        final_result: Dict[str, Any],
        context: Dict[str, Any]
    ) -> KnowledgeAssessment:
        """执行后评估"""
        trace_ctx = get_current_trace()
        
        with TraceSpan("metacognition_assess_after"):
            logger.info_ctx(
                "执行后元认知评估",
                session_id=trace_ctx.session_id if trace_ctx else None
            )
            
            assessment = self.assess_during_execution(
                query=query,
                observations=final_result.get("observations", []),
                actions=final_result.get("actions", []),
                context=context
            )
            
            logger.info_ctx(
                "执行后评估完成",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={
                    "confidence_level": assessment.confidence_level.value,
                    "confidence_score": round(assessment.confidence_score, 3)
                }
            )
            
            return assessment
    
    def should_request_clarification(
        self,
        assessment: KnowledgeAssessment
    ) -> bool:
        """判断是否需要请求澄清"""
        should = assessment.confidence_level in [
            ConfidenceLevel.LOW,
            ConfidenceLevel.VERY_LOW
        ]
        
        logger.debug_ctx(
            "澄清请求判断",
            session_id=None,
            extra_data={
                "confidence_level": assessment.confidence_level.value,
                "should_request": should
            }
        )
        
        return should
    
    def generate_clarification(
        self,
        query: str,
        assessment: KnowledgeAssessment
    ) -> ClarificationRequest:
        """生成澄清请求"""
        trace_ctx = get_current_trace()
        
        with TraceSpan("metacognition_generate_clarification"):
            return self.clarification_generator.generate(
                query=query,
                assessment=assessment,
                missing_info=assessment.limitations
            )
