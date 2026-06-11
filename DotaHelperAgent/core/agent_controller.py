"""Agent Controller - ReAct Agent 核心控制器

实现完整的 ReAct (Reasoning + Acting) 循环模式
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import time
import json
import sys
import logging
import traceback
from pathlib import Path
from datetime import datetime

# 确保可以导入项目模块
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.tool_registry import ToolRegistry
from core.llm_tool_selector import LLMToolSelector
from core.conversation_manager import ConversationManager, Message, MessageRole
from core.context_augmenter import ContextAugmenter
from core.goal_planner import GoalPlanner, GoalPlan, GoalStatus, GoalTracker
from core.metacognition.factory import MetacognitionFactory
from core.metacognition.interfaces import IMetacognitionEvaluator, KnowledgeAssessment
from core.reflection_evaluator import (
    ReflectionEvaluator, ReflectionResult, ReflectionAction,
    EvaluationDimension, QualityScore
)
from memory.memory import AgentMemory
from tools.base import ToolResult, ToolStatus
from utils.trace_context import TraceSpan, get_current_trace
from utils.log_config import get_logger

# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient, NoOpObservation
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
    NoOpObservation = None

# 获取带 Trace 支持的 logger
logger = get_logger("agent_controller", component="core")


class AgentState(Enum):
    """Agent 状态枚举"""
    THINKING = "thinking"
    PLANNING = "planning"
    ACTING = "acting"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class AgentThought:
    """Agent 思考状态

    记录 ReAct 循环中的中间状态和推理过程
    """
    query: str
    context: Dict[str, Any] = field(default_factory=dict)
    state: AgentState = AgentState.THINKING
    reasoning_steps: List[str] = field(default_factory=list)
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    observations: List[Any] = field(default_factory=list)
    reflections: List[str] = field(default_factory=list)
    final_answer: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    turn_count: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    def add_reasoning(self, reasoning: str) -> None:
        """添加推理步骤"""
        self.reasoning_steps.append(reasoning)

    def add_action(self, tool_name: str, parameters: Dict[str, Any], result: Optional[ToolResult] = None) -> None:
        """记录行动"""
        action = {
            "tool_name": tool_name,
            "parameters": parameters,
            "result": result.to_dict() if result else None,
            "timestamp": time.time()
        }
        self.actions_taken.append(action)

    def add_observation(self, observation: Any) -> None:
        """添加观察结果"""
        self.observations.append(observation)

    def add_reflection(self, reflection: str) -> None:
        """添加反思"""
        self.reflections.append(reflection)

    def set_complete(self, answer: Dict[str, Any]) -> None:
        """标记为完成状态"""
        self.state = AgentState.COMPLETE
        self.final_answer = answer
        self.end_time = time.time()

    def set_failed(self, error: str) -> None:
        """标记为失败状态"""
        self.state = AgentState.FAILED
        self.error = error
        self.end_time = time.time()

    def increment_turn(self) -> None:
        """增加轮次计数"""
        self.turn_count += 1

    def get_duration(self) -> float:
        """获取执行时长（秒）"""
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "query": self.query,
            "context": self.context,
            "state": self.state.value,
            "reasoning_steps": self.reasoning_steps,
            "actions_taken": self.actions_taken,
            "observations": self.observations,
            "reflections": self.reflections,
            "final_answer": self.final_answer,
            "error": self.error,
            "turn_count": self.turn_count,
            "duration": self.get_duration()
        }


class AgentController:
    """ReAct Agent 控制器

    实现完整的 ReAct 循环：
    1. Think - 理解问题和意图
    2. Plan - 制定行动计划
    3. Execute - 执行工具调用
    4. Observe - 观察结果
    5. Reflect - 反思是否需要继续

    特性：
    - 支持多轮推理循环
    - 自主工具选择和调用
    - 反思和错误恢复
    - 记忆系统集成
    - 流式输出支持
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_client,
        memory: Optional[AgentMemory] = None,
        conversation_manager: Optional[ConversationManager] = None,
        max_turns: int = 5,
        enable_reflection: bool = True,
        enable_memory: bool = True,
        metacognition_config: Optional[Dict[str, Any]] = None
    ):
        """初始化 Agent Controller

        Args:
            tool_registry: 工具注册表
            llm_client: LLM 客户端（用于智能工具选择）
            memory: 记忆系统（可选）
            conversation_manager: 会话管理器（可选）
            max_turns: 最大循环轮数
            enable_reflection: 是否启用反思
            enable_memory: 是否启用记忆系统
            metacognition_config: 元认知配置（可选）
                                示例：{"type": "rule_based", "clarification_threshold": "low"}
        """
        self.tool_registry = tool_registry
        self.llm_client = llm_client
        self.memory = memory
        self.conversation_manager = conversation_manager
        self.max_turns = max_turns
        self.enable_reflection = enable_reflection
        self.enable_memory = enable_memory and memory is not None
        self.current_thought: Optional[AgentThought] = None
        
        # 初始化 LLM 工具选择器
        self.tool_selector = LLMToolSelector(llm_client, tool_registry)
        logger.info("LLM 工具选择器已初始化")
        
        # 初始化上下文增强器
        self.context_augmenter = ContextAugmenter(llm_client)
        logger.info("上下文增强器已初始化")
        
        # 初始化目标规划器
        self.goal_planner = GoalPlanner(llm_client, tool_registry)
        self.goal_tracker = GoalTracker()
        self.current_goal_plan: Optional[GoalPlan] = None
        logger.info("目标规划器已初始化")
        
        # 初始化元认知评估器
        self.enable_metacognition = metacognition_config is not None
        self.metacognition: Optional[IMetacognitionEvaluator] = None
        
        if self.enable_metacognition:
            self.metacognition = MetacognitionFactory.create_evaluator(
                config=metacognition_config,
                tool_registry=tool_registry,
                memory=memory,
                api_client=None,
                llm_client=llm_client
            )
            logger.info_ctx(
                "元认知评估器已初始化",
                extra_data={
                    "evaluator_type": metacognition_config.get("type"),
                    "clarification_threshold": metacognition_config.get("clarification_threshold", "medium"),
                    "has_tool_registry": tool_registry is not None,
                    "has_memory": memory is not None,
                    "has_llm_client": llm_client is not None
                }
            )
        else:
            logger.info("元认知评估器未启用")
        
        # 加载已知英雄列表到上下文增强器
        self._load_known_heroes_to_augmenter()

        # 初始化并行执行组件
        from core.parallel_execution_config import ParallelExecutionConfig
        from core.dependency_analyzer import DependencyAnalyzer
        from core.parallel_executor import ParallelExecutor

        self.parallel_config = ParallelExecutionConfig()
        self.dependency_analyzer = DependencyAnalyzer()
        self.parallel_executor = ParallelExecutor(
            tool_registry=tool_registry,
            max_concurrency=self.parallel_config.get_max_concurrency(),
            timeout=self.parallel_config.get_timeout()
        )

        logger.info_ctx(
            "并行执行组件已初始化",
            extra_data={
                "parallel_enabled": self.parallel_config.is_enabled(),
                "max_concurrency": self.parallel_config.get_max_concurrency(),
                "timeout": self.parallel_config.get_timeout()
            }
        )

    def solve(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行完整的 ReAct 循环解决问题（带 Trace 和 Langfuse 支持）

        Args:
            query: 用户查询
            context: 额外上下文信息
            session_id: 会话 ID（可选，用于多轮对话）

        Returns:
            包含最终答案和相关元数据的字典
        """
        trace_ctx = get_current_trace()
        
        # 获取 Langfuse 客户端
        langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None
        
        # 创建 Agent Trace (Langfuse)
        if langfuse_client and langfuse_client.enabled:
            agent_trace = langfuse_client.observation(
                name="react_agent",
                as_type="agent",
                input={"query": query, "context": context},
                metadata={
                    "session_id": session_id,
                    "max_turns": self.max_turns,
                    "start_time": datetime.now().isoformat(),
                    "trace_id": trace_ctx.trace_id if trace_ctx else None
                }
            )
        else:
            agent_trace = NoOpObservation() if NoOpObservation else None
        
        with TraceSpan("agent_solve", parent=trace_ctx) as solve_span:
            # 同时使用 Langfuse Span（如果可用）
            if agent_trace and hasattr(agent_trace, 'span'):
                langfuse_solve_span = agent_trace.span(name="agent_solve_phase")
            else:
                langfuse_solve_span = NoOpObservation() if NoOpObservation else None
            
            logger.info_ctx(
                "开始处理查询",
                session_id=session_id,
                extra_data={
                    "query": query,
                    "context": context,
                    "trace_id": solve_span.trace_id if solve_span else 'N/A',
                    "langfuse_enabled": langfuse_client.enabled if langfuse_client else False
                }
            )
            
            original_query = query
            augmented_context = {}
            
            if session_id and self.conversation_manager:
                session = self.conversation_manager.get_or_create_session(session_id)
                
                augmented = self.context_augmenter.augment_query(query, session)
                
                query = augmented["augmented_query"]
                augmented_context = augmented["context"]
                
                if context:
                    context = self._deep_merge_contexts(context, augmented_context)
                else:
                    context = augmented_context
                
                logger.info_ctx(
                    "上下文增强完成",
                    session_id=session_id,
                    extra_data={
                        "original_query": original_query,
                        "augmented_query": query,
                        "inferred_intent": augmented.get('inferred_intent'),
                        "current_heroes": augmented_context.get('current_heroes'),
                        "current_topic": augmented_context.get('current_topic')
                    }
                )
            
            thought = AgentThought(query=query, context=context or {})
            self.current_thought = thought

            try:
                # 0. 元认知评估（执行前）
                if self.enable_metacognition:
                    with TraceSpan("metacognition_before_execution"):
                        assessment = self.metacognition.assess_before_execution(query, context or {})
                        
                        logger.info_ctx(
                            "元认知执行前评估完成",
                            session_id=session_id,
                            extra_data={
                                "confidence_level": assessment.confidence_level.value,
                                "confidence_score": round(assessment.confidence_score, 3),
                                "knowledge_coverage": round(assessment.knowledge_coverage, 3),
                                "data_quality_score": round(assessment.data_quality_score, 3),
                                "limitations": assessment.limitations,
                                "data_sources": assessment.data_sources,
                                "reasoning": assessment.reasoning
                            }
                        )
                        
                        # 保存评估结果供后续对比
                        pre_assessment = assessment
                        
                        # 如果置信度太低，请求用户澄清
                        if self.metacognition.should_request_clarification(assessment):
                            clarification = self.metacognition.generate_clarification(query, assessment)
                            
                            logger.info_ctx(
                                "元认知请求用户澄清",
                                session_id=session_id,
                                extra_data={
                                    "clarification_type": clarification.type,
                                    "confidence_level": clarification.confidence_level.value,
                                    "missing_info": clarification.missing_info,
                                    "questions": clarification.questions,
                                    "suggestions": clarification.suggestions,
                                    "has_partial_answer": clarification.partial_answer is not None
                                }
                            )
                            
                            thought.set_complete({
                                "answer": {
                                    "message": "我需要更多信息来准确回答您的问题",
                                    "clarification": clarification.to_dict()
                                },
                                "reasoning": thought.reasoning_steps,
                                "actions": thought.actions_taken,
                                "confidence": assessment.confidence_score,
                                "source": "metacognition_clarification",
                                "metacognition_assessment": assessment.to_dict()
                            })
                            
                            response = self._build_response(thought)
                            
                            if session_id and self.conversation_manager:
                                self._save_conversation_history(session_id, original_query, response, augmented_context)
                            
                            return response

                # 1. 目标分解阶段
                logger.info_ctx("开始目标分解", session_id=session_id)
                with TraceSpan("goal_decomposition"):
                    goal_plan = self.goal_planner.plan(query, context)
                self.current_goal_plan = goal_plan
                plan_id = f"plan_{int(time.time())}"
                self.goal_tracker.register_plan(plan_id, goal_plan)
                
                thought.add_reasoning(f"目标分解完成: {goal_plan.main_goal}")
                thought.add_reasoning(f"子目标数量: {len(goal_plan.sub_goals)}")
                
                logger.info_ctx(
                    "目标分解完成",
                    session_id=session_id,
                    extra_data={
                        "main_goal": goal_plan.main_goal,
                        "sub_goals_count": len(goal_plan.sub_goals)
                    }
                )
                
                # 如果只有一个子目标，使用传统 ReAct 循环
                if len(goal_plan.sub_goals) <= 1:
                    logger.info_ctx("单目标查询，使用传统 ReAct 循环", session_id=session_id)
                    return self._execute_single_goal(thought, goal_plan.sub_goals[0] if goal_plan.sub_goals else None, 
                                                     session_id, original_query, augmented_context)
                
                # 2. 多子目标执行阶段
                logger.info_ctx("开始执行多子目标", session_id=session_id)
                
                while not goal_plan.is_complete():
                    sub_goal = goal_plan.get_next_pending_goal()
                    if not sub_goal:
                        logger.warning_ctx("没有待执行的子目标，但计划未完成", session_id=session_id)
                        break
                    
                    logger.info_ctx(
                        "开始执行子目标",
                        session_id=session_id,
                        extra_data={
                            "sub_goal_id": sub_goal.id,
                            "description": sub_goal.description,
                            "tool_name": sub_goal.tool_name
                        }
                    )
                    
                    # 更新状态为执行中
                    sub_goal.status = GoalStatus.IN_PROGRESS
                    self.goal_tracker.update_goal_status(plan_id, sub_goal.id, GoalStatus.IN_PROGRESS)
                    
                    # 为子目标创建临时的 AgentThought
                    sub_thought = AgentThought(
                        query=f"{sub_goal.description} (来自: {goal_plan.main_goal})",
                        context={
                            **(context or {}),
                            "sub_goal_id": sub_goal.id,
                            "main_goal": goal_plan.main_goal,
                            "goal_plan": goal_plan.to_dict()
                        }
                    )
                    
                    # 执行子目标（带 Trace）
                    with TraceSpan(f"sub_goal_{sub_goal.id}"):
                        success = self._execute_sub_goal(sub_thought, sub_goal)
                    
                    if success:
                        sub_goal.status = GoalStatus.COMPLETED
                        sub_goal.result = sub_thought.final_answer
                        self.goal_tracker.update_goal_status(
                            plan_id, sub_goal.id, GoalStatus.COMPLETED, result=sub_thought.final_answer
                        )
                        logger.info_ctx("子目标完成", session_id=session_id, extra_data={"sub_goal_id": sub_goal.id})
                    else:
                        sub_goal.status = GoalStatus.FAILED
                        sub_goal.error = sub_thought.error
                        self.goal_tracker.update_goal_status(
                            plan_id, sub_goal.id, GoalStatus.FAILED, error=sub_thought.error
                        )
                        logger.error_ctx(
                            "子目标失败",
                            session_id=session_id,
                            extra_data={"sub_goal_id": sub_goal.id, "error": sub_thought.error}
                        )
                    
                    # 将子目标结果添加到主 thought
                    thought.add_observation({
                        "sub_goal_id": sub_goal.id,
                        "description": sub_goal.description,
                        "status": sub_goal.status.value,
                        "result": sub_goal.result,
                        "error": sub_goal.error
                    })
                    
                    # 更新进度
                    progress = goal_plan.get_progress()
                    logger.info_ctx(
                        "子目标执行进度",
                        session_id=session_id,
                        extra_data={
                            "completed": progress['completed'],
                            "total": progress['total'],
                            "percentage": progress['percentage']
                        }
                    )
                
                # 3. 合并结果
                logger.info_ctx("开始合并子目标结果", session_id=session_id)
                with TraceSpan("merge_results"):
                    final_answer = self._merge_sub_goal_results(goal_plan)
                
                # 元认知评估（执行后）
                if self.enable_metacognition:
                    with TraceSpan("metacognition_after_execution"):
                        post_assessment = self.metacognition.assess_after_execution(
                            query=original_query,
                            final_result=final_answer,
                            context=context or {}
                        )
                        
                        logger.info_ctx(
                            "元认知执行后评估完成",
                            session_id=session_id,
                            extra_data={
                                "pre_confidence": pre_assessment.confidence_score if 'pre_assessment' in locals() else 'N/A',
                                "post_confidence": post_assessment.confidence_score,
                                "confidence_delta": round(
                                    post_assessment.confidence_score - (pre_assessment.confidence_score if 'pre_assessment' in locals() else 0),
                                    3
                                ),
                                "confidence_level": post_assessment.confidence_level.value,
                                "final_quality": "high" if post_assessment.confidence_score >= 0.7 else "low",
                                "knowledge_coverage": round(post_assessment.knowledge_coverage, 3),
                                "data_quality_score": round(post_assessment.data_quality_score, 3),
                                "limitations": post_assessment.limitations
                            }
                        )
                        
                        # 添加元认知评估到最终结果
                        if isinstance(final_answer, dict):
                            final_answer["metacognition_assessment"] = post_assessment.to_dict()
                            final_answer["confidence"] = post_assessment.confidence_score
                
                thought.set_complete(final_answer)
                
                response = self._build_response(thought)
                
                if session_id and self.conversation_manager:
                    self._save_conversation_history(session_id, original_query, response, augmented_context)
                
                logger.info_ctx(
                    "查询处理完成",
                    session_id=session_id,
                    extra_data={
                        "state": response.get('state'),
                        "success": response.get('success'),
                        "turn_count": response.get('turn_count'),
                        "duration": response.get('duration')
                    }
                )
                
                return response

            except Exception as e:
                error_msg = f"查询处理失败: {str(e)}"
                logger.error_ctx(
                    error_msg,
                    session_id=session_id,
                    extra_data={"error": str(e), "traceback": traceback.format_exc()}
                )
                thought.set_failed(error_msg)
                
                if session_id and self.conversation_manager:
                    error_response = {
                        "success": False,
                        "error": str(e),
                        "state": AgentState.FAILED.value,
                        "turn_count": thought.turn_count
                    }
                    self._save_conversation_history(session_id, original_query, error_response, augmented_context)
                
                return self._build_response(thought)

    def _think(self, thought: AgentThought) -> None:
        """Think 步骤 - 理解问题和意图

        使用 LLM 智能分析用户查询，选择合适的工具并提取参数
        """
        thought.state = AgentState.THINKING

        # 理解查询意图
        thought.add_reasoning(f"分析用户查询：{thought.query}")

        # 使用 LLM 智能选择工具
        try:
            start_time = time.time()
            logger.info_ctx("调用 LLM 工具选择器", session_id=thought.context.get('session_id'))
            tool_plan = self.tool_selector.select_tools(
                query=thought.query,
                context=thought.context
            )
            selection_time = time.time() - start_time
            thought.context['tool_plan'] = tool_plan
            thought.add_reasoning(f"LLM 选择工具：{[t.tool_name for t in tool_plan.tools]}")
            thought.add_reasoning(f"选择理由：{tool_plan.reasoning}")
            logger.info_ctx(
                "LLM 工具选择完成",
                session_id=thought.context.get('session_id'),
                extra_data={
                    "selected_tools": [t.tool_name for t in tool_plan.tools],
                    "reasoning": tool_plan.reasoning,
                    "selection_time_ms": round(selection_time * 1000, 2)
                }
            )
        except Exception as e:
            error_msg = f"LLM 工具选择失败：{str(e)}"
            logger.error_ctx(
                error_msg,
                session_id=thought.context.get('session_id'),
                extra_data={"error": str(e)}
            )
            thought.set_failed(error_msg)
            return

        # 从记忆中检索相关上下文（如果启用）
        if self.enable_memory:
            relevant_context = self.memory.get_relevant_context(thought.query, limit=3)
            if relevant_context:
                thought.add_reasoning(f"从记忆中检索到 {len(relevant_context)} 条相关上下文")
                thought.context['memory_context'] = relevant_context
                logger.info_ctx(
                    "从记忆中检索到相关上下文",
                    session_id=thought.context.get('session_id'),
                    extra_data={"context_count": len(relevant_context)}
                )

    def _plan(self, thought: AgentThought) -> None:
        """Plan 步骤 - 制定行动计划

        使用 LLM 生成的工具计划，制定执行方案
        """
        thought.state = AgentState.PLANNING

        # 获取 LLM 生成的工具计划
        tool_plan = thought.context.get('tool_plan')
        if not tool_plan:
            error_msg = "工具计划缺失，无法制定执行计划"
            logger.error_ctx(error_msg, session_id=thought.context.get('session_id'))
            thought.set_failed(error_msg)
            return

        # 设置计划执行的工具
        planned_tools = [t.tool_name for t in tool_plan.tools]
        thought.context['planned_tools'] = planned_tools

        # 保存每个工具对应的参数
        thought.context['tool_params'] = {
            t.tool_name: t.parameters for t in tool_plan.tools
        }

        thought.add_reasoning(f"计划执行工具：{planned_tools}")
        logger.info_ctx(
            "制定执行计划",
            session_id=thought.context.get('session_id'),
            extra_data={
                "planned_tools": planned_tools,
                "tool_params": thought.context['tool_params']
            }
        )

        # 如果 LLM 返回空工具列表，说明不需要调用工具，直接用 LLM 回答
        if not planned_tools:
            logger.info_ctx("空工具列表，标记为直接回答模式", session_id=thought.context.get('session_id'))
            thought.context['direct_answer_mode'] = True

    def _execute(self, thought: AgentThought) -> None:
        """Execute 步骤 - 执行工具调用

        使用 LLM 提取的参数执行工具调用
        """
        thought.state = AgentState.ACTING

        planned_tools = thought.context.get('planned_tools', [])
        tool_params = thought.context.get('tool_params', {})
        session_id = thought.context.get('session_id')

        logger.info_ctx(
            "开始执行工具",
            session_id=session_id,
            extra_data={"planned_tools": planned_tools}
        )

        # 执行工具调用
        for tool_name in planned_tools:
            # 使用 LLM 提取的参数
            params = tool_params.get(tool_name, {})

            tool = self.tool_registry.get(tool_name)
            if tool:
                start_time = time.time()
                try:
                    thought.add_reasoning(f"执行工具：{tool_name}")
                    logger.info_ctx(
                        f"执行工具: {tool_name}",
                        session_id=session_id,
                        extra_data={"params": params}
                    )
                    result = self.tool_registry.execute(tool_name, **params)
                    execution_time = time.time() - start_time
                    thought.add_action(tool_name, params, result)

                    logger.info_ctx(
                        "工具执行完成",
                        session_id=session_id,
                        extra_data={
                            "tool_name": tool_name,
                            "execution_time_ms": round(execution_time * 1000, 2),
                            "success": result.is_success()
                        }
                    )

                    if result.is_success():
                        thought.add_observation(result.data)
                        logger.info_ctx(
                            "工具执行成功",
                            session_id=session_id,
                            extra_data={
                                "tool_name": tool_name,
                                "result_data": result.data
                            }
                        )
                        # 如果工具执行成功且有结果，可以考虑完成
                        if self._has_sufficient_data(thought):
                            logger.info_ctx("已收集足够数据，准备合成结果", session_id=session_id)
                            self._synthesize(thought)
                            return
                    else:
                        thought.add_reasoning(f"工具 {tool_name} 执行失败：{result.error}")
                        logger.error_ctx(
                            "工具执行失败",
                            session_id=session_id,
                            extra_data={"tool_name": tool_name, "error": result.error}
                        )

                except Exception as e:
                    execution_time = time.time() - start_time
                    thought.add_reasoning(f"工具 {tool_name} 执行异常：{str(e)}")
                    thought.add_action(tool_name, params, None)
                    logger.error_ctx(
                        "工具执行异常",
                        session_id=session_id,
                        extra_data={
                            "tool_name": tool_name,
                            "execution_time_ms": round(execution_time * 1000, 2),
                            "error": str(e),
                            "traceback": traceback.format_exc()
                        }
                    )

        # 检查是否有有效的观察结果（非空数据）
        has_valid_data = False
        for obs in thought.observations:
            if isinstance(obs, dict) and len(obs) > 0:
                has_valid_data = True
                break
            elif isinstance(obs, list) and len(obs) > 0:
                has_valid_data = True
                break
            elif obs is not None and obs != "":
                has_valid_data = True
                break
        
        if not has_valid_data:
            thought.add_reasoning("工具返回空数据，使用 LLM 直接回答作为 fallback")
            logger.warning_ctx("工具返回空数据，启用 LLM fallback", session_id=session_id)
            
            try:
                fallback_response = self._llm_fallback_answer(thought)
                if fallback_response:
                    thought.add_observation({"llm_fallback_answer": fallback_response})
                    thought.add_reasoning("LLM fallback 回答成功")
                    logger.info_ctx("LLM fallback 回答成功", session_id=session_id)
            except Exception as e:
                logger.error_ctx(f"LLM fallback 失败: {e}", session_id=session_id)

    async def _execute_async(self, thought: AgentThought) -> None:
        """Execute 步骤 - 异步执行工具调用（支持并行执行）

        使用 asyncio 并行执行工具调用，提升性能
        """
        import asyncio

        thought.state = AgentState.ACTING

        planned_tools = thought.context.get('planned_tools', [])
        tool_params = thought.context.get('tool_params', {})
        session_id = thought.context.get('session_id')

        logger.info_ctx(
            "开始异步执行工具",
            session_id=session_id,
            extra_data={
                "planned_tools": planned_tools,
                "parallel_enabled": self.parallel_config.is_enabled()
            }
        )

        # 检查是否启用并行执行
        if not self.parallel_config.is_enabled():
            # 降级到同步执行
            logger.info_ctx("并行执行未启用，降级到同步执行", session_id=session_id)
            self._execute(thought)
            return

        # 分析工具依赖关系
        dependencies = self.dependency_analyzer.analyze_dependencies(planned_tools, tool_params)

        # 获取并行分组
        parallel_groups = self.dependency_analyzer.get_parallel_groups(planned_tools, dependencies)

        logger.info_ctx(
            "工具依赖分析完成",
            session_id=session_id,
            extra_data={
                "dependencies": dependencies,
                "parallel_groups": parallel_groups,
                "group_count": len(parallel_groups)
            }
        )

        # 按组顺序执行
        for group_index, group in enumerate(parallel_groups):
            logger.info_ctx(
                f"开始执行第 {group_index + 1} 组工具",
                session_id=session_id,
                extra_data={"group": group, "group_index": group_index}
            )

            # 并行执行当前组的工具
            results = await self.parallel_executor.execute_parallel(group, tool_params)

            # 处理执行结果
            for tool_name, result in results.items():
                params = tool_params.get(tool_name, {})

                if isinstance(result, Exception):
                    # 工具执行失败
                    thought.add_reasoning(f"工具 {tool_name} 执行失败：{str(result)}")
                    thought.add_action(tool_name, params, None)
                    logger.error_ctx(
                        "工具执行失败",
                        session_id=session_id,
                        extra_data={"tool_name": tool_name, "error": str(result)}
                    )
                else:
                    # 工具执行成功
                    thought.add_reasoning(f"执行工具：{tool_name}")
                    thought.add_action(tool_name, params, result)

                    logger.info_ctx(
                        "工具执行完成",
                        session_id=session_id,
                        extra_data={
                            "tool_name": tool_name,
                            "execution_time_ms": round(result.execution_time * 1000, 2),
                            "success": result.is_success()
                        }
                    )

                    if result.is_success():
                        thought.add_observation(result.data)
                        logger.info_ctx(
                            "工具执行成功",
                            session_id=session_id,
                            extra_data={
                                "tool_name": tool_name,
                                "result_data": result.data
                            }
                        )
                    else:
                        thought.add_reasoning(f"工具 {tool_name} 执行失败：{result.error}")
                        logger.error_ctx(
                            "工具执行失败",
                            session_id=session_id,
                            extra_data={"tool_name": tool_name, "error": result.error}
                        )

            # 如果当前组执行后有足够数据，提前完成
            if self._has_sufficient_data(thought):
                logger.info_ctx("已收集足够数据，准备合成结果", session_id=session_id)
                self._synthesize(thought)
                return

        # 检查是否有有效的观察结果
        has_valid_data = False
        for obs in thought.observations:
            if isinstance(obs, dict) and len(obs) > 0:
                has_valid_data = True
                break
            elif isinstance(obs, list) and len(obs) > 0:
                has_valid_data = True
                break
            elif obs is not None and obs != "":
                has_valid_data = True
                break

        if not has_valid_data:
            thought.add_reasoning("工具返回空数据，使用 LLM 直接回答作为 fallback")
            logger.warning_ctx("工具返回空数据，启用 LLM fallback", session_id=session_id)

            try:
                fallback_response = self._llm_fallback_answer(thought)
                if fallback_response:
                    thought.add_observation({"llm_fallback_answer": fallback_response})
                    thought.add_reasoning("LLM fallback 回答成功")
                    logger.info_ctx("LLM fallback 回答成功", session_id=session_id)
            except Exception as e:
                logger.error_ctx(f"LLM fallback 失败: {e}", session_id=session_id)


    def _llm_fallback_answer(self, thought: AgentThought, query_type: str = "dota_query") -> Optional[str]:
        """LLM fallback 回答
        
        当工具执行失败时，直接使用 LLM 的知识回答问题
        
        Args:
            thought: Agent 思考状态
            query_type: 查询类型（"general_chat" 或 "dota_query"）
            
        Returns:
            LLM 回答内容
        """
        query = thought.query or thought.context.get('query', '')
        session_id = thought.context.get('session_id')
        
        # 根据查询类型使用不同的 prompt
        if query_type == "general_chat":
            fallback_prompt = f"""你是一个 Dota 2 游戏助手，同时也是一个通用的 AI 助手。请直接回答用户的问题。

用户问题：{query}

请提供友好、专业、详细的回答。如果问题涉及 Dota 2，请结合你的游戏知识给出建议；如果是通用问题，请给出通用的回答。"""
        else:
            fallback_prompt = f"""你是一个 Dota 2 游戏专家助手。由于数据 API 暂时不可用，请直接根据你的游戏知识回答用户问题。

用户问题：{query}

请提供专业、详细的回答，包括：
1. 直接回答用户的核心问题
2. 给出合理的理由和分析
3. 如果涉及英雄推荐，说明推荐理由和战术思路

注意：这是基于游戏知识的回答，不是基于实时数据的分析。"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": fallback_prompt}],
                temperature=0.7,
                max_tokens=1024
            )
            
            if "error" in response:
                logger.error_ctx(f"LLM fallback 调用失败: {response['error']}", session_id=session_id)
                return None
            
            content = response['choices'][0]['message']['content']
            return content
            
        except Exception as e:
            logger.error_ctx(f"LLM fallback 异常: {e}", session_id=session_id)
            return None
    
    def _llm_fallback_with_search(self, thought: AgentThought) -> Optional[str]:
        """LLM Fallback + 搜索增强
        
        当数据不可用时，先尝试搜索获取最新信息，再使用 LLM 回答
        
        Args:
            thought: Agent 思考状态
            
        Returns:
            LLM 回答内容
        """
        query = thought.query or thought.context.get('query', '')
        session_id = thought.context.get('session_id')
        
        search_context = ""
        
        try:
            from tools.search_tools import DuckDuckGoSearchTool
            search_tool = DuckDuckGoSearchTool()
            
            search_result = search_tool.execute(query=query, max_results=3)
            
            if search_result.success and search_result.data.get("results"):
                results = search_result.data.get("results", [])
                search_context = "\n\n以下是搜索到的相关信息：\n"
                for i, r in enumerate(results, 1):
                    search_context += f"{i}. {r.get('title', '')}\n"
                    search_context += f"   {r.get('snippet', '')[:200]}...\n"
                
                logger.info_ctx(f"搜索增强成功，获取 {len(results)} 条结果", session_id=session_id)
                
        except ImportError:
            logger.warning_ctx("搜索工具未安装，使用纯 LLM 知识回答", session_id=session_id)
        except Exception as e:
            logger.warning_ctx(f"搜索失败: {e}, 使用纯 LLM 知识回答", session_id=session_id)
        
        fallback_prompt = f"""你是一个 Dota 2 游戏专家助手。由于数据 API 暂时不可用，请根据你的游戏知识回答用户问题。
{search_context}
用户问题：{query}

请提供专业、详细的回答，包括：
1. 直接回答用户的核心问题
2. 给出合理的理由和分析
3. 如果涉及英雄推荐，说明推荐理由和战术思路

注意：这是基于游戏知识和搜索信息的回答，不是基于实时数据的分析。"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": fallback_prompt}],
                temperature=0.7,
                max_tokens=1024
            )
            
            if "error" in response:
                logger.error_ctx(f"LLM fallback 调用失败: {response['error']}", session_id=session_id)
                return None
            
            content = response['choices'][0]['message']['content']
            return content
            
        except Exception as e:
            logger.error_ctx(f"LLM fallback 异常: {e}", session_id=session_id)
            return None

    def _observe(self, thought: AgentThought) -> None:
        """Observe 步骤 - 观察和分析结果

        分析工具执行结果，提取关键信息
        """
        thought.state = AgentState.OBSERVING
        session_id = thought.context.get('session_id')

        if thought.observations:
            thought.add_reasoning(f"收集到 {len(thought.observations)} 条观察结果")
            logger.info_ctx(
                "收集到观察结果",
                session_id=session_id,
                extra_data={"observation_count": len(thought.observations)}
            )

            # 分析观察结果
            for i, obs in enumerate(thought.observations):
                if isinstance(obs, dict):
                    thought.add_reasoning(f"观察结果 {i+1}: 包含 {len(obs)} 个字段")
                elif isinstance(obs, list):
                    thought.add_reasoning(f"观察结果 {i+1}: 包含 {len(obs)} 项")
        else:
            logger.warning_ctx("没有收集到观察结果", session_id=session_id)

    def _reflect(self, thought: AgentThought) -> None:
        """Reflect 步骤 - 反思和评估

        评估当前结果质量，决定是否需要继续循环
        """
        try:
            thought.state = AgentState.REFLECTING
            session_id = thought.context.get('session_id')

            # 评估结果质量
            quality_score = self._evaluate_result_quality(thought)
            thought.add_reflection(f"结果质量评分：{quality_score:.2f}/1.00")
            logger.info_ctx(
                "结果质量评估完成",
                session_id=session_id,
                extra_data={"quality_score": quality_score}
            )

            # 检查是否需要更多行动
            if quality_score < 0.6 and thought.turn_count < self.max_turns:
                thought.add_reflection("结果质量不足，需要更多行动")
                logger.info_ctx("结果质量不足，调整策略", session_id=session_id)
                # 调整策略
                self._adjust_strategy(thought)
            else:
                thought.add_reflection("结果质量可接受，准备结束")
                logger.info_ctx("结果质量可接受，准备合成结果", session_id=session_id)
                self._synthesize(thought)
        except Exception as e:
            logger.error_ctx(
                f"Reflect 步骤失败: {e}",
                session_id=thought.context.get('session_id'),
                extra_data={"error": str(e), "traceback": traceback.format_exc()}
            )
            # 如果 reflect 失败，尝试直接合成结果
            try:
                self._synthesize(thought)
            except Exception as synthesize_error:
                logger.error_ctx(
                    f"Synthesize 也失败了: {synthesize_error}",
                    session_id=thought.context.get('session_id'),
                    extra_data={"error": str(synthesize_error)}
                )
                thought.set_failed(f"Reflect 步骤失败: {str(e)}")

    def _synthesize(self, thought: AgentThought) -> None:
        """Synthesize 步骤 - 综合决策

        综合所有观察和推理，形成最终答案
        """
        session_id = thought.context.get('session_id')
        
        # 直接回答模式：不需要调用工具，直接用 LLM 回答用户问题
        if thought.context.get('direct_answer_mode'):
            logger.info_ctx("直接回答模式，使用 LLM 生成答案", session_id=session_id)
            try:
                llm_response = self._generate_direct_answer(thought.query, thought)
                thought.set_complete({
                    "answer": {"message": llm_response},
                    "reasoning": thought.reasoning_steps,
                    "actions": thought.actions_taken,
                    "confidence": 0.8,
                    "source": "llm_direct"
                })
                logger.info_ctx("LLM 直接回答生成成功", session_id=session_id)
            except Exception as e:
                logger.error_ctx(
                    f"LLM 直接回答失败: {e}",
                    session_id=session_id,
                    extra_data={"error": str(e)}
                )
                thought.set_complete({
                    "answer": {"message": f"抱歉，我无法回答这个问题：{str(e)}"},
                    "reasoning": thought.reasoning_steps,
                    "actions": thought.actions_taken,
                    "confidence": 0.0,
                    "source": "error"
                })
        elif thought.observations:
            # 检查是否是 LLM fallback 回答
            llm_fallback = None
            for obs in thought.observations:
                if isinstance(obs, dict) and "llm_fallback_answer" in obs:
                    llm_fallback = obs["llm_fallback_answer"]
                    break
            
            if llm_fallback:
                # 使用 LLM fallback 回答
                thought.set_complete({
                    "answer": {"message": llm_fallback},
                    "reasoning": thought.reasoning_steps,
                    "actions": thought.actions_taken,
                    "confidence": 0.7,
                    "source": "llm_fallback"
                })
                logger.info_ctx("使用 LLM fallback 回答", session_id=session_id)
            else:
                # 检查是否是阵容分析结果，需要生成推荐答案
                composition_analysis = None
                for obs in thought.observations:
                    if isinstance(obs, dict) and self._is_composition_analysis(obs):
                        composition_analysis = obs
                        break
                
                if composition_analysis and self._should_generate_recommendation(thought.query):
                    # 基于阵容分析结果生成推荐英雄答案
                    logger.info_ctx("检测到阵容分析结果，生成推荐答案", session_id=session_id)
                    try:
                        recommendation = self._generate_hero_recommendation(
                            thought.query, 
                            composition_analysis, 
                            thought.context
                        )
                        thought.set_complete({
                            "answer": {"message": recommendation},
                            "reasoning": thought.reasoning_steps,
                            "actions": thought.actions_taken,
                            "confidence": 0.8,
                            "source": "hero_recommendation"
                        })
                        logger.info_ctx("推荐英雄答案生成成功", session_id=session_id)
                    except Exception as e:
                        logger.error_ctx(
                            f"推荐英雄答案生成失败: {e}",
                            session_id=session_id,
                            extra_data={"error": str(e)}
                        )
                        # 失败时使用合并的观察结果
                        final_data = self._merge_observations(thought.observations)
                        thought.set_complete({
                            "answer": final_data,
                            "reasoning": thought.reasoning_steps,
                            "actions": thought.actions_taken,
                            "confidence": self._evaluate_result_quality(thought)
                        })
                else:
                    # 合并所有观察结果
                    final_data = self._merge_observations(thought.observations)
                    thought.set_complete({
                        "answer": final_data,
                        "reasoning": thought.reasoning_steps,
                        "actions": thought.actions_taken,
                        "confidence": self._evaluate_result_quality(thought)
                    })
                    logger.info_ctx("观察结果合并完成", session_id=session_id)
        else:
            thought.set_complete({
                "answer": {"message": "无法获取有效数据"},
                "reasoning": thought.reasoning_steps,
                "actions": thought.actions_taken,
                "confidence": 0.0
            })
            logger.warning_ctx("无法获取有效数据", session_id=session_id)

    def _generate_direct_answer(self, query: str, thought: AgentThought) -> str:
        """使用 LLM 直接回答用户问题（不需要工具调用）

        Args:
            query: 用户查询
            thought: 当前思考状态

        Returns:
            str: LLM 生成的答案
        """
        system_prompt = """你是一个 Dota 2 游戏助手。请根据用户的问题直接回答，不需要调用工具。
