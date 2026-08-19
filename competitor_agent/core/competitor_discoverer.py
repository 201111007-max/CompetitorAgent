"""CompetitorDiscoverer — 自主发现竞品（设计文档 20 / 47）

职责边界：只负责"怎么找"（联网枚举候选 + 补全 official_links），
不负责"该不该找"——意图判定（REGISTRY/DISCOVERY/COMPARE）由 LLM 决策
（见 core/task_parser.py 的 ResolutionDecision），本类仅在判定 DISCOVERY 后被调用。

发现顺序（设计文档 47：无内置兜底清单）：
1. 注册表命中优先（任务文本含已知竞品名/别名，直接返回注册表条目，属数据查询）；
2. 未知 → 调用注入的 web_tool（如 MCP web 搜索）枚举候选（名称 + 官网），
   LLM 归纳去重、补全 official_links；LLM 不可用/失败抛 LLMUnavailableError；
3. 缺 web_tool / 搜索失败 / 无候选 → 返回空（不编造内置清单），由上层报"未能发现任何竞品"。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY, canonicalize
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient

logger = logging.getLogger("competitor_agent.core.competitor_discoverer")

# web_tool 返回的候选字段 key → official_links key（与 SourceSelector 对齐）
_LINK_KEYS = ("home", "pricing", "docs", "changelog")

_LLM_DEDUP_PROMPT = (
    "你是竞品发现助手。下面是抓取到的候选竞品 JSON 列表（可能含噪声/重复）。"
    "请输出去重后的竞品清单，只输出 JSON 数组，不要其他文字。"
    'JSON 格式：[{"name": "规范名", "home": "官网", "pricing": "定价页", "docs": "文档"}, ...]。'
    "name 用英文小写+连字符；无法确定的链接给空字符串。"
)


class CompetitorDiscoverer:
    """自主发现竞品：枚举候选 + 补全 official_links（不含意图判定）"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        use_llm: bool = True,
        web_tool: Callable[[str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._llm = llm
        self._use_llm = use_llm
        self._web_tool = web_tool

    def discover(
        self,
        task: str,
        on_candidate: Callable[[str], None] | None = None,
    ) -> list[Competitor]:
        """联网检索候选竞品列表（名称 + official_links），返回去重后的 ≥1 个竞品。

        1) 注册表命中优先；
        2) 未知 → web_tool 搜索（名称 + 官网），LLM 归纳去重补全。

        on_candidate: 每发现一个候选竞品名即回调（供 Web SSE 实时推送）。
        """
        candidates = self._search(task)
        if on_candidate is not None:
            for cand in candidates:
                name = str(cand.get("name", "")).strip()
                if name:
                    on_candidate(name)
        return self._to_competitors(candidates)

    def _search(self, task: str) -> list[dict[str, Any]]:
        """候选枚举：注册表命中 → web_tool 联网搜索（无内置兜底，设计文档 47）。"""
        # 1) 注册表命中：任务文本直接含已知竞品（数据查询，不算规则解析）
        registered = self._registry_hits(task)
        if registered:
            return registered
        # 2) web_tool 联网搜索（缺 web_tool / 搜索失败 → 无候选，不编造清单）
        if self._web_tool is None:
            logger.warning("发现任务缺少联网搜索工具（web_tool）")
            return []
        try:
            raw = self._web_tool(task)
        except Exception:
            logger.warning("web_tool 搜索失败: task=%r", task, exc_info=True)
            return []
        if not raw:
            return []
        return self._dedupe_with_llm(raw)

    @staticmethod
    def _registry_hits(task: str) -> list[dict[str, Any]]:
        """任务文本中含注册表竞品名/别名时，直接返回注册表条目。"""
        lowered = task.lower()
        hits: list[dict[str, Any]] = []
        for canon, competitor in COMPETITOR_REGISTRY.items():
            if canon in lowered or any(a in lowered for a in competitor.aliases):
                hits.append(
                    {
                        "name": competitor.name,
                        "aliases": list(competitor.aliases),
                        "official_links": dict(competitor.official_links),
                    }
                )
        return hits

    def _dedupe_with_llm(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """LLM 归纳去重 + 补全 official_links；LLM 不可用/失败抛 LLMUnavailableError。"""
        if not (self._use_llm and self._llm is not None):
            raise LLMUnavailableError("竞品去重仅支持 LLM：需要配置 LLM API Key")
        try:
            text = self._llm.complete(
                messages=[
                    {"role": "system", "content": _LLM_DEDUP_PROMPT},
                    {"role": "user", "content": json_dumps(raw)},
                ]
            )
            return json_loads_array(text)
        except Exception as exc:
            raise LLMUnavailableError(f"竞品去重失败: {exc}") from exc

    @staticmethod
    def _to_competitors(candidates: list[dict[str, Any]]) -> list[Competitor]:
        """把候选 dict 列表转成去重后的 Competitor 列表。"""
        seen: set[str] = set()
        competitors: list[Competitor] = []
        for cand in candidates:
            name = str(cand.get("name", "")).strip()
            if not name:
                continue
            resolved = _resolve_registry(name)
            if resolved is None:
                # 未知竞品：用规范名直接构建（保留连字符），并补全官方链接
                resolved = Competitor(
                    name=canonicalize(name),
                    aliases=[str(a) for a in cand.get("aliases", []) if a],
                    category="ai_coding_agent",
                    official_links=_extract_links(cand),
                )
            key = resolved.name
            if key in seen:
                continue
            seen.add(key)
            competitors.append(resolved)
        return competitors


def _resolve_registry(name: str) -> Competitor | None:
    """仅注册表匹配（不触犯 ASCII 抽取改名），命中返回注册表条目，否则 None。"""
    lowered = name.strip().lower()
    for canon, competitor in COMPETITOR_REGISTRY.items():
        if canon == lowered or any(a == lowered for a in competitor.aliases):
            return competitor
        if canon in lowered or any(a in lowered for a in competitor.aliases):
            return competitor
    return None


def _extract_links(cand: dict[str, Any]) -> dict[str, str]:
    """从候选 dict 提取 official_links（兼容 name 平铺字段 / official_links 子对象）。"""
    links: dict[str, str] = {}
    source = cand.get("official_links", cand) if isinstance(cand.get("official_links"), dict) else cand
    for key in _LINK_KEYS:
        value = str(source.get(key, "")).strip()
        if value.startswith("http"):
            links[key] = value
    return links


def json_dumps(data: Any) -> str:
    """序列化候选列表（独立函数便于测试 mock）。"""
    import json

    return json.dumps(data, ensure_ascii=False)


def json_loads_array(text: str) -> list[dict[str, Any]]:
    """解析 LLM 返回的 JSON 数组（容忍最外层对象包裹 / 前后噪声）。"""
    import json

    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 取第一个 '[' 到最后一个 ']' 的片段再解析
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < start:
            raise
        data = json.loads(text[start : end + 1])
    if isinstance(data, dict) and "competitors" in data:
        data = data["competitors"]
    if not isinstance(data, list):
        raise TypeError(f"非数组: {text[:200]}")
    return [d for d in data if isinstance(d, dict)]


__all__ = ["CompetitorDiscoverer"]
