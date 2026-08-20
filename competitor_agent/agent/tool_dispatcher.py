"""ToolDispatcher — 将 Agent 的 Action 分发到本地工具注册表

M1 为本地同步工具分发（MCP Server 在 M4 接入）。
工具以 {name: Callable} 注册，可被 ReAct 循环调用。

设计文档 38：注册带 JSON Schema 契约（ToolSpec）、dispatch 前参数校验（ToolArgumentError）、
可选超时执行、描述含参数类型——让 LLM 看到参数契约并在参数错误时自恢复。
"""
from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.tool_dispatcher")


@dataclass
class ToolSpec:
    """工具注册契约（设计文档 38）：name/func + 描述 + JSON Schema 子集 + 超时"""

    name: str
    func: Callable[..., str]
    description: str = ""
    params_schema: dict[str, Any] | None = None  # JSON Schema 子集：type/required/properties/enum
    timeout: float | None = None  # 秒；None 用 dispatcher 默认（再 None 则无超时）


class ToolArgumentError(ValueError):
    """工具参数校验失败（携带可读原因，供回灌 Observation）"""


class ToolDispatcher:
    """本地工具分发器"""

    def __init__(
        self,
        tools: dict[str, Callable[..., str]] | None = None,
        *,
        default_timeout: float | None = None,
    ) -> None:
        self._tools: dict[str, Callable[..., str]] = {}
        self._specs: dict[str, ToolSpec] = {}
        self._default_timeout = default_timeout
        for name, func in (tools or {}).items():
            self.register(name, func)

    def register(
        self,
        name: str,
        func: Callable[..., str],
        *,
        spec: ToolSpec | None = None,
    ) -> None:
        """注册工具；未给 spec 时建默认契约（无 schema/描述）。"""
        self._tools[name] = func
        self._specs[name] = spec or ToolSpec(name=name, func=func)

    def validate_tool(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def dispatch(self, tool_name: str, args: dict[str, Any] | None = None) -> str:
        """调用工具并返回文本结果。

        工具不存在抛 ValueError；参数不合 schema 抛 ToolArgumentError（可读原因）；
        超时返回可读文本（不悬挂循环）；执行异常原样冒泡由上层回灌。
        """
        args = args or {}
        spec = self._specs.get(tool_name)
        if spec is None:
            raise ValueError(f"工具 '{tool_name}' 未注册")
        if spec.params_schema:
            problems = LLMClient._validate_schema(args, spec.params_schema)
            if problems:
                raise ToolArgumentError(f"参数校验失败: {'；'.join(problems)}")
        timeout = spec.timeout if spec.timeout is not None else self._default_timeout
        func = self._tools[tool_name]
        logger.info("分发工具: %s args=%s", tool_name, args)
        if timeout is None:
            return str(func(**args))
        return self._call_with_timeout(func, args, tool_name, timeout)

    def _call_with_timeout(self, func: Callable, args: dict, tool_name: str, timeout: float) -> str:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(func, **args)
        try:
            return str(future.result(timeout))
        except TimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            return f"工具执行超时: {tool_name}"
        finally:
            if future.done() and not future.cancelled():
                executor.shutdown(wait=True)  # 正常完成路径快速回收；超时路径已 wait=False

    def get_tool_descriptions(self) -> str:
        """生成可注入 System Prompt 的工具描述（含参数类型与描述，设计文档 38）"""
        lines = []
        for name in self._tools:
            spec = self._specs[name]
            params = self._describe_params(name, spec)
            line = f"- {name}({params})"
            if spec.description:
                line += f" — {spec.description}"
            lines.append(line)
        return "\n".join(lines) if lines else "（暂无可用工具）"

    def _describe_params(self, name: str, spec: ToolSpec) -> str:
        schema = spec.params_schema
        if schema and schema.get("properties"):
            required = set(schema.get("required") or [])
            parts = []
            for pname, pdef in schema["properties"].items():
                ptype = pdef.get("type", "any")
                marker = ":" if pname in required else "?:"
                parts.append(f"{pname}{marker}{ptype}")
            return ", ".join(parts)
        sig = inspect.signature(self._tools[name])
        parts = []
        for p in sig.parameters.values():
            if p.name in ("self", "cls"):
                continue
            ann = p.annotation
            typename = getattr(ann, "__name__", "any") if ann is not inspect.Parameter.empty else "any"
            marker = ":" if p.default is inspect.Parameter.empty else "?:"
            parts.append(f"{p.name}{marker}{typename}")
        return ", ".join(parts)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def specs(self) -> dict[str, ToolSpec]:
        """已注册工具的契约表（设计文档 53：build_openai_tools 转换器读取）。"""
        return dict(self._specs)
