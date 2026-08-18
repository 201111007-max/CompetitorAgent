"""BaseCompetitorAnalyzer — 维度分析器基类

职责：
- 统一 analyze() 骨架：仅 LLM 链式分析（设计文档 47，无规则降级）
- 子类实现 dimension / _build_prompt / _parse_result
- 产出 DimensionResult（含置信度与证据）

LLM 不可用 / 注入命中 → 返回低置信 [PARTIAL]（保留结构化返回，不炸流水线，
报告标注"该维度未分析"）；不再降级规则。
"""
from __future__ import annotations

import json
from typing import Any

from competitor_agent.agent.prompts.trust_boundary import detect_injection, wrap_untrusted
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.domain_types.enums import DimensionType, ResultStatus
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.domain_types.observation import Observation
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient
from competitor_agent.observability.logger import get_logger
from competitor_agent.skills import get_skill_loader

logger = get_logger("analyzers.base")

# 链式分析（设计文档 44）：LLM 抽取 → 真值校验 → 工具补证 → 二次补全收敛。
# 初始抽取后再补证迭代的轮数上限（再 +初始 1 次 = 总共 2-3 次 complete_json）。
_MAX_CHAIN_STEPS = 2
# 置信度低于该值触发工具补证（尝试提升置信度，失败保留降级值）
_VERIFY_MIN_CONFIDENCE = 0.5

# 工具补证查询：维度 → 检索关键词（web_search query 拼 "竞品 + 维度关键词"）
_DIMENSION_VERIFY_QUERIES: dict[str, str] = {
    "pricing": "pricing price plan 定价 套餐 价格",
    "performance": "benchmark score performance 性能 评测",
    "feature": "features capabilities 功能 特性",
    "ecosystem": "ecosystem plugins mcp integrations 生态 插件",
    "sentiment": "reviews community feedback 口碑 评价",
    "roadmap": "roadmap roadmap 路线图 规划",
}

# 无补证价值的工具返回（搜索 API 未接入 / 采集失败 / 拦截等可读错误）：
# 命中任一即视为"无证据"，链式停止（不把 stub/错误当证据回灌，避免浪费后续 LLM 调用）。
_UNHELPFUL_TOOL_MARKERS = (
    "搜索功能需要接入搜索引擎 API",
    "URL 被安全守卫拦截",
    "工具执行超时:",
    "工具不存在",
    "参数校验失败",
    "⚠",
)

# 真值校验（设计文档 34 §2.4）：details 中"应可回溯到原文"的数值字段键名。
# 逻辑已迁至 domain_types/verification.py（设计文档 49 复核工具复用），此处仅保留别名。
from competitor_agent.domain_types.verification import (  # noqa: E402
    _VERIFY_NUMERIC_KEYS,
    _num_str,
    count_numeric_conflicts as _count_numeric_conflicts,
)


