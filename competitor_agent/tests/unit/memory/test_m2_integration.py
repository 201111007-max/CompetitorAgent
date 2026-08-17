"""M2 集成：技能/进化记忆影响规划与选源，prompt 注入记忆片段"""
from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.domain_types import Competitor, InfoGap
from competitor_agent.interfaces.context import Skill
from competitor_agent.memory import FourLayerMemory


class TestPromptEnrichment:
    def test_enrich_injects_skills(self):
        base = "system base"
        skills = [Skill(competitor_name="cursor", gap_field="pricing", source_name="docs", success=True)]
        prompt = enrich_prompt(base, skills=skills)
        assert "docs" in prompt
        assert "pricing" in prompt

    def test_enrich_injects_notes_and_knowledge(self):
        prompt = enrich_prompt("base", notes=["教训1"], knowledge=["知识片段A"], competitor="cursor")
        assert "教训1" in prompt
        assert "知识片段A" in prompt

    def test_skill_filtered_by_competitor(self):
        skills = [
            Skill(competitor_name="cursor", gap_field="pricing", source_name="docs", success=True),
            Skill(competitor_name="copilot", gap_field="pricing", source_name="home", success=True),
        ]
        prompt = enrich_prompt("base", skills=skills, competitor="cursor")
        assert "copilot" not in prompt
        assert "docs" in prompt


class TestSourcePreference:
    def test_high_success_rate_source_first(self):
        sel = SourceSelector()
        sel.set_success_rates({"official_pricing": 0.95, "official_home": 0.2})
        gap = InfoGap(field="pricing")
        competitor = Competitor(
            name="cursor",
            official_links={"pricing": "https://c.com/pricing", "home": "https://c.com"},
        )
        cands = sel.candidates(gap, competitor)
        assert cands[0].source_name == "official_pricing"

    def test_success_rates_affect_trust(self):
        sel = SourceSelector()
        sel.set_success_rates({"official_home": 1.0})
        gap = InfoGap(field="pricing")
        competitor = Competitor(name="cursor", official_links={"home": "https://c.com"})
        cands = sel.candidates(gap, competitor)
        assert cands[0].trust_level > 0.9


class TestMemoryDrivesPlanning:
    def test_second_analysis_boosts_confidence(self, tmp_path, mock_llm):
        mem = FourLayerMemory(tmp_path / "mem")
        mem.record_skill(Skill(competitor_name="cursor", gap_field="pricing", source_name="docs", success=True))
        p = StrategicPlanner(llm=mock_llm, use_llm=True)
        strategy = p.plan("cursor", memory=mem)
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].confidence == 0.2  # 记忆提升

    def test_no_memory_no_boost(self, tmp_path, mock_llm):
        p = StrategicPlanner(llm=mock_llm, use_llm=True)
        strategy = p.plan("cursor")
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].confidence == 0.0

    def test_memory_end_to_end_persistence(self, tmp_path):
        d = tmp_path / "m2"
        mem = FourLayerMemory(d)
        mem.record_success("cursor", "pricing", "docs")
        mem2 = FourLayerMemory(d)  # 重新加载
        assert mem2.retrieve_skills("cursor")[0].source_name == "docs"


class TestApiWithMemory:
    def test_api_memory_exposed(self, tmp_path, mock_llm):
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        mem = FourLayerMemory(tmp_path / "mem")
        api = CompetitorAnalysisAPI(extractor=None, llm=mock_llm, use_llm=True, memory=mem, max_iterations=2)
        assert api.memory is mem

    def test_api_memory_drives_confidence(self, tmp_path, mock_llm):
        from competitor_agent.domain_types import Observation, SourceEvidence
        from competitor_agent.facade.api import CompetitorAnalysisAPI
        from competitor_agent.interfaces.context import SourceContext

        mem = FourLayerMemory(tmp_path / "m")

        class FakeExtractor:
            source_name = "web_extractor"

            def fetch(self, gap, context: SourceContext) -> Observation:
                url = str(context.kwargs.get("url"))
                if "pricing" in url:
                    text = "Pro $20/month"
                else:
                    text = "Cursor is an AI code editor."
                ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)))
                return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)

        api = CompetitorAnalysisAPI(extractor=FakeExtractor(), llm=mock_llm, use_llm=True, memory=mem, max_iterations=4)
        api.analyze("分析 Cursor")
        # 分析后应沉淀技能，二次规划命中记忆（同存储目录重新加载）
        mem2 = FourLayerMemory(tmp_path / "m")
        assert mem2.retrieve_skills("cursor")  # 技能被落盘
        # 直接规划即可观察到记忆命中带来的置信度提升
        from competitor_agent.core.strategic_loop import StrategicPlanner

        strategy = StrategicPlanner(llm=mock_llm, use_llm=True).plan("cursor", memory=mem2)
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].confidence >= 0.2