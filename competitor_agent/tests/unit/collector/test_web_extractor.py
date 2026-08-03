"""collector/web_extractor.py 单测：mock 页面返回结构化 Observation"""
import httpx

from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.domain_types import InfoGap
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError

HTML = """
<html><head><title>Cursor</title></head>
<body>
<nav>Home Pricing Docs</nav>
<h1>Cursor Pricing</h1>
<p>Pro plan: $20/month</p>
<p>Team plan: $40/month</p>
<script>var secret = 1;</script>
<footer>Copyright 2024</footer>
</body></html>
"""


def _make_client(responses):
    """用 httpx.MockTransport 构造 mock client（响应表 url -> Response/异常）"""

    def handler(request):
        item = responses.get(str(request.url))
        if item is None:
            return httpx.Response(404, text="not found")
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ctx(url):
    return SourceContext(competitor_name="cursor", kwargs={"url": url})


class TestWebExtractor:
    def test_fetch_ok_returns_observation(self):
        client = _make_client({"https://www.cursor.com/pricing": httpx.Response(200, text=HTML)})
        we = WebExtractor(client=client)
        obs = we.fetch(InfoGap(field="pricing"), _ctx("https://www.cursor.com/pricing"))
        assert obs.gap_field == "pricing"
        assert obs.status.value == "ok"
        assert "Pro plan: $20/month" in obs.raw_text
        assert "var secret = 1;" not in obs.raw_text  # script 已移除
        assert "Home Pricing Docs" not in obs.raw_text  # nav 已移除
        assert obs.evidence.content_hash

    def test_fetch_missing_url_raises(self):
        we = WebExtractor()
        try:
            we.fetch(InfoGap(field="pricing"), SourceContext(competitor_name="cursor"))
            assert False, "应抛 DataSourceUnavailableError"
        except DataSourceUnavailableError:
            pass

    def test_http_404_raises_after_retries(self):
        client = _make_client({"https://example.com/x": httpx.Response(404, text="not found")})
        we = WebExtractor(max_retries=1, client=client)
        try:
            we.fetch(InfoGap(field="pricing"), _ctx("https://example.com/x"))
            assert False, "应抛 DataSourceUnavailableError"
        except DataSourceUnavailableError:
            pass

    def test_network_error_raises(self):
        client = _make_client({"https://example.com/err": httpx.ConnectError("boom")})
        we = WebExtractor(max_retries=1, client=client)
        try:
            we.fetch(InfoGap(field="pricing"), _ctx("https://example.com/err"))
            assert False, "应抛 DataSourceUnavailableError"
        except DataSourceUnavailableError:
            pass

    def test_tiny_page_is_degraded(self):
        client = _make_client({"https://example.com/tiny": httpx.Response(200, text="<p>hi</p>")})
        we = WebExtractor(client=client)
        obs = we.fetch(InfoGap(field="pricing"), _ctx("https://example.com/tiny"))
        assert obs.status.value == "degraded"

    def test_is_available(self):
        assert WebExtractor().is_available() is True