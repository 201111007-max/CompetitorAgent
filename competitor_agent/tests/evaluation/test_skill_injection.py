"""设计文档 48：skill 注入点测试（ReAct 化迁移）+ mock 门禁回归

- Lead Agent 系统提示 build_lead_system_prompt()：注入 planning / fact_verification /
  confidence_disclosure 三块 skill，首条指令（make_plan 强制 + REPORT_SCHEMA）保持不变
- 维度子 Agent 系统提示 build_subagent_system_prompt(dim)：注入 {dim}_analysis +
  fact_verification + confidence_disclosure（设计文档 49 §3.7）
- skill 缺失 → 注入点静默跳过（零依赖降级）
- mock 确定性：带 skill 的提示喂给 ReAct-scripted mock 走通 analyze 全链路，维度结果不回归
"""
from __future__ import annotations

from competitor_agent.agent.prompts.react_system import (
    build_lead_system_prompt,
    build_subagent_system_prompt,
)
from competitor_agent.agent.react_schemas import DIMENSIONS
from competitor_agent.skills import SkillLoader


class TestLeadInjection:
    def test_injects_three_skill_blocks(self):
        prompt = build_lead_system_prompt()
        assert '<skill name="planning">' in prompt
        assert '<skill name="fact_verification">' in prompt
        assert '<skill name="confidence_disclosure">' in prompt

    def test_first_instruction_preserved(self):
        """首条指令（make_plan 强制 + REPORT_SCHEMA）原样保留 → 编排分支不变。"""
        prompt = build_lead_system_prompt()
        assert prompt.startswith("你是竞品情报分析的 Lead Agent")
        assert "make_plan" in prompt
        assert "REPORT_SCHEMA" in prompt


class TestSubagentInjection:
    def test_all_dimensions_inject_own_skill(self):
        for dim in DIMENSIONS:
            prompt = build_subagent_system_prompt(dim)
            assert f'<skill name="{dim}_analysis">' in prompt, dim

    def test_subagent_injects_fact_and_confidence_skills(self):
        prompt = build_subagent_system_prompt("pricing")
        assert '<skill name="fact_verification">' in prompt
        assert '<skill name="confidence_disclosure">' in prompt

    def test_subagent_instruction_preserved(self):
        prompt = build_subagent_system_prompt("pricing")
        assert prompt.startswith('你是竞品分析的「pricing」维度子 Agent')
        assert "SUBAGENT_RESULT_SCHEMA" in prompt


class TestMissingSkillNoInjection:
    def test_lead_skips_when_no_skill_dir(self, tmp_path, monkeypatch):
        # _with_skills 在调用点 `from competitor_agent.skills import get_skill_loader`，
        # 故 patch skills 模块上的单例工厂（react_system 模块属性不存在）。
        import competitor_agent.skills as skills_mod

        empty = SkillLoader(tmp_path / "empty")
        monkeypatch.setattr(skills_mod, "get_skill_loader", lambda: empty)
        prompt = build_lead_system_prompt()
        assert "<skill name=" not in prompt
        assert "make_plan" in prompt  # 主指令仍保留

    def test_subagent_skips_when_no_skill_dir(self, tmp_path, monkeypatch):
        import competitor_agent.skills as skills_mod

        empty = SkillLoader(tmp_path / "empty")
        monkeypatch.setattr(skills_mod, "get_skill_loader", lambda: empty)
        prompt = build_subagent_system_prompt("pricing")
        assert "<skill name=" not in prompt
        assert "SUBAGENT_RESULT_SCHEMA" in prompt


class TestMockGateUnchanged:
    """带 skill 注入的提示走通 ReAct-scripted mock 全链路，维度结果不回归。"""

    def test_full_analyze_with_skills_still_produces_dimension(self):
        from competitor_agent.evaluation.benchmark import build_benchmark_api

        class Case:
            competitor = "cursor"
            dimension = "pricing"
            page = "Pro $20/month"
            best_url = "https://www.cursor.com"
            fail_urls: tuple = ()

        api = build_benchmark_api(Case())
        report = api.analyze("只分析 cursor 的定价")
        assert report.competitor.name == "cursor"
        assert [d.dimension for d in report.dimension_results] == ["pricing"]
