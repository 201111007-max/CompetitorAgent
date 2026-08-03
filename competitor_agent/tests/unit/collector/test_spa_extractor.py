"""collector/spa_extractor.py 单测：注入式渲染钩子，无需真实浏览器"""
from competitor_agent.collector.spa_extractor import SpaExtractor
from competitor_agent.domain_types import InfoGap
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

SPA_HTML = """
<html><head><title>Cursor (SPA)</title></head>
<body>
<main>
  <p>Cursor is an AI code editor forked from VS Code, used by teams worldwide.</p>
</main>
<script>
  // 真实 SPA 靠 JS 填充 root；渲染钩子返回"渲染后"的 DOM
  document.getElementById('root').innerHTML =
    '<h1>Cursor Pricing</h1><p>Pro plan: $20/month</p>';
</script>
<footer>Copyright 2024</footer>
</body></html>
"""

RENDERED_HTML = """
<html><head><title>Cursor (SPA)</title></head>
<body>
<div id="root">
  <h1>Cursor Pricing</h1>
  <p>Pro plan: $20/month</p>
  <p>Premier plan: $40/month</p>
  <p>Teams plan: $60/month</p>
  <p>All plans include unlimited AI usage and access to the latest models.</p>
</div>
<footer>Copyright 2024</footer>
</body></html>
"""


def _ctx(url: str) -> SourceContext:
    return SourceContext(competitor_name="cursor", kwargs={"url": url})


class TestSpaExtractor:
    def test_fetch_renders_js_content(self):
        extractor = SpaExtractor(render_page=lambda url: RENDERED_HTML)
        assert extractor.is_available()
        obs = extractor.fetch(InfoGap(field="pricing"), _ctx("https://www.cursor.com/pricing"))
        assert obs.gap_field == "pricing"
        assert obs.source == "spa_extractor"
        assert obs.status.value == "ok"
        assert "Pro plan: $20/month" in obs.raw_text
        assert obs.evidence.trust_level == 0.9

    def test_unavailable_without_playwright_and_hook(self):
        # 未装 playwright 且未注入钩子 → 不可用
        extractor = SpaExtractor()
        assert extractor.is_available() is False

    def test_fetch_missing_url_raises(self):
        extractor = SpaExtractor(render_page=lambda url: RENDERED_HTML)
        try:
            extractor.fetch(InfoGap(field="pricing"), SourceContext(competitor_name="cursor"))
            assert False, "应抛 DataSourceUnavailableError"
        except DataSourceUnavailableError:
            pass

    def test_fetch_empty_rendered_raises(self):
        extractor = SpaExtractor(render_page=lambda url: "")
        try:
            extractor.fetch(InfoGap(field="pricing"), _ctx("https://example.com/spa"))
            assert False, "应抛 DataSourceUnavailableError"
        except DataSourceUnavailableError:
            pass

    def test_tiny_rendered_is_degraded(self):
        extractor = SpaExtractor(render_page=lambda url: "<div>hi</div>")
        obs = extractor.fetch(InfoGap(field="pricing"), _ctx("https://example.com/tiny"))
        assert obs.status.value == "degraded"

    def test_clean_removes_script_and_nav(self):
        extractor = SpaExtractor(render_page=lambda url: SPA_HTML)
        obs = extractor.fetch(InfoGap(field="pricing"), _ctx("https://www.cursor.com/pricing"))
        assert "innerHTML" not in obs.raw_text
        assert "getElementById" not in obs.raw_text
