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

import json
import re
from datetime import datetime, timezone
from typing import Any

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import GapStatus, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import SourceEvidence
from competitor_agent.domain_types.report import CompetitorReport, DimensionResult
from competitor_agent.observability.logger import get_logger

logger = get_logger("facade.react_report")

# details 非空但零证据 URL 的维度：置信度封顶（防无来源断言）
_MAX_CONFIDENCE_NO_EVIDENCE = 0.5


def assemble(
    lead_answer: str,
    competitor: Competitor,
    loop_plan: dict[str, Any] | None,
    transcript: list[dict] | None = None,
    builder: Any | None = None,
    terminal_state: str = "success",
    use_lead_body: bool | None = None,
) -> CompetitorReport:
    """把 Lead Final Answer 组装为 CompetitorReport。

    设计文档 70 M1：Final Answer 两段式——①报告正文（Markdown，给人读）②结构化
    REPORT_SCHEMA JSON（给机器用）。``_split_body_and_payload`` 把两者拆开：
    ``markdown_report = body or 模板``（body 为空 → ``MarkdownRenderer`` 模板保底，
    mock 纯 JSON 输出确定性不变、既有模板断言零改动）；``dimension_results`` 仍从
    payload 解析（现状不变）。``use_lead_body=None`` 时取
    ``config.report.lead_formatted_body``（默认开，见设计文档 70 §7 #1）。
    """
    from competitor_agent.core.report_builder import ReportBuilder

    builder = builder or ReportBuilder()
    if use_lead_body is None:
        from competitor_agent.config.loader import load_config

        use_lead_body = load_config().report.lead_formatted_body
    body, payload = _split_body_and_payload(lead_answer)
    if payload is None:
        return _fallback_single_dimension(lead_answer, competitor, builder, terminal_state, loop_plan)

    dimensions: list[DimensionResult] = []
    for item in payload.get("dimensions") or []:
        dr = _dimension_from_item(item)
        if dr is not None:
            dimensions.append(dr)

    # 跨维度同源冲突兜底（按证据 URL 键，代码强制，不进 LLM 决策）
    conflict_note = ""
    if dimensions:
        try:
            from competitor_agent.domain_types.conflict import detect_conflicts_across

            conflicts = detect_conflicts_across(
                [
                    {
                        "dimension": d.dimension,
                        "details": d.details,
                        "evidence_urls": [e.url for e in d.evidence],
                    }
                    for d in dimensions
                ]
            )
            if conflicts:
                lines = [f"- {c.summary}" for c in conflicts]
                conflict_note = "## 跨维度冲突备注\n\n" + "\n".join(lines) + "\n"
        except Exception:
            logger.warning("跨维度冲突检测失败，跳过", exc_info=True)

    # plan 声明但未产出的维度 → gaps_pending（供 resume/预算/报告标注）
    planned = _planned_dimensions(loop_plan)
    produced = {d.dimension for d in dimensions}
    missing = [dim for dim in planned if dim not in produced]
    gaps_pending = [InfoGap(field=dim, priority=5, status=GapStatus.PARTIAL) for dim in missing]

    report = builder.build(
        competitor=competitor,
        results=dimensions,
        gaps_pending=gaps_pending,
        terminal_state=terminal_state,
    )
    # 设计文档 70 M1：正文优先（body 非空 → 用 Lead 生成正文，模板仅保底）
    if use_lead_body and body:
        report.markdown_report = body
    if conflict_note and report.markdown_report:
        report.markdown_report = report.markdown_report.rstrip() + "\n\n" + conflict_note
    return report


def _split_body_and_payload(lead_answer: str) -> tuple[str, dict[str, Any] | None]:
    """把 Lead Final Answer 拆成 (正文 body, 结构化 payload)（设计文档 70 M1）。

    - ``body``：剔除 JSON 块后的纯散文（复用 doc 65 ``_strip_json_blocks`` 防残留）；
    - ``payload``：REPORT_SCHEMA JSON（复用 ``_parse_report`` 括号配平提取 + 无 dimensions
      的兜底单 react 维度）。
    mock LLM 无正文（纯 JSON）→ body 空 → 模板保底（既有断言零改动）。
    """
    body = _close_orphan_fence(
        _dedupe_repeated_report(
            _strip_structured_data_section(_strip_json_blocks(lead_answer or ""))
        )
    )
    payload = _parse_report(lead_answer)
    return body, payload


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


