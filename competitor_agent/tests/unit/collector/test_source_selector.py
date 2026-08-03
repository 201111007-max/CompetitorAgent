"""collector/source_selector.py 单测：降级链排序"""
from competitor_agent.collector.source_selector import SourceSelector
from competitor_agent.domain_types import Competitor, InfoGap


def _gap(field="pricing"):
    return InfoGap(field=field)


def _cursor():
    return Competitor(
        name="cursor",
        official_links={
            "home": "https://www.cursor.com",
            "pricing": "https://www.cursor.com/pricing",
            "docs": "https://docs.cursor.com",
        },
    )


class TestSourceSelector:
    def test_pricing_uses_pricing_then_home(self):
        s = SourceSelector()
        gap = _gap("pricing")
        cands = s.candidates(gap, _cursor())
        assert cands[0].source_name == "official_pricing"
        assert cands[1].source_name == "official_home"

    def test_feature_uses_docs_then_home(self):
        s = SourceSelector()
        cands = s.candidates(_gap("feature"), _cursor())
        assert cands[0].source_name == "official_docs"
        assert cands[1].source_name == "official_home"

    def test_tried_sources_removed(self):
        s = SourceSelector()
        gap = _gap("pricing")
        gap.record_source_try("official_pricing")
        cands = s.candidates(gap, _cursor())
        assert all(c.source_name != "official_pricing" for c in cands)
        assert cands[0].source_name == "official_home"

    def test_trust_level_decending(self):
        s = SourceSelector()
        cands = s.candidates(_gap("pricing"), _cursor())
        assert cands[0].trust_level == 0.9
        assert cands[1].trust_level == 0.9

    def test_has_next(self):
        s = SourceSelector()
        assert s.has_next(_gap("pricing"), _cursor(), 0)
        assert not s.has_next(_gap("pricing"), _cursor(), 5)

    def test_no_links_no_candidates(self):
        s = SourceSelector()
        comp = Competitor(name="codex")  # 无 official_links
        assert s.candidates(_gap("pricing"), comp) == []