回答要求：
1. 简洁明了，直接回答问题
2. 如果涉及游戏知识，给出合理的解释
3. 如果不确定，诚实地说明"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]

        response = self.llm_client.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )

        if "error" in response:
            raise Exception(response["error"])

        return response['choices'][0]['message']['content']

    def _is_composition_analysis(self, observation: Dict[str, Any]) -> bool:
        """检查观察结果是否是阵容分析结果
        
        Args:
            observation: 观察结果
            
        Returns:
            bool: 是否是阵容分析结果
        """
        composition_keys = {'our_advantages', 'enemy_advantages', 'overall_advantage', 'conclusion'}
        return isinstance(observation, dict) and any(key in observation for key in composition_keys)

    def _should_generate_recommendation(self, query: str) -> bool:
        """检查查询是否需要生成推荐答案
        
        Args:
            query: 用户查询
            
        Returns:
            bool: 是否需要生成推荐答案
        """
        recommendation_keywords = ['推荐', '建议', '选什么', '用什么', '适合']
        return any(keyword in query for keyword in recommendation_keywords)

    def _generate_hero_recommendation(
        self, 
        query: str, 
        composition_analysis: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> str:
        """基于阵容分析结果生成推荐英雄答案
        
        Args:
            query: 用户查询
            composition_analysis: 阵容分析结果
            context: 上下文信息
            
        Returns:
            str: 推荐英雄答案
        """
        session_id = context.get('session_id')
        
        # 提取阵容信息
        our_heroes = context.get('our_heroes', [])
        enemy_heroes = context.get('enemy_heroes', [])
        
        # 构造推荐提示
        system_prompt = """你是一个 Dota 2 游戏专家助手。根据阵容分析结果，为用户推荐合适的英雄。

推荐要求：
1. 基于阵容分析结果（优势、劣势、整体评估）
2. 考虑我方已有英雄的协同性和阵容平衡
3. 如果有敌方英雄，考虑克制关系
4. 如果有强势英雄列表，优先推荐强势英雄中适合的英雄
5. 给出明确的推荐英雄和理由
6. 理由要简洁明了，包含：
   - 为什么推荐这个英雄（协同性、克制性、补位需求、强势程度等）
   - 这个英雄如何弥补阵容短板
   - 这个英雄如何增强阵容优势"""

        # 提取强势英雄列表（如果有）
        meta_heroes = context.get('meta_heroes', [])
        meta_heroes_info = ""
        if meta_heroes and len(meta_heroes) > 0:
            # 只显示前10个强势英雄，避免信息过长
            top_meta_heroes = meta_heroes[:10]
            meta_heroes_names = [h.get('hero_name', '未知') for h in top_meta_heroes]
            meta_heroes_info = f"\n当前版本强势英雄（前10）：{', '.join(meta_heroes_names)}"

        # 构造用户消息
        user_message = f"""用户查询：{query}

我方英雄：{', '.join(our_heroes) if our_heroes else '未提供'}
敌方英雄：{', '.join(enemy_heroes) if enemy_heroes else '未提供'}
{meta_heroes_info}

阵容分析结果：
- 我方优势：{composition_analysis.get('our_advantages', [])}
- 敌方优势：{composition_analysis.get('enemy_advantages', [])}
- 整体评估：{composition_analysis.get('overall_advantage', 0)}
- 结论：{composition_analysis.get('conclusion', '未分析')}

请基于以上信息，推荐合适的英雄并给出理由。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        try:
            response = self.llm_client.chat(
                messages=messages,
                temperature=0.7,
                max_tokens=1024
            )

            if "error" in response:
                logger.error_ctx(
                    f"LLM 推荐生成失败: {response['error']}",
                    session_id=session_id
                )
                raise Exception(response["error"])

            recommendation = response['choices'][0]['message']['content']
            logger.info_ctx(
                "推荐英雄答案生成成功",
                session_id=session_id,
                extra_data={"recommendation_length": len(recommendation)}
            )
            return recommendation

        except Exception as e:
            logger.error_ctx(
                f"推荐英雄答案生成异常: {e}",
                session_id=session_id,
                extra_data={"error": str(e)}
            )
            raise

    def _finalize(self, thought: AgentThought) -> None:
        """Finalize 步骤 - 强制结束

        当达到最大轮数或其他原因需要结束时调用
        """
        thought.add_reasoning(f"达到最大轮数 ({self.max_turns}) 或满足结束条件")
        self._synthesize(thought)

    def _build_response(self, thought: AgentThought) -> Dict[str, Any]:
        """构建最终响应"""
        response = {
            "query": thought.query,
            "context": thought.context,
            "state": thought.state.value,
            "turn_count": thought.turn_count,
            "duration": thought.get_duration(),
            "reasoning": thought.reasoning_steps,
            "actions": thought.actions_taken,
            "reflections": thought.reflections if self.enable_reflection else []
        }

        if thought.state == AgentState.COMPLETE:
            response["answer"] = thought.final_answer
            response["success"] = True
        else:
            response["error"] = thought.error or "未能完成查询"
            response["success"] = False

        # 保存到记忆（如果启用）
        if self.enable_memory and thought.state == AgentState.COMPLETE:
            self._save_to_memory(thought)

        return response

    def _has_sufficient_data(self, thought: AgentThought) -> bool:
        """检查是否已收集足够数据"""
        if not thought.observations:
            return False

        valid_keys = {
            'recommendations', 'answer', 'meta_heroes', 'matchups',
            'hero_info', 'items', 'skills', 'talents', 'composition',
            'counter_picks', 'result'
        }

        for obs in thought.observations:
            if isinstance(obs, dict):
                if any(key in obs for key in valid_keys):
                    return True
                if len(obs) > 0:
                    return True
            elif isinstance(obs, list) and len(obs) > 0:
                return True
            elif obs is not None:
                return True

        return False

    def _merge_observations(self, observations: List[Any]) -> Dict[str, Any]:
        """合并观察结果"""
        merged = {
            "recommendations": [],
            "data_sources": []
        }

        for obs in observations:
            if isinstance(obs, dict):
                if 'recommendations' in obs:
                    merged['recommendations'].extend(obs['recommendations'])
                merged['data_sources'].append(obs)
            elif isinstance(obs, list):
                # 处理直接返回列表的情况（如 analyze_matchups 的返回）
                if len(obs) > 0 and isinstance(obs[0], dict):
                    # 检查是否是英雄推荐格式
                    if 'hero_name' in obs[0] or 'hero_id' in obs[0]:
                        merged['recommendations'].extend(obs)
                    else:
                        merged['data_sources'].extend(obs)
                else:
                    merged['raw_data'] = obs
            else:
                merged['raw_data'] = obs

        logger.info_ctx(
            "观察结果合并完成",
            session_id=None,
            extra_data={
                "recommendations_count": len(merged['recommendations']),
                "data_sources_count": len(merged['data_sources'])
            }
        )
        return merged

    def _evaluate_result_quality(self, thought: AgentThought) -> float:
        """评估结果质量（0-1 之间）"""
        score = 0.0

        # 基于观察结果数量
        if thought.observations:
            score += min(0.4, len(thought.observations) * 0.1)

        # 基于行动执行成功数
        successful_actions = sum(
            1 for action in thought.actions_taken
            if action.get('result', {}).get('status') == 'success'
        )
        if thought.actions_taken:
            score += min(0.4, (successful_actions / len(thought.actions_taken)) * 0.4)

        # 基于推理深度
        if thought.reasoning_steps:
            score += min(0.2, len(thought.reasoning_steps) * 0.05)

        return min(1.0, score)

    def _adjust_strategy(self, thought: AgentThought) -> None:
        """调整策略（增强版）
        
        根据反思评估结果智能调整：
        1. 分析低分维度
        2. 选择替代工具
        3. 调整工具参数
        4. 利用历史经验
        5. 记录调整决策
        """
        session_id = thought.context.get('session_id')
        
        # 1. 执行完整反思评估
        reflection_result = self._full_reflection_evaluation(thought)
        
        # 2. 根据反思结果调整
        if reflection_result is None:
            # 降级方案
            thought.add_reasoning("反思评估失败，使用默认调整策略")
            self._default_strategy_adjustment(thought)
            return
        
        # 3. 记录反思结果
        thought.add_reflection(f"反思结果：{reflection_result.action.value}")
        thought.add_reflection(f"总体评分：{reflection_result.overall_score:.2f}")
        thought.add_reflection(f"策略调整：{reflection_result.strategy_adjustments}")
        
        logger.info_ctx(
            "反思评估完成，开始策略调整",
            session_id=session_id,
            extra_data={
                "action": reflection_result.action.value,
                "overall_score": reflection_result.overall_score,
                "strategy_adjustments": reflection_result.strategy_adjustments,
                "missing_information": reflection_result.missing_information
            }
        )
        
        # 4. 根据行动类型调整
        if reflection_result.action == ReflectionAction.ADJUST_STRATEGY:
            self._apply_strategy_adjustments(thought, reflection_result)
        elif reflection_result.action == ReflectionAction.CONTINUE:
            self._continue_with_more_data(thought, reflection_result)
        elif reflection_result.action == ReflectionAction.REQUEST_CLARIFICATION:
            self._request_user_clarification(thought, reflection_result)
        elif reflection_result.action == ReflectionAction.FINALIZE:
            self._finalize_with_current_results(thought)

    def _full_reflection_evaluation(self, thought: AgentThought) -> Optional[ReflectionResult]:
        """执行完整的反思评估
        
        使用 ReflectionEvaluator 进行多维度评估
        """
        try:
            # 检查是否已初始化反思评估器
            if not hasattr(self, 'reflection_evaluator'):
                self.reflection_evaluator = ReflectionEvaluator()
            
            # 执行评估
            reflection_result = self.reflection_evaluator.evaluate(
                query=thought.query,
                observations=thought.observations,
                actions=thought.actions_taken,
                context=thought.context
            )
            
            return reflection_result
            
        except Exception as e:
            logger.error_ctx(
                f"反思评估失败：{e}",
                session_id=thought.context.get('session_id'),
                extra_data={"error": str(e)}
            )
            return None

    def _apply_strategy_adjustments(
        self,
        thought: AgentThought,
        reflection_result: ReflectionResult
    ) -> None:
        """应用策略调整建议
        
        根据反思结果的具体建议调整策略
        """
        session_id = thought.context.get('session_id')
        
        # 分析各维度评分
        low_dimensions = [
            ds for ds in reflection_result.dimension_scores
            if ds.score < 0.6
        ]
        
        for dim_score in low_dimensions:
            dimension = dim_score.dimension
            
            # 完整性不足：尝试更多工具
            if dimension == EvaluationDimension.COMPLETENESS:
                thought.add_reasoning("完整性不足，尝试更多工具")
                self._try_additional_tools(thought)
            
            # 一致性不足：检查数据矛盾
            elif dimension == EvaluationDimension.CONSISTENCY:
                thought.add_reasoning("一致性不足，检查数据矛盾")
                self._resolve_data_conflicts(thought)
            
            # 可信度不足：使用更权威数据源
            elif dimension == EvaluationDimension.CREDIBILITY:
                thought.add_reasoning("可信度不足，切换到更权威数据源")
                self._switch_to_reliable_source(thought)
            
            # 相关性不足：调整工具选择
            elif dimension == EvaluationDimension.RELEVANCE:
                thought.add_reasoning("相关性不足，调整工具选择")
                self._select_more_relevant_tools(thought)
            
            # 可操作性不足：提供更详细信息
            elif dimension == EvaluationDimension.ACTIONABILITY:
                thought.add_reasoning("可操作性不足，提供更详细信息")
                self._enhance_actionable_details(thought)
        
        # 应用通用调整建议
        for adjustment in reflection_result.strategy_adjustments:
            thought.add_reasoning(f"应用调整建议：{adjustment}")
            self._apply_single_adjustment(thought, adjustment)
        
        logger.info_ctx(
            "策略调整应用完成",
            session_id=session_id,
            extra_data={
                "low_dimensions": [d.dimension.value for d in low_dimensions],
                "adjustments_applied": len(reflection_result.strategy_adjustments)
            }
        )

    def _try_additional_tools(self, thought: AgentThought) -> None:
        """尝试更多工具
        
        基于当前已用工具，选择未使用的相关工具
        """
        # 获取已使用的工具
        used_tools = set()
        for action in thought.actions_taken:
            used_tools.add(action.get("tool_name"))
        
        # 获取可用工具
        all_tools = self.tool_registry.list_tools()
        available_tools = [t for t in all_tools if t.name not in used_tools]
        
        # 使用 LLM 选择最相关的未使用工具
        if available_tools:
            try:
                tool_plan = self.tool_selector.select_tools(
                    query=thought.query,
                    context={
                        **thought.context,
                        "exclude_tools": list(used_tools)
                    }
                )
                
                # 执行新选择的工具
                for tool_call in tool_plan.tools:
                    if tool_call.tool_name not in used_tools:
                        result = self.tool_registry.execute(
                            tool_call.tool_name,
                            **tool_call.parameters
                        )
                        thought.add_action(tool_call.tool_name, tool_call.parameters, result)
                        thought.add_observation(result.data if result.is_success() else None)
                        
                        logger.info_ctx(
                            f"尝试额外工具：{tool_call.tool_name}",
                            session_id=thought.context.get('session_id'),
                            extra_data={"success": result.is_success()}
                        )
            except Exception as e:
                logger.warning_ctx(
                    f"尝试额外工具失败：{e}",
                    session_id=thought.context.get('session_id')
                )

    def _resolve_data_conflicts(self, thought: AgentThought) -> None:
        """解决数据冲突
        
        检查观察结果中的矛盾信息，尝试解决
        """
        session_id = thought.context.get('session_id')
        
        # 检查是否有多个观察结果
        if len(thought.observations) < 2:
            return
        
        # 简单冲突检测：检查相同字段的不同值
        conflicts_found = []
        for i, obs1 in enumerate(thought.observations):
            for j, obs2 in enumerate(thought.observations[i+1:], i+1):
                if isinstance(obs1, dict) and isinstance(obs2, dict):
                    common_keys = set(obs1.keys()) & set(obs2.keys())
                    for key in common_keys:
                        if obs1[key] != obs2[key]:
                            conflicts_found.append({
                                "key": key,
                                "value1": obs1[key],
                                "value2": obs2[key]
                            })
        
        if conflicts_found:
            logger.info_ctx(
                "检测到数据冲突",
                session_id=session_id,
                extra_data={"conflicts": conflicts_found[:5]}  # 最多记录5个
            )
            
            thought.add_reasoning(f"检测到 {len(conflicts_found)} 个数据冲突，尝试解决")
            
            # 简单解决策略：使用最新的数据
            thought.add_reasoning("使用最新数据源解决冲突")

    def _switch_to_reliable_source(self, thought: AgentThought) -> None:
        """切换到更可靠的数据源
        
        如果当前数据源不可靠，尝试使用备用数据源
        """
        session_id = thought.context.get('session_id')
        
        # 检查是否有失败的工具
        failed_tools = [
            action for action in thought.actions_taken
            if not action.get("result", {}).get("status") == "success"
        ]
        
        if failed_tools:
            thought.add_reasoning(f"检测到 {len(failed_tools)} 个失败工具，尝试备用数据源")
            
            # 尝试使用不同的参数重试
            for action in failed_tools[:2]:  # 最多重试2个
                tool_name = action.get("tool_name")
                original_params = action.get("parameters", {})
                
                # 调整参数
                adjusted_params = self._adjust_tool_parameters(tool_name, original_params)
                
                try:
                    result = self.tool_registry.execute(tool_name, **adjusted_params)
                    thought.add_action(f"{tool_name}_retry", adjusted_params, result)
                    thought.add_observation(result.data if result.is_success() else None)
                    
                    logger.info_ctx(
                        f"工具重试成功：{tool_name}",
                        session_id=session_id,
                        extra_data={"success": result.is_success()}
                    )
                except Exception as e:
                    logger.warning_ctx(
                        f"工具重试失败：{tool_name}",
                        session_id=session_id,
                        extra_data={"error": str(e)}
                    )

    def _select_more_relevant_tools(self, thought: AgentThought) -> None:
        """选择更相关的工具
        
        重新执行工具选择，强调相关性
        """
        try:
            # 使用增强的上下文重新选择工具
            enhanced_context = {
                **thought.context,
                "focus_on_relevance": True,
                "previous_tools_failed": [
                    action.get("tool_name")
                    for action in thought.actions_taken
                    if not action.get("result", {}).get("status") == "success"
                ]
            }
            
            tool_plan = self.tool_selector.select_tools(
                query=thought.query,
                context=enhanced_context
            )
            
            # 更新工具计划
            thought.context['tool_plan'] = tool_plan
            thought.add_reasoning(f"重新选择工具：{[t.tool_name for t in tool_plan.tools]}")
            
        except Exception as e:
            logger.error_ctx(
                f"重新选择工具失败：{e}",
                session_id=thought.context.get('session_id')
            )

    def _enhance_actionable_details(self, thought: AgentThought) -> None:
        """提供更详细的信息
        
        增强结果的可操作性，添加更多解释和建议
        """
        session_id = thought.context.get('session_id')
        
        # 标记需要增强详细信息
        thought.context['enhance_details'] = True
        
        logger.info_ctx(
            "标记增强详细信息",
            session_id=session_id
        )

    def _adjust_tool_parameters(
        self,
        tool_name: str,
        original_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调整工具参数
        
        根据工具类型智能调整参数
        """
        adjusted = original_params.copy()
        tool_name_lower = tool_name.lower()
        
        # 技能加点工具：提供更多信息（优先检查，避免被 recommend 匹配）
        if "skill" in tool_name_lower:
            adjusted["include_explanations"] = True
        
        # 英雄分析工具：扩大分析范围
        elif "counter" in tool_name_lower or "analyze" in tool_name_lower:
            adjusted["include_alternatives"] = True
            adjusted["min_recommendations"] = original_params.get("min_recommendations", 3) + 2
        
        # 物品推荐工具：增加物品数量
        elif "item" in tool_name_lower or "recommend" in tool_name_lower:
            adjusted["max_items"] = original_params.get("max_items", 5) + 3
        
        return adjusted

    def _apply_single_adjustment(self, thought: AgentThought, adjustment: str) -> None:
        """应用单个调整建议
        
        根据调整建议字符串执行相应操作
        """
        # 根据调整建议关键词匹配操作
        if "更多观察" in adjustment or "更多工具" in adjustment:
            self._try_additional_tools(thought)
        elif "一致性" in adjustment or "矛盾" in adjustment:
            self._resolve_data_conflicts(thought)
        elif "权威" in adjustment or "数据源" in adjustment:
            self._switch_to_reliable_source(thought)
        elif "聚焦" in adjustment or "相关" in adjustment:
            self._select_more_relevant_tools(thought)
        elif "详细" in adjustment or "信息" in adjustment:
            self._enhance_actionable_details(thought)

    def _default_strategy_adjustment(self, thought: AgentThought) -> None:
        """默认策略调整（降级方案）
        
        当反思评估不可用时的简单调整
        """
        # 1. 检查是否有失败的工具
        failed_tools = [
            action for action in thought.actions_taken
            if not action.get("result", {}).get("status") == "success"
        ]
        
        if failed_tools:
            thought.add_reasoning(f"检测到 {len(failed_tools)} 个失败工具，尝试替代方案")
            
            # 2. 尝试使用不同的参数重试
            for action in failed_tools:
                tool_name = action.get("tool_name")
                original_params = action.get("parameters", {})
                
                # 简单参数调整示例
                adjusted_params = self._adjust_tool_parameters(tool_name, original_params)
                
                try:
                    result = self.tool_registry.execute(tool_name, **adjusted_params)
                    thought.add_action(f"{tool_name}_retry", adjusted_params, result)
                    thought.add_observation(result.data if result.is_success() else None)
                except Exception as e:
                    logger.warning_ctx(
                        f"工具重试失败：{tool_name}",
                        session_id=thought.context.get('session_id')
                    )
        else:
            # 3. 没有失败工具但质量不足，尝试更多工具
            thought.add_reasoning("结果质量不足，尝试收集更多数据")
            self._try_additional_tools(thought)

    def _continue_with_more_data(self, thought: AgentThought, reflection_result: ReflectionResult) -> None:
        """继续收集更多数据
        
        当反思结果为 CONTINUE 时，继续下一轮循环
        """
        thought.add_reasoning("需要更多信息，继续下一轮循环")
        logger.info_ctx(
            "继续收集数据",
            session_id=thought.context.get('session_id'),
            extra_data={
                "missing_info": reflection_result.missing_information
            }
        )

    def _request_user_clarification(self, thought: AgentThought, reflection_result: ReflectionResult) -> None:
        """请求用户澄清
        
        当反思结果为 REQUEST_CLARIFICATION 时，生成澄清请求
        """
        thought.add_reasoning("需要用户澄清，生成澄清请求")
        
        # 设置直接回答模式，返回澄清请求
        thought.set_complete({
            "answer": {
                "message": "我需要更多信息来准确回答您的问题",
                "clarification_request": True,
                "missing_info": reflection_result.missing_information,
                "reasoning": reflection_result.reasoning
            },
            "reasoning": thought.reasoning_steps,
            "actions": thought.actions_taken,
            "confidence": reflection_result.confidence,
            "source": "clarification_request"
        })

    def _finalize_with_current_results(self, thought: AgentThought) -> None:
        """使用当前结果结束
        
        当反思结果为 FINALIZE 时，直接合成结果
        """
        thought.add_reasoning("结果质量可接受，准备结束")
        self._synthesize(thought)

    def _save_to_memory(self, thought: AgentThought) -> None:
        """保存思考过程到记忆系统"""
        if not self.enable_memory:
            return

        try:
            # 保存查询和答案
            self.memory.store(
                key=f"query_{int(time.time())}",
                value={
                    "query": thought.query,
                    "answer": thought.final_answer,
                    "timestamp": time.time()
                },
                memory_type="long_term",
                tags=["dota", "query"]
            )
        except Exception as e:
            thought.add_reasoning(f"保存到记忆失败：{str(e)}")

    def _save_conversation_history(
        self,
        session_id: str,
        original_query: str,
        response: Dict[str, Any],
        augmented_context: Dict[str, Any]
    ) -> None:
        """保存对话历史到会话管理器

        Args:
            session_id: 会话 ID
            original_query: 原始查询
            response: Agent 响应
            augmented_context: 增强上下文
        """
        try:
            user_message = Message(
                role=MessageRole.USER.value,
                content=original_query,
                metadata={
                    "entities": augmented_context.get("entities", []),
                    "inferred_intent": augmented_context.get("inferred_intent", "general")
                }
            )
            self.conversation_manager.add_message(session_id, user_message)

            answer_content = ""
            if response.get("success"):
                answer_data = response.get("answer", {})
                if isinstance(answer_data, dict):
                    answer_content = str(answer_data.get("answer", answer_data))
                else:
                    answer_content = str(answer_data)
            else:
                answer_content = response.get("error", "处理失败")

            assistant_message = Message(
                role=MessageRole.ASSISTANT.value,
                content=answer_content,
                metadata={
                    "state": response.get("state"),
                    "turn_count": response.get("turn_count"),
                    "success": response.get("success", False)
                }
            )
            self.conversation_manager.add_message(session_id, assistant_message)

            current_heroes = augmented_context.get("current_heroes", {})
            if current_heroes.get("our") or current_heroes.get("enemy"):
                self.conversation_manager.update_context_state(
                    session_id, "current_heroes", current_heroes
                )

            inferred_intent = augmented_context.get("inferred_intent", "general")
            topic_map = {
                "recommend_heroes": "counter",
                "recommend_items": "items",
                "recommend_skills": "skills"
            }
            new_topic = topic_map.get(inferred_intent, "general")
            self.conversation_manager.update_context_state(
                session_id, "current_topic", new_topic
            )

        except Exception as e:
            logger.error_ctx(
                f"保存对话历史失败：{str(e)}",
                session_id=session_id,
                extra_data={"error": str(e)}
            )

    def _load_known_heroes_to_augmenter(self) -> None:
        """加载已知英雄列表到上下文增强器"""
        try:
            from utils.api_client import OpenDotaClient
            client = OpenDotaClient()
            heroes = client.get_heroes()
            if heroes:
                hero_names = []
                for hero in heroes:
                    name = hero.get("name", "").replace("npc_dota_hero_", "")
                    localized_name = hero.get("localized_name", "")
                    if name:
                        hero_names.append(name)
                    if localized_name:
                        hero_names.append(localized_name)
                
                self.context_augmenter.load_known_heroes(hero_names)
                logger.info_ctx(f"已加载 {len(hero_names)} 个英雄名称到上下文增强器")
            else:
                logger.warning("未能获取英雄列表，使用默认实体提取")
        except Exception as e:
            logger.error(f"加载英雄列表失败: {e}")

    def _deep_merge_contexts(
        self,
        base_context: Dict[str, Any],
        override_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """深度合并两个上下文字典

        Args:
            base_context: 基础上下文
            override_context: 覆盖上下文

        Returns:
            Dict: 合并后的上下文
        """
        merged = base_context.copy()
        
        for key, value in override_context.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_contexts(merged[key], value)
            else:
                merged[key] = value
        
        return merged

    def _should_finalize(self, thought: AgentThought) -> bool:
        """判断是否应该结束循环"""
        # 直接回答模式：不需要工具调用，直接结束
        if thought.context.get('direct_answer_mode'):
            logger.info_ctx("直接回答模式，提前结束循环", session_id=thought.context.get('session_id'))
            return True
        
        # 如果已经收集了足够的观察结果
        if len(thought.observations) >= 3:
            return True

        # 如果已经有高质量的合成结果
        if thought.final_answer:
            return True

        return False

    def _execute_single_goal(
        self, 
        thought: AgentThought, 
        sub_goal: Optional[Any],
        session_id: Optional[str],
        original_query: str,
        augmented_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行单个子目标（传统 ReAct 循环，带 Trace 支持）
        
        用于处理只有一个子目标的查询，保持向后兼容
        """
        try:
            for turn in range(self.max_turns):
                thought.increment_turn()
                logger.info_ctx(f"第 {turn + 1} 轮循环", session_id=session_id)

                # 1. Think - 理解问题
                logger.info_ctx("[Step 1/5] Think - 理解问题", session_id=session_id)
                with TraceSpan(f"turn_{turn+1}_think"):
                    self._think(thought)
                if thought.state == AgentState.FAILED:
                    logger.warning_ctx("Think 步骤失败，终止循环", session_id=session_id)
                    break

                # 2. Plan - 制定计划
                logger.info_ctx("[Step 2/5] Plan - 制定计划", session_id=session_id)
                with TraceSpan(f"turn_{turn+1}_plan"):
                    self._plan(thought)
                if thought.state == AgentState.FAILED:
                    logger.warning_ctx("Plan 步骤失败，终止循环", session_id=session_id)
                    break

                # 3. Execute - 执行行动
                logger.info_ctx("[Step 3/5] Execute - 执行行动", session_id=session_id)
                with TraceSpan(f"turn_{turn+1}_execute"):
                    self._execute(thought)
                if thought.state == AgentState.FAILED:
                    logger.warning_ctx("Execute 步骤失败，终止循环", session_id=session_id)
                    break

                # 4. Observe - 观察结果
                logger.info_ctx("[Step 4/5] Observe - 观察结果", session_id=session_id)
                with TraceSpan(f"turn_{turn+1}_observe"):
                    self._observe(thought)

                # 5. Reflect - 反思（可选）
                if self.enable_reflection:
                    logger.info_ctx("[Step 5/5] Reflect - 反思", session_id=session_id)
                    with TraceSpan(f"turn_{turn+1}_reflect"):
                        self._reflect(thought)

                # 检查是否已完成
                if thought.state == AgentState.COMPLETE:
                    logger.info_ctx(f"循环完成，状态: COMPLETE", session_id=session_id)
                    break

                # 如果已经收集了足够的信息，可以提前结束
                if self._should_finalize(thought):
                    logger.info_ctx("满足提前结束条件", session_id=session_id)
                    self._finalize(thought)
                    break

            # 如果达到最大轮数仍未完成，强制结束
            if thought.state not in [AgentState.COMPLETE, AgentState.FAILED]:
                logger.warning_ctx(f"达到最大轮数 ({self.max_turns})，强制结束", session_id=session_id)
                self._finalize(thought)

            response = self._build_response(thought)
            
            if session_id and self.conversation_manager:
                self._save_conversation_history(session_id, original_query, response, augmented_context)
            
            logger.info_ctx(
                "最终响应",
                session_id=session_id,
                extra_data={
                    "state": response.get('state'),
                    "success": response.get('success'),
                    "turn_count": response.get('turn_count'),
                    "duration": response.get('duration')
                }
            )
            
            return response

        except Exception as e:
            logger.error_ctx(
                f"执行单目标异常: {str(e)}",
                session_id=session_id,
                extra_data={"error": str(e), "traceback": traceback.format_exc()}
            )
            thought.set_failed(str(e))
            return self._build_response(thought)

    def _execute_sub_goal(self, thought: AgentThought, sub_goal: Any) -> bool:
        """执行单个子目标
        
        Args:
            thought: 子目标的 AgentThought
            sub_goal: 子目标对象
            
        Returns:
            bool: 是否执行成功
        """
        try:
            session_id = thought.context.get('session_id')
            
            logger.debug_ctx(
                "开始执行子目标",
                session_id=session_id,
                extra_data={
                    "sub_goal_id": sub_goal.id,
                    "description": sub_goal.description,
                    "tool_name": sub_goal.tool_name,
                    "parameters": sub_goal.parameters
                }
            )
            
            if sub_goal.tool_name:
                logger.info_ctx(
                    "使用指定工具执行子目标",
                    session_id=session_id,
                    extra_data={"tool_name": sub_goal.tool_name, "parameters": sub_goal.parameters}
                )
                
                from core.llm_tool_selector import ToolCall, ToolCallPlan
                tool_plan = ToolCallPlan(
                    tools=[ToolCall(tool_name=sub_goal.tool_name, parameters=sub_goal.parameters or {})],
                    reasoning=f"执行子目标: {sub_goal.description}"
                )
                
                thought.context['tool_plan'] = tool_plan
                logger.debug_ctx(
                    "工具计划已创建",
                    session_id=session_id,
                    extra_data={
                        "tools": [t.tool_name for t in tool_plan.tools],
                        "tool_params": [t.parameters for t in tool_plan.tools]
                    }
                )
                
                logger.debug_ctx("调用 _plan 方法", session_id=session_id)
                self._plan(thought)
                logger.debug_ctx(
                    "_plan 方法完成",
                    session_id=session_id,
                    extra_data={"state": thought.state.value, "planned_tools": thought.context.get('planned_tools')}
                )
                if thought.state == AgentState.FAILED:
                    logger.error_ctx(
                        "_plan 失败",
                        session_id=session_id,
                        extra_data={"error": thought.error}
                    )
                    return False
                
                logger.debug_ctx("调用 _execute 方法", session_id=session_id)
                self._execute(thought)
                logger.debug_ctx(
                    "_execute 方法完成",
                    session_id=session_id,
                    extra_data={"state": thought.state.value, "observations_count": len(thought.observations)}
                )
                if thought.state == AgentState.FAILED:
                    logger.error_ctx(
                        "_execute 失败",
                        session_id=session_id,
                        extra_data={"error": thought.error}
                    )
                    return False
                
                logger.debug_ctx("调用 _observe 方法", session_id=session_id)
                self._observe(thought)
                logger.debug_ctx(
                    "_observe 方法完成",
                    session_id=session_id,
                    extra_data={"observations_count": len(thought.observations)}
                )
                
                if thought.observations:
                    logger.debug_ctx("调用 _synthesize 方法", session_id=session_id)
                    self._synthesize(thought)
                    logger.debug_ctx(
                        "_synthesize 方法完成",
                        session_id=session_id,
                        extra_data={"state": thought.state.value}
                    )
                else:
                    logger.warning_ctx(
                        "没有观察结果，无法合成",
                        session_id=session_id,
                        extra_data={"actions_taken": [a.get('tool_name') for a in thought.actions_taken]}
                    )
                    thought.set_failed("工具执行后没有观察结果")
                    return False
                
                success = thought.state == AgentState.COMPLETE
                logger.info_ctx(
                    "子目标执行完成",
                    session_id=session_id,
                    extra_data={
                        "sub_goal_id": sub_goal.id,
                        "success": success,
                        "state": thought.state.value
                    }
                )
                return success
            else:
                logger.info_ctx("使用标准 ReAct 流程执行子目标", session_id=session_id)
                for turn in range(self.max_turns):
                    thought.increment_turn()
                    
                    self._think(thought)
                    if thought.state == AgentState.FAILED:
                        return False
                    
                    self._plan(thought)
                    if thought.state == AgentState.FAILED:
                        return False
                    
                    self._execute(thought)
                    if thought.state == AgentState.FAILED:
                        return False
                    
                    self._observe(thought)
                    
                    if thought.state == AgentState.COMPLETE:
                        return True
                    
                    if self._should_finalize(thought):
                        self._finalize(thought)
                        return True
                
                logger.warning_ctx("子目标执行达到最大轮数", session_id=session_id)
                self._finalize(thought)
                return thought.state == AgentState.COMPLETE
                
        except Exception as e:
            logger.error_ctx(
                f"执行子目标异常: {str(e)}",
                session_id=thought.context.get('session_id'),
                extra_data={"error": str(e), "traceback": traceback.format_exc()}
            )
            thought.set_failed(str(e))
            return False

    def _merge_sub_goal_results(self, goal_plan: Any) -> Dict[str, Any]:
        """合并所有子目标的结果
        
        Args:
            goal_plan: 目标计划
            
        Returns:
            Dict: 合并后的最终结果
        """
        results = []
        completed_goals = []
        failed_goals = []
        
        for sg in goal_plan.sub_goals:
            if sg.status == GoalStatus.COMPLETED and sg.result:
                results.append({
                    "sub_goal_id": sg.id,
                    "description": sg.description,
                    "result": sg.result
                })
                completed_goals.append(sg.description)
            elif sg.status == GoalStatus.FAILED:
                failed_goals.append({
                    "id": sg.id,
                    "description": sg.description,
                    "error": sg.error
                })
        
        # 构建最终答案
        final_answer = {
            "main_goal": goal_plan.main_goal,
            "original_query": goal_plan.original_query,
            "sub_goals_summary": {
                "total": len(goal_plan.sub_goals),
                "completed": len(completed_goals),
                "failed": len(failed_goals)
            },
            "completed_goals": completed_goals,
            "failed_goals": failed_goals,
            "sub_goals_results": results
        }
        
        # 检查是否需要生成推荐答案
        if results and self._should_generate_recommendation(goal_plan.original_query):
            # 检查是否有阵容分析结果和强势英雄列表
            composition_analysis = None
            meta_heroes = None
            
            for result in results:
                result_data = result.get("result", {})
                if isinstance(result_data, dict):
                    if self._is_composition_analysis(result_data):
                        composition_analysis = result_data
                    elif "meta_heroes" in result_data:
                        meta_heroes = result_data.get("meta_heroes")
            
            # 如果有阵容分析结果，生成推荐答案
            if composition_analysis:
                logger.info_ctx(
                    "检测到阵容分析结果，生成推荐答案",
                    session_id=None,
                    extra_data={"has_meta_heroes": meta_heroes is not None}
                )
                try:
                    # 构造上下文信息
                    context = {
                        "our_heroes": goal_plan.original_query.split("我方英雄有")[1].split("，")[0].split(",") if "我方英雄有" in goal_plan.original_query else [],
                        "enemy_heroes": goal_plan.original_query.split("敌方英雄有")[1].split("，")[0].split(",") if "敌方英雄有" in goal_plan.original_query else [],
                        "meta_heroes": meta_heroes
                    }
                    
                    recommendation = self._generate_hero_recommendation(
                        goal_plan.original_query,
                        composition_analysis,
                        context
                    )
                    final_answer["answer"] = {"message": recommendation}
                    logger.info_ctx("推荐英雄答案生成成功", session_id=None)
                except Exception as e:
                    logger.error_ctx(
                        f"推荐英雄答案生成失败: {e}",
                        session_id=None,
                        extra_data={"error": str(e)}
                    )
                    # 失败时使用原有逻辑
                    final_answer["answer"] = self._extract_answer_from_results(results)
            else:
                # 没有阵容分析结果，使用原有逻辑
                final_answer["answer"] = self._extract_answer_from_results(results)
        else:
            # 不需要生成推荐答案，使用原有逻辑
            if results:
                final_answer["answer"] = self._extract_answer_from_results(results)
            else:
                final_answer["answer"] = {"message": "未能完成任何子目标"}
        
        logger.info_ctx(
            "子目标结果合并完成",
            session_id=None,
            extra_data={
                "total": len(goal_plan.sub_goals),
                "completed": len(completed_goals),
                "failed": len(failed_goals)
            }
        )
        
        return final_answer
    
    def _extract_answer_from_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从子目标结果中提取答案
        
        Args:
            results: 子目标结果列表
            
        Returns:
            Dict: 提取的答案
        """
        if not results:
            return {"message": "未能完成任何子目标"}
        
        # 优先使用最后一个子目标的结果作为主要答案
        last_result = results[-1].get("result", {})
        
        if isinstance(last_result, dict) and "answer" in last_result:
            return last_result["answer"]
        elif isinstance(last_result, dict):
            return last_result
        elif isinstance(last_result, list):
            return last_result
        else:
            return {"message": str(last_result)}
