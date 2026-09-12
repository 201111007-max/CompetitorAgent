"""设计文档 79：Domain Pack 配置化——回归基线（coding 等价）+ 可插拔（saas_pm）+ 防呆。

验收映射（doc 79 §4）：4.1 回归基线（coding pack 下沉 = 现状等价改写）；4.2/4.3 可插拔
（saas_pm 全链路：注册表/维度/品类/权重/技能来自 pack，零领域渗漏）；4.4 防呆（缺段可读错误）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from competitor_agent.agent.make_plan import make_plan
from competitor_agent.agent.react_schemas import DIMENSIONS, pack_dimensions
from competitor_agent.agent.subagent_registry import (
    SubagentRegistry,
    get_subagent_registry,
    reset_subagent_registry,
)
from competitor_agent.core.competitor_registry import (
    canonicalize,
    resolve_competitor,
)
from competitor_agent.core.domain_pack import (
    load_domain_pack,
    set_active_pack,
)
from competitor_agent.core.report_builder import ReportBuilder
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.enums import ResultStatus
from competitor_agent.domain_types.report import DimensionResult
from competitor_agent.skills.loader import SkillLoader


@pytest.fixture()
def coding_pack():
    """测试前后恢复 coding_agent（防 pack 状态跨测试泄漏）。"""
    set_active_pack("coding_agent")
    yield
    set_active_pack("coding_agent")


class TestRegressionBaseline:
    """doc 79 §4.1：coding pack 下沉 = 现状等价改写（任何行为差异都是 bug）。"""

    def test_yaml_matches_inline_defaults(self) -> None:
        from competitor_agent.agent.subagent_registry_defaults import CODING_DIMENSIONS

        yaml_pack = load_domain_pack("coding_agent")
        assert yaml_pack.dimension_names == CODING_DIMENSIONS.dimension_names == list(DIMENSIONS)
        for d_yaml, d_inline in zip(yaml_pack.dimensions, CODING_DIMENSIONS.dimensions):
            assert d_yaml.tools == d_inline.tools
            assert d_yaml.skills == d_inline.skills
            assert d_yaml.description == d_inline.description
        assert yaml_pack.default_dimension_weights == CODING_DIMENSIONS.default_dimension_weights

    def test_coding_registry_seeds_equivalent(self) -> None:
        yaml_pack = load_domain_pack("coding_agent")
        assert {s.name for s in yaml_pack.registry_seeds} == set(
            _fallback_names()
        )
        for seed in yaml_pack.registry_seeds:
            assert resolve_competitor(seed.name).name == seed.name

    def test_active_registry_matches_coding_shape(self, coding_pack) -> None:
        registry = get_subagent_registry()
        assert [n for n in registry.names() if n != "competitor"] == list(DIMENSIONS)
        cfg = registry.get("pricing")
        assert cfg is not None
        assert "analyze_pricing" in cfg.tools
        assert cfg.skills == ("pricing_analysis", "fact_verification", "confidence_disclosure")

    def test_make_plan_accepts_coding_dimensions(self, coding_pack) -> None:
        plan = {"competitor": "cursor", "dimensions": list(DIMENSIONS)}
        result = make_plan(plan, allowed_dimensions=pack_dimensions())
        assert result.startswith("{")  # 校验通过原样回传
        bad = make_plan({"competitor": "cursor", "dimensions": ["integrations"]},
                        allowed_dimensions=pack_dimensions())
        assert bad.startswith("make_plan 校验失败")


def _fallback_names() -> list[str]:
    from competitor_agent.core.competitor_registry import _fallback_registry

    return sorted(_fallback_registry())


class TestPluggability:
    """doc 79 §4.2/§4.3：saas_pm 全链路独立（注册表/维度/品类/权重/技能）。"""

    def test_switch_pack_rebuilds_registry_and_dimensions(self) -> None:
        set_active_pack("saas_pm")
        try:
            assert pack_dimensions() == [
                "pricing", "feature", "integrations", "adoption", "sentiment", "roadmap",
            ]
            registry = get_subagent_registry()
            assert registry.get("integrations") is not None
            assert registry.get("adoption") is not None
            assert registry.get("performance") is None  # coding 专属维度不在 saas pack
            # 注册表随 pack：seed 竞品可解析、category 来自 pack
            assert resolve_competitor("Notion").name == "notion"
            assert resolve_competitor("linear.app").name == "linear"
            assert resolve_competitor("notion").category == "saas_project_management"
            with pytest.raises(ValueError):
                resolve_competitor("cursor")  # coding 竞品不在 saas 注册表
        finally:
            set_active_pack("coding_agent")
        # 切回后恢复
        assert resolve_competitor("cursor").name == "cursor"
        assert resolve_competitor("cursor").category == "ai_coding_agent"

    def test_pack_skills_resolvable(self) -> None:
        set_active_pack("saas_pm")
        try:
            loader = SkillLoader()  # 主目录 + pack 目录叠加扫描
            assert loader.get("integrations_analysis") is not None
            assert loader.get("adoption_analysis") is not None
            assert loader.get("pricing_analysis") is not None  # 主目录同名仍可用
        finally:
            set_active_pack("coding_agent")

    def test_discovered_competitor_gets_pack_category(self) -> None:
        from competitor_agent.core.competitor_discoverer import CompetitorDiscoverer

        set_active_pack("saas_pm")
        try:
            competitors = CompetitorDiscoverer._to_competitors(
                [{"name": "Height", "home": "https://height.app"}]
            )
            assert competitors[0].category == "saas_project_management"
        finally:
            set_active_pack("coding_agent")

    def test_report_uses_pack_weights_and_no_coding_vocabulary(self) -> None:
        """doc 79 §4.2 验收：saas 维度出报告，全文零 coding agent 词汇。"""
        set_active_pack("saas_pm")
        try:
            pack = load_domain_pack("saas_pm")
            builder = ReportBuilder(dimension_weights=pack.default_dimension_weights)
            results = [
                DimensionResult(
                    dimension=name,
                    summary=f"{name} 结论",
                    details={},
                    confidence=0.8,
                    status=ResultStatus.COMPLETE,
                )
                for name in pack.dimension_names
            ]
            report = builder.build(
                Competitor(name="notion", category=pack.category_label),
                results,
                gaps_pending=[],
                terminal_state="success",
            )
            assert report.terminal_state == "success"
            for name in pack.dimension_names:
                assert name in report.markdown_report
            lowered = report.markdown_report.lower()
            for forbidden in ("ai ide", "代码补全", "mcp server 数量", "github copilot", "编码"):
                assert forbidden not in lowered, forbidden
        finally:
            set_active_pack("coding_agent")

    def test_canonicalize_unchanged(self) -> None:
        assert canonicalize("Notion ") == "notion"


class TestGuardRails:
    """doc 79 §4.4：pack 缺段 → 可读错误（不静默半装配）。"""

    def test_missing_pack_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_domain_pack("nope", domains_dir=tmp_path)

    def test_missing_dimensions_section(self, tmp_path: Path) -> None:
        (tmp_path / "bad.yaml").write_text("domain: bad\n", encoding="utf-8")
        with pytest.raises(ValueError, match="dimensions"):
            load_domain_pack("bad", domains_dir=tmp_path)

    def test_missing_registry_seeds(self, tmp_path: Path) -> None:
        (tmp_path / "bad2.yaml").write_text(
            "domain: bad2\ncategory_label: x\ndimensions:\n  - name: pricing\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="registry_seeds"):
            load_domain_pack("bad2", domains_dir=tmp_path)

    def test_duplicate_dimensions_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "dup.yaml").write_text(
            "domain: dup\ndimensions:\n  - name: a\n  - name: a\nregistry_seeds:\n  - name: x\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="重复"):
            load_domain_pack("dup", domains_dir=tmp_path)

    def test_fallback_when_dir_missing(self, tmp_path: Path, monkeypatch) -> None:
        """yaml 目录缺失 → 内联 coding 默认（行为与现状逐位一致）。"""
        from competitor_agent.core.domain_pack import active_domain_pack

        monkeypatch.setenv("COMPETITOR_AGENT_DOMAINS_DIR", str(tmp_path / "nope"))
        pack = active_domain_pack()
        assert pack.dimension_names == list(DIMENSIONS)


class TestSubagentRegistryCompat:
    def test_subagent_registry_from_pack_and_competitor_namespace(self) -> None:
        pack = load_domain_pack("coding_agent")
        registry = SubagentRegistry.from_pack(pack)
        assert registry.get("competitor") is not None
        assert registry.resolve("Some Unknown Agent").name == "competitor"
        assert registry.get("pricing").tools == ("web_extract", "web_search", "analyze_pricing")

    def test_reset_rebuilds(self, coding_pack) -> None:
        first = get_subagent_registry()
        reset_subagent_registry()
        second = get_subagent_registry()
        assert first is not second
        assert second.get("pricing") is not None
