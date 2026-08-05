"""SourceSelector — 信息缺口 → 数据源候选排序（降级链）

降级链：官方源 → 缓存/镜像 → 替代源 →（M2）Playwright。
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


@dataclass(frozen=True)
class SourceCandidate:
    """单个数据源候选"""

    source_name: str
    url: str
    trust_level: float
    kind: str = "web"  # web / cache / alternative

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
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._success_rates: dict[str, float] = {}

    def set_success_rates(self, success_rates: dict[str, float]) -> None:
        """注入 L4 数据源成功率（驱动优选）"""
        self._success_rates = dict(success_rates)

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        """返回按可信度降序的候选源"""
        link_keys = _DIMENSION_LINK_KEY.get(gap.field, ["home"])
        candidates: list[SourceCandidate] = []

        seen: set[str] = set()
        for key in link_keys:
            url = competitor.official_links.get(key)
            if url and url not in seen:
                seen.add(url)
                candidates.append(
                    SourceCandidate(source_name=f"official_{key}", url=url, trust_level=0.9)
                )

        # 成功率高（已验证的杀手源）——优先前置
        boosted: list[SourceCandidate] = []
        for cand in candidates:
            rate = self._success_rates.get(cand.source_name)
            if rate is not None:
                cand = cand.with_trust(0.5 + 0.5 * rate)  # 0.5~1.0
            boosted.append(cand)
        boosted.sort(key=lambda c: c.trust_level, reverse=True)

        # 已尝试过的源降级（避免重复抓取失败源）
        tried = set(gap.sources_tried)
        boosted = [c for c in boosted if c.source_name not in tried]

        # SPA 兜底：静态抓取拿不到内容时，用 Playwright 渲染同一官方页
        if boosted:
            boosted.append(
                SourceCandidate(
                    source_name="spa_extractor",
                    url=boosted[0].url,
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
            kwargs={"url": best.url, "source_name": best.source_name},
        )

    def record_cache(self, source_name: str, url: str) -> None:
        self._cache[source_name] = url