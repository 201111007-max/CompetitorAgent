"""Lead Final Answer → CompetitorReport 组装（设计文档 49 §3.4）

解析 Lead 的 REPORT_SCHEMA JSON（competitor + dimensions[{dimension, summary,
details, confidence, evidence_urls}]）→ 多维度 ``DimensionResult`` → CompetitorReport
（复用 ``ReportBuilder`` 渲染/freshness）。

设计文档 65 §2：JSON 提取健壮化——Lead Final Answer 可能带散文前缀
（"数据已齐备。以下是最终竞品分析报告。\\n\\n{...json...}"），``_parse_report`` 不再要求
整体以 ``{`` 开头，改用 ``_extract_json_block`` 括号配平提取首个平衡 JSON 对象；
提取失败时兜底净化（剔除 JSON 块，只留纯散文）。

兜底：
- 非 JSON / 缺 dimensions → 单 ``react`` 维度 PARTIAL（解析健壮性，非规则决策）；
- 数值真值核对：details 非空但无证据 URL 的维度 → 置信度封顶 0.5 并标注；
- 跨维度同源冲突（按证据 URL 键，``detect_conflicts_across``）→ 报告追加
  「## 跨维度冲突备注」（复用 49 旧版渲染约定）；
- plan 中声明但报告未产出的维度 → ``gaps_pending`` 列明（供 resume/预算判定）。
"""
from __future__ import annotations

import re
from typing import Any

from competitor_agent.core.json_extract import (
    extract_json_block,
    light_fix_json,
    parse_json_candidate,
)
from competitor_agent.core.report_aggregator import (
    aggregate_researcher_results,
    dimension_from_item,
    planned_dimensions,
)
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.observability.logger import get_logger

logger = get_logger("facade.react_report")

# 向后兼容别名（设计文档 87 §3.1：基建下移 core/json_extract，纯平移语义不变；
# comparison_report 与既有测试仍引用旧名）
_extract_json_block = extract_json_block
_light_fix_json = light_fix_json
_parse_json_candidate = parse_json_candidate

# 向后兼容别名（设计文档 88 §4.1：聚合逻辑平移 core/report_aggregator，纯平移语义不变）
_dimension_from_item = dimension_from_item
_planned_dimensions = planned_dimensions


def assemble(
    lead_answer: str,
    competitor: Competitor,
    loop_plan: dict[str, Any] | None,
    transcript: list[dict] | None = None,
    builder: Any | None = None,
    terminal_state: str = "success",
    error_kind: str = "",
) -> CompetitorReport:
    """把 Lead Final Answer 组装为 CompetitorReport（设计文档 88 单一事实源）。

    设计文档 88 §7 第 7 步（两段式退役）：Lead Final Answer 只含 REPORT_SCHEMA JSON，
    散文正文不再消费——``_parse_report`` 括号配平提取 payload →
    ``aggregate_researcher_results`` 确定性合并 → ``ReportBuilder.build`` 代码渲染；
    ``writer_pass`` 开启时正文由 facade 收尾的 writer pass 以骨架+叙事槽改写
    （见 ``facade/writer_pass.py``）。Lead 答非 JSON（解析失败/超步数/取消）→
    ``_fallback_single_dimension`` 兜底（净化链仍生效）。
    """
    from competitor_agent.core.report_builder import ReportBuilder

    builder = builder or ReportBuilder()
    payload = _parse_report(lead_answer)
    if payload is None:
        return _fallback_single_dimension(
            lead_answer, competitor, builder, terminal_state, loop_plan, error_kind=error_kind
        )

    # 聚合层（设计文档 88 §4.1，N1）：确定性合并 + 冲突检测 + planned/produced 对账
    agg = aggregate_researcher_results(payload.get("dimensions") or [], loop_plan)
    dimensions = agg.dimensions
    conflict_note = agg.conflict_note
    gaps_pending = agg.gaps_pending

    report = builder.build(
        competitor=competitor,
        results=dimensions,
        gaps_pending=gaps_pending,
        terminal_state=terminal_state,
    )
    if conflict_note and report.markdown_report:
        report.markdown_report = report.markdown_report.rstrip() + "\n\n" + conflict_note
    return report


def _dedupe_repeated_report(text: str) -> str:
    """正文去重（设计文档 73 §3.1）：含 2+ 个 H1 标题（^# ）时只保留最后一个 H1 起的内容。

    触发条件：合法报告仅 1 个 H1；出现 ≥2 即「草稿 + 正式稿」形态，取尾（正式稿在后，
    实证含完整聚合 JSON）。正常单 H1 文本逐字节不变（黄金回归安全）。
    复查（2026-08-30）：跳过 ``` 围栏内（代码示例）的 ``# `` 行，避免把示例注释误当第二个 H1。
    """
    if not text:
        return text
    in_fence = False
    h1_positions: list[int] = []
    for m in re.finditer(r"^```[^\n]*$|^#\s+[^\n]*", text, re.MULTILINE):
        if m.group(0).startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            h1_positions.append(m.start())
    return text[h1_positions[-1]:] if len(h1_positions) >= 2 else text


def _close_orphan_fence(text: str) -> str:
    """未闭合围栏兜底（设计文档 73 §3.2）：`` ``` `` 开/闭计数失衡（开 > 闭）时文末补闭合。

    对任意章节的截断生效；围栏已配平则原样返回（正常文本零改动）。
    """
    if text and text.count("```") % 2 != 0:
        return text.rstrip() + "\n```\n"
    return text


