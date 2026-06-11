#!/usr/bin/env python
"""验证并行执行是否生效的脚本

运行此脚本可以看到：
1. 顺序执行时间
2. 并行执行时间
3. 性能提升百分比
"""

import asyncio
import time
from unittest.mock import Mock
from core.parallel_executor import ParallelExecutor
from core.parallel_execution_config import ParallelExecutionConfig
from tools.base import ToolResult, ToolStatus


class TestTool:
    """测试工具"""

    def __init__(self, name: str, delay: float):
        self.name = name
        self.delay = delay

    def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        print(f"[{time.strftime('%H:%M:%S')}] 开始执行 {self.name}")
        time.sleep(self.delay)  # 模拟耗时操作
        print(f"[{time.strftime('%H:%M:%S')}] 完成 {self.name}")
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            data={"result": f"success_{self.name}"}
        )


async def verify_parallel_execution():
    """验证并行执行"""
    print("=" * 60)
    print("并行执行验证脚本")
    print("=" * 60)

    # 创建模拟工具注册表
    mock_registry = Mock()

    # 创建测试工具（每个工具耗时不同）
    tools = {
        "tool_1s": TestTool("tool_1s", 1.0),
        "tool_2s": TestTool("tool_2s", 2.0),
        "tool_3s": TestTool("tool_3s", 3.0),
    }

    def mock_execute(tool_name, **kwargs):
        return tools[tool_name].execute(**kwargs)

    mock_registry.execute = mock_execute
    mock_registry.tools = tools

    # 创建并行执行器
    executor = ParallelExecutor(
        tool_registry=mock_registry,
        max_concurrency=5,
        timeout=30.0
    )

    # 计算顺序执行的理论时间
    sequential_time = 1.0 + 2.0 + 3.0  # 6秒
    print(f"\n理论顺序执行时间: {sequential_time}秒")
    print("  - tool_1s: 1秒")
    print("  - tool_2s: 2秒")
    print("  - tool_3s: 3秒")

    # 执行并行测试
    print(f"\n开始并行执行...")
    tool_names = ["tool_1s", "tool_2s", "tool_3s"]
    tool_params = {tool: {} for tool in tool_names}

    start_time = time.time()
    results = await executor.execute_parallel(tool_names, tool_params)
    parallel_time = time.time() - start_time

    # 显示结果
    print(f"\n并行执行时间: {parallel_time:.2f}秒")
    print(f"理论并行时间: 3秒 (最长的工具时间)")

    # 计算性能提升
    improvement = ((sequential_time - parallel_time) / sequential_time) * 100
    print(f"\n性能提升: {improvement:.2f}%")

    # 验证结果
    print("\n验证结果:")
    if parallel_time < sequential_time * 0.6:  # 应该小于顺序时间的60%
        print("✅ 并行执行生效！执行时间显著减少")
    else:
        print("❌ 并行执行可能未生效，请检查配置")

    if abs(parallel_time - 3.0) < 0.5:  # 应该接近最长工具时间
        print("✅ 并行执行时间接近最长工具时间")
    else:
        print("⚠️  并行执行时间与预期不符")

    # 检查配置
    print("\n配置检查:")
    config = ParallelExecutionConfig()
    print(f"  - 并行执行启用: {config.is_enabled()}")
    print(f"  - 最大并发数: {config.get_max_concurrency()}")
    print(f"  - 超时时间: {config.get_timeout()}秒")
    print(f"  - 依赖分析启用: {config.is_dependency_analysis_enabled()}")
    print(f"  - 异步执行启用: {config.is_async_execution_enabled()}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(verify_parallel_execution())
