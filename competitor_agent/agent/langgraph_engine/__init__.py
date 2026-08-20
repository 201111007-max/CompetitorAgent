"""LangGraph 引擎包（设计文档 51）— 可切换的第二编排引擎

惰性导出：langgraph 为 optional extra，未安装时本包可正常 import，
只有真正构建图（run_langgraph）才触发 ImportError（可读安装指引）。
"""
from __future__ import annotations

from typing import Any

_INSTALL_HINT = 'LangGraph 引擎需要可选依赖：pip install -e ".[langgraph]"'


def ensure_langgraph_available() -> None:
    """构造期检查（设计文档 51 §2.2）：langgraph 未安装 → 可读 ImportError。"""
    try:
        import langgraph  # noqa: F401
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc


def __getattr__(name: str) -> Any:
    if name == "run_langgraph":
        ensure_langgraph_available()
        from competitor_agent.agent.langgraph_engine.engine import run_langgraph

        return run_langgraph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
