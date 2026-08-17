"""设计文档 48：SkillLoader 单测

- frontmatter 解析（含 CRLF / 无 frontmatter / 空文本）
- get / get_content / 缺失降级（get → None，get_content → 可读错误）
- SKILLS_DIR 环境变量覆盖、reload、缺目录静默空
- 默认包内 skills/ 目录含 9 个 skill；显式目录绕过单例缓存
"""
from __future__ import annotations

from competitor_agent.skills import SkillLoader, get_skill_loader


def _write(tmp_path, name: str, text: str):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path / name


class TestParseFrontmatter:
    def test_parses_meta_and_body(self):
        meta, body = SkillLoader._parse_frontmatter(
            "---\nname: planning\ndescription: 规划规范\n---\n正文内容"
        )
        assert meta == {"name": "planning", "description": "规划规范"}
        assert body == "正文内容"

    def test_crlf_normalized(self):
        meta, body = SkillLoader._parse_frontmatter("---\r\nname: x\r\n---\r\nbody\r\n")
        assert meta == {"name": "x"}
        assert body == "body"

    def test_no_frontmatter_returns_body(self):
        meta, body = SkillLoader._parse_frontmatter("plain text")
        assert meta == {}
        assert body == "plain text"

    def test_empty_text(self):
        assert SkillLoader._parse_frontmatter("") == ({}, "")


class TestSkillLoader:
    def test_loads_by_stem(self, tmp_path):
        _write(tmp_path, "planning.md", "---\nname: planning\ndescription: d\n---\nbody")
        loader = SkillLoader(tmp_path)
        assert list(loader.skills) == ["planning"]
        assert loader.get("planning") == "body"

    def test_get_missing_returns_none(self, tmp_path):
        assert SkillLoader(tmp_path).get("missing") is None

    def test_get_content_wraps_skill(self, tmp_path):
        _write(tmp_path, "planning.md", "---\nname: planning\ndescription: d\n---\nbody")
        loader = SkillLoader(tmp_path)
        assert loader.get_content("planning") == '<skill name="planning">\nbody\n</skill>'

    def test_get_content_unknown_returns_error(self, tmp_path):
        assert "Unknown skill" in SkillLoader(tmp_path).get_content("nope")

    def test_missing_dir_is_empty(self, tmp_path):
        assert SkillLoader(tmp_path / "nope").skills == {}

    def test_descriptions_listing(self, tmp_path):
        _write(tmp_path, "a.md", "---\nname: a\ndescription: 技能A\n---\nx")
        _write(tmp_path, "b.md", "---\nname: b\ndescription: 技能B\n---\ny")
        desc = SkillLoader(tmp_path).get_descriptions()
        assert "- a: 技能A" in desc
        assert "- b: 技能B" in desc

    def test_reload_picks_up_new_file(self, tmp_path):
        loader = SkillLoader(tmp_path)
        assert loader.get("planning") is None
        _write(tmp_path, "planning.md", "---\nname: planning\ndescription: d\n---\nbody")
        loader.reload()
        assert loader.get("planning") == "body"

    def test_skills_dir_env_override(self, tmp_path, monkeypatch):
        _write(tmp_path, "planning.md", "---\nname: planning\ndescription: d\n---\nenv body")
        monkeypatch.setenv("SKILLS_DIR", str(tmp_path))
        loader = SkillLoader()
        assert loader.skills_dir == tmp_path
        assert loader.get("planning") == "env body"

    def test_default_package_dir_has_9_skills(self):
        loader = SkillLoader()
        assert len(loader.skills) == 9
        assert {
            "planning",
            "pricing_analysis",
            "feature_analysis",
            "performance_analysis",
            "ecosystem_analysis",
            "sentiment_analysis",
            "roadmap_analysis",
            "fact_verification",
            "confidence_disclosure",
        } <= set(loader.skills)

    def test_get_skill_loader_explicit_dir_bypasses_cache(self, tmp_path):
        _write(tmp_path, "x.md", "---\nname: x\ndescription: d\n---\nbody")
        loader = get_skill_loader(skills_dir=tmp_path)
        assert loader.get("x") == "body"