def _parse_report(answer: str) -> dict[str, Any] | None:
    """解析 REPORT_SCHEMA JSON；非 JSON/缺 dimensions → None。

    设计文档 65 §2：改用 ``_extract_json_block`` 从"散文前缀 + JSON"中提取首个平衡
    JSON 对象（不再要求整体以 ``{`` 开头）。提取成功且含 ``dimensions`` 列表 →
    返回 payload；提取成功但缺 ``dimensions`` → 尝试取 ``conclusion``/``summary``/
    ``answer`` 字段作为单 react 维度正文（可溯源），否则 None。
    """
    text = (answer or "").strip()
    if not text:
        return None
    payload = _extract_json_block(text)
    if payload is None:
        return None
    if isinstance(payload.get("dimensions"), list):
        return payload
    # 取出 dict 但缺 dimensions → 可溯源的单 react 维度正文（设计文档 65 §2.2）
    for key in ("conclusion", "summary", "answer"):
        val = payload.get(key)
        if val:
            return {
                "dimensions": [
                    {
                        "dimension": "react",
                        "summary": str(val),
                        "details": {},
                        "confidence": 0.4,
                        "evidence_urls": [],
                    }
                ]
            }
    return None



def _looks_like_json_block(candidate: str) -> bool:
    """判定一块 ``{...}`` 是否"像报告 JSON dump"（设计文档 66 §3.3）。

    仅对含报告/对比 JSON 关键键（``competitor``/``competitors``/``dimensions``/
    ``conclusion``/``kind``）的平衡块强制剔除——即使 ``json.loads`` 失败（模型手滑畸形）
    也按 dump 处理；普通散文花括号不受影响。``conclusion``/``kind``/``competitors``
    为设计文档 70 M1 对比 JSON（aggregate_report 聚合结论）的键。
    """
    if not candidate.startswith("{"):
        return False
    for key in ("competitor", "competitors", "dimensions", "conclusion", "kind"):
        if f'"{key}"' in candidate:
            return True
    return False


def _strip_json_blocks(text: str) -> str:
    """剔除文本中的 JSON 块，只保留纯散文（设计文档 65 §2.2 兜底净化）。

    括号配平定位每个顶层 JSON 对象（与 ``_extract_json_block`` 同算法），命中即移除；
    设计文档 66 §3.3：判定收敛到 ``_looks_like_json_block``——对"像报告 JSON 的块"
    （含 competitor/dimensions 键）即使 ``json.loads`` 失败也强制剔除，普通散文花括号
    不被误删。
    """
    if not text:
        return ""
    out: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        start = text.find("{", pos)
        if start == -1:
            out.append(text[pos:])
            break
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for i in range(start, n):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        candidate = text[start : end + 1] if end != -1 else text[start:]
        # 仅剔除"像报告 JSON dump 的块"（含 competitor/dimensions 键）；空 {} 与
        # 纯散文花括号保留（Lead 真实 JSON dump 必含报告键）
        if _looks_like_json_block(candidate):
            out.append(text[pos:start])
            pos = end + 1 if end != -1 else n
        else:
            # 非 JSON 的 {…}：保留单个字符继续扫描（避免死循环）
            out.append(text[pos : start + 1])
            pos = start + 1
    cleaned = "".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _fallback_single_dimension(
    answer: str,
    competitor: Competitor,
    builder: Any,
    terminal_state: str,
    loop_plan: dict[str, Any] | None = None,
    *,
    error_kind: str = "",
) -> CompetitorReport:
    """非 JSON / 无 dimensions：单 react 维度 PARTIAL（LLM 不可用/超步数文案）。

    设计文档 65 §2.2 兜底净化：即使无有效 JSON，赋给 react 维度 summary 前先剔除文中
    的 JSON 块（复用括号配平定位），只保留纯散文——用户不再看到一坨 JSON dump；
    doc 73 P1 净化链（H1 归并去重 + 未闭合围栏兜底）在兜底路径继续生效
    （设计文档 88 步骤 7：两段式正文退役后，这是净化链唯一存活消费方）。

    设计文档 87 §1.3：unavailable 判定改结构化信号——``error_kind`` 非空（unavailable/
    max_steps/stopped）即非正常终止，置信度 0.1；不再做中文字符串包含匹配。

    plan 已声明但未产出的维度 → gaps_pending（供 resume/预算判定），与
    assemble() 正常路径一致。
    """
    text = (answer or "").strip()
    if text:
        text = _close_orphan_fence(_dedupe_repeated_report(_strip_json_blocks(text)))
    status = ResultStatus.PARTIAL
    confidence = 0.1 if error_kind else 0.4
    dr = DimensionResult(
        dimension="react",
        summary=text or "（Lead Agent 未产出结构化结论）",
        details={},
        confidence=confidence,
        status=status,
    )
    planned = _planned_dimensions(loop_plan)
    gaps_pending = [InfoGap(field=dim, priority=5, status=GapStatus.PARTIAL) for dim in planned]
    return builder.build(
        competitor=competitor,
        results=[dr],
        gaps_pending=gaps_pending,
        terminal_state=terminal_state,
    )
