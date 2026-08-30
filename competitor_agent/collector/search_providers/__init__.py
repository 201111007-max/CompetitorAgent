"""搜索 provider 子包（设计文档 71 §3.3）：DDG 免费主力 + 未来预留（Bocha 等）。

统一经 ``collector.search.build_search_router`` 装配，provider 各自实现
``SearchProvider.search``；``source_engine`` 类属性供路由标注命中引擎。
"""
