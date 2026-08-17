"""core/url_guard.py 单测 + ReAct/MCP 两入口接入测试（设计文档 41）

黑名单 / scheme 畸形 / DNS rebinding / 重定向逐跳 / max_content_chars 统一。
全程 mock 网络（socket.getaddrinfo / httpx），不触真实网络与 Key。
"""
from __future__ import annotations

import socket

import pytest

from competitor_agent.config.loader import AppConfig
from competitor_agent.core.url_guard import URLError, guard_http_url, resolve_all
from competitor_agent.domain_types import Observation, SourceEvidence
from competitor_agent.interfaces.context import SourceContext

PUBLIC_IP = "93.184.216.34"  # example.com 公网示例 IP


def _resolve(*ips: str):
    """mock socket.getaddrinfo：对任意 host 返回给定 IP 列表（IPv4/IPv6 混合）"""

    def fake(*_args, **_kwargs):
        infos = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            infos.append((family, socket.SOCK_STREAM, 6, "", (ip, 0)))
        return infos

    return fake


def _blocked_urls():
    """(url, 应解析出的 IP) 黑名单用例"""
    return [
        ("http://127.0.0.1/", "127.0.0.1"),
        ("http://127.0.0.1:8080/admin", "127.0.0.1"),
        ("http://10.0.0.1/", "10.0.0.1"),
        ("http://172.16.0.1/", "172.16.0.1"),
        ("http://172.31.255.255/", "172.31.255.255"),
        ("http://192.168.1.1/", "192.168.1.1"),
        ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
        ("http://[::1]/", "::1"),
        ("http://[fc00::1]/", "fc00::1"),
        ("http://[fe80::1]/", "fe80::1"),
    ]


class TestGuardBlacklist:
    @pytest.mark.parametrize("url,ip", _blocked_urls())
    def test_private_networks_rejected(self, monkeypatch, url, ip):
        monkeypatch.setattr(socket, "getaddrinfo", _resolve(ip))
        with pytest.raises(URLError, match="内网|保留"):
            guard_http_url(url)

    def test_public_url_passes(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _resolve(PUBLIC_IP))
        assert guard_http_url("https://example.com/pricing") == "https://example.com/pricing"

    def test_block_private_false_allows_private(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _resolve("127.0.0.1"))
        # block_private=False：本地调试豁免，仅校验 scheme
        assert guard_http_url("http://127.0.0.1:8000/", block_private=False) == "http://127.0.0.1:8000/"


class TestGuardScheme:
    def test_non_http_scheme_rejected(self):
        with pytest.raises(URLError, match="http/https"):
            guard_http_url("file:///etc/passwd")
        with pytest.raises(URLError, match="http/https"):
            guard_http_url("ftp://example.com/file")

    def test_no_scheme_rejected(self):
        with pytest.raises(URLError, match="http/https"):
            guard_http_url("example.com/pricing")

    def test_missing_host_rejected(self):
        with pytest.raises(URLError, match="主机名"):
            guard_http_url("https://")

    def test_resolve_failure_rejected(self, monkeypatch):
        def raise_gaierror(*_a, **_k):
            raise socket.gaierror("No address")

        monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
        with pytest.raises(URLError, match="域名解析失败"):
            guard_http_url("https://no-such-host.invalid/")


class TestGuardDnsRebinding:
    def test_multi_ip_one_private_rejected(self, monkeypatch):
        # DNS rebinding：解析返回 一公网 + 一内网 → 任一命中即拒绝
        monkeypatch.setattr(socket, "getaddrinfo", _resolve(PUBLIC_IP, "10.0.0.5"))
        with pytest.raises(URLError, match="内网|保留"):
            guard_http_url("https://attacker.example/")

    def test_multi_ip_all_public_passes(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _resolve(PUBLIC_IP, "1.1.1.1"))
        assert guard_http_url("https://attacker.example/") == "https://attacker.example/"

    def test_ipv4_mapped_ipv6_private_rejected(self, monkeypatch):
        # ::ffff:127.0.0.1 按底层 IPv4 判定
        monkeypatch.setattr(socket, "getaddrinfo", _resolve("::ffff:127.0.0.1"))
        with pytest.raises(URLError, match="内网|保留"):
            guard_http_url("https://attacker.example/")


class TestResolveAll:
    def test_dedup_and_parse(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _resolve(PUBLIC_IP, PUBLIC_IP))
        ips = resolve_all("example.com")
        assert len(ips) == 1
        assert str(ips[0]) == PUBLIC_IP

    def test_resolve_failure_raises(self, monkeypatch):
        def raise_gaierror(*_a, **_k):
            raise socket.gaierror("boom")

        monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
        with pytest.raises(URLError, match="域名解析失败"):
            resolve_all("no-such-host.invalid")


