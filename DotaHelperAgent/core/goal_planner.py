"""目标规划器 - 将复杂查询分解为可执行的子目标树

实现目标分解与追踪能力，支持：
- 使用 LLM 将复杂查询分解为子目标树
- 确定子目标之间的依赖关系
- 追踪子目标执行状态
- 合并子目标结果
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import re
import sys
from pathlib import Path

# 确保可以导入项目模块
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.log_config import get_logger
from utils.trace_context import get_current_trace

logger = get_logger("goal_planner", component="core")


class GoalStatus(Enum):
    """目标状态枚举"""
    PENDING = "pending"           # 待执行
    IN_PROGRESS = "in_progress"   # 执行中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败
    SKIPPED = "skipped"          # 跳过


@dataclass
class SubGoal:
    """子目标
    
    表示一个可执行的子目标，包含工具调用信息和依赖关系
    """
    id: str
    description: str
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: GoalStatus = GoalStatus.PENDING
    dependencies: List[str] = field(default_factory=list)  # 依赖的其他子目标ID
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "description": self.description,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubGoal":
        """从字典创建"""
        return cls(
            id=data["id"],
            description=data["description"],
            tool_name=data.get("tool_name"),
            parameters=data.get("parameters", {}),
            status=GoalStatus(data.get("status", "pending")),
            dependencies=data.get("dependencies", []),
            result=data.get("result"),
            error=data.get("error"),
            execution_time=data.get("execution_time", 0.0)
        )


@dataclass
class GoalPlan:
    """目标计划
    
    包含主目标和所有子目标，管理子目标执行状态
    """
    original_query: str
    main_goal: str
    sub_goals: List[SubGoal] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: __import__('time').time())
    
    def get_next_pending_goal(self) -> Optional[SubGoal]:
        """获取下一个待执行的子目标（考虑依赖关系）
        
        Returns:
            下一个可执行的子目标，如果没有则返回 None
        """
        for goal in self.sub_goals:
            if goal.status == GoalStatus.PENDING:
                # 检查依赖是否都已完成
                deps_completed = all(
                    self.get_goal_by_id(dep_id).status == GoalStatus.COMPLETED
                    for dep_id in goal.dependencies
                    if self.get_goal_by_id(dep_id)
                )
                if deps_completed:
                    return goal
        return None
    
    def get_goal_by_id(self, goal_id: str) -> Optional[SubGoal]:
        """根据ID获取子目标"""
        for goal in self.sub_goals:
            if goal.id == goal_id:
                return goal
        return None
    
    def is_complete(self) -> bool:
        """检查是否所有子目标都已完成"""
        if not self.sub_goals:
            return True
        return all(
            goal.status in [GoalStatus.COMPLETED, GoalStatus.SKIPPED, GoalStatus.FAILED]
            for goal in self.sub_goals
        )
    
    def get_progress(self) -> Dict[str, int]:
        """获取执行进度"""
        total = len(self.sub_goals)
        completed = sum(1 for g in self.sub_goals if g.status == GoalStatus.COMPLETED)
        failed = sum(1 for g in self.sub_goals if g.status == GoalStatus.FAILED)
        in_progress = sum(1 for g in self.sub_goals if g.status == GoalStatus.IN_PROGRESS)
        pending = sum(1 for g in self.sub_goals if g.status == GoalStatus.PENDING)
        
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": pending,
            "percentage": (completed / total * 100) if total > 0 else 100
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "original_query": self.original_query,
            "main_goal": self.main_goal,
            "sub_goals": [g.to_dict() for g in self.sub_goals],
            "created_at": self.created_at,
            "is_complete": self.is_complete(),
            "progress": self.get_progress()
        }


class GoalPlanner:
    """目标规划器
    
    使用 LLM 将复杂查询分解为子目标树
    """
    
    GOAL_DECOMPOSITION_PROMPT = """你是一个 Dota 2 游戏助手，负责将用户的复杂查询分解为可执行的子目标。

## 任务
分析用户查询，将其分解为一系列子目标。每个子目标应该：
1. 有明确的描述
2. 对应一个具体的工具（如果需要）
3. 可能有依赖关系（某些子目标需要先完成其他子目标）

## 可用工具

{tools_description}

## 用户查询

{query}

## 当前上下文

{context}

## 返回格式

请严格按照以下 JSON 格式返回：

```json
{{
    "main_goal": "主目标描述",
    "sub_goals": [
        {{
            "id": "goal_1",
            "description": "子目标描述",
            "tool_name": "工具名称（可选）",
            "parameters": {{
                "参数名": "参数值"
            }},
            "dependencies": []
        }},
        {{
            "id": "goal_2",
            "description": "子目标描述",
            "tool_name": "工具名称（可选）",
            "parameters": {{
                "参数名": "参数值"
            }},
            "dependencies": ["goal_1"]
        }}
    ]
}}
```

## 注意事项

