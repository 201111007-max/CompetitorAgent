# 设计文档 41 — SSRF / URL 防护（统一 URL 守卫）

> 触发：2026-08-15 第二轮评审——`_react_web_extract`（`facade/api.py:480-489`）把模型/用户给出的 URL 原样丢给
> `self._extractor.fetch(...)`，MCP `web_extract`（`mcp_server/tools/web_tools.py:9-44`）`httpx.get(url, follow_redirects=True)`
> 同样不设防——**agent 可被诱导抓取内网/本机地址**（SSRF），且工具调用方是 LLM 输出（不可信数据，叠加设计文档 06 注入面）。
> 依赖：`core/url_guard.py`（新）、`config/loader.py`（`CollectorConfig.timeout_seconds`）、`interfaces/collector.py`（`ICompetitorDataSource.fetch`）、设计文档 40（两入口统一接入）。

## 1. 问题现状

- `_react_web_extract`（`facade/api.py:480-489`）对 URL 无任何校验：`http://127.0.0.1:8080/admin`、
  `http://169.254.169.254/latest/meta-data/`、`http://10.0.0.1/` 都会被直接抓取——**可读取本机/内网敏感信息**。
- MCP `web_extract`（`web_tools.py:19`）`httpx.get(url, follow_redirects=True)`：跳转可把公网 URL 重定向到内网地址再抓取（经典 SSRF 绕过），同样无防护。
- 超时/大小硬编码且不一致：web_tools 写死 `timeout=15.0`、`max_chars=8000`（web_tools.py:19/33）；ReAct 侧 `[:2000]`（api.py:489）；与 `CollectorConfig.timeout_seconds=20`（config/loader.py:56）三处并存——行为不可配置、口径混乱。
- 影响：agent 工具面（本批设计文档 38/40 强化后）能力越强，SSRF 风险面越大；"URL 安全边界"作为安全项必须有实证。

## 2. 目标设计

1. **统一 URL 守卫** `core/url_guard.py::guard_http_url(url)`：仅允许 http/https；解析后**拒绝私网/环回/保留地址段**（IPv4：127.0.0.0/8、10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、169.254.0.0/16、0.0.0.0/8、100.64.0.0/10；IPv6：::1、fc00::/7、fe80::/10、::ffff:内网映射）。
2. **DNS rebinding 缓解**：解析 hostname 得到**全部** IP（`socket.getaddrinfo` 全量），任一落在黑名单即拒绝——防止"解析时公网、抓取时内网"绕过。
3. **统一超时与内容上限**：读写 `CollectorConfig`（`timeout_seconds` + 新增 `max_content_chars`），消除三处硬编码。
4. **两入口统一生效**：ReAct `_react_web_extract`、MCP `web_extract`（及未来接真实 API 的 `web_search` 结果 URL）抓取前先过 `guard_http_url`（设计文档 40 的两入口同一守卫）。
5. **失败可回灌**：被拒绝返回可读原因（如"URL 指向内网地址，已拦截"），不抛原生异常——配合设计文档 38 四类反馈，模型可自恢复。

## 3. 模块/接口设计

### 3.1 新 `core/url_guard.py`

```python
PRIVATE_NETS = (  # ipaddress.ip_network 黑名单，IPv4/IPv6 统一
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "0.0.0.0/8", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10", "::ffff:0:0/96",
)

class URLError(ValueError):
    """URL 校验失败（携带可读原因，供回灌；与 ToolArgumentError 语义一致）"""

def resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """getaddrinfo 全量解析；解析失败抛 URLError('域名解析失败')"""

def guard_http_url(url: str) -> str:
    """校验 url：http/https 且 host 全部 IP 不在黑名单；通过返回规范化 url，失败抛 URLError(可读原因)"""
```

- 解析黑名单判定用 `ip_address.is_private / is_loopback / is_link_local / is_reserved / is_multicast`（标准库，覆盖比手写网段更稳）；手写网段保留为显式兜底。
- `guard_http_url` 内部做 DNS 解析是**抓取前预检**；`WebExtractor` 实际抓取仍走其 `httpx`（不保证与预检同 IP，故配合重定向白名单拦截，见 3.3）。

### 3.2 `config/loader.py` 扩展

```python
class CollectorConfig:
    ...
    max_content_chars: int = 8000   # 统一内容大小上限（替代 web_tools 硬编码 8000 / ReAct 2000）
    block_private_urls: bool = True # 默认开启；False 用于本地调试
```

### 3.3 接入点

- **ReAct**：`facade/api.py::_react_web_extract` 抓取前 `url = guard_http_url(url)`（`URLError` 捕获返回可读文本），`[:2000]` 改为读 `config.max_content_chars`。
- **MCP**：`mcp_server/tools/web_tools.py::web_extract` 抓取前 `guard_http_url`；`follow_redirects=True` 改为**手动跟随且每跳重新校验**（`httpx` 关掉自动 follow，循环校验 Location）——杜绝重定向到内网。
- **WebExtractor**（`interfaces/collector.py` 实现）如为独立抓取入口，同样加守卫；`web_search`（web_tools.py:47）接真实 API 后对结果 URL 复用守卫。
- 统一超时：`timeout = config.collector.timeout_seconds`（替代 web_tools 的 15.0 硬编码）。

## 4. 接入方式

```
LLM/用户 URL（不可信）→ guard_http_url（scheme + 全量 IP 黑名单 + DNS 预检）
  ├─ ReAct _react_web_extract（facade/api.py）→ 失败回灌可读原因（设计文档 38）
  └─ MCP web_extract（web_tools.py）→ 每跳重校验（防重定向绕过）
统一超时/大小读 CollectorConfig；block_private_urls=False 可本地调试豁免
```

- 主流程（GapExecutor 的 SourceSelector 源）URL 由配置/白名单源提供，另做来源级校验（不在本批范围）。
- 兼容：`block_private_urls=True` 时仅拦截私网/环回，公网采集行为不变；合法公网 URL 全量通过。

## 5. 验证方式

- **单测（黑名单）**：`guard_http_url` 对 `127.0.0.1`、`10.x`、`172.16-31.x`、`192.168.x`、`169.254.x`、`::1`、`fc00::/7`、`fe80::/10` 均抛 `URLError` 且 message 可读；`https://example.com` 通过。
- **单测（scheme/畸形）**：`file://`、`ftp://`、无 scheme、非法 host → 拒绝。
- **单测（DNS rebinding）**：mock `socket.getaddrinfo` 返回多 IP（一公网一内网）→ 拒绝（全量校验）。
- **单测（大小/超时统一）**：`max_content_chars` 生效于 ReAct 侧与 MCP 侧；超时读 `CollectorConfig.timeout_seconds`（非硬编码）。
- **集成（重定向）**：mock httpx 返回 302 → Location 指向 `127.0.0.1` → 拒绝且不跟随。
- **回归**：既有 web_extract / ReAct 测试全绿（公网 URL 行为不变）。

## 6. 实现优先级与工作量

- 优先级：**高**（安全边界；设计文档 38/40 强化工具面后的必要配套）。
- 工作量：约 0.5 天。
  - `url_guard.py` + 黑名单/全量解析：0.2 天；
  - 两入口接入 + 重定向逐跳校验 + 配置化超时/大小：0.2 天；
  - 测试：0.1 天。
- 前置：设计文档 40（两入口接线）；与 38（失败回灌语义）复用 `ToolArgumentError` 风格，同批落地。
