"""设计文档 72 — Agent.md（类 CLAUDE.md 全局提示词资产）测试

覆盖（§7 验收表）：
- Agent.md 存在 / frontmatter 完整 / 有界（>40 行 Warning + 字符硬截断）
- 注入：Lead / 维度子 Agent / 候选竞品子 Agent / 对话 build_* 尾部均含 Agent.md 段
- 缺 assets / 渲染异常 / 空 Agent.md → _agent_md_section() 返回 ""，build_* 输出=现状（黄金回归）
- PROMPTS_DIR 覆盖 → build_* 输出随之变（"改 md 生效"）
- 与阶段二正交：make_plan 注入的 plan 适配段不含重复 Agent.md
- 记忆/知识库（enrich_prompt 尾拼）在 Agent.md 之后
- {{key}} 逐键替换 / version() / PROMPTS_USER_FILE 扩展 B / 版本漂移 Warning
"""
from __future__ import annotations

import logging

from competitor_agent.agent.prompts.react_system import (
    _MAX_AGENT_MD_CHARS,
    _MAX_AGENT_MD_LINES,
    _agent_md_section,
    build_chat_system_prompt,
    build_lead_system_prompt,
    build_report_phase2_section,
    build_subagent_system_prompt,
    enrich_prompt,
)
from competitor_agent.agent.react_schemas import DIMENSIONS

_AGENT_MD_MARK = "# Agent.md"
_AGENT_MD_KNOWN_FACT = "项目级 Agent 指令"


def _write_agent_md(dir_path, body: str, version: str = "1.0.0") -> str:
    """写一个最小可用的 Agent.md 资产，返回其绝对路径。"""
    import pathlib

    p = pathlib.Path(dir_path)
    p.mkdir(parents=True, exist_ok=True)
    text = f"---\nname: Agent\nversion: {version}\ndescription: 测试资产\n---\n\n{body}"
    (p / "Agent.md").write_text(text, encoding="utf-8")
    return str(p)


class TestAssetBasics:
    def test_builtin_asset_exists_and_parses(self):
        from competitor_agent.agent.prompts.loader import PromptAsset

        asset = PromptAsset()
        body = asset.get("Agent")
        assert body is not None
        assert _AGENT_MD_KNOWN_FACT in body
        assert asset.version("Agent") == "1.0.0"

    def test_render_returns_body(self):
        from competitor_agent.agent.prompts.loader import PromptAsset

        body = PromptAsset().render("Agent")
        assert body
        assert _AGENT_MD_KNOWN_FACT in body

    def test_unknown_stem_none(self):
        from competitor_agent.agent.prompts.loader import PromptAsset

        asset = PromptAsset()
        assert asset.get("nonexistent") is None
        assert asset.version("nonexistent") is None
        assert asset.render("nonexistent") == ""

    def test_no_frontmatter_returns_whole_body(self, tmp_path):
        from competitor_agent.agent.prompts.loader import PromptAsset

        (tmp_path / "Agent.md").write_text(
            "plain body without frontmatter", encoding="utf-8"
        )
        asset = PromptAsset(prompts_dir=tmp_path)
        assert asset.get("Agent") == "plain body without frontmatter"
        assert asset.version("Agent") is None


