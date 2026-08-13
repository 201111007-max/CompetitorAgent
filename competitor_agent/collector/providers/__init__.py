"""collector/providers — 官网之外的外部源提供方（设计文档 23）

`build_providers(cfg)` 按配置构造外部源提供方列表（用于 SourceSelector 路由）。
主开关 `collector.enable_external_sources` 默认关闭——无网络/无 Key 的评测与测试
不触发真实网络；开启后按维度开关逐个启用提供方。
"""
from __future__ import annotations

from competitor_agent.collector.providers.benchmark_source import BenchmarkSourceProvider
from competitor_agent.collector.providers.community_provider import CommunitySourceProvider
from competitor_agent.collector.providers.github_provider import GithubSourceProvider
from competitor_agent.collector.providers.marketplace_provider import MarketplaceSourceProvider
from competitor_agent.config.loader import CollectorConfig

__all__ = [
    "BenchmarkSourceProvider",
    "build_providers",
    "CommunitySourceProvider",
    "GithubSourceProvider",
    "MarketplaceSourceProvider",
]


def build_providers(cfg: CollectorConfig | None = None) -> list[object]:
    """按配置构造外部源提供方列表。

    - `cfg.enable_external_sources` 主开关关闭（默认）→ 返回空列表（行为与现状一致）；
    - 开启后按 `enable_github` / `enable_marketplace` / `enable_community` / `enable_benchmark` 逐个启用。
    注：CommunitySourceProvider 未注入搜索函数时 supports()=False，实际不产候选。
    """
    cfg = cfg or CollectorConfig()
    if not cfg.enable_external_sources:
        return []
    providers: list[object] = []
    if cfg.enable_github:
        providers.append(GithubSourceProvider())
    if cfg.enable_marketplace:
        providers.append(MarketplaceSourceProvider())
    if cfg.enable_community:
        providers.append(CommunitySourceProvider())
    if cfg.enable_benchmark:
        providers.append(BenchmarkSourceProvider(cache_ttl_seconds=cfg.cache_ttl_seconds))
    return providers
