"""writer 叙事槽契约（设计文档 88 §4.2，D2 核心）

研究员/作家分离下 writer 的唯一职责：填叙事槽。槽位标题由骨架代码渲染，
writer 只产段落 prose；输入只做减法——``NarrativeSlot.input_facts`` 为蒸馏事实清单
（``DimensionFacts``），writer 不接触原始 details（幻觉防火墙，doc 88 §10.3）。

- ``build_slots``：三槽切分——executive_summary（全量事实）/ dimension_insight×n
  （单维事实）/ market_conclusion（全量事实），槽序稳定；
- ``build_writer_messages``：prompt = 槽位指令 + ``wrap_untrusted`` 包裹 facts JSON
  （数字只能取自 facts、禁写 URL/年份、引用只用 [n] 占位）；
- ``validate_slot_prose``（N2 保真校验）：prose 中数字 token ⊆ 允许集（facts 数值 +
  可直接派生安全数的三形态），返回违规列表；
- ``anchor_citations``（N3 引用锚定）：先剔 prose 自写 URL，再把 [n] 占位锚定为
  槽位 evidence_urls 的 markdown 链接（越界删除）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.domain_types.distilled import DimensionFacts, numeric_allowlist
from competitor_agent.domain_types.report import CompetitorReport

# mock LLM 识别标记（确定性：BenchmarkMockLLM 检测 system 含此串 → 返回 MOCK_SLOT_PROSE）
WRITER_SYSTEM_MARKER = "你是竞品报告的叙事槽位撰写器"
# mock 固定串：无数字（N2 必过）、无 URL（N3 无操作）、无 [n] 占位
MOCK_SLOT_PROSE = "这是确定性槽位解读（mock）。"

SLOT_EXECUTIVE = "executive_summary"
SLOT_CONCLUSION = "market_conclusion"

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_URL_RE = re.compile(r"https?://\S+")
_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def dimension_slot_id(dimension: str) -> str:
    return f"dimension_insight:{dimension}"


@dataclass
class NarrativeSlot:
    """单个叙事槽：槽位标题骨架渲染，writer 只填 prose。"""

    slot_id: str
    heading: str  # 槽位标题（骨架组成部分；writer prompt 亦据此说明写作目标）
    input_facts: list[DimensionFacts] = field(default_factory=list)
    # executive/conclusion = 全量维度事实，dimension_insight = 单维事实
    mock_text: str = MOCK_SLOT_PROSE

    @property
    def evidence_urls(self) -> list[str]:
        """槽可见证据 URL（跨 input_facts 保序去重；N3 锚定的 [n] 序号基准）。"""
        out: list[str] = []
        for df in self.input_facts:
            for url in df.evidence_urls:
                if url and url not in out:
                    out.append(url)
        return out


def build_slots(report: CompetitorReport, facts_by_dim: list[DimensionFacts]) -> list[NarrativeSlot]:
    """三槽切分（槽序稳定 = executive → dimension×n（report 维度序）→ conclusion）。"""
    by_dim = {df.dimension: df for df in facts_by_dim}
    slots = [
        NarrativeSlot(
            slot_id=SLOT_EXECUTIVE, heading="执行摘要", input_facts=list(facts_by_dim)
        )
    ]
    for result in report.dimension_results:
        df = by_dim.get(result.dimension)
        slots.append(
            NarrativeSlot(
                slot_id=dimension_slot_id(result.dimension),
                heading=f"{result.dimension} 维度解读",
                input_facts=[df] if df is not None else [],
            )
        )
    slots.append(
        NarrativeSlot(
            slot_id=SLOT_CONCLUSION, heading="市场格局结论", input_facts=list(facts_by_dim)
        )
    )
    return slots


def build_writer_messages(slot: NarrativeSlot) -> list[dict[str, str]]:
    """writer prompt：槽位指令 + wrap_untrusted 包裹的蒸馏事实 JSON。

    指令即 N2/N3 的模型侧契约：数字只能取自 facts、禁写 URL 与年份（年份是 N2
    误报面）、引用只用 [n] 占位（代码后处理锚定，writer 不接触真实 URL）。
    """
    facts_payload = json.dumps(
        [
            {
                "dimension": df.dimension,
                "status": df.status,
                "confidence": round(df.confidence, 2),
                "summary": df.summary,
                "facts": [
                    {"label": f.label, "value": f.value, "unit": f.unit} for f in df.facts
                ],
                "evidence_urls": df.evidence_urls,
            }
            for df in slot.input_facts
        ],
        ensure_ascii=False,
    )
    system = (
        f"{WRITER_SYSTEM_MARKER}。你在撰写竞品分析报告的「{slot.heading}」段落。\n"
        "硬性规则：\n"
        "1. 只能依据下方 <untrusted_data> 中给出的事实（facts）写作，禁止引入任何外部知识；\n"
        "2. 段落中出现的每个数字必须与 facts 中的数值完全一致，禁止估算、四舍五入或编造；\n"
        "3. 禁止书写任何 URL 与年份；引用证据时只用 [n] 占位符"
        "（n 为 facts 中 evidence_urls 的序号，从 1 开始）；\n"
        "4. 中文，120-200 字，信息密度优先；不使用标题/列表，只输出一个自然段。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": wrap_untrusted(facts_payload)},
    ]


def slot_allowed_numbers(slot: NarrativeSlot, *, overall_confidence: float | None = None) -> set[str]:
    """N2 允许集：facts 数值 + **可直接派生**的安全数（三形态：{:g}/{:.2f}/int）。

    派生安全数 = 维度数 / 各维 facts 数 / 各维证据数 / 各维置信度 / 综合置信度——
    全部是 facts payload 内或直接可数派生的值，放行不引入幻觉面（doc 88 §10.3：
    接触面即校验面）；年份等不可派生数字仍违规（prompt 侧已禁写）。
    """
    values: list[float] = [float(len(slot.input_facts))]
    for df in slot.input_facts:
        values.append(df.confidence)
        values.append(float(len(df.facts)))
        values.append(float(len(df.evidence_urls)))
        values.extend(f.numeric for f in df.facts if f.numeric is not None)
    if overall_confidence is not None:
        values.append(overall_confidence)
    facts = [f for df in slot.input_facts for f in df.facts]
    out = numeric_allowlist(facts)
    for v in values:
        out.add(f"{v:g}")
        out.add(f"{v:.2f}")
        if v == int(v):
            out.add(str(int(v)))
    return out


def validate_slot_prose(
    slot: NarrativeSlot, prose: str, *, allowed: set[str] | None = None
) -> list[str]:
    """N2 保真校验：prose 中数字 token 必须 ⊆ 允许集；返回违规 token 列表（空 = 通过）。

    口径：``$``/单位等上下文不进 token（``$20/月`` 抽 ``20``），单位正确性由 prompt
    指令约束；漏报面（碰巧匹配无关 facts 的同值数字）接受——宁浅勿假，N2 是防火墙
    不是证明器。
    """
    allowed_set = allowed if allowed is not None else slot_allowed_numbers(slot)
    seen: list[str] = []
    for token in _NUM_RE.findall(prose):
        if token not in allowed_set and token not in seen:
            seen.append(token)
    return seen


def anchor_citations(slot: NarrativeSlot, prose: str) -> str:
    """N3 引用锚定后处理：引用归代码，writer 只标占位。

    ① 先剔除 prose 自写 URL（越权：URL 权威在代码）；② 再把 ``[n]`` 占位锚定为
    槽位 evidence_urls 的 markdown 链接（越界序号删除 token）。顺序重要：先剔 URL
    不会误伤尚未生成的 markdown 链接。
    """
    prose = _URL_RE.sub("", prose)
    urls = slot.evidence_urls

    def _sub(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if 1 <= n <= len(urls):
            return f"[{n}]({urls[n - 1]})"
        return ""

    return _CITATION_RE.sub(_sub, prose).strip()


__all__ = [
    "MOCK_SLOT_PROSE",
    "SLOT_CONCLUSION",
    "SLOT_EXECUTIVE",
    "WRITER_SYSTEM_MARKER",
    "NarrativeSlot",
    "anchor_citations",
    "build_slots",
    "build_writer_messages",
    "dimension_slot_id",
    "slot_allowed_numbers",
    "validate_slot_prose",
]
