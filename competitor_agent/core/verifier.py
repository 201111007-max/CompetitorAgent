"""NLI 事实校验器（设计文档 77，工单 2）。

把 ``validate_facts``（仅数值核对）升级为**报告级事实校验器**：
报告 → 断言抽取（LLM，失败回退确定性抽取）→ 来源定位（snapshot=知识库检索 /
refetch=联网重抓，受 FetchPolicy 护栏）→ 三态判定。

**三态判定是本设计的灵魂**（doc 77 §6.1）：
- ``supported``：断言被来源支持；
- ``contradicted``：断言与来源矛盾（真幻觉）；
- ``superseded``：报告与知识库快照一致、但最新原文已变（现实已变/信息过期）——
  **矛盾 ≠ 幻觉**，不计入幻觉率；自动落 TimelineMemory + 告警 + 可选回灌知识库；
- ``unverifiable``：无来源可判（不编造），不计入幻觉率分母。

幻觉率口径：``contradicted / (supported + contradicted)``——superseded 与
unverifiable 均不计入分母（把「时效性问题」从「质量问题」中剥离）。

不进 Agent 工具面（doc 77 §3）：自查自证是评测大忌，校验器固定走代码调用路径。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from competitor_agent.domain_types.verification import count_numeric_conflicts

logger = logging.getLogger("competitor_agent.core.verifier")

# 断言抽取的维度枚举（对齐 react_schemas.DIMENSIONS 的合法口径）
_DIMENSIONS = ("pricing", "feature", "performance", "ecosystem", "sentiment", "roadmap", "")

# 数值型实体键（对齐 _VERIFY_NUMERIC_KEYS，供抽取 prompt 约束）
_NUMERIC_KEYS = (
    "monthly_price_usd",
    "annual_price_usd",
    "per_unit_price",
    "stars",
    "commits_30d",
    "count",
    "score",
)

# fallback 抽取的事实性启发（含数字或含断言性谓词）
_FACT_MARKER_RE = re.compile(r"支持|提供|定价|价格|发布|版本|上线|月|年|美元|\$|免费|收费|档")
_SENT_SPLIT_RE = re.compile(r"[。！？!?.；;\n]")

# web_extract 失败文案特征（不把错误提示当原文判 NLI）
_UNHELPFUL_SOURCE_MARKERS = (
    "URL 被安全守卫拦截",
    "抓取失败",
    "已达上限",
    "错误",
)


@dataclass
class Claim:
    """原子事实断言（一句一事）。"""

    text: str
    dimension: str = ""
    source_urls: list[str] = field(default_factory=list)
    numeric: dict[str, float] = field(default_factory=dict)


@dataclass
class Verdict:
    """单条断言判定结果（三态 + 不可判定）。"""

    claim: Claim
    verdict: str  # supported / contradicted / superseded / unverifiable
    evidence_url: str = ""
    reason: str = ""
    mode: str = "snapshot"


@dataclass
class ReportVerification:
    """报告级校验汇总。幻觉率 = contradicted / (supported + contradicted)。"""

    hallucination_rate: float = 0.0
    verdicts: list[Verdict] = field(default_factory=list)
    superseded_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def n_supported(self) -> int:
        return sum(1 for v in self.verdicts if v.verdict == "supported")

    @property
    def n_contradicted(self) -> int:
        return sum(1 for v in self.verdicts if v.verdict == "contradicted")

    @property
    def n_superseded(self) -> int:
        return sum(1 for v in self.verdicts if v.verdict == "superseded")

    @property
    def n_unverifiable(self) -> int:
        return sum(1 for v in self.verdicts if v.verdict == "unverifiable")

    @property
    def total(self) -> int:
        return len(self.verdicts)

    def contradicted_reasons(self) -> list[str]:
        """审批门拒绝理由（doc 77 §2.2 步骤 4）。"""
        return [f"{v.claim.text}：{v.reason}" for v in self.verdicts if v.verdict == "contradicted"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hallucination_rate": self.hallucination_rate,
            "total": self.total,
            "supported": self.n_supported,
            "contradicted": self.n_contradicted,
            "superseded": self.n_superseded,
            "unverifiable": self.n_unverifiable,
            "superseded_events": list(self.superseded_events),
        }


_EXTRACT_PROMPT = (
    "从报告正文抽取原子事实断言（一句一事），输出 JSON 数组（不要输出其他文本），"
    '每项形如 {{"text": "断言原文", "dimension": "pricing|feature|performance|'
    'ecosystem|sentiment|roadmap|空串", "evidence_urls": ["报告中引用的来源URL"], '
    '"numeric": {{"score": 7.5}}}}；numeric 键只能取 {keys}，无数值则空对象。'
    "最多 {max_claims} 条。\n\n报告正文：\n{report}"
)

_NLI_PROMPT = (
    "判断断言是否被来源原文支持（NLI 三选一：来源支持=supported，来源矛盾="
    "contradicted，来源未提及=unverifiable）。只输出 JSON: "
    '{{"result": "supported|contradicted|unverifiable", "reason": "一句话理由"}}。\n\n'
    "断言：{claim}\n\n来源原文：\n{source}"
)


class NLIVerifier:
    """报告级 NLI 事实校验器（snapshot / refetch 双模式，三态判定）。"""

    def __init__(
        self,
        llm: Any,
        retriever: Any = None,
        web_extract: Callable[[str], str] | None = None,
        fetch_policy: Any = None,
        timeline: Any = None,
        alert_sink: Any = None,
        ingester: Any = None,
        max_claims: int = 40,
        auto_ingest_superseded: bool = True,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._web_extract = web_extract
        self._fetch_policy = fetch_policy
        self._timeline = timeline
        self._alert_sink = alert_sink
        self._ingester = ingester
        self._max_claims = max(1, int(max_claims))
        self._auto_ingest = auto_ingest_superseded
        self._pending_superseded: list[dict[str, Any]] = []

    # ── 断言抽取 ─────────────────────────────────────────────────────

    def extract_claims(self, report_text: str) -> list[Claim]:
        """LLM 结构化抽取原子断言；失败/畸形输出回退确定性抽取（评测确定性兜底）。"""
        claims = self._extract_claims_llm(report_text)
        if claims:
            return claims
        return self._extract_claims_fallback(report_text)[: self._max_claims]

    def _extract_claims_llm(self, report_text: str) -> list[Claim]:
        if self._llm is None or not report_text.strip():
            return []
        prompt = _EXTRACT_PROMPT.format(
            keys="/".join(_NUMERIC_KEYS), max_claims=self._max_claims, report=report_text[:8000]
        )
        try:
            raw = self._llm.complete([{"role": "user", "content": prompt}], json_mode=True)
        except Exception:  # noqa: BLE001 — LLM 失败回退确定性抽取
            return []
        match = re.search(r"\[.*\]", str(raw), re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list):
            return []
        claims: list[Claim] = []
        for item in items[: self._max_claims]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if len(text) < 4:
                continue
            dimension = str(item.get("dimension") or "")
            if dimension not in _DIMENSIONS:
                dimension = ""
            urls = [str(u) for u in (item.get("evidence_urls") or []) if str(u).startswith("http")]
            numeric = {
                str(k): float(v)
                for k, v in (item.get("numeric") or {}).items()
                if k in _NUMERIC_KEYS
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
                and v != 0  # 非 0 纪律（对齐 count_numeric_conflicts：0 值缺省豁免）
            }
            claims.append(Claim(text=text[:300], dimension=dimension, source_urls=urls, numeric=numeric))
        return claims

    @staticmethod
    def _extract_claims_fallback(report_text: str) -> list[Claim]:
        """确定性抽取：正文行 → 句子级拆分 → 事实性启发过滤（无 LLM、无网络）。"""
        claims: list[Claim] = []
        for line in report_text.splitlines():
            line = line.strip().lstrip("-*").strip()
            if not line or line.startswith(("#", "|")):
                continue
            for sent in _SENT_SPLIT_RE.split(line):
                sent = sent.strip().lstrip("-*").strip()
                if len(sent) >= 8 and (re.search(r"\d", sent) or _FACT_MARKER_RE.search(sent)):
                    claims.append(Claim(text=sent[:300]))
                if len(claims) >= 200:
                    return claims
        return claims[:200]

    # ── 来源定位 ─────────────────────────────────────────────────────

    def _snapshot_source(self, claim: Claim, competitor: str) -> tuple[str, str]:
        """snapshot 来源：知识库检索 top1 chunk → (原文, source_url)；无 → ("", "")。

        ``strategy="lexical"``（doc 77 §2.3 评测确定性）：纯词袋检索无嵌入开销且
        输入固定 → 判定输入固定（snapshot 模式的确定性边界，doc 77 §6.3）。
        """
        if self._retriever is None:
            return "", ""
        try:
            chunks = self._retriever.retrieve(
                claim.text, competitor, dimension=claim.dimension, top_k=1, strategy="lexical"
            )
        except Exception:  # noqa: BLE001 — 检索失败不炸校验
            return "", ""
        if not chunks:
            return "", ""
        text = str(getattr(chunks[0], "text", "") or "")
        url = str(getattr(chunks[0], "source_url", "") or "")
        return text, url

    def _fetch_fresh(self, url: str) -> str:
        """refetch 原文：逐 URL 经 FetchPolicy 护栏（上限/去重）调 web_extract。"""
        if self._web_extract is None or not url:
            return ""
        if self._fetch_policy is not None:
            kind, note = self._fetch_policy.get(url)
            if kind == "limit":
                return ""
            if kind == "cached":
                return str(note or "")  # 本轮已抓过 → 不重抓不计上限（去重回读）
        try:
            result = self._web_extract(url)
        except Exception:  # noqa: BLE001 — 抓取失败按无原文处理
            return ""
        text = str(result or "")
        if self._fetch_policy is not None:
            self._fetch_policy.record(url, text)
        if not text.strip() or any(marker in text[:200] for marker in _UNHELPFUL_SOURCE_MARKERS):
            return ""
        return text

    # ── NLI 判定 ─────────────────────────────────────────────────────

    def _nli(self, claim: Claim, source_text: str, evidence_url: str, mode: str) -> Verdict:
        """LLM NLI 判定；LLM 失败/畸形输出 → unverifiable（不猜测、不编造）。"""
        if self._llm is None:
            return Verdict(claim, "unverifiable", evidence_url, "无 LLM 可判定", mode)
        prompt = _NLI_PROMPT.format(claim=claim.text, source=source_text[:6000])
        try:
            raw = self._llm.complete([{"role": "user", "content": prompt}], json_mode=True)
        except Exception:  # noqa: BLE001 — LLM 失败保守缺省
            return Verdict(claim, "unverifiable", evidence_url, "LLM 判定失败", mode)
        match = re.search(r"\{.*\}", str(raw), re.DOTALL)
        if not match:
            return Verdict(claim, "unverifiable", evidence_url, "LLM 输出无法解析", mode)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return Verdict(claim, "unverifiable", evidence_url, "LLM 输出无法解析", mode)
        result = str(data.get("result") or "")
        reason = str(data.get("reason") or "")[:200]
        if result in ("supported", "contradicted"):
            return Verdict(claim, result, evidence_url, reason, mode)
        return Verdict(claim, "unverifiable", evidence_url, reason or "来源未提及", mode)

    # ── 单断言校验 ───────────────────────────────────────────────────

    def verify_claim(self, claim: Claim, competitor: str, *, mode: str = "snapshot") -> Verdict:
        if mode == "refetch":
            return self._verify_claim_refetch(claim, competitor)
        return self._verify_claim_snapshot(claim, competitor)

    def _verify_claim_snapshot(self, claim: Claim, competitor: str) -> Verdict:
        snap_text, snap_url = self._snapshot_source(claim, competitor)
        if not snap_text:
            return Verdict(claim, "unverifiable", "", "知识库无该断言来源（不编造）", "snapshot")
        # 数值快路径：数值冲突直接 contradicted，不过 LLM（doc 77 §2.2 步骤 1）
        if claim.numeric:
            conflicts = count_numeric_conflicts(claim.numeric, snap_text)
            if conflicts:
                return Verdict(
                    claim, "contradicted", snap_url, f"{conflicts} 处数值与快照原文不符", "snapshot"
                )
        return self._nli(claim, snap_text, snap_url, "snapshot")

    def _verify_claim_refetch(self, claim: Claim, competitor: str) -> Verdict:
        snap_text, snap_url = self._snapshot_source(claim, competitor)
        urls = [u for u in claim.source_urls if u] or ([snap_url] if snap_url else [])
        fresh_text, fresh_url = "", ""
        for url in urls[:3]:
            fresh_text = self._fetch_fresh(url)
            if fresh_text:
                fresh_url = url
                break
        # 数值三态快路径：与快照就矛盾 → 真幻觉；快照一致但新原文矛盾 → superseded；
        # 无快照基线时与最新原文矛盾 → 真幻觉（不伪装 superseded）
        if claim.numeric:
            if snap_text and count_numeric_conflicts(claim.numeric, snap_text):
                return Verdict(
                    claim, "contradicted", snap_url, "数值与知识库快照原文不符（真幻觉）", "refetch"
                )
            if fresh_text and count_numeric_conflicts(claim.numeric, fresh_text):
                if snap_text:
                    return self._register_superseded(claim, competitor, snap_url, fresh_url, fresh_text)
                return Verdict(
                    claim, "contradicted", fresh_url, "数值与最新原文不符（无快照基线，真幻觉）", "refetch"
                )
        # 语义三态：先快照 NLI；快照矛盾即真幻觉；快照支持 + 新原文矛盾 → superseded
        if snap_text:
            snap_verdict = self._nli(claim, snap_text, snap_url, "refetch")
            if snap_verdict.verdict == "contradicted":
                return snap_verdict
            if not fresh_text:
                return snap_verdict
        if not fresh_text:
            return Verdict(
                claim, "unverifiable", snap_url, "快照与最新原文均不可得", "refetch"
            )
        fresh_verdict = self._nli(claim, fresh_text, fresh_url, "refetch")
        # superseded 需要快照基线（快照支持 + 新原文矛盾 = 现实已变）；无快照时与
        # 最新原文矛盾即真幻觉（计入幻觉率），不得伪装成「信息过期」逃避分母
        if (
            fresh_verdict.verdict == "contradicted"
            and snap_text
            and snap_verdict.verdict == "supported"
        ):
            return self._register_superseded(claim, competitor, snap_url, fresh_url, fresh_text)
        return fresh_verdict

    # ── superseded 落账（doc 77 §2.2 步骤 4 + §2.3 知识库反馈）────────

    def _register_superseded(
        self, claim: Claim, competitor: str, snap_url: str, fresh_url: str, fresh_text: str
    ) -> Verdict:
        """superseded：TimelineMemory 事件 + 告警推送 + 可选新原文回灌知识库。"""
        from competitor_agent.memory.timeline_memory import _EVENT_TYPE_BY_DIM, TimelineEvent

        receipt: dict[str, Any] = {
            "competitor": competitor,
            "event_type": _EVENT_TYPE_BY_DIM.get(claim.dimension, "version_release"),
            "summary": claim.text[:120],
            "snapshot_url": snap_url,
            "fresh_url": fresh_url,
            "ingested_chunks": None,
        }
        if self._timeline is not None:
            try:
                self._timeline.append(
                    TimelineEvent(
                        competitor=competitor,
                        event_type=receipt["event_type"],
                        summary=f"信息过期（superseded）：{claim.text[:100]}",
                        evidence_urls=[fresh_url] if fresh_url else [],
                    )
                )
            except Exception:
                logger.warning("superseded 时间线落账失败", exc_info=True)
        if self._alert_sink is not None:
            try:
                from competitor_agent.core.alerting import Alert

                self._alert_sink.emit(
                    Alert(
                        competitor=competitor,
                        kind=receipt["event_type"],
                        summary=f"报告信息过期：{claim.text[:100]}",
                        old_value="（快照一致）",
                        new_value="（来源已更新）",
                        evidence_urls=[fresh_url] if fresh_url else [],
                    )
                )
            except Exception:
                logger.warning("superseded 告警推送失败", exc_info=True)
        if self._ingester is not None and self._auto_ingest and claim.dimension and fresh_text:
            try:
                receipt["ingested_chunks"] = self._ingester.ingest(
                    competitor,
                    claim.dimension,
                    fresh_text,
                    source_url=fresh_url,
                )
            except Exception:
                logger.warning("superseded 知识库回灌失败", exc_info=True)
        self._pending_superseded.append(receipt)
        return Verdict(
            claim,
            "superseded",
            fresh_url,
            "与快照一致但最新原文已变化（信息过期，不计幻觉）",
            "refetch",
        )

    # ── 报告级校验 ───────────────────────────────────────────────────

    def verify_report(
        self, report_text: str, competitor: str, *, mode: str = "snapshot"
    ) -> ReportVerification:
        claims = self.extract_claims(report_text)
        verdicts = [self.verify_claim(c, competitor, mode=mode) for c in claims]
        events = list(self._pending_superseded)
        self._pending_superseded.clear()
        judged = [v for v in verdicts if v.verdict in ("supported", "contradicted")]
        contradicted = sum(1 for v in judged if v.verdict == "contradicted")
        rate = round(contradicted / len(judged), 4) if judged else 0.0
        return ReportVerification(
            hallucination_rate=rate, verdicts=verdicts, superseded_events=events
        )


__all__ = [
    "Claim",
    "NLIVerifier",
    "ReportVerification",
    "Verdict",
]
