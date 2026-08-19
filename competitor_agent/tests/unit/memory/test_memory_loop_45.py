"""设计文档 45/49：L4 记忆回路契约 + ReAct 提示注入消费

- L4 契约：retrieve_patterns_with_outcome（带 outcome 供判定）/ failure_patterns_for（失败源提取）
- 消费迁移（49）：原 StrategicPlanner 提权/降权与 SourceSelector 降级由 LLM 决策，
  L4 模式改经 enrich_prompt 的 notes 注入系统提示引导（选源/避坑）
"""
from __future__ import annotations

from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.memory import FourLayerMemory
from competitor_agent.memory.evolution_memory import EvolutionMemory


class TestL4Contract:
    def test_retrieve_patterns_with_outcome(self, tmp_path):
        evo = EvolutionMemory(tmp_path / "evo")
        evo.note_pattern("cursor", "performance", "命中 SWE-bench 榜单", outcome="success")
        evo.note_pattern("cursor", "performance", "榜单源缺失 → 回退页面", outcome="degraded")
        got = evo.retrieve_patterns_with_outcome("cursor", "performance")
        assert ("命中 SWE-bench 榜单", "success") in got
        assert ("榜单源缺失 → 回退页面", "degraded") in got
        assert evo.retrieve_patterns_with_outcome("cursor", "pricing") == []

    def test_failure_patterns_for_extracts_failed_sources(self, tmp_path):
        evo = EvolutionMemory(tmp_path / "evo")
        evo.note_pattern("cursor", "pricing", "失败: 源 official_pricing 无数据", outcome="failure")
        evo.note_pattern("cursor", "pricing", "由源 docs 有效", outcome="success")
        evo.note_pattern("cursor", "performance", "由源 github 降级命中", outcome="degraded")
        evo.note_pattern("cursor", "roadmap", "无具体源的反例", outcome="failure")
        assert evo.failure_patterns_for("cursor") == ["github", "official_pricing"]

    def test_four_layer_memory_delegates(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "m")
        mem.note_pattern("cursor", "pricing", "失败: 源 docs 无数据", outcome="failure")
        assert mem.failure_patterns_for("cursor") == ["docs"]
        assert mem.retrieve_patterns_with_outcome("cursor", "pricing") == [
            ("失败: 源 docs 无数据", "failure")
        ]


class TestL4PromptGuidance:
    """设计文档 49：L4 模式作为 notes 注入系统提示，LLM 自行做提权/降权决策。"""

    def test_patterns_inject_as_notes(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "m")
        mem.note_pattern("cursor", "pricing", "由源 docs 有效", outcome="success")
        mem.note_pattern("cursor", "pricing", "失败: 源 docs 无数据", outcome="failure")
        notes = mem.retrieve_patterns("cursor", "pricing")
        prompt = enrich_prompt("base", notes=notes)
        assert "由源 docs 有效" in prompt
        assert "失败: 源 docs 无数据" in prompt

    def test_failure_sources_surface_as_avoid_guidance(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "m")
        mem.note_pattern("cursor", "pricing", "失败: 源 official_pricing 无数据", outcome="failure")
        failed = mem.failure_patterns_for("cursor")
        assert failed == ["official_pricing"]
        prompt = enrich_prompt("base", notes=[f"避免失败源: {s}" for s in failed])
        assert "official_pricing" in prompt

    def test_no_patterns_no_note_section(self):
        prompt = enrich_prompt("base", notes=[])
        assert "历史教训/笔记" not in prompt