class BaseCompetitorAnalyzer:
    """分析器基类（实现 ICompetitorAnalyzer 契约）"""

    dimension: DimensionType

    def __init__(
        self,
        llm: LLMClient | None = None,
        use_llm: bool = True,
        tool_dispatcher: ToolDispatcher | None = None,
    ) -> None:
        self._llm = llm
        self._use_llm = use_llm
        # 工具补证分发器（设计文档 44）：链式分析触发时经 web_search/web_extract 补证；
        # 未注入则为 None（链式降级为单轮，规则路径不变）
        self._tool_dispatcher = tool_dispatcher

    def analyze(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> DimensionResult:
        """仅 LLM 链式分析（设计文档 47）；LLM 不可用/注入命中返回不可信 PARTIAL。

        保留结构化返回：无规则可降，但报告仍可标注"该维度未分析"。
        """
        if not (self._use_llm and self._llm is not None):
            return self._unavailable_result(observation, gap, "LLM 不可用")
        try:
            return self._analyze_with_llm(observation, gap, context)
        except LLMUnavailableError:
            logger.info("LLM 不可用/内容不可信，返回 PARTIAL: field=%s", gap.field)
            return self._unavailable_result(observation, gap, "LLM 不可用/内容不可信")
        except Exception:
            logger.exception("LLM 分析失败，返回 PARTIAL: field=%s", gap.field)
            return self._unavailable_result(observation, gap, "LLM 分析失败")

    def _unavailable_result(
        self,
        observation: Observation,
        gap: InfoGap,
        reason: str,
    ) -> DimensionResult:
        """LLM 不可用/注入命中的低置信 PARTIAL（设计文档 47 §3.5）。"""
        return DimensionResult(
            dimension=self.dimension.value,
            summary=reason,
            details={},
            confidence=0.1,
            evidence=[observation.evidence],
            status=ResultStatus.PARTIAL,
        )

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
                "检测到提示注入特征，跳过 LLM 分析，返回不可信 PARTIAL: field=%s source=%s",
                gap.field,
                observation.evidence.source_name,
            )
            raise LLMUnavailableError("untrusted content contains injection attempt")
        messages = self._base_messages(observation, gap, context)
        parsed = self._llm.complete_json(messages, schema=self._schema_for(gap))
        # 链式分析（设计文档 44）：抽取 → 真值校验 → 工具补证 → 二次补全收敛。
        # 上限 _MAX_CHAIN_STEPS 轮（初始 1 次 + 补证 2 次 ≈ 2-3 步）；无工具/补证失败即停，
        # 保留降级置信不无限循环；规则路径与无 LLM 环境完全不变。
        for step in range(1, _MAX_CHAIN_STEPS + 1):
            if not self._needs_verification(parsed, observation):
                break
            evidence = self._verify_via_tools(gap, context)
            if not evidence:
                break
            logger.info(
                "工具补证第 %d/%d 轮: field=%s evidence=%d 字符",
                step,
                _MAX_CHAIN_STEPS,
                gap.field,
                len(evidence),
            )
            messages = self._base_messages(observation, gap, context)
            messages = self._inject_extra_evidence(messages, evidence)
            parsed = self._llm.complete_json(messages, schema=self._schema_for(gap))
        confidence = float(parsed.get("confidence", 0.7))
        status = ResultStatus.COMPLETE
        if confidence < 0.5:
            # 低置信 LLM 结果 → PARTIAL（该维度未充分分析，不标 COMPLETE）
            status = ResultStatus.PARTIAL
        adjusted = self._verify_details(parsed, observation)
        if adjusted is not None and adjusted < confidence:
            confidence = adjusted
            if confidence < 0.5:
                status = ResultStatus.PARTIAL
        return self._make_result(observation, gap, parsed, confidence=confidence, status=status)

    def _base_messages(
        self,
        observation: Observation,
        gap: InfoGap,
        context: AnalysisContext,
    ) -> list[dict[str, str]]:
        """组装分析 prompt：子类 _build_prompt + RAG/记忆注入 + skill 注入（链式各轮复用）。"""
        messages = self._build_prompt(observation, gap)
        if context.rag_context:
            messages = self._inject_rag_context(messages, context.rag_context)
        if context.memory_context:
            messages = self._inject_memory_context(messages, context.memory_context)
        return self._inject_skills(messages)

    def _inject_skills(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """注入 skill 块（设计文档 48）：维度抽取 + 事实边界 + 置信度披露。

        以独立 system 消息插在首条 system（维度抽取指令）之后——messages[0]
        与末条 user（观察文本）均保持原样，故 BenchmarkMockLLM 的维度分支与
        观察抽取不受影响（skill 块不进入"用户任务"/观察文本段）。
        目录缺失/文件解析失败 → 静默跳过（零依赖降级，不影响主流程）。
        """
        loader = get_skill_loader()
        names = [
            f"{self.dimension.value}_analysis",
            "fact_verification",
            "confidence_disclosure",
        ]
        blocks: list[str] = []
        for name in names:
            body = loader.get(name)
            if body:
                blocks.append(f'<skill name="{name}">\n{body}\n</skill>')
        if not blocks:
            return messages
        skill_msg: dict[str, str] = {"role": "system", "content": "\n\n".join(blocks)}
        if messages and messages[0].get("role") == "system":
            messages.insert(1, skill_msg)
        else:
            messages.insert(0, skill_msg)
        return messages

    def _needs_verification(self, parsed: dict[str, Any], observation: Observation) -> bool:
        """是否需要工具补证：真值冲突 > 0，或置信度过低，或 details 关键键为空。"""
        if self._verify_details(parsed, observation) is not None:
            return True
        if float(parsed.get("confidence", 0.7)) < _VERIFY_MIN_CONFIDENCE:
            return True
        details = parsed.get("details")
        return not isinstance(details, dict) or not details

    def _verify_via_tools(self, gap: InfoGap, context: AnalysisContext) -> str:
        """经工具分发器做一次补证（设计文档 44 §3.1）：优先 web_search，兜底 web_extract。

        - 无分发器（context 或 self 均无）→ 返回 ""（链式降级单轮，不破坏规则路径）；
        - 工具缺失/调用异常 → 静默返回 ""（补证失败不影响主流程）。
        """
        dispatcher = getattr(context, "tool_dispatcher", None) or self._tool_dispatcher
        if dispatcher is None:
            return ""
        query = self._verification_query(
            getattr(context, "competitor_name", "") or "", gap.field
        )
        if not query:
            return ""
        try:
            if dispatcher.validate_tool("web_search"):
                result = dispatcher.dispatch("web_search", {"query": query})
            elif dispatcher.validate_tool("web_extract"):
                result = dispatcher.dispatch("web_extract", {"url": query})
            else:
                return ""
        except Exception as exc:  # noqa: BLE001 — 补证失败完全回退，不阻塞主流程
            logger.warning("工具补证失败: field=%s: %s", gap.field, exc)
            return ""
        result = str(result or "").strip()
        # 无补证价值的返回（搜索 stub / 采集错误 / 拦截）→ 视为无证据，链式停止
        cleaned: str = result
        if not cleaned or any(marker in cleaned for marker in _UNHELPFUL_TOOL_MARKERS):
            return ""
        return cleaned

    def _verification_query(self, competitor: str, dimension: str) -> str:
        """补证检索 query：竞品名 + 维度关键词。"""
        hint = _DIMENSION_VERIFY_QUERIES.get(dimension, dimension)
        return f"{competitor} {hint}".strip()

    def _inject_extra_evidence(
        self, messages: list[dict[str, str]], evidence: str
    ) -> list[dict[str, str]]:
        """把工具补证的新证据注入最后一条 user 消息（按不可信数据包裹，防提示注入）。"""
        if not messages:
            return messages
        last = messages[-1]
        if last["role"] != "user":
            messages = messages + [{"role": "user", "content": ""}]
            last = messages[-1]
        last["content"] = (
            f"{last['content']}\n\n"
            f"[外部补充证据（工具检索/抓取所得，请据此核对修正你的答案）]\n"
            f"{wrap_untrusted(evidence)}"
        )
        return messages

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
            # 证据链哈希（设计文档 49 §3.1）：供编排层跨维度同源冲突核对
            evidence_hashes=[observation.evidence.content_hash]
            if observation.evidence and observation.evidence.content_hash
            else [],
        )


