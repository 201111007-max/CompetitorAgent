"""RAG 接入主流程：采集后摄入 + 分析前检索注入"""
from competitor_agent.domain_types import Observation, SourceEvidence
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext


class FakeExtractor:
    source_name = "web_extractor"

    def fetch(self, gap, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = "Pro $20/month, Team $40/month"
        else:
            text = "Cursor is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)))
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


class TestApiRagWiring:
    def test_api_instantiates_knowledge_base(self):
        api = CompetitorAnalysisAPI(extractor=None, use_llm=False, max_iterations=2)
        assert api._store is not None
        assert api._ingester is not None
        assert api._retriever is not None

    def test_analysis_ingests_observations(self):
        api = CompetitorAnalysisAPI(extractor=FakeExtractor(), use_llm=False, max_iterations=4)
        api.analyze("分析 Cursor")
        chunks = api._store.all_chunks()
        assert chunks, "分析后知识库应摄入观测片段"
        assert any(c.competitor == "cursor" for c in chunks)

    def test_retriever_hits_ingested_chunks(self):
        api = CompetitorAnalysisAPI(extractor=FakeExtractor(), use_llm=False, max_iterations=4)
        api.analyze("分析 Cursor")
        hits = api._retriever.retrieve(query="pricing", competitor="cursor", dimension="pricing", top_k=3)
        assert hits, "检索应命中已摄入片段"
        assert any("$20" in c.text for c in hits)


class TestRagContextInjection:
    def test_analyzer_prompt_includes_rag_context(self):
        from competitor_agent.analyzers.base import BaseCompetitorAnalyzer
        from competitor_agent.domain_types.enums import DimensionType
        from competitor_agent.domain_types.info_gap import InfoGap
        from competitor_agent.domain_types.observation import Observation
        from competitor_agent.interfaces.context import AnalysisContext

        class DummyAnalyzer(BaseCompetitorAnalyzer):
            dimension = DimensionType.PRICING

            def _build_prompt(self, observation, gap):
                return [{"role": "user", "content": "分析定价"}]

            def _parse_result(self, text):
                return {"summary": text, "details": {}, "confidence": 0.5}

        analyzer = DummyAnalyzer()
        obs = Observation(gap_field="pricing", source="x", raw_text="Pro $20")
        gap = InfoGap(field="pricing")
        ctx = AnalysisContext(competitor_name="cursor", dimension=DimensionType.PRICING, rag_context="知识片段A（来源: https://c.com/pricing）")
        messages = analyzer._build_prompt(obs, gap)
        injected = analyzer._inject_rag_context(messages, ctx.rag_context)
        assert "知识片段A" in injected[-1]["content"]
        assert "https://c.com/pricing" in injected[-1]["content"]
