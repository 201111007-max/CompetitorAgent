"""并行执行器

管理工具的并行执行，处理异常和结果收集
"""

import asyncio
from typing import Dict, List, Any, Union, Tuple
from tools.base import ToolResult, ToolStatus
from utils.log_config import get_logger

logger = get_logger("parallel_executor", component="core")


class ParallelExecutor:
    """工具并行执行器

    管理工具的并行执行，处理异常和结果收集

    关键特性：
    - 使用 asyncio.Semaphore 控制最大并发数
    - 使用 asyncio.wait_for() 实现超时控制
    - 使用 asyncio.gather(return_exceptions=True) 实现宽松模式
    - 自动捕获异常，记录失败工具，继续执行其他工具
    """

    def __init__(
        self,
        tool_registry,
        max_concurrency: int = 5,
        timeout: float = 30.0
    ):
        """初始化

        Args:
            tool_registry: 工具注册表
            max_concurrency: 最大并发数（默认5）
            timeout: 单个工具超时时间（默认30秒）
        """
        self.tool_registry = tool_registry
        self.max_concurrency = max_concurrency
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrency)

        logger.info_ctx(
            "并行执行器初始化完成",
            extra_data={
                "max_concurrency": max_concurrency,
                "timeout": timeout
            }
        )

    async def execute_parallel(
        self,
        tools: List[str],
        tool_params: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Union[ToolResult, Exception]]:
        """并行执行工具

        Args:
            tools: 待执行的工具列表
            tool_params: 工具参数映射

        Returns:
            工具执行结果映射 {tool_name: ToolResult | Exception}
        """
        logger.info_ctx(
            "开始并行执行工具",
            extra_data={
                "tools": tools,
                "max_concurrency": self.max_concurrency,
                "timeout": self.timeout
            }
        )

        # 创建任务列表
        tasks = [
            self._execute_tool_with_error_handling(
                tool_name,
                tool_params.get(tool_name, {})
            )
            for tool_name in tools
        ]

        # 并行执行所有任务（宽松模式）
        results_list = await asyncio.gather(*tasks, return_exceptions=False)

        # 转换为字典格式
        results = {}
        for tool_name, result in zip(tools, results_list):
            results[tool_name] = result

        # 统计执行结果
        success_count = sum(1 for r in results.values() if isinstance(r, ToolResult) and r.is_success())
        failure_count = len(results) - success_count

        logger.info_ctx(
            "并行执行完成",
            extra_data={
                "total_count": len(results),
                "success_count": success_count,
                "failure_count": failure_count
            }
        )

        return results

    async def _execute_tool_with_error_handling(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> Union[ToolResult, Exception]:
        """执行单个工具（带错误处理）

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            工具执行结果或异常
        """
        async with self.semaphore:
            try:
                # 使用 asyncio.wait_for 实现超时控制
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.tool_registry.execute,
                        tool_name,
                        **params
                    ),
                    timeout=self.timeout
                )

                logger.debug_ctx(
                    f"工具执行成功: {tool_name}",
                    extra_data={
                        "tool_name": tool_name,
                        "params": params,
                        "execution_time": result.execution_time
                    }
                )

                return result

            except asyncio.TimeoutError:
                error_msg = f"工具执行超时: {tool_name} (timeout: {self.timeout}s)"
                logger.error_ctx(
                    error_msg,
                    extra_data={
                        "tool_name": tool_name,
                        "params": params,
                        "timeout": self.timeout
                    }
                )
                return TimeoutError(error_msg)

            except Exception as e:
                error_msg = f"工具执行异常: {tool_name} - {str(e)}"
                logger.error_ctx(
                    error_msg,
                    extra_data={
                        "tool_name": tool_name,
                        "params": params,
                        "error": str(e)
                    }
                )
                return Exception(error_msg)
