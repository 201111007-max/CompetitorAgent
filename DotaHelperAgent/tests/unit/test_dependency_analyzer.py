# tests/unit/test_dependency_analyzer.py
import pytest
from core.dependency_analyzer import DependencyAnalyzer


def test_analyze_dependencies_no_dependencies():
    """测试无依赖关系的工具"""
    analyzer = DependencyAnalyzer()
    tools = ["get_hero_items", "get_hero_matchups"]
    tool_params = {
        "get_hero_items": {"hero_name": "axe"},
        "get_hero_matchups": {"hero_name": "axe"}
    }

    dependencies = analyzer.analyze_dependencies(tools, tool_params)

    # 两个工具参数完全独立，无依赖关系
    # 返回所有工具的依赖关系（包括空列表）
    assert dependencies == {
        "get_hero_items": [],
        "get_hero_matchups": []
    }


def test_analyze_dependencies_has_dependencies():
    """测试有依赖关系的工具"""
    analyzer = DependencyAnalyzer()
    tools = ["get_hero_matchups", "analyze_counter_picks"]
    tool_params = {
        "get_hero_matchups": {"hero_name": "axe"},
        "analyze_counter_picks": {"matchup_data": "from_get_hero_matchups"}
    }

    dependencies = analyzer.analyze_dependencies(tools, tool_params)

    # analyze_counter_picks 依赖 get_hero_matchups
    assert "analyze_counter_picks" in dependencies
    assert "get_hero_matchups" in dependencies["analyze_counter_picks"]


def test_get_parallel_groups_no_dependencies():
    """测试无依赖关系的工具分组"""
    analyzer = DependencyAnalyzer()
    tools = ["get_hero_items", "get_hero_matchups"]
    dependencies = {}

    groups = analyzer.get_parallel_groups(tools, dependencies)

    # 所有工具可以并行执行
    assert len(groups) == 1
    assert set(groups[0]) == set(tools)


def test_get_parallel_groups_has_dependencies():
    """测试有依赖关系的工具分组"""
    analyzer = DependencyAnalyzer()
    tools = ["get_hero_matchups", "analyze_counter_picks"]
    dependencies = {
        "analyze_counter_picks": ["get_hero_matchups"]
    }

    groups = analyzer.get_parallel_groups(tools, dependencies)

    # 应该分为两组，顺序执行
    assert len(groups) == 2
    assert groups[0] == ["get_hero_matchups"]
    assert groups[1] == ["analyze_counter_picks"]


def test_get_parallel_groups_circular_dependency():
    """测试循环依赖（降级到顺序执行）"""
    analyzer = DependencyAnalyzer()
    tools = ["tool_a", "tool_b"]
    dependencies = {
        "tool_a": ["tool_b"],
        "tool_b": ["tool_a"]
    }

    groups = analyzer.get_parallel_groups(tools, dependencies)

    # 循环依赖，降级到顺序执行
    assert len(groups) == 1
    assert set(groups[0]) == set(tools)


def test_has_circular_dependency_true():
    """测试检测到循环依赖"""
    analyzer = DependencyAnalyzer()
    dependencies = {
        "tool_a": ["tool_b"],
        "tool_b": ["tool_a"]
    }

    assert analyzer._has_circular_dependency(dependencies) == True


def test_has_circular_dependency_false():
    """测试无循环依赖"""
    analyzer = DependencyAnalyzer()
    dependencies = {
        "tool_a": ["tool_b"],
        "tool_b": []
    }

    assert analyzer._has_circular_dependency(dependencies) == False
