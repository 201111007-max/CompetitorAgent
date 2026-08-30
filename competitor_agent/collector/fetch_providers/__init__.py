"""抓取 provider 子包（设计文档 71 §3.4 三级降级链）：
``trafilatura``（本地解析，默认）→ ``crawl4ai``（本地浏览器渲染，可选）→ ``jina_reader``（云端兜底）。

统一经 ``collector.fetch.build_fetch_router`` 装配；各 provider 实现
``FetchProvider.fetch``，失败返回 ``FetchResult(success=False, reason=...)`` 不抛异常。
"""
