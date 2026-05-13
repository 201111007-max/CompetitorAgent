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
from memory.memory import AgentMemory
from tools.base import ToolResult, ToolStatus
from utils.trace_context import TraceSpan, get_current_trace
from utils.log_config import get_logger

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
            logger.info("元认知评估器已初始化")
        else:
            logger.info("元认知评估器未启用")
        
        # 加载已知英雄列表到上下文增强器
        self._load_known_heroes_to_augmenter()

    def solve(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行完整的 ReAct 循环解决问题（带 Trace 支持）

        Args:
            query: 用户查询
            context: 额外上下文信息
            session_id: 会话 ID（可选，用于多轮对话）

        Returns:
            包含最终答案和相关元数据的字典
        """
        # 获取当前 Trace 上下文
        trace_ctx = get_current_trace()
        
        with TraceSpan("agent_solve", parent=trace_ctx) as solve_span:
            logger.info_ctx(
                "开始处理查询",
                session_id=session_id,
                extra_data={
                    "query": query,
                    "context": context,
                    "trace_id": solve_span.trace_id if solve_span else 'N/A'
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
                                "limitations": assessment.limitations
                            }
                        )
                        
                        # 如果置信度太低，请求用户澄清
                        if self.metacognition.should_request_clarification(assessment):
                            clarification = self.metacognition.generate_clarification(query, assessment)
                            
                            logger.info_ctx(
                                "元认知请求用户澄清",
                                session_id=session_id,
                                extra_data={
                                    "clarification_type": clarification.type,
                                    "questions": clarification.questions
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
                                "confidence_level": post_assessment.confidence_level.value,
                                "confidence_score": round(post_assessment.confidence_score, 3)
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

        # 如果没有工具执行成功，标记为失败
        if not thought.observations:
            thought.add_reasoning("所有工具执行失败")
            logger.warning_ctx("所有工具执行失败，无观察结果", session_id=session_id)

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

        # 简单判断：至少有一条观察结果且包含有效数据
        for obs in thought.observations:
            if isinstance(obs, dict):
                if 'recommendations' in obs or 'answer' in obs:
                    return True
            elif isinstance(obs, list) and len(obs) > 0:
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
        """调整策略"""
        thought.add_reasoning("调整策略：尝试不同的工具或参数")
        # 可以在这里实现更复杂的策略调整逻辑

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
            
            # 如果子目标指定了工具，直接使用
            if sub_goal.tool_name:
                logger.info_ctx(
                    "使用指定工具执行子目标",
                    session_id=session_id,
                    extra_data={"tool_name": sub_goal.tool_name}
                )
                
                # 构造工具计划
                from core.llm_tool_selector import ToolCall
                tool_plan = type('ToolCallPlan', (), {
                    'tools': [ToolCall(tool_name=sub_goal.tool_name, parameters=sub_goal.parameters)],
                    'reasoning': f"执行子目标: {sub_goal.description}"
                })()
                
                thought.context['tool_plan'] = tool_plan
                
                # 执行 ReAct 循环的一个迭代
                self._plan(thought)
                if thought.state == AgentState.FAILED:
                    return False
                
                self._execute(thought)
                if thought.state == AgentState.FAILED:
                    return False
                
                self._observe(thought)
                
                # 合成结果
                if thought.observations:
                    self._synthesize(thought)
                
                return thought.state == AgentState.COMPLETE
            else:
                # 没有指定工具，使用标准 ReAct 流程
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
                
                # 达到最大轮数
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
        
        # 如果有成功的子目标，尝试提取主要答案
        if results:
            # 优先使用最后一个子目标的结果作为主要答案
            last_result = results[-1].get("result", {})
            
            if isinstance(last_result, dict) and "answer" in last_result:
                final_answer["answer"] = last_result["answer"]
            elif isinstance(last_result, dict):
                final_answer["answer"] = last_result
            elif isinstance(last_result, list):
                # 如果结果是列表（如英雄推荐列表），直接作为 answer
                final_answer["answer"] = last_result
            else:
                final_answer["answer"] = {"message": str(last_result)}
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
