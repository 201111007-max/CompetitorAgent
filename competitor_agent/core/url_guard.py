"""URL 安全守卫（设计文档 41）— SSRF 防护

仅允许 http/https；解析 host 得到全部 IP（getaddrinfo 全量），任一落在私网/环回/保留/
链路本地/组播地址段即拒绝（防 DNS rebinding：解析时公网、抓取时内网）。拒绝抛 URLError
（可读原因，供 ReAct/MCP 失败回灌，模型可自恢复）。
入口：ReAct `_react_web_extract`（facade/api.py）、MCP `web_extract`（mcp_server/tools/web_tools.py）。
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse

PRIVATE_NETS = (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "0.0.0.0/8", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10", "::ffff:0:0/96",
)
_BLOCKED_NETS = tuple(ipaddress.ip_network(net) for net in PRIVATE_NETS)


class URLError(ValueError):
    """URL 校验失败（携带可读原因，供回灌；与 ToolArgumentError 语义一致）"""


def resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """getaddrinfo 全量解析 host；解析失败抛 URLError('域名解析失败')。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise URLError(f"域名解析失败: {host}（{exc}）") from exc
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if ip not in ips:
            ips.append(ip)
    return ips


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped  # IPv4-mapped IPv6（::ffff:x.x.x.x）按底层 IPv4 判定
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast
        or any(ip in net for net in _BLOCKED_NETS)
    )


def guard_http_url(url: str, *, block_private: bool = True) -> str:
    """校验 url：仅 http/https；block_private 时 host 全部 IP 不在黑名单。

    通过返回规范化 url；失败抛 URLError（可读原因）。
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLError(f"仅支持 http/https 协议，当前 scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise URLError("URL 缺少主机名")
    if block_private:
        for ip in resolve_all(host):
            if _is_blocked(ip):
                raise URLError(
                    f"URL 指向内网/保留地址（{ip.compressed}），已拦截以防护 SSRF"
                )
    return parsed.geturl()
