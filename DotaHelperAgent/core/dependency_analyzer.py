"""工具依赖分析器

分析工具之间的依赖关系，判断哪些工具可以并行执行
"""

from typing import Dict, List, Set, Any
from utils.log_config import get_logger

logger = get_logger("dependency_analyzer", component="core")


class DependencyAnalyzer:
    """工具依赖分析器

    分析工具之间的依赖关系，判断哪些工具可以并行执行

    依赖判断规则：
    - 如果工具 A 的参数中包含工具 B 的输出数据，则 A 依赖 B
    - 如果两个工具的参数完全独立，则可以并行执行
    - 如果两个工具都依赖同一个上游工具，但彼此独立，则可以并行执行
    """

    def analyze_dependencies(
        self,
        tools: List[str],
        tool_params: Dict[str, Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """分析工具依赖关系

        Args:
            tools: 待执行的工具列表
            tool_params: 工具参数映射 {tool_name: {param_name: param_value}}

        Returns:
            依赖关系映射 {tool_name: [dependent_tool_names]}
        """
        dependencies: Dict[str, List[str]] = {}

        # 为每个工具分析依赖关系
        for tool_name in tools:
            dependencies[tool_name] = []
            params = tool_params.get(tool_name, {})

            # 检查参数中是否包含其他工具的输出数据
            for param_name, param_value in params.items():
                # 如果参数值是字符串，且包含 "from_<tool_name>" 格式，则认为有依赖
                if isinstance(param_value, str) and param_value.startswith("from_"):
                    # 提取依赖的工具名
                    dependent_tool = param_value.replace("from_", "")
                    if dependent_tool in tools and dependent_tool != tool_name:
                        dependencies[tool_name].append(dependent_tool)

                        logger.debug_ctx(
                            f"发现工具依赖: {tool_name} -> {dependent_tool}",
                            extra_data={
                                "tool_name": tool_name,
                                "dependent_tool": dependent_tool,
                                "param_name": param_name,
                                "param_value": param_value
                            }
                        )

        logger.info_ctx(
            "依赖分析完成",
            extra_data={
                "tools": tools,
                "dependencies": dependencies,
                "has_dependencies": any(deps for deps in dependencies.values())
            }
        )

        return dependencies

    def get_parallel_groups(
        self,
        tools: List[str],
        dependencies: Dict[str, List[str]]
    ) -> List[List[str]]:
        """获取可并行执行的工具分组

        Args:
            tools: 待执行的工具列表
            dependencies: 依赖关系映射

        Returns:
            工具分组列表，每组内的工具可以并行执行
        """
        # 检查循环依赖
        if self._has_circular_dependency(dependencies):
            logger.warning_ctx(
                "发现循环依赖，降级到顺序执行",
                extra_data={"tools": tools, "dependencies": dependencies}
            )
            return [tools]  # 所有工具顺序执行

        # 使用拓扑排序分组
        groups = self._topological_sort(tools, dependencies)

        logger.info_ctx(
            "工具分组完成",
            extra_data={
                "tools": tools,
                "groups": groups,
                "group_count": len(groups)
            }
        )

        return groups

    def _has_circular_dependency(self, dependencies: Dict[str, List[str]]) -> bool:
        """检查是否存在循环依赖

        Args:
            dependencies: 依赖关系映射

        Returns:
            是否存在循环依赖
        """
        # 使用 DFS 检测循环依赖
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(tool: str) -> bool:
            visited.add(tool)
            rec_stack.add(tool)

            for dependent in dependencies.get(tool, []):
                if dependent not in visited:
                    if has_cycle(dependent):
                        return True
                elif dependent in rec_stack:
                    return True

            rec_stack.remove(tool)
            return False

        for tool in dependencies:
            if tool not in visited:
                if has_cycle(tool):
                    return True

        return False

    def _topological_sort(
        self,
        tools: List[str],
        dependencies: Dict[str, List[str]]
    ) -> List[List[str]]:
        """拓扑排序，将工具分为多个并行组

        Args:
            tools: 待执行的工具列表
            dependencies: 依赖关系映射

        Returns:
            工具分组列表
        """
        # 计算每个工具的入度（依赖数量）
        in_degree: Dict[str, int] = {tool: 0 for tool in tools}
        for tool, deps in dependencies.items():
            in_degree[tool] = len(deps)

        groups: List[List[str]] = []
        remaining_tools = set(tools)

        while remaining_tools:
            # 找出所有入度为 0 的工具（无依赖）
            current_group = [
                tool for tool in remaining_tools
                if in_degree[tool] == 0
            ]

            if not current_group:
                # 如果没有入度为 0 的工具，说明有循环依赖（理论上不应该到达这里）
                logger.warning_ctx(
                    "拓扑排序异常：没有入度为0的工具，可能存在循环依赖",
                    extra_data={"remaining_tools": remaining_tools, "in_degree": in_degree}
                )
                current_group = list(remaining_tools)

            groups.append(current_group)

            # 移除当前组的工具，并更新入度
            for tool in current_group:
                remaining_tools.remove(tool)

                # 更新依赖当前工具的其他工具的入度
                for other_tool in remaining_tools:
                    if tool in dependencies.get(other_tool, []):
                        in_degree[other_tool] -= 1

        return groups