def _long_extractor(text: str):
    class _Fake:
        def fetch(self, gap, context: SourceContext) -> Observation:
            ev = SourceEvidence(source_name="web_extractor", url=str(context.kwargs.get("url")), content_hash="h")
            return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)

    return _Fake()


class TestReActSide:
    """ReAct _react_web_extract：守卫拦截可读回灌 + max_content_chars 统一"""

    def test_private_url_intercepted_readable(self, monkeypatch, mock_llm):
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        monkeypatch.setattr(socket, "getaddrinfo", _resolve("127.0.0.1"))
        api = CompetitorAnalysisAPI(extractor=_long_extractor("secret"), llm=mock_llm, use_llm=True)
        out = api._react_web_extract("http://127.0.0.1:8080/admin")
        assert "URL 被安全守卫拦截" in out
        assert "secret" not in out  # 未抓取内网

    def test_max_content_chars_applied(self, monkeypatch, mock_llm):
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        monkeypatch.setattr(socket, "getaddrinfo", _resolve(PUBLIC_IP))
        cfg = AppConfig()
        cfg.collector.max_content_chars = 10
        api = CompetitorAnalysisAPI(extractor=_long_extractor("A" * 100), llm=mock_llm, use_llm=True, config=cfg)
        out = api._react_web_extract("https://example.com/")
        assert out == "A" * 10

    def test_block_private_false_skips_guard(self, monkeypatch, mock_llm):
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        monkeypatch.setattr(socket, "getaddrinfo", _resolve("127.0.0.1"))
        cfg = AppConfig()
        cfg.collector.block_private_urls = False
        api = CompetitorAnalysisAPI(extractor=_long_extractor("ok"), llm=mock_llm, use_llm=True, config=cfg)
        assert api._react_web_extract("http://127.0.0.1/") == "ok"


class TestMcpSide:
    """MCP web_extract：守卫 + 手动逐跳重校验 + 配置化超时/大小"""

    @pytest.fixture(autouse=True)
    def _ensure_httpx(self):
        pytest.importorskip("httpx")

    def test_private_url_intercepted(self):
        from mcp_server.tools.web_tools import web_extract

        out = web_extract("http://127.0.0.1:8080/admin")
        assert "URL 被安全守卫拦截" in out

    def test_redirect_to_private_rejected_not_followed(self, monkeypatch):
        import httpx

        from mcp_server.tools.web_tools import web_extract

        calls: list[str] = []

        def fake_get(url, **_kwargs):
            calls.append(str(url))
            if str(url).startswith("https://example.com"):
                return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
            return httpx.Response(200, text="<html><body>private</body></html>")

        def host_resolve(host, *_a, **_k):
            # example.com → 公网；重定向目标（127.0.0.1 字面量）→ 自身内网
            if str(host) == "example.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", host_resolve)
        monkeypatch.setattr(httpx, "get", fake_get)
        out = web_extract("https://example.com/")
        assert "URL 被安全守卫拦截" in out
        assert len(calls) == 1  # 302 未被跟随

    def test_redirect_public_followed(self, monkeypatch):
        pytest.importorskip("bs4")
        import httpx

        from mcp_server.tools.web_tools import web_extract

        calls: list[str] = []

        def fake_get(url, **_kwargs):
            calls.append(str(url))
            if str(url) == "https://example.com/":
                return httpx.Response(302, headers={"location": "https://example.com/pricing"})
            return httpx.Response(200, text="<html><body>pricing page</body></html>", request=httpx.Request("GET", url))

        monkeypatch.setattr(socket, "getaddrinfo", _resolve(PUBLIC_IP))
        monkeypatch.setattr(httpx, "get", fake_get)
        out = web_extract("https://example.com/")
        assert "pricing page" in out
        assert len(calls) == 2  # 公网重定向逐跳跟随

    def test_config_timeout_and_max_chars(self, monkeypatch):
        pytest.importorskip("bs4")
        import httpx

        from mcp_server.tools.web_tools import web_extract

        cfg = AppConfig()
        cfg.collector.timeout_seconds = 7
        cfg.collector.max_content_chars = 10

        captured: dict = {}

        def fake_get(url, **kwargs):
            captured.update(kwargs)
            return httpx.Response(200, text="<html><body>" + "X" * 100 + "</body></html>", request=httpx.Request("GET", url))

        monkeypatch.setattr(socket, "getaddrinfo", _resolve(PUBLIC_IP))
        monkeypatch.setattr("mcp_server.tools.web_tools.load_config", lambda: cfg)
        monkeypatch.setattr(httpx, "get", fake_get)
        out = web_extract("https://example.com/")
        assert captured["timeout"] == 7  # 读 CollectorConfig.timeout_seconds，非硬编码
        assert captured["follow_redirects"] is False
        assert out.startswith("X" * 10)
        assert "（截断）" in out
