"""M2 集成（设计文档 49 迁移）：技能/进化记忆经 enrich_prompt 注入 ReAct 系统提示，
引导 LLM 选源；analyze 记忆写侧落盘、跨加载持久。"""
from competitor_agent.agent.prompts.react_system import enrich_prompt
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


class TestSkillGuidedSourceSelection:
    """选源引导（设计文档 49）：记忆技能作为「推荐优先使用的数据源」注入系统提示。"""

    def test_success_skill_recommends_source(self):
        skills = [Skill(competitor_name="cursor", gap_field="pricing", source_name="official_pricing", success=True)]
        prompt = enrich_prompt("base", skills=skills, competitor="cursor")
        assert "official_pricing" in prompt
        assert "pricing" in prompt

    def test_failed_skill_not_recommended(self):
        skills = [Skill(competitor_name="cursor", gap_field="pricing", source_name="official_pricing", success=False)]
        prompt = enrich_prompt("base", skills=skills, competitor="cursor")
        assert "official_pricing" not in prompt


class TestMemoryDrivesPrompt:
    def test_second_analysis_surfaces_skill_in_prompt(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "mem")
        mem.record_skill(Skill(competitor_name="cursor", gap_field="pricing", source_name="docs", success=True))
        prompt = enrich_prompt("base", skills=mem.retrieve_skills("cursor"), competitor="cursor")
        assert "docs" in prompt  # 记忆沉淀的技能进入提示引导选源

    def test_no_memory_no_recommendation(self):
        prompt = enrich_prompt("base", skills=[], competitor="cursor")
        assert "历史技能" not in prompt

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

    def test_api_memory_persists_after_analyze(self, tmp_path, mock_llm):
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
        # 分析后记忆写侧落盘：技能跨加载可见（设计文档 49 唯一写侧）
        mem2 = FourLayerMemory(tmp_path / "m")
        assert mem2.retrieve_skills("cursor"), "分析后技能被落盘"