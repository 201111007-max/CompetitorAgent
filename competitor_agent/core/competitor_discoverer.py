"""CompetitorDiscoverer — 自主发现竞品（设计文档 20）

职责边界：只负责"怎么找"（联网枚举候选 + 补全 official_links），
不负责"该不该找"——意图判定（REGISTRY/DISCOVERY/COMPARE）由 LLM 决策
（见 core/task_parser.py 的 ResolutionDecision），本类仅在判定 DISCOVERY 后被调用。

发现顺序：
1. 注册表命中优先（任务文本含已知竞品名/别名，直接返回注册表条目）；
2. 未知 → 调用注入的 web_tool（如 MCP web 搜索）枚举候选（名称 + 官网）；
   use_llm=True 时用 LLM 归纳去重、补全 official_links；
3. 无 Key / 无网络 / 无候选 → 内置兜底清单（常见 AI coding agent），保证不 0 维度。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY, canonicalize
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.llm.client import LLMClient

logger = logging.getLogger("competitor_agent.core.competitor_discoverer")

# 无 Key / 无网络时的内置兜底清单（常见 AI Coding Agent，保证普查任务不 0 维度）
_FALLBACK_CANDIDATES: list[dict[str, str]] = [
    {"name": "cursor", "home": "https://www.cursor.com", "pricing": "https://www.cursor.com/pricing"},
    {"name": "claude-code", "home": "https://www.anthropic.com/claude-code", "docs": "https://docs.anthropic.com/en/docs/claude-code"},
    {"name": "copilot", "home": "https://github.com/features/copilot", "docs": "https://docs.github.com/en/copilot"},
    {"name": "codex", "home": "https://openai.com/index/introducing-codex/"},
    {"name": "windsurf", "home": "https://windsurf.com", "pricing": "https://windsurf.com/pricing"},
    {"name": "aider", "home": "https://aider.chat", "docs": "https://aider.chat/docs/"},
    {"name": "gemini-cli", "home": "https://github.com/google-gemini/gemini-cli"},
    {"name": "opencode", "home": "https://opencode.ai"},
]

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

    def discover(self, task: str) -> list[Competitor]:
        """联网检索候选竞品列表（名称 + official_links），返回去重后的 ≥1 个竞品。

        1) 注册表命中优先；
        2) 未知 → web_tool 搜索（名称 + 官网），use_llm=True 时 LLM 归纳去重补全；
        3) 兜底内置清单。
        """
        candidates = self._search(task)
        return self._to_competitors(candidates)

    def _search(self, task: str) -> list[dict[str, Any]]:
        """候选枚举：注册表命中 → web_tool → 内置兜底。"""
        # 1) 注册表命中：任务文本直接含已知竞品
        registered = self._registry_hits(task)
        if registered:
            return registered
        # 2) web_tool 联网搜索
        if self._web_tool is not None:
            try:
                raw = self._web_tool(task)
                if raw:
                    return self._dedupe_with_llm(raw)
            except Exception:  # noqa: BLE001 - 搜索失败回退兜底，不崩溃
                logger.warning("web_tool 搜索失败，回退内置清单: task=%r", task, exc_info=True)
        # 3) 内置兜底清单（无 Key / 无网络 / 搜索失败）
        logger.info("使用内置竞品兜底清单（无 web_tool / 无候选）")
        return list(_FALLBACK_CANDIDATES)

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
        """use_llm=True 时用 LLM 归纳去重 + 补全 official_links；否则规则去重。"""
        if self._use_llm and self._llm is not None:
            try:
                text = self._llm.complete(
                    messages=[
                        {"role": "system", "content": _LLM_DEDUP_PROMPT},
                        {"role": "user", "content": json_dumps(raw)},
                    ]
                )
                parsed = json_loads_array(text)
                if parsed:
                    return parsed
            except Exception:  # noqa: BLE001 - LLM 失败回退规则去重
                logger.warning("LLM 去重失败，回退规则去重", exc_info=True)
        return raw

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
        raise ValueError(f"非数组: {text[:200]}")
    return [d for d in data if isinstance(d, dict)]


__all__ = ["CompetitorDiscoverer"]
