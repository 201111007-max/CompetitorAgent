"""设计文档 44：链式分析单测（LLM 抽取 → 真值校验 → 工具补证 → 二次补全收敛）

- 数值冲突触发工具补证 → 二轮修正通过（COMPLETE）
- 无分发器 / 补证无证据 / 工具异常 → 链式降级单轮（不破坏现状）
- _MAX_CHAIN_STEPS 后仍冲突 → 保留降级置信，不无限循环
- 低置信也触发补证；补证证据按不可信数据包裹（防提示注入）
"""
from __future__ import annotations

import json

from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.analyzers import PricingAnalyzer
from competitor_agent.domain_types import InfoGap, Observation, SourceEvidence
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.interfaces.context import AnalysisContext
from competitor_agent.llm.client import LLMClient


def _obs(raw_text, gap_field="pricing"):
    ev = SourceEvidence(source_name="web_extractor", content_hash="h1")
    return Observation(gap_field=gap_field, source="web_extractor", raw_text=raw_text, evidence=ev)


def _search_dispatcher(result="", raises=None):
    """注册 web_search 的 mock 分发器：返回固定结果 / 抛异常。"""
    def _web_search(query, max_results=5):
        if raises is not None:
            raise raises
        return result

    dispatcher = ToolDispatcher()
    dispatcher.register("web_search", _web_search)
    return dispatcher


def _pricing_payload(price, confidence=0.9):
    return json.dumps(
        {
            "summary": "pricing",
            "details": {"plans": [{"name": "pro", "monthly_price_usd": price}]},
            "confidence": confidence,
        }
    )


class TestChainAnalysis:
    def test_conflict_triggers_tool_and_second_round_fixes(self):
        """首轮数值与原文冲突 → 工具补证返回正确证据 → 二轮修正通过 COMPLETE。"""
        calls = []
        script = [_pricing_payload(30), _pricing_payload(20)]

        def fake_llm(messages, model):
            calls.append([m["content"] for m in messages])
            return script.pop(0)

        analyzer = PricingAnalyzer(
            llm=LLMClient(call_func=fake_llm),
            tool_dispatcher=_search_dispatcher(result="Cursor Pro plan costs $20/month"),
        )
        obs = _obs("Pro plan $20/month", "pricing")
        result = analyzer.analyze(obs, InfoGap(field="pricing"), AnalysisContext(competitor_name="cursor"))
        assert len(calls) == 2
        assert result.confidence == 0.9
        assert result.status == ResultStatus.COMPLETE
        # 补证证据注入第二轮 user 消息（不可信数据块包裹，防提示注入）
        second = "".join(calls[1])
        assert "$20/month" in second
        assert "<untrusted_data>" in second

    def test_no_dispatcher_degrades_to_single_round(self):
        """无分发器（context 与 self 均无）→ 不触发补证，保留降级置信，仅一次 LLM 调用。"""
        calls = []

        def fake_llm(messages, model):
            calls.append(1)
            return _pricing_payload(30)  # 与原文冲突

        analyzer = PricingAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("Pro plan $20/month", "pricing")
        result = analyzer.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert len(calls) == 1
        assert result.confidence == 0.75  # 0.9 - 0.15（1 处冲突）

    def test_max_chain_steps_no_infinite_loop(self):
        """补证多轮仍冲突 → 到 _MAX_CHAIN_STEPS 停（初始 1 + 补证 2 = 3 次），保留降级置信。"""
        calls = []

        def fake_llm(messages, model):
            calls.append(1)
            return _pricing_payload(30)  # 一直冲突

        analyzer = PricingAnalyzer(
            llm=LLMClient(call_func=fake_llm),
            tool_dispatcher=_search_dispatcher(result="evidence that never fixes it"),
        )
        obs = _obs("Pro plan $20/month", "pricing")
        result = analyzer.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert len(calls) == 3  # 1 初始 + 2 补证（_MAX_CHAIN_STEPS）
        assert result.confidence == 0.75

    def test_empty_evidence_stops_chain(self):
        """补证返回空 → 无证据停止链式，保留首轮结果（仅一次调用）。"""
        calls = []

        def fake_llm(messages, model):
            calls.append(1)
            return _pricing_payload(30)

        analyzer = PricingAnalyzer(
            llm=LLMClient(call_func=fake_llm),
            tool_dispatcher=_search_dispatcher(result=""),
        )
        obs = _obs("Pro plan $20/month", "pricing")
        result = analyzer.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert len(calls) == 1
        assert result.confidence == 0.75

    def test_tool_exception_falls_back_silently(self):
        """补证工具抛异常 → 静默返回无证据，链式停止，不阻塞主流程。"""
        calls = []

        def fake_llm(messages, model):
            calls.append(1)
            return _pricing_payload(30)

        analyzer = PricingAnalyzer(
            llm=LLMClient(call_func=fake_llm),
            tool_dispatcher=_search_dispatcher(raises=RuntimeError("network down")),
        )
        obs = _obs("Pro plan $20/month", "pricing")
        result = analyzer.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert len(calls) == 1
        assert result.confidence == 0.75

    def test_low_confidence_triggers_verification(self):
        """置信度低于阈值（0.5）也触发补证 → 二轮提升置信度。"""
        calls = []
        script = [_pricing_payload(20, confidence=0.3), _pricing_payload(20, confidence=0.85)]

        def fake_llm(messages, model):
            calls.append(1)
            return script.pop(0)

        analyzer = PricingAnalyzer(
            llm=LLMClient(call_func=fake_llm),
            tool_dispatcher=_search_dispatcher(result="Pro plan $20/month"),
        )
        obs = _obs("Pro plan $20/month", "pricing")
        result = analyzer.analyze(obs, InfoGap(field="pricing"), AnalysisContext())
        assert len(calls) == 2
        assert result.confidence == 0.85
        assert result.status == ResultStatus.COMPLETE

    def test_context_dispatcher_takes_precedence(self):
        """context.tool_dispatcher 优先于分析器自带的（测试/多场景复用入口）。"""
        calls = []
        script = [_pricing_payload(30), _pricing_payload(20)]

        def fake_llm(messages, model):
            calls.append(1)
            return script.pop(0)

        # 分析器无分发器；context 注入
        analyzer = PricingAnalyzer(llm=LLMClient(call_func=fake_llm))
        obs = _obs("Pro plan $20/month", "pricing")
        ctx = AnalysisContext(
            competitor_name="cursor",
            tool_dispatcher=_search_dispatcher(result="Pro plan $20/month"),
        )
        result = analyzer.analyze(obs, InfoGap(field="pricing"), ctx)
        assert len(calls) == 2
        assert result.confidence == 0.9
        assert result.status == ResultStatus.COMPLETE