class TestAgentMdSection:
    def test_empty_when_asset_missing(self, tmp_path):
        from competitor_agent.agent.prompts.loader import PromptAsset

        empty = PromptAsset(prompts_dir=tmp_path / "empty")
        # 直接验证：渲染空资产 → 空串
        assert empty.render("Agent") == ""

    def test_render_exception_returns_empty(self, monkeypatch):
        from competitor_agent.agent.prompts import loader as prompts_loader

        def boom():
            raise RuntimeError("bad asset")

        monkeypatch.setattr(prompts_loader, "get_prompt_asset", boom)
        assert _agent_md_section() == ""

    def test_bounded_line_warning(self, tmp_path, caplog, monkeypatch):
        from competitor_agent.agent.prompts import loader as prompts_loader
        from competitor_agent.agent.prompts.loader import PromptAsset

        body = "\n".join(f"- 第 {i} 行" for i in range(_MAX_AGENT_MD_LINES + 5))
        _write_agent_md(tmp_path, body)
        monkeypatch.setattr(
            prompts_loader, "get_prompt_asset", lambda: PromptAsset(prompts_dir=tmp_path)
        )
        with caplog.at_level(logging.WARNING):
            _agent_md_section()
        assert any("行数上限" in r.message for r in caplog.records)

    def test_bounded_char_truncate(self, tmp_path, monkeypatch):
        from competitor_agent.agent.prompts import loader as prompts_loader
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "x" * (_MAX_AGENT_MD_CHARS + 500))
        monkeypatch.setattr(
            prompts_loader, "get_prompt_asset", lambda: PromptAsset(prompts_dir=tmp_path)
        )
        section = _agent_md_section()
        assert len(section) <= _MAX_AGENT_MD_CHARS

    def test_version_drift_warning(self, tmp_path, caplog, monkeypatch):
        from competitor_agent.agent.prompts import loader as prompts_loader
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "drifted conventions", version="9.9.9")
        monkeypatch.setattr(
            prompts_loader, "get_prompt_asset", lambda: PromptAsset(prompts_dir=tmp_path)
        )
        with caplog.at_level(logging.WARNING):
            _agent_md_section()
        assert any("版本漂移" in r.message for r in caplog.records)


class TestInjection:
    def test_lead_injects_at_tail(self):
        prompt = build_lead_system_prompt()
        assert _AGENT_MD_MARK in prompt
        # Agent.md 段在尾部（prompt 以渲染出的完整段收尾，不耦合具体文案）
        assert prompt.rstrip().endswith(_agent_md_section().rstrip())

    def test_chat_injects_at_tail(self):
        prompt = build_chat_system_prompt()
        assert _AGENT_MD_MARK in prompt
        assert "回答完成后直接结束" in prompt

    def test_dimension_subagent_injects(self):
        for dim in DIMENSIONS:
            prompt = build_subagent_system_prompt(dim)
            assert _AGENT_MD_MARK in prompt, dim
            assert f'<skill name="{dim}_analysis">' in prompt, dim

    def test_competitor_subagent_injects(self):
        prompt = build_subagent_system_prompt("cursor")
        assert _AGENT_MD_MARK in prompt
        assert "official_links" in prompt

    def test_agent_md_before_memory_and_knowledge(self):
        base = build_lead_system_prompt()
        out = enrich_prompt(base, notes=["n1"], knowledge=["k1"])
        assert out.index(_AGENT_MD_MARK) < out.index("历史教训")
        assert out.index(_AGENT_MD_MARK) < out.index("知识库参考片段")


class TestGoldenRegression:
    def test_missing_assets_keeps_status_quo(self, tmp_path, monkeypatch):
        from competitor_agent.agent.prompts import loader as prompts_loader
        from competitor_agent.agent.prompts.loader import PromptAsset

        empty = PromptAsset(prompts_dir=tmp_path / "empty")
        monkeypatch.setattr(prompts_loader, "get_prompt_asset", lambda: empty)
        lead = build_lead_system_prompt()
        assert _AGENT_MD_MARK not in lead
        assert lead.startswith("你是竞品情报分析的 Lead Agent")
        assert lead.rstrip("\n") == lead  # 无尾随空行/多余空白

    def test_empty_asset_body_keeps_status_quo(self, tmp_path, monkeypatch):
        from competitor_agent.agent.prompts import loader as prompts_loader
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "   ")  # 仅 frontmatter + 空白正文 → get() None
        empty = PromptAsset(prompts_dir=tmp_path)
        monkeypatch.setattr(prompts_loader, "get_prompt_asset", lambda: empty)
        chat = build_chat_system_prompt()
        assert _AGENT_MD_MARK not in chat
        assert chat.startswith("你是竞品情报 Agent 的对话助手")

    def test_status_quo_is_byte_identical_without_section(self, tmp_path, monkeypatch):
        """黄金回归：缺资产时 build_* 输出 == 无 Agent.md 段的基线（逐字节）。"""
        from competitor_agent.agent.prompts import loader as prompts_loader
        from competitor_agent.agent.prompts.loader import PromptAsset

        full = build_lead_system_prompt()
        md = _agent_md_section()
        assert md  # 内置资产存在
        baseline = full[: -len(f"\n\n{md}")]

        empty = PromptAsset(prompts_dir=tmp_path / "empty")
        monkeypatch.setattr(prompts_loader, "get_prompt_asset", lambda: empty)
        assert build_lead_system_prompt() == baseline


