"""设计文档 27 §5 集成：analyze 完整流水线 → 报告含定价档位表 / 按量计费表 / 成本场景表 / 需询价标注"""
from __future__ import annotations

import pytest

from competitor_agent.domain_types.pricing import PricingProfile
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.memory import FourLayerMemory
from tests.conftest import FakeExtractor

pytestmark = pytest.mark.integration

_RICH_PRICING = (
    "Free $0\nPro $20/month (1000 requests/month)\nTeams $40/month\n"
    "Enterprise (contact sales)\nper 1000 requests $0.5\nincludes 1000 requests/month\n"
    "Advanced model $2.00/request"
)


class RichPricingExtractor(FakeExtractor):
    """定价页文本含免费/付费档位 + 按量计费 + 模型档位 + 企业询价。"""

    def fetch(self, gap, context):
        obs = super().fetch(gap, context)
        if str(getattr(gap, "field", "")) == "pricing":
            obs.raw_text = _RICH_PRICING
        return obs


class TestPricingModelingIntegration:
    def test_report_contains_pricing_tables(self, fake_extractor, tmp_path) -> None:
        api = CompetitorAnalysisAPI(
            extractor=RichPricingExtractor(),
            use_llm=False,
            memory=FourLayerMemory(tmp_path / "memory"),
            max_iterations=10,
        )
        report = api.analyze("分析 Cursor 的定价", mode="single", session_id="sess_pricing_1")
        pricing = [r for r in report.dimension_results if r.dimension == "pricing"]
        assert pricing, "报告应包含 pricing 维度"

        profile = PricingProfile.from_dict(pricing[0].details["pricing"])
        assert profile is not None and profile.has_pricing_data
        # 免费/Pro/Teams/Enterprise 四档 + 按量 + 企业询价
        assert len(profile.plans) == 4
        assert any(p.requires_quote for p in profile.plans)
        assert profile.usage is not None and profile.usage.per_unit_usd == 0.0005

        md = report.markdown_report
        assert "#### 定价档位" in md
        assert "#### 按量计费" in md
        assert "#### 成本场景估算" in md
        assert "需询价" in md
        assert "| light | 30 次/天 |" in md
        # 中等用量（100 次/天）成本可估算（非空）
        assert profile.cost_scenarios["medium"] is not None

    def test_profile_serialized_into_session_archive(self, tmp_path) -> None:
        mem = FourLayerMemory(tmp_path / "memory")
        api = CompetitorAnalysisAPI(
            extractor=RichPricingExtractor(),
            use_llm=False,
            memory=mem,
            max_iterations=10,
        )
        api.analyze("分析 Cursor 的定价", mode="single", session_id="sess_pricing_arch")
        sessions = mem.list_sessions("cursor")
        assert sessions
        pricing_profiles = sessions[0].raw.get("pricing_profiles") or []
        assert pricing_profiles, "定价画像随报告归档落盘（设计文档 27 §3.3）"
        assert pricing_profiles[0]["plans"]
        assert pricing_profiles[0]["cost_scenarios"]
