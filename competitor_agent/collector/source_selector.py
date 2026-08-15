"""SourceSelector — 信息缺口 → 数据源候选排序（降级链）

降级链：官方源 → 缓存/镜像 → 替代源 →（M2）Playwright →（设计文档 23）外部源。
设计文档 23：缺口 → 外部源路由（ecosystem → GitHub+插件市场、sentiment → 社区、
performance → 榜单、roadmap → GitHub Releases），候选统一为带 kind 的 SourceCandidate。
M1 用规则：每个维度给出一组候选 URL，按可信度排序。
"""
from __future__ import annotations

from dataclasses import dataclass

from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.domain_types.info_gap import InfoGap
from competitor_agent.interfaces.context import SourceContext

# 官方链接 key（competitor.official_links）→ 维度映射
_DIMENSION_LINK_KEY: dict[str, list[str]] = {
    "pricing": ["pricing", "home"],
    "feature": ["docs", "home"],
    "performance": ["docs", "home"],
    "ecosystem": ["docs", "home"],
    "sentiment": ["home"],
    "roadmap": ["docs", "changelog", "home"],
}

# 缺口 → 候选源 kind 路由表（设计文档 23 §3.2）；"web" 由官方链接覆盖，
# 其余 kind 命中注入的 ExternalSourceProvider。
_GAP_TO_KINDS: dict[str, list[str]] = {
    "pricing": ["web"],
    "feature": ["web", "github"],
    "performance": ["benchmark", "web"],
    "ecosystem": ["github", "marketplace", "web"],
    "sentiment": ["social", "web"],
    "roadmap": ["github", "web"],
}

# 走默认 extractor 的候选 kind（官网/SPA/缓存）
_WEB_KINDS = frozenset({"web", "spa", "cache"})


@dataclass(frozen=True)
class SourceCandidate:
    """单个数据源候选"""

    source_name: str
    url: str
    trust_level: float
    kind: str = "web"  # web / spa / cache / github / marketplace / benchmark / social

    def with_trust(self, trust_level: float) -> SourceCandidate:
        return SourceCandidate(
            source_name=self.source_name,
            url=self.url,
            trust_level=trust_level,
            kind=self.kind,
        )


class SourceSelector:
    """根据缺口与竞品产出候选数据源（降级链排序）

    M2 增强：若提供 source_success_rates（L4 进化），按成功率提升
    对应数据源的优先级，使"SPA 站点 → Playwright"等历史经验生效。
    设计文档 23：注入 ExternalSourceProvider 后，对缺口追加官网之外的外部源候选。
    """

    def __init__(
        self,
        providers: list[object] | None = None,
    ) -> None:
        self._cache: dict[str, str] = {}
        self._success_rates: dict[str, float] = {}
        # 失败反例命中的源（设计文档 45）：candidates 中把记录 failures 的源排后
        self._failure_penalties: set[str] = set()
        # 外部源提供方：按 kind 索引（design doc 23）
        self._providers: dict[str, object] = {p.kind: p for p in providers or []}  # type: ignore[union-attr]

    def set_success_rates(self, success_rates: dict[str, float]) -> None:
        """注入 L4 数据源成功率（驱动优选）"""
        self._success_rates = dict(success_rates)

    def set_failure_penalties(self, failure_sources: list[str]) -> None:
        """注入 L4 失败反例命中的源（设计文档 45）：candidates 中把这些源降级排后。"""
        self._failure_penalties = set(failure_sources)

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        """返回按可信度降序的候选源。

        顺序：官方 web 链接 → 命中 kind 的外部源候选（按 trust 降序）→ 成功率提升 →
        剔除已尝试源 → SPA 兜底（仅针对官方 web 候选）。
        """
        link_keys = _DIMENSION_LINK_KEY.get(gap.field, ["home"])
        candidates: list[SourceCandidate] = []

        seen: set[str] = set()
        # 1) 官方链接（web）
        official_web: list[SourceCandidate] = []
        for key in link_keys:
            url = competitor.official_links.get(key)
            if url and url not in seen:
                seen.add(url)
                candidates.append(
                    SourceCandidate(source_name=f"official_{key}", url=url, trust_level=0.9, kind="web")
                )
        official_web = [c for c in candidates if c.kind == "web"]

        # 2) 外部源候选（设计文档 23）：按缺口 kind 路由到 provider
        for kind in _GAP_TO_KINDS.get(gap.field, []):
            if kind in _WEB_KINDS:
                continue
            provider = self._providers.get(kind)
            if provider is None:
                continue
            supports = getattr(provider, "supports", None)
            if supports is not None and not supports(gap, competitor):  # type: ignore[misc]
                continue
            for cand in provider.candidates(gap, competitor):  # type: ignore[union-attr]
                if cand.url and cand.url not in seen:
                    seen.add(cand.url)
                    candidates.append(cand)

        # 成功率高（已验证的杀手源）——优先前置；失败反例命中的源降级排后（设计文档 45）
        boosted: list[SourceCandidate] = []
        for cand in candidates:
            if cand.source_name in self._failure_penalties:
                boosted.append(cand.with_trust(0.05))
                continue
            rate = self._success_rates.get(cand.source_name)
            if rate is not None:
                cand = cand.with_trust(0.5 + 0.5 * rate)  # 0.5~1.0
            boosted.append(cand)
        boosted.sort(key=lambda c: c.trust_level, reverse=True)

        # 已尝试过的源降级（避免重复抓取失败源）
        tried = set(gap.sources_tried)
        boosted = [c for c in boosted if c.source_name not in tried]

        # SPA 兜底：静态抓取拿不到内容时，用 Playwright 渲染同一官方页（仅针对官方 web 候选）
        if official_web:
            boosted.append(
                SourceCandidate(
                    source_name="spa_extractor",
                    url=official_web[0].url,
                    trust_level=0.75,
                    kind="spa",
                )
            )

        return boosted

    def has_next(self, gap: InfoGap, competitor: Competitor, index: int) -> bool:
        return index < len(self.candidates(gap, competitor))

    def select(self, gap: InfoGap, competitor: Competitor) -> SourceContext:
        """选择最佳候选源并返回采集上下文"""
        cands = self.candidates(gap, competitor)
        if not cands:
            return SourceContext(competitor_name=competitor.name)
        best = cands[0]
        return SourceContext(
            competitor_name=competitor.name,
            kwargs={"url": best.url, "source_name": best.source_name, "kind": best.kind},
        )

    def record_cache(self, source_name: str, url: str) -> None:
        self._cache[source_name] = url