def _strip_structured_data_section(text: str) -> str:
    """移除「结构化数据（JSON）」机器段（设计文档 70 M1 第②段）整节。

    JSON 内容块已由 ``_strip_json_blocks`` 剥除；此处把「结构化数据」标题（含编号
    形态如 ``## 七、结构化数据（JSON）``）及其下直到下一个 Markdown 标题之间的内容
    （散文、空 ```json 围栏等）一并剔除——该段是给机器/矩阵/compare.json 用的，
    不应出现在给人读的报告正文。结构化数据仍保留在原始 answer 中供矩阵/导出提取。
    """
    if not text:
        return ""
    return re.sub(
        r"^#{1,6}\s*[^\n]*结构化数据[^\n]*\n(?:(?!^#{1,6}\s).*\n?)*",
        "",
        text,
        flags=re.MULTILINE,
    )


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


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """从文本中提取首个平衡 JSON 对象（设计文档 65 §2.1 括号配平 + 字符串感知）。

    快路径：文本整体以 ``{`` 开头 → 直接 ``json.loads``（覆盖绝大多数场景，行为不变）。
    慢路径：定位首个 ``{`` 后逐字符扫描，维护深度；字符串字面量感知——命中 ``"`` 时
    进入字符串态并跳过 ``\\"`` 转义，防止 JSON 字符串内部的 ``{``/``}`` 干扰配平；
    深度归零处截取候选块 ``_parse_json_candidate``（失败先轻修复再解析），成功且为
    dict → 返回。首个候选失败时再尝试 ``re.search`` 懒提取兜底。未闭合/无 JSON → None。

    设计文档 66 §3.3：候选块 ``json.loads`` 失败时先做两条轻修复（``"key": ,`` 空值 →
    null、``, ,``/``,]`` 空数组项）再试，兜住模型手滑畸形（``"details": ,`` 等）。
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = _parse_json_candidate(stripped)
        if payload is not None:
            return payload
    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
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
                candidate = stripped[start : i + 1]
                payload = _parse_json_candidate(candidate)
                if payload is not None:
                    return payload
                break
    # 慢路径候选失败/未闭合 → 懒提取兜底（贪婪到最后一个 }，容忍尾部散文）
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        payload = _parse_json_candidate(match.group(0))
        if payload is not None:
            return payload
    return None


def _light_fix_json(candidate: str) -> str:
    """轻修复模型手滑畸形 JSON（设计文档 66 §3.3）：

    - ``"key": ,``（空值）→ ``"key": null,``；
    - ``, ,``（空数组项）/ `,]`` / `,}`` → 去除多余逗号；
    - ``[,``（数组开头多余逗号）→ 去除（如 ``[ , , ]`` 叠代后残留）。
    修复后由调用方再次 ``json.loads``；仍失败才放弃（保守语义不变）。
    """
    fixed = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)":\s*,', r'"\1": null,', candidate)
    fixed = re.sub(r',\s*,', ",", fixed)
    fixed = re.sub(r',\s*\]', "]", fixed)
    fixed = re.sub(r',\s*\}', "}", fixed)
    fixed = re.sub(r"\[\s*,", "[", fixed)
    return fixed


def _parse_json_candidate(candidate: str) -> dict[str, Any] | None:
    """解析候选 JSON 块；``json.loads`` 失败先 ``_light_fix_json`` 轻修复再试一次。"""
    payload: Any = None
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        try:
            payload = json.loads(_light_fix_json(candidate))
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(payload, dict) and payload:
        return payload
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


def _dimension_from_item(item: dict[str, Any]) -> DimensionResult | None:
    dim = str(item.get("dimension") or "").strip()
    if not dim:
        return None
    summary = str(item.get("summary") or "")
    raw_details = item.get("details")
    details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
    raw_confidence = item.get("confidence")
    confidence = 0.5
    if raw_confidence is not None:
        try:
            confidence = max(0.0, min(1.0, float(raw_confidence)))
        except (TypeError, ValueError):
            confidence = 0.5
    urls = [str(u) for u in (item.get("evidence_urls") or []) if u]
    # 数值真值核对兜底：details 非空但零证据 → 置信度封顶并标注（防无来源断言）
    if details and not urls:
        confidence = min(confidence, _MAX_CONFIDENCE_NO_EVIDENCE)
    evidence = [
        SourceEvidence(
            source_name="web",
            url=url,
            access_time=datetime.now(timezone.utc).isoformat(),
            trust_level=0.8,
        )
        for url in urls
    ]
    return DimensionResult(
        dimension=dim,
        summary=summary,
        details=details,
        confidence=confidence,
        evidence=evidence,
        status=ResultStatus.COMPLETE if confidence >= 0.5 else ResultStatus.PARTIAL,
        # 证据链（设计文档 49 §3.1）：无 content_hash，以 URL 代理（跨维度冲突按 URL 键）
        evidence_hashes=list(urls),
    )


def _planned_dimensions(loop_plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(loop_plan, dict):
        return []
    dims = loop_plan.get("dimensions")
    if isinstance(dims, list):
        return [str(d) for d in dims if d]
    return []


def _fallback_single_dimension(
    answer: str,
    competitor: Competitor,
    builder: Any,
    terminal_state: str,
    loop_plan: dict[str, Any] | None = None,
) -> CompetitorReport:
    """非 JSON / 无 dimensions：单 react 维度 PARTIAL（LLM 不可用/超步数文案）。

    设计文档 65 §2.2 兜底净化：即使无有效 JSON，赋给 react 维度 summary 前先剔除文中
    的 JSON 块（复用括号配平定位），只保留纯散文——用户不再看到一坨 JSON dump。

    plan 已声明但未产出的维度 → gaps_pending（供 resume/预算判定），与
    assemble() 正常路径一致。
    """
    text = (answer or "").strip()
    if text:
        text = _strip_json_blocks(text)
    is_unavailable = "LLM 服务不可用" in text or "已达最大" in text or "推理已停止" in text
    status = ResultStatus.PARTIAL
    confidence = 0.1 if is_unavailable else 0.4
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
