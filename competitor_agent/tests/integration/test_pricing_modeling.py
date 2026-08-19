"""设计文档 27 §5 集成（49 命名空间）：analyze → 报告含定价档位表 / 成本场景表

details 沿用 49 命名空间（``details["plans"]`` 原始档位），经
``profile_from_details`` 结构抽取为 PricingProfile（含成本估算）→ 渲染定价表。
"""
from __future__ import annotations

import pytest

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.domain_types.pricing import profile_from_details
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.memory import FourLayerMemory
from tests.conftest import FakeExtractor

pytestmark = pytest.mark.integration

_RICH_PRICING = (
    "Free $0\nPro $20/month (1000 requests/month)\nTeams $40/month\n"
    "Enterprise (contact sales)\nper 1000 requests $0.5\nincludes 1000 requests/month\n"
    "Advanced model $2.00/request"
)

# 离线环境 URL 守卫（DNS 解析）会拦截 before 采集器运行：关闭守卫让采集器真被命中
_OFFLINE_CFG = AppConfig(collector=CollectorConfig(block_private_urls=False))


class RichPricingExtractor(FakeExtractor):
    """定价页文本含免费/付费档位 + 按量计费 + 模型档位 + 企业询价。

    doc 49：web_extract 传 InfoGap(field="web")，按 URL 判定定价页而非 gap.field。
    """

    def fetch(self, gap, context):
        obs = super().fetch(gap, context)
        if "pricing" in str(context.kwargs.get("url")):
            obs.raw_text = _RICH_PRICING
        return obs


class TestPricingModelingIntegration:
    def test_report_contains_pricing_tables(self, tmp_path, mock_llm) -> None:
        api = CompetitorAnalysisAPI(
            extractor=RichPricingExtractor(),
            llm=mock_llm,
            use_llm=True,
            memory=FourLayerMemory(tmp_path / "memory"),
            max_iterations=10,
            config=_OFFLINE_CFG,
        )
        report = api.analyze("分析 Cursor 的定价", mode="single", session_id="sess_pricing_1")
        pricing = [r for r in report.dimension_results if r.dimension == "pricing"]
        assert pricing, "报告应包含 pricing 维度"

        profile = profile_from_details(pricing[0].details, pricing[0].evidence)
        assert profile is not None and profile.has_pricing_data
        # 档位表：mock LLM 确定性抽取 free/pro/teams 等档位
        assert len(profile.plans) >= 4
        assert {"free", "pro", "business"} <= {p.tier for p in profile.plans}

        # 注：mock LLM 将按量行 "per 1000 requests $0.5" 解析为档位而非 usage，
        # 且不产出企业询价档，故 usage/需询价 断言在 mock 路径下不成立
        # （设计文档 27 §3.2 按量/询价标注需真实 LLM 解析）。
        md = report.markdown_report
        assert "#### 定价档位" in md
        assert "#### 成本场景估算" in md
        assert "| light | 30 次/天 |" in md
        # 中等用量（100 次/天）成本可估算（非空）
        assert profile.cost_scenarios["medium"] is not None

    def test_profile_serialized_into_session_archive(self, tmp_path, mock_llm) -> None:
        mem = FourLayerMemory(tmp_path / "memory")
        api = CompetitorAnalysisAPI(
            extractor=RichPricingExtractor(),
            llm=mock_llm,
            use_llm=True,
            memory=mem,
            max_iterations=10,
            config=_OFFLINE_CFG,
        )
        api.analyze("分析 Cursor 的定价", mode="single", session_id="sess_pricing_arch")
        sessions = mem.list_sessions("cursor")
        assert sessions
        pricing_profiles = sessions[0].raw.get("pricing_profiles") or []
        assert pricing_profiles, "定价画像随报告归档落盘（设计文档 27 §3.3）"
        assert pricing_profiles[0]["plans"]
        assert pricing_profiles[0]["cost_scenarios"]
