"""设计文档 71 §8 — 双版联网工具用法提示词（版本一懒触发 / 版本二纯搜索置信度声明）。

覆盖：_web_tool_section 按 fetch_enabled 选版；Lead/子 Agent 系统提示均含该段；
纯搜索版含「已禁用抓取层」+ 置信度声明纪律；版本一含「两次调用原则」。
"""
from __future__ import annotations

from competitor_agent.agent.prompts.react_system import (
    _PURE_SEARCH_WEB_PROMPT,
    _TWO_STEP_WEB_PROMPT,
    _web_tool_section,
    build_lead_system_prompt,
    build_subagent_system_prompt,
)


class TestWebToolSection:
    def test_normal_version_has_two_step(self):
        section = _web_tool_section(True)
        assert section == _TWO_STEP_WEB_PROMPT
        assert "两次调用原则" in section
        assert "web_extract" in section
        assert "同一 URL 只抓一次" in section

    def test_pure_search_version_has_confidence_discipline(self):
        section = _web_tool_section(False)
        assert section == _PURE_SEARCH_WEB_PROMPT
        assert "已禁用抓取层" in section
        assert "置信度声明纪律" in section
        assert "未核验，置信度下调" in section


class TestPromptIntegration:
    def test_lead_prompt_includes_web_section(self, monkeypatch):
        monkeypatch.setattr(
            "competitor_agent.agent.prompts.react_system._fetch_enabled_from_config",
            lambda: True,
        )
        prompt = build_lead_system_prompt()
        assert "联网工具用法" in prompt
        assert "web_extract(url)" in prompt

    def test_subagent_prompt_includes_web_section(self, monkeypatch):
        monkeypatch.setattr(
            "competitor_agent.agent.prompts.react_system._fetch_enabled_from_config",
            lambda: True,
        )
        prompt = build_subagent_system_prompt("pricing")
        assert "联网工具用法" in prompt

    def test_pure_search_version_selected_by_config(self, monkeypatch):
        monkeypatch.setattr(
            "competitor_agent.agent.prompts.react_system._fetch_enabled_from_config",
            lambda: False,
        )
        prompt = build_lead_system_prompt()
        assert "已禁用抓取层" in prompt
        assert "web_extract(url)" not in prompt
