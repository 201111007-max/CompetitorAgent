"""Agent Controller - ReAct Agent 核心控制器

实现完整的 ReAct (Reasoning + Acting) 循环模式
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import time
import json
import sys
from pathlib import Path

# 确保可以导入项目模块
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.tool_registry import ToolRegistry
from memory.memory import AgentMemory
from tools.base import ToolResult, ToolStatus


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
        memory: Optional[AgentMemory] = None,
        max_turns: int = 5,
        enable_reflection: bool = True,
        enable_memory: bool = True
    ):
        """初始化 Agent Controller

        Args:
            tool_registry: 工具注册表
            memory: 记忆系统（可选）
            max_turns: 最大循环轮数
            enable_reflection: 是否启用反思
            enable_memory: 是否启用记忆系统
        """
        self.tool_registry = tool_registry
        self.memory = memory
        self.max_turns = max_turns
        self.enable_reflection = enable_reflection
        self.enable_memory = enable_memory and memory is not None
        self.current_thought: Optional[AgentThought] = None

    def solve(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行完整的 ReAct 循环解决问题

        Args:
            query: 用户查询
            context: 额外上下文信息

        Returns:
            包含最终答案和相关元数据的字典
        """
        thought = AgentThought(query=query, context=context or {})
        self.current_thought = thought

        try:
            for turn in range(self.max_turns):
                thought.increment_turn()

                # 1. Think - 理解问题
                self._think(thought)
                if thought.state == AgentState.FAILED:
                    break

                # 2. Plan - 制定计划
                self._plan(thought)
                if thought.state == AgentState.FAILED:
                    break

                # 3. Execute - 执行行动
                self._execute(thought)
                if thought.state == AgentState.FAILED:
                    break

                # 4. Observe - 观察结果
                self._observe(thought)

                # 5. Reflect - 反思（可选）
                if self.enable_reflection:
                    self._reflect(thought)

                # 检查是否已完成
                if thought.state == AgentState.COMPLETE:
                    break

                # 如果已经收集了足够的信息，可以提前结束
                if self._should_finalize(thought):
                    self._finalize(thought)
                    break

            # 如果达到最大轮数仍未完成，强制结束
            if thought.state not in [AgentState.COMPLETE, AgentState.FAILED]:
                self._finalize(thought)

            return self._build_response(thought)

        except Exception as e:
            thought.set_failed(str(e))
            return self._build_response(thought)

    def _think(self, thought: AgentThought) -> None:
        """Think 步骤 - 理解问题和意图

        分析用户查询，确定查询类型和所需信息
        """
        thought.state = AgentState.THINKING
        query = thought.query.lower()

        # 理解查询意图
        thought.add_reasoning(f"分析用户查询：{thought.query}")

        # 检测查询类型
        query_type = self._detect_query_type(query)
        thought.add_reasoning(f"查询类型：{query_type}")

        # 从记忆中检索相关上下文（如果启用）
        if self.enable_memory:
            relevant_context = self.memory.get_relevant_context(thought.query, limit=3)
            if relevant_context:
                thought.add_reasoning(f"从记忆中检索到 {len(relevant_context)} 条相关上下文")
                thought.context['memory_context'] = relevant_context

        # 检查是否有足够的信息继续
        if not query_type or query_type == 'unknown':
            thought.add_reasoning("无法识别查询类型，需要更多信息")

    def _plan(self, thought: AgentThought) -> None:
        """Plan 步骤 - 制定行动计划

        根据查询类型和可用工具，制定执行计划
        """
        thought.state = AgentState.PLANNING

        query = thought.query.lower()
        query_type = self._detect_query_type(query)

        # 根据查询类型选择工具
        available_tools = self._select_tools_for_query(query_type, thought.context)

        if not available_tools:
            thought.add_reasoning("没有找到合适的工具，尝试使用通用方法")
            available_tools = self.tool_registry.list_tools()

        thought.add_reasoning(f"计划使用工具：{available_tools}")
        print(f"[DEBUG] Plan: query_type={query_type}, available_tools={available_tools}")

        # 制定行动顺序
        thought.context['planned_tools'] = available_tools
        thought.context['query_type'] = query_type

    def _execute(self, thought: AgentThought) -> None:
        """Execute 步骤 - 执行工具调用

        根据计划调用相应的工具
        """
        thought.state = AgentState.ACTING

        planned_tools = thought.context.get('planned_tools', [])
        query_type = thought.context.get('query_type', 'unknown')

        # 准备工具调用参数
        params = self._prepare_tool_parameters(thought.query, query_type, thought.context)

        print(f"[DEBUG] Execute: planned_tools={planned_tools}, params={params}")

        # 执行工具调用
        for tool_name in planned_tools:
            tool = self.tool_registry.get(tool_name)
            if tool:
                try:
                    thought.add_reasoning(f"执行工具：{tool_name}")
                    print(f"[DEBUG] Executing tool: {tool_name} with params: {params}")
                    result = self.tool_registry.execute(tool_name, **params)
                    print(f"[DEBUG] Tool result: {result}")
                    thought.add_action(tool_name, params, result)

                    if result.is_success():
                        thought.add_observation(result.data)
                        # 如果工具执行成功且有结果，可以考虑完成
                        if self._has_sufficient_data(thought):
                            self._synthesize(thought)
                            return
                    else:
                        thought.add_reasoning(f"工具 {tool_name} 执行失败：{result.error}")
                        print(f"[DEBUG] Tool failed: {tool_name}, error: {result.error}")

                except Exception as e:
                    thought.add_reasoning(f"工具 {tool_name} 执行异常：{str(e)}")
                    thought.add_action(tool_name, params, None)
                    print(f"[DEBUG] Tool exception: {tool_name}, error: {str(e)}")

        # 如果没有工具执行成功，标记为失败
        if not thought.observations:
            thought.add_reasoning("所有工具执行失败，尝试降级方案")
            print(f"[DEBUG] No observations, all tools failed")

    def _observe(self, thought: AgentThought) -> None:
        """Observe 步骤 - 观察和分析结果

        分析工具执行结果，提取关键信息
        """
        thought.state = AgentState.OBSERVING

        if thought.observations:
            thought.add_reasoning(f"收集到 {len(thought.observations)} 条观察结果")

            # 分析观察结果
            for i, obs in enumerate(thought.observations):
                if isinstance(obs, dict):
                    thought.add_reasoning(f"观察结果 {i+1}: 包含 {len(obs)} 个字段")
                elif isinstance(obs, list):
                    thought.add_reasoning(f"观察结果 {i+1}: 包含 {len(obs)} 项")

    def _reflect(self, thought: AgentThought) -> None:
        """Reflect 步骤 - 反思和评估

        评估当前结果质量，决定是否需要继续循环
        """
        thought.state = AgentState.REFLECTING

        # 评估结果质量
        quality_score = self._evaluate_result_quality(thought)
        thought.add_reflection(f"结果质量评分：{quality_score:.2f}/1.00")

        # 检查是否需要更多行动
        if quality_score < 0.6 and thought.turn_count < self.max_turns:
            thought.add_reflection("结果质量不足，需要更多行动")
            # 调整策略
            self._adjust_strategy(thought)
        else:
            thought.add_reflection("结果质量可接受，准备结束")
            self._synthesize(thought)

    def _synthesize(self, thought: AgentThought) -> None:
        """Synthesize 步骤 - 综合决策

        综合所有观察和推理，形成最终答案
        """
        if thought.observations:
            # 合并所有观察结果
            final_data = self._merge_observations(thought.observations)
            thought.set_complete({
                "answer": final_data,
                "reasoning": thought.reasoning_steps,
                "actions": thought.actions_taken,
                "confidence": self._evaluate_result_quality(thought)
            })
        else:
            thought.set_complete({
                "answer": {"message": "无法获取有效数据"},
                "reasoning": thought.reasoning_steps,
                "actions": thought.actions_taken,
                "confidence": 0.0
            })

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

    def _detect_query_type(self, query: str) -> str:
        """检测查询类型"""
        if any(kw in query for kw in ['克制', 'counter', '推荐', '选什么英雄', '什么英雄']):
            return 'hero_recommendation'
        elif any(kw in query for kw in ['出装', '装备', 'item', 'build']):
            return 'item_recommendation'
        elif any(kw in query for kw in ['技能', '加点', 'skill', 'ability']):
            return 'skill_recommendation'
        elif any(kw in query for kw in ['阵容', 'composition', 'balance']):
            return 'composition_analysis'
        elif any(kw in query for kw in ['版本', 'meta', '强势']):
            return 'meta_analysis'
        else:
            return 'unknown'

    def _select_tools_for_query(self, query_type: str, context: Dict) -> List[str]:
        """根据查询类型选择工具"""
        tool_mapping = {
            'hero_recommendation': ['analyze_counter_picks', 'analyze_composition'],
            'item_recommendation': ['recommend_items'],
            'skill_recommendation': ['recommend_skills'],
            'composition_analysis': ['analyze_composition'],
            'meta_analysis': ['get_meta_heroes']
        }

        tools = tool_mapping.get(query_type, [])
        # 过滤出实际可用的工具
        available_tools = []
        for tool_name in tools:
            if self.tool_registry.get(tool_name):
                available_tools.append(tool_name)

        return available_tools

    def _prepare_tool_parameters(self, query: str, query_type: str, context: Dict) -> Dict[str, Any]:
        """准备工具调用参数"""
        params = {
            'top_n': context.get('top_n', 3),
            'limit': context.get('limit', 10)
        }

        # 从上下文或 query 中提取英雄信息
        if 'our_heroes' in context:
            params['our_heroes'] = context['our_heroes']
        if 'enemy_heroes' in context:
            params['enemy_heroes'] = context['enemy_heroes']

        return params

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
            else:
                merged['raw_data'] = obs

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

    def _should_finalize(self, thought: AgentThought) -> bool:
        """判断是否应该结束循环"""
        # 如果已经收集了足够的观察结果
        if len(thought.observations) >= 3:
            return True

        # 如果已经有高质量的合成结果
        if thought.final_answer:
            return True

        return False
