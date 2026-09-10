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
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from competitor_agent.agent.writer_slots import (
    NarrativeSlot,
    anchor_citations,
    build_slots,
    build_writer_messages,
    slot_allowed_numbers,
    validate_slot_prose,
)
from competitor_agent.config.loader import ReportConfig
from competitor_agent.core.markdown_renderer import MarkdownRenderer, inject_slots
from competitor_agent.domain_types.distilled import distill_report
from competitor_agent.domain_types.report import CompetitorReport
from competitor_agent.observability.logger import get_logger

logger = get_logger("facade.writer_pass")


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
    overall_confidence: float,
) -> str | None:
    """单槽 LLM 写作 + N2 校验重试；失败/两败 → None（调用方落降级注记）。"""
    if llm is None:
        return None
    allowed = slot_allowed_numbers(slot, overall_confidence=overall_confidence)
    messages = build_writer_messages(slot)
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


__all__ = ["maybe_run_writer_pass", "run_writer_pass"]
