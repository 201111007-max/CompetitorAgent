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
from core.llm_tool_selector import LLMToolSelector
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
        llm_client,
        memory: Optional[AgentMemory] = None,
        max_turns: int = 5,
        enable_reflection: bool = True,
        enable_memory: bool = True
    ):
        """初始化 Agent Controller

        Args:
            tool_registry: 工具注册表
            llm_client: LLM 客户端（用于智能工具选择）
            memory: 记忆系统（可选）
            max_turns: 最大循环轮数
            enable_reflection: 是否启用反思
            enable_memory: 是否启用记忆系统
        """
        self.tool_registry = tool_registry
        self.llm_client = llm_client
        self.memory = memory
        self.max_turns = max_turns
        self.enable_reflection = enable_reflection
        self.enable_memory = enable_memory and memory is not None
        self.current_thought: Optional[AgentThought] = None
        
        # 初始化 LLM 工具选择器
        self.tool_selector = LLMToolSelector(llm_client, tool_registry)
        print(f"[AGENT_CONTROLLER] LLM 工具选择器已初始化")

    def solve(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行完整的 ReAct 循环解决问题

        Args:
            query: 用户查询
            context: 额外上下文信息

        Returns:
            包含最终答案和相关元数据的字典
        """
        print(f"\n{'='*60}")
        print(f"[AGENT_CONTROLLER] 开始处理查询")
        print(f"[AGENT_CONTROLLER] Query: {query}")
        print(f"[AGENT_CONTROLLER] Context: {context}")
        print(f"{'='*60}\n")
        
        thought = AgentThought(query=query, context=context or {})
        self.current_thought = thought

        try:
            for turn in range(self.max_turns):
                thought.increment_turn()
                print(f"\n[AGENT_CONTROLLER] ===== 第 {turn + 1} 轮循环 =====")

                # 1. Think - 理解问题
                print(f"[AGENT_CONTROLLER] [Step 1/5] Think - 理解问题")
                self._think(thought)
                if thought.state == AgentState.FAILED:
                    print(f"[AGENT_CONTROLLER] Think 步骤失败，终止循环")
                    break

                # 2. Plan - 制定计划
                print(f"[AGENT_CONTROLLER] [Step 2/5] Plan - 制定计划")
                self._plan(thought)
                if thought.state == AgentState.FAILED:
                    print(f"[AGENT_CONTROLLER] Plan 步骤失败，终止循环")
                    break

                # 3. Execute - 执行行动
                print(f"[AGENT_CONTROLLER] [Step 3/5] Execute - 执行行动")
                self._execute(thought)
                if thought.state == AgentState.FAILED:
                    print(f"[AGENT_CONTROLLER] Execute 步骤失败，终止循环")
                    break

                # 4. Observe - 观察结果
                print(f"[AGENT_CONTROLLER] [Step 4/5] Observe - 观察结果")
                self._observe(thought)

                # 5. Reflect - 反思（可选）
                if self.enable_reflection:
                    print(f"[AGENT_CONTROLLER] [Step 5/5] Reflect - 反思")
                    self._reflect(thought)

                # 检查是否已完成
                if thought.state == AgentState.COMPLETE:
                    print(f"[AGENT_CONTROLLER] 循环完成，状态: COMPLETE")
                    break

                # 如果已经收集了足够的信息，可以提前结束
                if self._should_finalize(thought):
                    print(f"[AGENT_CONTROLLER] 满足提前结束条件")
                    self._finalize(thought)
                    break

            # 如果达到最大轮数仍未完成，强制结束
            if thought.state not in [AgentState.COMPLETE, AgentState.FAILED]:
                print(f"[AGENT_CONTROLLER] 达到最大轮数 ({self.max_turns})，强制结束")
                self._finalize(thought)

            response = self._build_response(thought)
            print(f"\n[AGENT_CONTROLLER] 最终响应:")
            print(f"[AGENT_CONTROLLER]   State: {response.get('state')}")
            print(f"[AGENT_CONTROLLER]   Success: {response.get('success')}")
            print(f"[AGENT_CONTROLLER]   Turn Count: {response.get('turn_count')}")
            print(f"[AGENT_CONTROLLER]   Duration: {response.get('duration'):.2f}s")
            print(f"{'='*60}\n")
            
            return response

        except Exception as e:
            print(f"[AGENT_CONTROLLER] 异常: {str(e)}")
            import traceback
            print(f"[AGENT_CONTROLLER] Traceback: {traceback.format_exc()}")
            thought.set_failed(str(e))
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
            print(f"[AGENT_CONTROLLER._think] 调用 LLM 工具选择器...")
            tool_plan = self.tool_selector.select_tools(
                query=thought.query,
                context=thought.context
            )
            thought.context['tool_plan'] = tool_plan
            thought.add_reasoning(f"LLM 选择工具：{[t.tool_name for t in tool_plan.tools]}")
            thought.add_reasoning(f"选择理由：{tool_plan.reasoning}")
            print(f"[AGENT_CONTROLLER._think] LLM 工具选择完成")
            print(f"[AGENT_CONTROLLER._think] 选择工具: {[t.tool_name for t in tool_plan.tools]}")
            print(f"[AGENT_CONTROLLER._think] 选择理由: {tool_plan.reasoning}")
        except Exception as e:
            error_msg = f"LLM 工具选择失败：{str(e)}"
            print(f"[AGENT_CONTROLLER._think] {error_msg}")
            thought.set_failed(error_msg)
            return

        # 从记忆中检索相关上下文（如果启用）
        if self.enable_memory:
            relevant_context = self.memory.get_relevant_context(thought.query, limit=3)
            if relevant_context:
                thought.add_reasoning(f"从记忆中检索到 {len(relevant_context)} 条相关上下文")
                thought.context['memory_context'] = relevant_context

    def _plan(self, thought: AgentThought) -> None:
        """Plan 步骤 - 制定行动计划

        使用 LLM 生成的工具计划，制定执行方案
        """
        thought.state = AgentState.PLANNING

        # 获取 LLM 生成的工具计划
        tool_plan = thought.context.get('tool_plan')
        if not tool_plan:
            error_msg = "工具计划缺失，无法制定执行计划"
            print(f"[AGENT_CONTROLLER._plan] {error_msg}")
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
        print(f"[AGENT_CONTROLLER._plan] 计划执行工具: {planned_tools}")
        print(f"[AGENT_CONTROLLER._plan] 工具参数:")
        for tool_name, params in thought.context['tool_params'].items():
            print(f"[AGENT_CONTROLLER._plan]   {tool_name}: {params}")

    def _execute(self, thought: AgentThought) -> None:
        """Execute 步骤 - 执行工具调用

        使用 LLM 提取的参数执行工具调用
        """
        thought.state = AgentState.ACTING

        planned_tools = thought.context.get('planned_tools', [])
        tool_params = thought.context.get('tool_params', {})

        print(f"[AGENT_CONTROLLER._execute] 计划执行工具: {planned_tools}")
        print(f"[AGENT_CONTROLLER._execute] 工具参数:")
        for tool_name, params in tool_params.items():
            print(f"[AGENT_CONTROLLER._execute]   {tool_name}: {params}")

        # 执行工具调用
        for tool_name in planned_tools:
            # 使用 LLM 提取的参数
            params = tool_params.get(tool_name, {})

            tool = self.tool_registry.get(tool_name)
            if tool:
                try:
                    thought.add_reasoning(f"执行工具：{tool_name}")
                    print(f"\n[AGENT_CONTROLLER._execute] >>> 执行工具: {tool_name}")
                    print(f"[AGENT_CONTROLLER._execute]     参数: {params}")
                    result = self.tool_registry.execute(tool_name, **params)
                    print(f"[AGENT_CONTROLLER._execute]     结果状态: {result.status.value if result else 'None'}")
                    if result:
                        print(f"[AGENT_CONTROLLER._execute]     结果数据: {result.data}")
                        if result.error:
                            print(f"[AGENT_CONTROLLER._execute]     错误信息: {result.error}")
                    thought.add_action(tool_name, params, result)

                    if result.is_success():
                        thought.add_observation(result.data)
                        print(f"[AGENT_CONTROLLER._execute]     工具执行成功，已添加观察结果")
                        # 如果工具执行成功且有结果，可以考虑完成
                        if self._has_sufficient_data(thought):
                            print(f"[AGENT_CONTROLLER._execute]     已收集足够数据，准备合成结果")
                            self._synthesize(thought)
                            return
                    else:
                        thought.add_reasoning(f"工具 {tool_name} 执行失败：{result.error}")
                        print(f"[AGENT_CONTROLLER._execute]     工具执行失败: {result.error}")

                except Exception as e:
                    thought.add_reasoning(f"工具 {tool_name} 执行异常：{str(e)}")
                    thought.add_action(tool_name, params, None)
                    print(f"[AGENT_CONTROLLER._execute]     工具执行异常: {str(e)}")
                    import traceback
                    print(f"[AGENT_CONTROLLER._execute]     Traceback: {traceback.format_exc()}")

        # 如果没有工具执行成功，标记为失败
        if not thought.observations:
            thought.add_reasoning("所有工具执行失败")
            print(f"[AGENT_CONTROLLER._execute] 所有工具执行失败，无观察结果")

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
                print(f"[AGENT_CONTROLLER._merge_observations] 处理列表格式观察结果，包含 {len(obs)} 项")
                if len(obs) > 0 and isinstance(obs[0], dict):
                    # 检查是否是英雄推荐格式
                    if 'hero_name' in obs[0] or 'hero_id' in obs[0]:
                        merged['recommendations'].extend(obs)
                        print(f"[AGENT_CONTROLLER._merge_observations] 已添加 {len(obs)} 条英雄推荐")
                    else:
                        merged['data_sources'].extend(obs)
                else:
                    merged['raw_data'] = obs
            else:
                merged['raw_data'] = obs

        print(f"[AGENT_CONTROLLER._merge_observations] 最终合并结果: {len(merged['recommendations'])} 条推荐")
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
