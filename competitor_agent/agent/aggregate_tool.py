"""aggregate_report 工具 — 聚合口径与收尾引导（设计文档 62 §3.3）

Lead 在 DISCOVERY/COMPARE 编排阶段调用：把 delegate 委派回来的候选/维度结论，
按 Lead 决策的聚合口径（``kind``：compare 明确对比 / position 普查格局）收拢，
并回填结构化收尾引导，使 Lead 下一轮 LLM 以 comparison JSON 作 Final Answer
（设计文档 95：结论 prose 走 writer 蒸馏通道，Lead 不再被要求写 conclusion 字段）。

职责边界：本工具只做**聚合决策声明 + 结构校验**（kind/dimensions），不调 LLM、
不渲染矩阵。矩阵仍由 ``ReportBuilder.build_comparison`` 渲染（执行层保留）。
"""
from __future__ import annotations

from typing import Any, Callable

from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.aggregate_tool")

_VALID_KINDS = ("compare", "position")


def make_aggregate_tool() -> Callable[..., str]:
    """构造 aggregate_report 工具（Lead 工具面注册用，不依赖外部状态）。

    - ``aggregate_report(parts, dimensions=None, kind="position") -> str``；
    - ``kind`` 非法 → ``ValueError``（经 ToolDispatcher 按可读回灌，Lead 可修正）；
    - 返回文本 = 决策声明 + 已收候选/维度 + comparison JSON 收尾引导。
    """

    def aggregate_report(
        parts: str,
        dimensions: list[str] | None = None,
        kind: str = "position",
    ) -> str:
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"aggregate_report kind 非法: {kind!r}，必须为 compare（明确对比）或 position（普查格局）。"
            )
        if not parts or not parts.strip():
            raise ValueError("aggregate_report parts 为空：请先完成候选分析（delegate）再聚合。")
        dims_text = "、".join(dimensions) if dimensions else "全部维度"
        logger.info(
            "aggregate_report 聚合决策（Lead）: kind=%s dimensions=%r", kind, dimensions
        )
        return (
            f"[aggregate_report 决策] 口径 kind={kind}；范围={dims_text}。\n"
            "以下为各候选竞品的已收集结论（页脚为部分候选缺失标注，可据此对齐）。\n"
            f"{parts}\n"
            "- 请以 comparison JSON 作最终答复：kind/dimensions/best_per_dimension/gaps "
            "照实填写；不要只交数据矩阵——矩阵与市场格局核心结论段由报告器另行渲染"
            "（结论走蒸馏事实生成，无需你撰写结论 prose）。"
        )

    return aggregate_report


def aggregate_payload_valid(payload: dict[str, Any]) -> bool:
    """聚合工具载荷的轻量结构校验（供重放/评测断言复用）。"""
    return payload.get("kind") in _VALID_KINDS


__all__ = ["aggregate_payload_valid", "make_aggregate_tool"]