1. 只分解必要的子目标，不要过度分解
2. 工具名称必须从可用工具列表中选择
3. 参数值从用户查询中提取，不要编造
4. 合理安排依赖关系，确保执行顺序正确
5. 必须返回有效的 JSON，不要添加额外内容"""
    
    def __init__(self, llm_client, tool_registry):
        """初始化目标规划器
        
        Args:
            llm_client: LLM 客户端
            tool_registry: 工具注册表
        """
        self.llm = llm_client
        self.registry = tool_registry
    
    def plan(self, query: str, context: Optional[Dict[str, Any]] = None) -> GoalPlan:
        """将查询分解为目标计划
        
        Args:
            query: 用户查询
            context: 上下文信息
            
        Returns:
            GoalPlan: 目标计划
        """
        trace_ctx = get_current_trace()
        logger.info_ctx(
            "开始目标分解",
            session_id=trace_ctx.session_id if trace_ctx else None,
            extra_data={"query": query}
        )
        
        # 获取工具描述
        tools_desc = self._format_tools_description()
        
        # 构造 prompt
        prompt = self.GOAL_DECOMPOSITION_PROMPT.format(
            tools_description=tools_desc,
            query=query,
            context=json.dumps(context or {}, ensure_ascii=False)
        )
        
        # 调用 LLM
        logger.info_ctx("调用 LLM 进行目标分解", session_id=trace_ctx.session_id if trace_ctx else None)
        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024
        )
        
        # 检查错误
        if "error" in response:
            error_msg = f"LLM 目标分解失败: {response['error']}"
            logger.warning_ctx(error_msg, session_id=trace_ctx.session_id if trace_ctx else None)
            # 返回单目标计划
            return GoalPlan(
                original_query=query,
                main_goal=query,
                sub_goals=[SubGoal(id="goal_1", description=query)]
            )
        
        # 解析结果
        try:
            content = response['choices'][0]['message']['content']
            plan_data = self._parse_plan(content)
            
            # 创建 GoalPlan
            sub_goals = [
                SubGoal(
                    id=g["id"],
                    description=g["description"],
                    tool_name=g.get("tool_name"),
                    parameters=g.get("parameters", {}),
                    dependencies=g.get("dependencies", [])
                )
                for g in plan_data.get("sub_goals", [])
            ]
            
            # 如果没有子目标，创建一个默认的
            if not sub_goals:
                sub_goals = [SubGoal(id="goal_1", description=query)]
            
            goal_plan = GoalPlan(
                original_query=query,
                main_goal=plan_data.get("main_goal", query),
                sub_goals=sub_goals
            )
            
            logger.info_ctx(
                "目标分解完成",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={
                    "main_goal": goal_plan.main_goal,
                    "sub_goals_count": len(goal_plan.sub_goals),
                    "sub_goals": [{"id": sg.id, "description": sg.description, "dependencies": sg.dependencies} for sg in goal_plan.sub_goals]
                }
            )
            
            return goal_plan
            
        except Exception as e:
            error_msg = f"解析目标计划失败: {str(e)}"
            logger.error_ctx(error_msg, session_id=trace_ctx.session_id if trace_ctx else None)
            # 返回单目标计划
            return GoalPlan(
                original_query=query,
                main_goal=query,
                sub_goals=[SubGoal(id="goal_1", description=query)]
            )
    
    def _format_tools_description(self) -> str:
        """格式化工具描述"""
        tools = self.registry.list_tools()
        if not tools:
            return "无可用工具"
        
        desc_parts = []
        for tool_name in tools:
            tool = self.registry.get(tool_name)
            if tool:
                schema = tool.get_schema()
                desc_parts.append(f"- {tool_name}: {schema['description']}")
        return "\n".join(desc_parts)
    
    def _parse_plan(self, content: str) -> Dict[str, Any]:
        """解析 LLM 返回的计划
        
        Args:
            content: LLM 返回的文本
            
        Returns:
            解析后的计划字典
        """
        # 尝试提取 JSON（可能包含在 markdown 代码块中）
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\{[\s\S]*\}', content, re.DOTALL)
            json_str = json_match.group() if json_match else content
        
        try:
            data = json.loads(json_str)
            
            # 验证必要字段
            if "main_goal" not in data:
                data["main_goal"] = "执行用户查询"
            
            if "sub_goals" not in data or not isinstance(data["sub_goals"], list):
                data["sub_goals"] = []
            
            return data
            
        except json.JSONDecodeError as e:
            logger.error_ctx(
                "JSON 解析失败",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={"error": str(e), "content_preview": content[:500]}
            )
            raise


class GoalTracker:
    """目标追踪器
    
    追踪目标计划的执行状态，提供进度查询
    """
    
    def __init__(self):
        self.active_plans: Dict[str, GoalPlan] = {}
    
    def register_plan(self, plan_id: str, plan: GoalPlan) -> None:
        """注册目标计划"""
        self.active_plans[plan_id] = plan
    
    def update_goal_status(self, plan_id: str, goal_id: str, 
                          status: GoalStatus, result: Any = None, 
                          error: Optional[str] = None) -> bool:
        """更新子目标状态
        
        Args:
            plan_id: 计划ID
            goal_id: 子目标ID
            status: 新状态
            result: 执行结果
            error: 错误信息
            
        Returns:
            是否更新成功
        """
        plan = self.active_plans.get(plan_id)
        if not plan:
            return False
        
        goal = plan.get_goal_by_id(goal_id)
        if not goal:
            return False
        
        goal.status = status
        if result is not None:
            goal.result = result
        if error is not None:
            goal.error = error
        
        return True
    
    def get_plan_progress(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """获取计划执行进度"""
        plan = self.active_plans.get(plan_id)
        if not plan:
            return None
        return plan.get_progress()
    
    def get_plan_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """获取计划完整状态"""
        plan = self.active_plans.get(plan_id)
        if not plan:
            return None
        return plan.to_dict()
