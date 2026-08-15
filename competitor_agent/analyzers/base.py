"""BaseCompetitorAnalyzer — 维度分析器基类

职责：
- 统一 analyze() 骨架：LLM 驱动优先，失败自动降级到规则提取
- 子类实现 dimension / _build_prompt / _rule_extract / _parse_result
- 产出 DimensionResult（含置信度与证据）
"""
from __future__ import annotations

import json
from typing import Any

from competitor_agent.agent.prompts.trust_boundary import detect_injection, wrap_untrusted
from competitor_agent.domain_types.enums import DimensionType, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("analyzers.base")

# 真值校验（设计文档 34 §2.4）：details 中"应可回溯到原文"的数值字段键名。
# 只核对这些实体型数值（价格/单价/数量/得分/计数），
# 比例型（polarity_ratio 的 pos/neg/neu）与 0 值缺省由计算/缺失语义豁免，避免误伤。
_VERIFY_NUMERIC_KEYS = frozenset(
    {
        "monthly_price_usd",
        "annual_price_usd",
        "per_unit_price",
        "per_unit_usd",
        "stars",
        "commits_30d",
        "count",
        "score",
    }
)


def _num_str(value: float) -> str:
    """数值 → 用于原文匹配的字符串（20.0 → "20"）。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _count_numeric_conflicts(details: Any, raw_text: str) -> int:
    """details 中实体数值与原文证据交叉核对：值应出现在原文（忽略标点差异）。

    返回冲突数：声称自原文的数值（非 0）在原文里找不到 → 计数冲突。
    """
    if not isinstance(details, dict):
        return 0
    text = (raw_text or "").lower()
    text_flat = text.replace(",", "")  # "12,000 stars" ↔ 12000 视作一致
    conflicts = 0
    stack: list[Any] = [details]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key in _VERIFY_NUMERIC_KEYS
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and value != 0
                ):
                    needle = _num_str(value)
                    if needle not in text and needle not in text_flat:
                        conflicts += 1
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(item for item in node if isinstance(item, (dict, list)))
    return conflicts


class BaseCompetitorAnalyzer:
    """分析器基类（实现 ICompetitorAnalyzer 契约）"""

    dimension: DimensionType

    def __init__(self, llm: LLMClient | None = None, use_llm: bool = True) -> None:
        self._llm = llm
        self._use_llm = use_llm

    def analyze(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        """LLM 驱动优先，失败自动降级规则提取"""
        if self._use_llm and self._llm is not None:
            try:
                return self._analyze_with_llm(observation, gap, context)
            except LLMUnavailableError:
                logger.info("LLM 不可用，降级规则提取: field=%s", gap.field)
            except Exception:
                logger.exception("LLM 分析失败，降级规则提取: field=%s", gap.field)

        return self._analyze_with_rules(observation, gap, context)

    def confidence(self, result: DimensionResult) -> float:
        return result.confidence

    # ---- 子类接口 ----

    def _build_prompt(self, observation: Observation, gap: InfoGap) -> list[dict[str, str]]:
        raise NotImplementedError

    def _parse_result(self, text: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """解析 LLM 输出（设计文档 34 后由 ``complete_json`` 内部承担，此处保留为兼容钩子）"""
        return json.loads(text)

    def _schema_for(self, gap: InfoGap) -> dict[str, Any]:
        """按维度返回 JSON Schema（设计文档 34 §3.2）。

        子类覆盖 ``_details_properties`` 声明 details 结构；顶层 summary/details/confidence
        为各维度统一必备键。返回 dict 传给 ``LLMClient.complete_json`` 做结构约束 + 修复重试。
        """
        return {
            "type": "object",
            "required": ["summary", "details", "confidence"],
            "properties": {
                "summary": {"type": "string"},
                "confidence": {"type": "number"},
                "details": {"type": "object", "properties": self._details_properties()},
            },
        }

    def _details_properties(self) -> dict[str, Any]:
        """details 结构声明（子类覆盖，对齐评测 extract_prediction 的抽取键命名空间）"""
        return {}

    def _analyze_with_llm(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        assert self._llm is not None
        if detect_injection(observation.raw_text):
            logger.warning(
                "检测到提示注入特征，跳过 LLM 分析，降级规则提取: field=%s source=%s",
                gap.field,
                observation.evidence.source_name,
            )
            raise LLMUnavailableError("untrusted content contains injection attempt")
        messages = self._build_prompt(observation, gap)
        if context.rag_context:
            messages = self._inject_rag_context(messages, context.rag_context)
        if context.memory_context:
            messages = self._inject_memory_context(messages, context.memory_context)
        parsed = self._llm.complete_json(messages, schema=self._schema_for(gap))
        confidence = float(parsed.get("confidence", 0.7))
        status = ResultStatus.COMPLETE
        adjusted = self._verify_details(parsed, observation)
        if adjusted is not None and adjusted < confidence:
            confidence = adjusted
            if confidence < 0.5:
                status = ResultStatus.PARTIAL
        return self._make_result(observation, gap, parsed, confidence=confidence, status=status)

    def _verify_details(self, parsed: dict[str, Any], observation: Observation) -> float | None:
        """真值校验（设计文档 34 §2.4）：details 数值字段与原文证据交叉核对。

        冲突 → 置信度下调（每处 -0.15，下限 0.1）；无冲突返回 None（不调整）。
        """
        conflicts = _count_numeric_conflicts(parsed.get("details", {}), observation.raw_text)
        if not conflicts:
            return None
        base = float(parsed.get("confidence", 0.7))
        adjusted = max(0.1, base - 0.15 * conflicts)
        logger.info(
            "证据交叉核对发现 %d 处数值与原文不符，置信度 %.2f → %.2f: field=%s",
            conflicts,
            base,
            adjusted,
            observation.gap_field,
        )
        return adjusted

    def _inject_rag_context(
        self, messages: list[dict[str, str]], rag_context: str
    ) -> list[dict[str, str]]:
        """把 RAG 检索到的背景知识片段注入最后一条 user 消息（作为外部事实依据）"""
        if not messages:
            return messages
        last = messages[-1]
        if last["role"] != "user":
            messages = messages + [{"role": "user", "content": ""}]
            last = messages[-1]
        last["content"] = (
            f"{last['content']}\n\n"
            f"[知识库参考片段（外部事实依据，可引用其来源）]\n"
            f"{wrap_untrusted(rag_context)}"
        )
        return messages

    def _inject_memory_context(
        self, messages: list[dict[str, str]], memory_context: str
    ) -> list[dict[str, str]]:
        """把记忆召回的历史经验（设计文档 35）注入最后一条 user 消息。

        与 RAG 不同：记忆是本系统沉淀的过往结论（可信、仅作参考），
        排在 RAG 块之后，不影响 mock LLM 对观测文本的抽取（见 benchmark _user_text）。
        """
        if not messages:
            return messages
        last = messages[-1]
        if last["role"] != "user":
            messages = messages + [{"role": "user", "content": ""}]
            last = messages[-1]
        last["content"] = (
            f"{last['content']}\n\n"
            f"[历史经验参考（本系统沉淀的过往结论，仅作参考，请交叉核实后再采信）]\n"
            f"{memory_context}"
        )
        return messages

    def _analyze_with_rules(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        parsed = self._rule_extract(observation)
        # 规则路径默认 0.5；子类可在 _rule_extract 返回中显式给 confidence
        # （如 sentiment 无信号 → 低置信 PARTIAL，避免编造）
        confidence = float(parsed.get("confidence", 0.5))
        status = ResultStatus.COMPLETE if confidence >= 0.5 else ResultStatus.PARTIAL
        return self._make_result(
            observation, gap, parsed, confidence=confidence, status=status
        )

    def _make_result(
        self,
        observation: Observation,
        gap: InfoGap,
        parsed: dict[str, Any],
        confidence: float,
        status: ResultStatus = ResultStatus.COMPLETE,
    ) -> DimensionResult:
        return DimensionResult(
            dimension=self.dimension.value,
            summary=str(parsed.get("summary", "")),
            details=parsed.get("details", {}),
            confidence=confidence,
            evidence=[observation.evidence],
            status=status,
        )

    def _rule_extract(self, observation: Observation) -> dict[str, Any]:
        """规则降级提取（子类覆盖）"""
        return {"summary": observation.raw_text[:200], "details": {}}