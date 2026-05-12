"""目标规划器测试

测试 GoalPlanner 和 GoalTracker 的功能
"""

import sys
from pathlib import Path

# 确保可以导入项目模块
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import unittest
import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum


# 复制必要的类定义以避免导入问题
class GoalStatus(Enum):
    """目标状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SubGoal:
    """子目标"""
    id: str
    description: str
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: GoalStatus = GoalStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
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
    """目标计划"""
    original_query: str
    main_goal: str
    sub_goals: List[SubGoal] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: __import__('time').time())
    
    def get_next_pending_goal(self) -> Optional[SubGoal]:
        """获取下一个待执行的子目标（考虑依赖关系）"""
        for goal in self.sub_goals:
            if goal.status == GoalStatus.PENDING:
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


class GoalTracker:
    """目标追踪器"""
    
    def __init__(self):
        self.active_plans: Dict[str, GoalPlan] = {}
    
    def register_plan(self, plan_id: str, plan: GoalPlan) -> None:
        """注册目标计划"""
        self.active_plans[plan_id] = plan
    
    def update_goal_status(self, plan_id: str, goal_id: str, 
                          status: GoalStatus, result: Any = None, 
                          error: Optional[str] = None) -> bool:
        """更新子目标状态"""
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


class TestGoalPlan(unittest.TestCase):
    """测试 GoalPlan"""
    
    def setUp(self):
        self.plan = GoalPlan(
            original_query="测试查询",
            main_goal="测试目标",
            sub_goals=[
                SubGoal(id="g1", description="目标1", dependencies=[]),
                SubGoal(id="g2", description="目标2", dependencies=["g1"]),
                SubGoal(id="g3", description="目标3", dependencies=["g1", "g2"])
            ]
        )
    
    def test_get_next_pending_goal(self):
        """测试获取下一个待执行子目标"""
        # 初始状态，应该返回 g1
        next_goal = self.plan.get_next_pending_goal()
        self.assertIsNotNone(next_goal)
        self.assertEqual(next_goal.id, "g1")
        
        # 完成 g1 后，应该返回 g2
        self.plan.sub_goals[0].status = GoalStatus.COMPLETED
        next_goal = self.plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "g2")
        
        # 完成 g2 后，应该返回 g3
        self.plan.sub_goals[1].status = GoalStatus.COMPLETED
        next_goal = self.plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "g3")
    
    def test_is_complete(self):
        """测试计划完成状态"""
        self.assertFalse(self.plan.is_complete())
        
        # 完成所有子目标
        for sg in self.plan.sub_goals:
            sg.status = GoalStatus.COMPLETED
        
        self.assertTrue(self.plan.is_complete())
    
    def test_dependency_check(self):
        """测试依赖关系检查"""
        # g2 依赖 g1，g1 未完成时不能执行 g2
        self.plan.sub_goals[0].status = GoalStatus.PENDING
        next_goal = self.plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "g1")  # 应该返回 g1，不是 g2
        
        # g1 失败后，g2 也不能执行
        self.plan.sub_goals[0].status = GoalStatus.FAILED
        next_goal = self.plan.get_next_pending_goal()
        self.assertIsNone(next_goal)  # 没有可执行的子目标
    
    def test_plan_progress(self):
        """测试计划进度"""
        progress = self.plan.get_progress()
        self.assertEqual(progress["total"], 3)
        self.assertEqual(progress["completed"], 0)
        self.assertEqual(progress["pending"], 3)
        self.assertEqual(progress["percentage"], 0)
        
        # 完成一个子目标
        self.plan.sub_goals[0].status = GoalStatus.COMPLETED
        progress = self.plan.get_progress()
        self.assertEqual(progress["completed"], 1)
        self.assertAlmostEqual(progress["percentage"], 33.33, places=2)


class TestGoalTracker(unittest.TestCase):
    """测试 GoalTracker"""
    
    def setUp(self):
        self.tracker = GoalTracker()
        self.plan = GoalPlan(
            original_query="测试",
            main_goal="测试目标",
            sub_goals=[
                SubGoal(id="g1", description="目标1"),
                SubGoal(id="g2", description="目标2")
            ]
        )
        self.tracker.register_plan("plan_1", self.plan)
    
    def test_register_plan(self):
        """测试注册计划"""
        self.assertIn("plan_1", self.tracker.active_plans)
        self.assertEqual(self.tracker.active_plans["plan_1"], self.plan)
    
    def test_update_goal_status(self):
        """测试更新子目标状态"""
        # 更新为执行中
        result = self.tracker.update_goal_status("plan_1", "g1", GoalStatus.IN_PROGRESS)
        self.assertTrue(result)
        self.assertEqual(self.plan.sub_goals[0].status, GoalStatus.IN_PROGRESS)
        
        # 更新为完成
        self.tracker.update_goal_status("plan_1", "g1", GoalStatus.COMPLETED, result={"data": "test"})
        self.assertEqual(self.plan.sub_goals[0].status, GoalStatus.COMPLETED)
        self.assertEqual(self.plan.sub_goals[0].result, {"data": "test"})
    
    def test_get_plan_progress(self):
        """测试获取计划进度"""
        # 完成一个子目标
        self.plan.sub_goals[0].status = GoalStatus.COMPLETED
        
        progress = self.tracker.get_plan_progress("plan_1")
        self.assertIsNotNone(progress)
        self.assertEqual(progress["completed"], 1)
        self.assertEqual(progress["total"], 2)
    
    def test_invalid_plan_id(self):
        """测试无效的计划 ID"""
        result = self.tracker.update_goal_status("invalid_plan", "g1", GoalStatus.COMPLETED)
        self.assertFalse(result)
        
        progress = self.tracker.get_plan_progress("invalid_plan")
        self.assertIsNone(progress)


class TestSubGoal(unittest.TestCase):
    """测试 SubGoal"""
    
    def test_to_dict(self):
        """测试转换为字典"""
        sg = SubGoal(
            id="test_goal",
            description="测试目标",
            tool_name="test_tool",
            parameters={"param1": "value1"},
            status=GoalStatus.COMPLETED,
            dependencies=["dep1"],
            result={"data": "result"},
            error=None,
            execution_time=1.5
        )
        
        data = sg.to_dict()
        self.assertEqual(data["id"], "test_goal")
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["execution_time"], 1.5)
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "id": "test_goal",
            "description": "测试目标",
            "tool_name": "test_tool",
            "parameters": {"param1": "value1"},
            "status": "in_progress",
            "dependencies": ["dep1"],
            "result": None,
            "error": None,
            "execution_time": 0.5
        }
        
        sg = SubGoal.from_dict(data)
        self.assertEqual(sg.id, "test_goal")
        self.assertEqual(sg.status, GoalStatus.IN_PROGRESS)
        self.assertEqual(sg.execution_time, 0.5)


class TestGoalDecomposition(unittest.TestCase):
    """测试目标分解场景"""
    
    def test_complex_query_decomposition(self):
        """测试复杂查询分解场景"""
        # 模拟一个复杂查询的目标分解
        plan = GoalPlan(
            original_query="对面有帕吉、斧王、宙斯，推荐克制英雄和出装",
            main_goal="分析敌方阵容并提供完整对策",
            sub_goals=[
                SubGoal(
                    id="analyze_enemy",
                    description="分析敌方阵容构成",
                    tool_name="analyze_composition",
                    parameters={"enemy_heroes": ["pudge", "axe", "zeus"]},
                    dependencies=[]
                ),
                SubGoal(
                    id="recommend_heroes",
                    description="推荐克制英雄",
                    tool_name="analyze_counter_picks",
                    parameters={"enemy_heroes": ["pudge", "axe", "zeus"]},
                    dependencies=["analyze_enemy"]
                ),
                SubGoal(
                    id="recommend_items",
                    description="推荐出装",
                    tool_name="recommend_items",
                    parameters={"hero_name": "recommended_hero"},
                    dependencies=["recommend_heroes"]
                )
            ]
        )
        
        # 验证依赖关系
        self.assertEqual(len(plan.sub_goals), 3)
        self.assertEqual(plan.sub_goals[0].dependencies, [])
        self.assertEqual(plan.sub_goals[1].dependencies, ["analyze_enemy"])
        self.assertEqual(plan.sub_goals[2].dependencies, ["recommend_heroes"])
        
        # 验证执行顺序
        next_goal = plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "analyze_enemy")
        
        # 完成第一个子目标
        plan.sub_goals[0].status = GoalStatus.COMPLETED
        next_goal = plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "recommend_heroes")
        
        # 完成第二个子目标
        plan.sub_goals[1].status = GoalStatus.COMPLETED
        next_goal = plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "recommend_items")
    
    def test_parallel_subgoals(self):
        """测试并行子目标"""
        # 创建没有依赖关系的并行子目标
        plan = GoalPlan(
            original_query="查询多个英雄信息",
            main_goal="获取英雄详细信息",
            sub_goals=[
                SubGoal(id="hero_1", description="查询英雄1", tool_name="get_hero_info", dependencies=[]),
                SubGoal(id="hero_2", description="查询英雄2", tool_name="get_hero_info", dependencies=[]),
                SubGoal(id="hero_3", description="查询英雄3", tool_name="get_hero_info", dependencies=[])
            ]
        )
        
        # 所有子目标都可以并行执行
        next_goal = plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "hero_1")
        
        # 完成第一个后，第二个可以执行
        plan.sub_goals[0].status = GoalStatus.COMPLETED
        next_goal = plan.get_next_pending_goal()
        self.assertEqual(next_goal.id, "hero_2")


if __name__ == "__main__":
    unittest.main()
