"""ReAct Agent - 推理-行动循环模式"""

from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time

try:
    from .tool_registry import ToolRegistry
    from ..memory import AgentMemory
    from ..tools.base import ToolResult, ToolStatus
except ImportError:
    try:
        from tool_registry import ToolRegistry
        from memory import AgentMemory
        from tools.base import ToolResult, ToolStatus
    except ImportError:
        from core.tool_registry import ToolRegistry
        from memory.memory import AgentMemory
        from tools.base import ToolResult, ToolStatus


class AgentThought:
    """Agent 思考状态"""
    def __init__(self, query: str):
        self.query = query
        self.observations: List[str] = []
        self.reasoning: List[str] = []
        self.actions_taken: List[str] = []
        self.final_answer: Optional[Dict] = None
        self.is_complete: bool = False
        self.turn_count: int = 0

    def add_observation(self, observation: str) -> None:
        self.observations.append(observation)

    def add_reasoning(self, reasoning: str) -> None:
        self.reasoning.append(reasoning)

    def add_action(self, action: str) -> None:
        self.actions_taken.append(action)

    def increment_turn(self) -> None:
        self.turn_count += 1

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "observations": self.observations,
            "reasoning": self.reasoning,
            "actions_taken": self.actions_taken,
            "final_answer": self.final_answer,
            "is_complete": self.is_complete,
            "turn_count": self.turn_count
        }


