"""writer pass 编排（设计文档 88 §4.4）

facade 收尾（``_finalize_competitor_report`` 顶部，双引擎汇聚点）调用：
``distill_report`` 蒸馏事实 → ``build_slots`` 三槽切分 → ``render_skeleton`` 代码骨架
→ 逐槽 LLM（串行，槽序稳定；``stream_sink`` 复用 doc 64 text_delta 通道）→
N2 保真校验（违规重试 ``writer_slot_max_retries`` 次，仍败降级）→ N3 引用锚定 →
``inject_slots`` 原地改写 ``report.markdown_report``。

降级两形态（钉死，无第三态）：
- writer 整体异常 → 不动 report（保持 assemble 产物 = legacy render）；
- 单槽异常/N2 两败 → 该槽「解读暂缺」注记，骨架与他槽照常。

mock/CI 确定性三层：① ``writer_pass=false``（默认）不走本模块；② mock LLM 检测
``WRITER_SYSTEM_MARKER`` 返回 ``MOCK_SLOT_PROSE``（无数字 → N2 必过）；③ 测试可
``prose_override`` 直注（不经 LLM）。

设计文档 95：comparison（compare/discovery）结论段接入 writer 体系——
``maybe_run_comparison_writer_pass`` 单槽（SLOT_CONCLUSION）从逐候选蒸馏事实
（``competitor`` 名入载荷）生成横向格局 prose；失败/关闭一律不追加结论段。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from competitor_agent.agent.writer_slots import (
    SLOT_CONCLUSION,
    NarrativeSlot,
    anchor_citations,
    build_slots,
    build_writer_messages,
    slot_allowed_numbers,
    validate_slot_prose,
)
from competitor_agent.config.loader import ReportConfig
from competitor_agent.core.markdown_renderer import MarkdownRenderer, inject_slots
from competitor_agent.domain_types.distilled import DimensionFacts, distill_report
from competitor_agent.domain_types.report import ComparisonReport, CompetitorReport
from competitor_agent.observability.logger import get_logger

logger = get_logger("facade.writer_pass")

# 设计文档 95：comparison 结论段标题（唯一合法来源 = writer LLM 从蒸馏事实生成的 prose）
_COMPARISON_CONCLUSION_HEADING = "## 市场格局核心结论"


def maybe_run_writer_pass(
    report: CompetitorReport,
    *,
    llm: Any,
    stream_sink: Callable[[Any], None] | None = None,
    config: ReportConfig,
    on_skeleton: Callable[[str], None] | None = None,
) -> None:
    """writer 总入口：整体异常 → log warning 且不动 report（降级形态一）。"""
    try:
        run_writer_pass(
            report,
            llm=llm,
            stream_sink=stream_sink,
            config=config,
            on_skeleton=on_skeleton,
        )
    except Exception:
        logger.warning("writer pass 整体失败，保持 assemble 产物（legacy 渲染）", exc_info=True)


def run_writer_pass(
    report: CompetitorReport,
    *,
    llm: Any,
    stream_sink: Callable[[Any], None] | None = None,
    config: ReportConfig,
    prose_override: dict[str, str] | None = None,
    on_skeleton: Callable[[str], None] | None = None,
) -> None:
    """骨架渲染 + 逐槽 prose + 注入，原地改写 ``report.markdown_report``。

    ``prose_override`` 非 None 时不经 LLM（测试直注）；缺键的槽走降级注记。
    ``on_skeleton`` 为骨架就绪钩子（SSE report_skeleton 事件，设计文档 88 §2.1）。
    """
    facts_by_dim = distill_report(report)
    slots = build_slots(report, facts_by_dim)
    skeleton = MarkdownRenderer().render_skeleton(report)
    if on_skeleton is not None:
        on_skeleton(skeleton)
    prose_by_slot: dict[str, str] = {}
    for slot in slots:
        if prose_override is not None:
            prose = (prose_override.get(slot.slot_id) or "").strip() or None
        else:
            prose = _write_slot(slot, llm, config, stream_sink, report.overall_confidence)
        if prose:
            prose_by_slot[slot.slot_id] = anchor_citations(slot, prose)
    report.markdown_report = inject_slots(skeleton, prose_by_slot)


def _write_slot(
    slot: NarrativeSlot,
    llm: Any,
    config: ReportConfig,
    stream_sink: Callable[[Any], None] | None,
    overall_confidence: float | None,
    *,
    comparison: bool = False,
) -> str | None:
    """单槽 LLM 写作 + N2 校验重试；失败/两败 → None（调用方落降级注记）。

    ``comparison=True``（设计文档 95）：横向格局指令形态，无 overall_confidence 口径。
    """
    if llm is None:
        return None
    allowed = slot_allowed_numbers(slot, overall_confidence=overall_confidence)
    messages = build_writer_messages(slot, comparison=comparison)
    attempts = 1 + max(0, config.writer_slot_max_retries)
    for attempt in range(attempts):
        try:
            reply = llm.complete_with_tools(
                messages, tools=[], stream_sink=stream_sink, final_as_payload=False
            )
        except Exception:
            # 单槽 LLM 异常：降级注记，不重试（异常不是内容问题，重试无意义）
            logger.warning("writer 槽位 %s LLM 调用失败，降级注记", slot.slot_id, exc_info=True)
            return None
        prose = str(getattr(reply, "content", "") or "").strip()
        if not prose:
            logger.warning("writer 槽位 %s 返回空内容，降级注记", slot.slot_id)
            return None
        violations = validate_slot_prose(slot, prose, allowed=allowed)
        if not violations:
            return prose
        if attempt < attempts - 1:
            messages = [
                *messages,
                {"role": "assistant", "content": prose},
                {
                    "role": "user",
                    "content": (
                        f"上次输出包含未授权数字: {', '.join(violations)}。"
                        "严格只用给定事实中的数字重写该段落。"
                    ),
                },
            ]
    logger.warning("writer 槽位 %s N2 校验 %d 次未过，降级注记", slot.slot_id, attempts)
    return None


def maybe_run_comparison_writer_pass(
    comparison: ComparisonReport,
    *,
    llm: Any,
    stream_sink: Callable[[Any], None] | None = None,
    config: ReportConfig,
    on_skeleton: Callable[[str], None] | None = None,
) -> None:
    """comparison 结论段 writer 总入口：整体异常 → log warning 且不动矩阵（降级形态一）。"""
    try:
        run_comparison_writer_pass(
            comparison,
            llm=llm,
            stream_sink=stream_sink,
            config=config,
            on_skeleton=on_skeleton,
        )
    except Exception:
        logger.warning("comparison writer pass 整体失败，保持矩阵产物", exc_info=True)


def run_comparison_writer_pass(
    comparison: ComparisonReport,
    *,
    llm: Any,
    stream_sink: Callable[[Any], None] | None = None,
    config: ReportConfig,
    prose_override: str | None = None,
    on_skeleton: Callable[[str], None] | None = None,
) -> None:
    """comparison 单槽（市场格局核心结论）写作 + 注入，原地改写 ``comparison.markdown_report``。

    设计文档 95：事实 = 逐候选 ``distill_report`` 且 ``competitor`` 名并入 facts 载荷；
    prose 成功 → 追加「## 市场格局核心结论」段（幂等：已有该标题则跳过）；
    prose 为 None（writer 关闭由调用方门控 / LLM 异常 / N2 两败 / 零候选）→ 不追加
    任何结论段——矩阵自身说话，绝不回退解析 Lead 文本（垃圾无入口）。
    """
    if _COMPARISON_CONCLUSION_HEADING in comparison.markdown_report:
        return
    all_facts: list[DimensionFacts] = []
    for report in comparison.reports:
        for df in distill_report(report):
            df.competitor = report.competitor.name
            all_facts.append(df)
    if not all_facts:
        return
    slot = NarrativeSlot(
        slot_id=SLOT_CONCLUSION,
        heading="市场格局核心结论",
        input_facts=all_facts,
    )
    if on_skeleton is not None:
        on_skeleton(comparison.markdown_report)
    if prose_override is not None:
        prose = prose_override.strip() or None
    else:
        prose = _write_slot(slot, llm, config, stream_sink, None, comparison=True)
    if not prose:
        return
    comparison.markdown_report = (
        comparison.markdown_report.rstrip()
        + f"\n\n{_COMPARISON_CONCLUSION_HEADING}\n\n"
        + anchor_citations(slot, prose)
        + "\n"
    )


__all__ = [
    "maybe_run_comparison_writer_pass",
    "maybe_run_writer_pass",
    "run_comparison_writer_pass",
    "run_writer_pass",
]
