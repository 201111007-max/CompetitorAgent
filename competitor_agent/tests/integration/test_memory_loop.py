"""集成测试 — 记忆闭环：分析后沉淀 → 二次分析命中（Memory Loop）

对齐设计文档 11 §3.1：
- 分析成功后 record_skill（L3 技能）+ record_outcome（L4 进化）
- 落盘可持久化：重新加载同一 data_dir 仍可检索
- 二次规划命中记忆：历史技能间隙置信度 +0.2（StrategicPlanner._apply_memory_boost）
"""

from __future__ import annotations

import pytest

from competitor_agent.core.strategic_loop import StrategicPlanner
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.memory import FourLayerMemory

pytestmark = pytest.mark.integration


class TestMemoryLoop:
    def test_analysis_sediments_skills_and_source_outcomes(self, fake_extractor, memory, mock_llm) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, memory=memory, max_iterations=10)
        api.analyze("分析 Cursor", mode="single")

        skills = memory.retrieve_skills("cursor")
        assert skills, "分析成功后应沉淀技能"
        assert {s.gap_field for s in skills} >= {"pricing", "feature"}
        assert memory.source_success_rates(), "应记录数据源成功率（L4 进化记忆）"

    def test_memory_persists_across_reload(self, tmp_path, fake_extractor, mock_llm) -> None:
        data_dir = tmp_path / "persist"

        mem = FourLayerMemory(data_dir)
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, memory=mem, max_iterations=10)
        api.analyze("分析 Cursor", mode="single")

        reloaded = FourLayerMemory(data_dir)
        assert reloaded.retrieve_skills("cursor"), "记忆应落盘并可重新加载"

    def test_second_plan_hits_memory_boost(self, fake_extractor, memory, mock_llm) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, llm=mock_llm, use_llm=True, memory=memory, max_iterations=10)
        api.analyze("分析 Cursor", mode="single")

        strategy = StrategicPlanner(llm=mock_llm, use_llm=True).plan("cursor", memory=memory)
        by_field = {g.field: g for g in strategy.gaps}
        assert by_field["pricing"].confidence >= 0.2, "记忆命中应提升间隙初始置信度"