class ReActAgent:
    """ReAct Agent - 推理-行动循环

    实现 ReAct (Reasoning + Acting) 模式，Agent 可以：
    1. 理解用户意图（Think）
    2. 制定行动计划（Plan）
    3. 自主调用工具（Act）
    4. 收集观察结果（Observe）
    5. 综合决策输出（Synthesize）
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        memory: Optional[AgentMemory] = None,
        max_turns: int = 5,
        enable_reflection: bool = True
    ):
        """初始化 ReAct Agent

        Args:
            tool_registry: 工具注册表
            memory: 记忆系统（可选）
            max_turns: 最大循环轮数
            enable_reflection: 是否启用反思
        """
        self.tool_registry = tool_registry
        self.memory = memory or AgentMemory()
        self.max_turns = max_turns
        self.enable_reflection = enable_reflection

    def think(self, query: str) -> AgentThought:
        """思考：理解用户意图，初始化思考状态

        Args:
            query: 用户查询

        Returns:
            AgentThought: 初始思考状态
        """
        thought = AgentThought(query)

        thought.add_reasoning(f"用户查询: {query}")

        if "推荐" in query or "选什么" in query:
            thought.add_reasoning("这是一个英雄推荐请求，需要分析克制关系")
        elif "出装" in query or "装备" in query:
            thought.add_reasoning("这是一个出装推荐请求")
        elif "技能" in query or "加点" in query:
            thought.add_reasoning("这是一个技能加点推荐请求")
        else:
            thought.add_reasoning("这是一个综合查询，可能需要多个工具")

        relevant_context = self.memory.get_relevant_context(query, limit=3)
        if relevant_context:
            thought.add_reasoning(f"从记忆中找到 {len(relevant_context)} 条相关上下文")

        return thought

    def plan(self, thought: AgentThought) -> List[Dict[str, Any]]:
        """规划：根据当前思考状态制定行动计划

        Args:
            thought: 当前思考状态

        Returns:
            List[Dict]: 行动计划列表
        """
        query = thought.query.lower()
        actions = []

        if "推荐" in query or "选什么" in query or "counter" in query:
            actions.append({
                "tool": "analyze_counter_picks",
                "params": self._extract_hero_params(query),
                "purpose": "分析克制关系，推荐英雄"
            })

        if "出装" in query or "装备" in query or "item" in query:
            hero_name = self._extract_single_hero(query)
            if hero_name:
                actions.append({
                    "tool": "recommend_items",
                    "params": {
                        "hero_name": hero_name,
                        "game_stage": "all",
                        "enemy_heroes": []
                    },
                    "purpose": f"推荐 {hero_name} 的出装"
                })

        if "技能" in query or "加点" in query or "skill" in query:
            hero_name = self._extract_single_hero(query)
            if hero_name:
                actions.append({
                    "tool": "recommend_skills",
                    "params": {
                        "hero_name": hero_name,
                        "role": "core",
                        "enemy_heroes": []
                    },
                    "purpose": f"推荐 {hero_name} 的技能加点"
                })

        if not actions:
            actions.append({
                "tool": "get_meta_heroes",
                "params": {"limit": 5},
                "purpose": "获取版本强势英雄作为参考"
            })

        return actions

    def execute(self, thought: AgentThought, actions: List[Dict[str, Any]]) -> List[ToolResult]:
        """执行：调用工具执行行动计划

        Args:
            thought: 当前思考状态
            actions: 行动计划

        Returns:
            List[ToolResult]: 工具执行结果
        """
        results = []

        for action in actions:
            tool_name = action["tool"]
            params = action.get("params", {})
            purpose = action.get("purpose", "")

            thought.add_action(f"调用 {tool_name}: {purpose}")

            result = self.tool_registry.execute(tool_name, **params)
            results.append(result)

            if result.is_success():
                observation = f"{tool_name} 执行成功"
                if isinstance(result.data, dict):
                    if "recommendations" in result.data:
                        observation += f", 获得 {len(result.data['recommendations'])} 条推荐"
                    elif "meta_heroes" in result.data:
                        observation += f", 获得 {len(result.data['meta_heroes'])} 个版本强势英雄"
            else:
                observation = f"{tool_name} 执行失败: {result.error}"

            thought.add_observation(observation)

        return results

    def reflect(self, thought: AgentThought, results: List[ToolResult]) -> AgentThought:
        """反思：根据执行结果调整思考

        Args:
            thought: 当前思考状态
            results: 工具执行结果

        Returns:
            AgentThought: 更新后的思考状态
        """
        if not self.enable_reflection:
            return thought

        all_success = all(r.is_success() for r in results)
        any_success = any(r.is_success() for r in results)

        if all_success:
            thought.add_reasoning("所有工具执行成功，可以综合输出结果")
            thought.is_complete = True
        elif any_success:
            thought.add_reasoning("部分工具执行成功，基于已有结果输出")
            thought.is_complete = True
        else:
            thought.add_reasoning("所有工具执行失败，需要降级处理")
            thought.is_complete = True

        thought.increment_turn()

        if thought.turn_count >= self.max_turns:
            thought.add_reasoning(f"达到最大轮数 {self.max_turns}，强制结束")
            thought.is_complete = True

        return thought

    def synthesize(self, thought: AgentThought, results: List[ToolResult]) -> Dict[str, Any]:
        """综合：整合所有结果输出最终答案

        Args:
            thought: 思考状态
            results: 工具执行结果

        Returns:
            Dict: 最终答案
        """
        output = {
            "query": thought.query,
            "reasoning": thought.reasoning,
            "actions": thought.actions_taken,
            "observations": thought.observations,
            "turns": thought.turn_count,
            "recommendations": {}
        }

        for result in results:
            if result.is_success() and result.data:
                output["recommendations"][result.tool_name] = result.data

        thought.final_answer = output
        self._update_memory(thought)

        return output

    def solve(self, query: str) -> Dict[str, Any]:
        """解决问题：完整的 ReAct 循环

        Args:
            query: 用户查询

        Returns:
            Dict: 最终答案
        """
        thought = self.think(query)

        while not thought.is_complete and thought.turn_count < self.max_turns:
            actions = self.plan(thought)

            if not actions:
                thought.add_reasoning("没有可执行的行动")
                break

            results = self.execute(thought, actions)
            thought = self.reflect(thought, results)

        return self.synthesize(thought, self._get_last_results(thought))

    def _get_last_results(self, thought: AgentThought) -> List[ToolResult]:
        """获取最后一次工具执行结果"""
        history = self.tool_registry.get_call_history(limit=10)
        results = []
        for call in history:
            if call.result:
                results.append(call.result)
        return results

    def _extract_hero_params(self, query: str) -> Dict[str, Any]:
        """提取英雄参数"""
        our_heroes = self._extract_heroes(query, "our")
        enemy_heroes = self._extract_heroes(query, "enemy")

        if not our_heroes and not enemy_heroes:
            our_heroes = self._extract_heroes(query, "all")

        return {
            "our_heroes": our_heroes,
            "enemy_heroes": enemy_heroes,
            "top_n": 3
        }

    def _update_memory(self, thought: AgentThought) -> None:
        """更新记忆"""
        if thought.final_answer and "recommendations" in thought.final_answer:
            for tool_name, data in thought.final_answer["recommendations"].items():
                if data and isinstance(data, dict):
                    key = f"last_{tool_name}_result"
                    self.memory.remember(key, data, "short")

    def _extract_heroes(self, query: str, side: str = "all") -> List[str]:
        """提取英雄名称（简单实现）"""
        heroes = []
        hero_keywords = ["anti-mage", "am", "pudge", "pa", "phantom", "lion", "cm", "sf", "invoker"]

        query_lower = query.lower()
        for hero in hero_keywords:
            if hero in query_lower:
                heroes.append(hero.replace(" ", "-"))

        return heroes if heroes else []

    def _extract_single_hero(self, query: str) -> Optional[str]:
        """提取单个英雄名称"""
        heroes = self._extract_heroes(query)
        return heroes[0] if heroes else None