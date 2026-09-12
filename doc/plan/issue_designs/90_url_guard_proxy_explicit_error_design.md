# 设计文档 90 —— 第四十轮：url_guard 代理环境显式报错（C 方案）

> 第四十轮。来源：`doc/tech_review_2026-09-12.md` 修复顺序建议节的"新设计观察"——
> url_guard 的 SSRF 防护用 `socket.getaddrinfo` 做**本机直接 DNS 预检**，与 http 代理
> 出网模式互斥（代理模式下 DNS 应由代理服务器代做，本机解析公网域名必失败）。
> 后果：企业代理环境下整个抓取链（trafilatura→crawl4ai→jina）静默降级为
> "域名解析失败"，用户无法区分是目标站挂了还是环境不兼容。
>
> 用户已选定 **C 方案：维持防护现状 + 显式报错**（不做代理豁免，不引 DoH）。
> A（代理豁免+域名白名单，削弱 SSRF 防护）/ B（DoH 代理解析，引依赖）均不实施，
> 留作后续真需要代理环境抓取时的再决策项。

---

## 1. 方案

单点修改 `core/url_guard.py::resolve_all`（DNS 失败唯一 choke point）：
`socket.gaierror` 时检测代理环境变量（`https_proxy/HTTPS_PROXY/http_proxy/HTTP_PROXY`
任一非空）——

- **有代理** → `URLError` 文案改为显式不兼容说明：代理出网模式下本机不做 DNS，
  而 SSRF 守卫必须本机预检目标 IP，二者不兼容；指引"在 DNS 可直连环境运行抓取；
  代理环境支持属待决策设计项"。**不降级、不豁免、不加开关**。
- **无代理** → 保持原文案不变（`域名解析失败: host（原始 gaierror）`）。

行为面零变化（抛的仍是 `URLError`，21 个调用点与失败回灌路径不动），仅文案在
代理环境下更可行动。

## 2. 测试验收

`tests/unit/core/test_url_guard.py` 新增 `TestProxyEnvMessage`（全程 mock，无网络依赖）：
- getaddrinfo 抛 gaierror + 设 `https_proxy` → 消息含"代理"与"SSRF"字样；
- getaddrinfo 抛 gaierror + 清空全部代理变量 → 保持原始"域名解析失败"文案；
- 既有用例零改动（CI DNS 直连环境行为不变；`network` 标记家族不受影响）。

## 3. 风险权衡

- 代理检测只看环境变量存在性，不判断代理是否真生效：误报场景（设了代理但 DNS
  也可直连）下 DNS 本就成功、走不到该分支，无影响；漏报场景（代理经其他机制
  注入）退化为原文案，可接受。
- 不验证"代理环境下 fetch 是否真的可用"（block_private=False + httpx 走代理理论
  可用）：C 方案明确不做运行时豁免，该路径不开放也就不需要验证。