def analyze_with_context(
    analyzer: BaseCompetitorAnalyzer,
    observation: Observation,
    gap: InfoGap,
    *,
    competitor_name: str,
    rag_context: str = "",
    memory_context: str = "",
    benchmark_scores: Any = None,
) -> DimensionResult:
    """统一分析段（设计文档 46 §3.1）：组装注入上下文的 AnalysisContext 并调分析器。

    GapExecutor（single/parallel 缺口闭环）与 AnalyzerAgent（team 多 Agent）两条路径
    复用同一实现，消除两套"RAG/记忆注入 + 校验 + 补全"分析段的漂移。
    """
    ctx = AnalysisContext(
        competitor_name=competitor_name,
        dimension=analyzer.dimension,
        rag_context=rag_context,
        memory_context=memory_context,
    )
    if benchmark_scores:
        ctx.benchmark_scores = benchmark_scores
    return analyzer.analyze(observation, gap, ctx)


def retrieve_rag_text(
    retriever: Any, competitor: str, dimension: str, top_k: int = 5
) -> str:
    """检索知识库相关片段，拼成可注入的文本（含来源）；失败/无检索器静默降级。

    设计文档 46 §3.1：GapExecutor._retrieve_rag 与 AnalyzerAgent._retrieve_rag 原为
    同一实现的复制，此处收敛为共享函数（top_k/截断/来源标注口径统一）。
    """
    if retriever is None:
        return ""
    try:
        chunks = retriever.retrieve(
            query=dimension,
            competitor=competitor,
            dimension=dimension,
            top_k=top_k,
        )
    except Exception:  # noqa: BLE001 — 检索失败不影响主流程
        logger.warning("知识库检索失败: %s/%s", competitor, dimension)
        return ""
    if not chunks:
        return ""
    lines = []
    for c in chunks:
        src = f"（来源: {c.source_url}）" if c.source_url else ""
        lines.append(f"- [{c.competitor}/{c.dimension}]{src} {c.text[:300]}")
    return "\n".join(lines)