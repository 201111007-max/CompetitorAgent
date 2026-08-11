"""BaseCompetitorAnalyzer — 维度分析器基类

职责：
- 统一 analyze() 骨架：LLM 驱动优先，失败自动降级到规则提取
- 子类实现 dimension / _build_prompt / _rule_extract / _parse_result
- 产出 DimensionResult（含置信度与证据）
"""
from __future__ import annotations

from typing import Any

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.domain_types.enums import DimensionType, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger

logger = get_logger("analyzers.base")


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

    def _parse_result(self, text: str) -> dict[str, Any]:
        raise NotImplementedError

    def _analyze_with_llm(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        assert self._llm is not None
        messages = self._build_prompt(observation, gap)
        if context.rag_context:
            messages = self._inject_rag_context(messages, context.rag_context)
        text = self._llm.complete(messages)
        parsed = self._parse_result(text)
        return self._make_result(observation, gap, parsed, confidence=parsed.get("confidence", 0.7))

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

    def _analyze_with_rules(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        parsed = self._rule_extract(observation)
        return self._make_result(
            observation, gap, parsed, confidence=0.5, status=ResultStatus.PARTIAL
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