"""任务语义解析 — LLM 优先 + 规则降级（对照 hermes 交给 LLM、规则兜底）

`parse_task()` 把用户任务解析为结构化 `TaskParseResult`：
- competitors: 1 个 = 单竞品；2 个 = 对比
- dimensions: None = 全部维度；非空 = 维度白名单（只分析 X）
- custom_sources: 维度/来源 → 用户指定的 URL

LLM 版：`use_llm=True` 且 LLMClient 可用时轻量解析；失败回退规则版（不崩溃）。
规则版：复用 `competitor_registry.resolve_competitors`（对比拆分）+ 关键词维度提取。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from competitor_agent.core.competitor_registry import resolve_competitors

if TYPE_CHECKING:
    from competitor_agent.llm.client import LLMClient

logger = logging.getLogger("competitor_agent.core.task_parser")

# 维度关键词（规则版维度白名单/提权共用）
DIMENSION_KEYWORDS: dict[str, list[str]] = {
    "pricing": ["定价", "价格", "多少钱", "pricing", "price", "plan", "收费"],
    "performance": ["性能", "benchmark", "swe-bench", "speed", "性能评测", "速度"],
    "feature": ["功能", "特性", "features", "feature", "能力"],
    "ecosystem": ["生态", "插件", "扩展", "ecosystem", "集成", "mcp"],
    "sentiment": ["口碑", "评价", "社区", "sentiment", "评论"],
    "roadmap": ["路线图", "roadmap", "规划", "未来", "版本"],
}

# 只分析 X 的触发词（出现才产出维度白名单；否则全部维度）
_RESTRICT_MARKERS = ("只分析", "仅分析", "只看", "只关注", "only analyze", "just analyze")

# 市场普查/发现意图触发词（规则版弱推断 resolution=DISCOVERY；主决策交给 LLM）
_DISCOVERY_MARKERS = (
    "所有",
    "全部",
    "有哪些",
    "哪些",
    "盘点",
    "市场",
    "市面上",
    "现在市场上的",
    "帮我找",
    "帮我寻找",
    "discover",
    "find all",
    "list all",
    "top ai coding",
    "best ai coding",
)

# 自定义数据源模式：官网/定价页/文档页 → URL
_SOURCE_URL_PATTERNS: dict[str, re.Pattern[str]] = {
    "home": re.compile(r"(?:官网|首页|主页)(?:地址|链接|是)?[:：]?\s*(https?://\S+)"),
    "pricing": re.compile(r"(?:定价|价格)页?(?:地址|链接|是)?[:：]?\s*(https?://\S+)"),
    "docs": re.compile(r"(?:文档|docs)(?:地址|链接|是)?[:：]?\s*(https?://\S+)"),
}

_LLM_PARSE_PROMPT = (
    "你是竞品分析任务的语义解析器。从用户任务中提取结构化信息，只输出 JSON，不要其他文字。"
    'JSON 格式：{"resolution": "registry" 或 "discovery" 或 "compare", '
    '"competitors": ["竞品规范名1", "竞品规范名2（对比才有）"], '
    '"dimensions": ["维度名"] 或 null（null 表示全部维度，'
    '["pricing","performance","feature","ecosystem","sentiment","roadmap"] 之一），'
    '"custom_sources": {"home或pricing或docs": "用户提供的URL"}}。'
    "resolution 判定：任务点名具体竞品=registry；任务是市场普查/发现（如"
    "'所有 AI coding agent''有哪些''盘点'）=discovery；任务点名 ≥2 个竞品做对比=compare。"
)


class ResolutionDecision(str, Enum):
    """解析决策：走注册表匹配 / 联网发现 / N 向对比（设计文档 20，由 LLM 决定）"""

    REGISTRY = "registry"
    DISCOVERY = "discovery"
    COMPARE = "compare"


@dataclass
class TaskParseResult:
    """任务语义解析结果"""

    competitors: list[str]
    dimensions: list[str] | None = None  # None = 全部维度
    custom_sources: dict[str, str] = field(default_factory=dict)
    raw_task: str = ""
    resolution: ResolutionDecision = ResolutionDecision.REGISTRY  # LLM 决定，规则版弱推断

    @property
    def is_compare(self) -> bool:
        return self.resolution == ResolutionDecision.COMPARE or len(self.competitors) >= 2

    @property
    def is_discovery(self) -> bool:
        return self.resolution == ResolutionDecision.DISCOVERY

    @property
    def primary_competitor(self) -> str:
        return self.competitors[0] if self.competitors else "unknown"


def parse_task(
    task: str,
    llm: LLMClient | None = None,
    use_llm: bool = False,
) -> TaskParseResult:
    """解析任务语义：LLM 优先，失败/不可用回退规则版。"""
    if use_llm and llm is not None:
        try:
            result = _parse_task_llm(task, llm)
            if result.competitors:
                return result
        except Exception as exc:  # noqa: BLE001 - LLM 任何失败都回退规则版，不崩溃（M1 fallback 精神）
            logger.warning("LLM 任务解析失败，回退规则版: %s", exc)
    return _parse_task_rule(task)


def _parse_task_rule(task: str) -> TaskParseResult:
    """规则版：对比拆分 + 维度白名单 + 自定义源 + 弱推断 resolution"""
    competitors = [c.name for c in resolve_competitors(task)]
    return TaskParseResult(
        competitors=competitors,
        dimensions=_extract_dimensions(task),
        custom_sources=_extract_custom_sources(task),
        raw_task=task,
        resolution=_infer_resolution(task, competitors),
    )


def _infer_resolution(task: str, competitors: list[str]) -> ResolutionDecision:
    """规则版弱推断 resolution（主决策在 LLM；此处仅无 Key 降级路径）"""
    lowered = task.lower()
    if len(competitors) >= 2:
        return ResolutionDecision.COMPARE
    if any(marker in lowered for marker in _DISCOVERY_MARKERS):
        return ResolutionDecision.DISCOVERY
    return ResolutionDecision.REGISTRY


def _parse_task_llm(task: str, llm: LLMClient) -> TaskParseResult:
    """LLM 版：一次轻量 JSON 调用解析结构（含 resolution 决策）"""
    raw = llm.complete(
        messages=[
            {"role": "system", "content": _LLM_PARSE_PROMPT},
            {"role": "user", "content": task},
        ]
    )
    data = json.loads(raw)
    competitors = [str(c) for c in data.get("competitors", [])]
    dimensions_raw = data.get("dimensions")
    dimensions: list[str] | None = None
    if isinstance(dimensions_raw, list) and dimensions_raw:
        valid = {d for d in dimensions_raw if d in DIMENSION_KEYWORDS}
        dimensions = sorted(valid) if valid else None
    custom_sources = {
        str(k): str(v) for k, v in data.get("custom_sources", {}).items()
    }
    # LLM 决策 resolution；畸形/缺失回退规则弱推断（不崩溃）
    resolution = ResolutionDecision.REGISTRY
    res_raw = str(data.get("resolution", "")).strip().lower()
    for candidate in ResolutionDecision:
        if candidate.value == res_raw:
            resolution = candidate
            break
    else:
        resolution = _infer_resolution(task, competitors)
    return TaskParseResult(
        competitors=competitors,
        dimensions=dimensions,
        custom_sources=custom_sources,
        raw_task=task,
        resolution=resolution,
    )


def _extract_dimensions(task: str) -> list[str] | None:
    """维度白名单：仅当出现 '只分析 X' 类触发词时产出；否则 None（全部维度）。"""
    lowered = task.lower()
    for marker in _RESTRICT_MARKERS:
        idx = lowered.find(marker)
        if idx >= 0:
            segment = task[idx + len(marker):]
            return _dimensions_in(segment) or None
    return None


def _dimensions_in(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for dim, keywords in DIMENSION_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            found.append(dim)
    return found


def _extract_custom_sources(task: str) -> dict[str, str]:
    """从任务中提取用户指定的数据源 URL（官网/定价页/文档页）。"""
    sources: dict[str, str] = {}
    for key, pattern in _SOURCE_URL_PATTERNS.items():
        match = pattern.search(task)
        if match:
            sources[key] = match.group(1).rstrip("。，,、")
    return sources


__all__ = ["DIMENSION_KEYWORDS", "ResolutionDecision", "TaskParseResult", "parse_task"]