class TestOverride:
    def test_prompts_dir_changes_build_output(self, tmp_path, monkeypatch):
        from competitor_agent.agent.prompts import loader as prompts_loader
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "自定义项目公约：所有数字必须标注来源页码。")
        monkeypatch.setattr(
            prompts_loader, "get_prompt_asset", lambda: PromptAsset(prompts_dir=tmp_path)
        )
        prompt = build_lead_system_prompt()
        assert "自定义项目公约" in prompt
        assert "来源页码" in prompt

    def test_prompts_dir_env_honored(self, tmp_path, monkeypatch):
        from competitor_agent.agent.prompts import loader

        _write_agent_md(tmp_path, "env 覆盖的 Agent.md 内容")
        monkeypatch.setenv("PROMPTS_DIR", str(tmp_path))
        loader.reset_prompt_asset()
        try:
            asset = loader.get_prompt_asset()
            assert "env 覆盖的 Agent.md 内容" in asset.render("Agent")
        finally:
            loader.reset_prompt_asset()

    def test_user_file_extension_b_appended(self, tmp_path):
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "项目级公约")
        user = tmp_path / "user.md"
        user.write_text("---\nname: user\n---\n\n个人偏爱：回答尽量用表格。", encoding="utf-8")
        rendered = PromptAsset(prompts_dir=tmp_path, user_file=user).render("Agent")
        assert "项目级公约" in rendered
        assert "个人偏爱" in rendered
        assert rendered.index("项目级公约") < rendered.index("个人偏爱")

    def test_user_file_missing_ignored(self, tmp_path):
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "项目级公约")
        rendered = PromptAsset(prompts_dir=tmp_path, user_file=tmp_path / "nope.md").render("Agent")
        assert "项目级公约" in rendered
        assert "个人偏爱" not in rendered


class TestSubstitution:
    def test_placeholder_replaced_with_context(self, tmp_path):
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "本次分析竞品：{{competitor}}")
        rendered = PromptAsset(prompts_dir=tmp_path).render("Agent", {"competitor": "Cursor"})
        assert "本次分析竞品：Cursor" in rendered
        assert "{{competitor}}" not in rendered

    def test_no_context_keeps_placeholder(self, tmp_path):
        from competitor_agent.agent.prompts.loader import PromptAsset

        _write_agent_md(tmp_path, "保持 {{competitor}} 原样")
        assert PromptAsset(prompts_dir=tmp_path).render("Agent") == "保持 {{competitor}} 原样"


class TestPhase2Orthogonal:
    def test_phase2_section_has_no_agent_md(self):
        plan = {"competitor": "cursor", "resolution": "compare", "format_hint": "compare"}
        section = build_report_phase2_section(plan)
        assert section is not None
        assert _AGENT_MD_MARK not in section
        assert "报告结构" in section

    def test_phase2_returns_none_for_open_plan(self):
        assert build_report_phase2_section({"format_hint": "open"}) is None
        assert build_report_phase2_section(None) is None
