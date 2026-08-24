"""facade/api.py 端到端测试：注入 fake 采集器，无 LLM/无网络跑通完整链路"""
from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.domain_types import (
    InfoGap,
    Observation,
    SourceEvidence,
)
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext

CURSOR_PRICING = "Pro $20/month\nTeams $40/month\nUltra $60/month"

# 离线环境 URL 守卫（DNS 解析）会拦截 before 采集器运行：关闭守卫让 FakeExtractor 真被命中
_OFFLINE_CFG = AppConfig(collector=CollectorConfig(block_private_urls=False))


class FakeExtractor:
    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = CURSOR_PRICING
        elif "docs" in url or "cursor.com" in url:
            text = "Cursor supports MCP integration, agent mode, and Codex-style reviews."
        else:
            text = "Cursor is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _api(llm, **kwargs):
    return CompetitorAnalysisAPI(
        extractor=FakeExtractor(),
        llm=llm,
        use_llm=True,
        config=_OFFLINE_CFG,
        **kwargs,
    )


class TestAnalyze:
    def test_analyze_returns_report(self, mock_llm):
        api = _api(mock_llm)
        report = api.analyze("分析 Cursor")
        assert report.competitor.name == "cursor"
        assert report.overall_confidence > 0
        assert report.markdown_report
        assert "# cursor 竞品分析报告" in report.markdown_report

    def test_analyze_pricing_dimension_found(self, mock_llm):
        api = _api(mock_llm)
        report = api.analyze("分析 Cursor")
        pricing = [r for r in report.dimension_results if r.dimension == "pricing"]
        assert pricing
        assert pricing[0].details["plans"]

    def test_analyze_fallback_unknown_competitor(self, mock_llm):
        # 未知竞品也能产出报告（走 home 链接，无官方链接则缺 url → 该维度无结果但不崩溃）
        api = _api(mock_llm)
        report = api.analyze("分析 UnknownToolX")
        assert "unknowntoolx" in report.competitor.name
        assert report.markdown_report

    def test_analyze_emits_events(self, mock_llm):
        events = []
        api = CompetitorAnalysisAPI(extractor=FakeExtractor(), llm=mock_llm, use_llm=True, event_sink=events.append)
        api.analyze("分析 Cursor")
        assert events
        assert any(e.event == "phase_start" for e in events)
        assert any(e.event == "report" for e in events)

    def test_analyze_gap_pending_not_crashed(self, mock_llm):
        # 未关闭缺口会进报告，但不崩溃
        api = _api(mock_llm, max_iterations=1, cost_limit=0.05)
        report = api.analyze("分析 Cursor")
        assert report.gaps_pending is not None


class TestAnalyzeReact:
    def test_analyze_react_llm_unavailable_degrades(self):
        from competitor_agent.interfaces.exceptions import LLMUnavailableError
        from competitor_agent.llm.client import LLMClient

        class FailingLLM(LLMClient):
            def complete(self, messages):
                raise LLMUnavailableError("no key")

        api = CompetitorAnalysisAPI(
            extractor=FakeExtractor(),
            llm=FailingLLM(),
            use_llm=True,
        )
        result = api.analyze_react("分析 Cursor")
        assert "不可用" in result  # 降级文案

    def test_analyze_react_success_with_fake_llm(self):
        from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply

        def fake_llm(messages, model, **kwargs):
            # plan-first（设计文档 49）：首步必须先 make_plan，之后才可收尾（native 形状）
            if not any(m.get("role") == "assistant" for m in messages):
                return ToolCallReply(tool_calls=[ToolCall(
                    id="call_0", name="make_plan",
                    arguments={"plan_json": {"competitor": "Cursor", "dimensions": ["pricing"]}},
                )])
            return ToolCallReply(content="Cursor 定价已收集")

        api = CompetitorAnalysisAPI(
            extractor=FakeExtractor(),
            llm=LLMClient(call_func=fake_llm),
            use_llm=True,
            config=_OFFLINE_CFG,
        )
        result = api.analyze_react("分析 Cursor")
        assert "定价" in result