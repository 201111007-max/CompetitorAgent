"""任务语义解析 — 仅 LLM（设计文档 47，去除规则降级）

`parse_task()` 把用户任务解析为结构化 `TaskParseResult`：
- competitors: 1 个 = 单竞品；2 个 = 对比
- dimensions: None = 全部维度；非空 = 维度白名单（只分析 X）
- custom_sources: 维度/来源 → 用户指定的 URL

主路径只保留 LLM 解析；LLM 不可用/解析失败抛 `LLMUnavailableError`，
不再静默降级规则（无 Key 可复现与确定性由 benchmark mock LLM 承担）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from competitor_agent.interfaces.exceptions import LLMUnavailableError

if TYPE_CHECKING:
    from competitor_agent.llm.client import LLMClient

# 合法维度集合（规划枚举约束，供 _parse_task_llm 校验 dimensions 白名单）
_VALID_DIMENSIONS = frozenset(
    {"pricing", "performance", "feature", "ecosystem", "sentiment", "roadmap"}
)

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
    resolution: ResolutionDecision = ResolutionDecision.REGISTRY  # LLM 决定

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
    use_llm: bool = True,
) -> TaskParseResult:
    """仅 LLM 解析；LLM 不可用/解析失败抛 LLMUnavailableError，不降级规则。"""
    if not use_llm or llm is None:
        raise LLMUnavailableError(
            "任务解析仅支持 LLM：需要配置 LLM API Key（无规则降级，设计文档 47）"
        )
    try:
        return _parse_task_llm(task, llm)
    except LLMUnavailableError:
        raise
    except Exception as exc:
        raise LLMUnavailableError(f"LLM 任务解析失败: {exc}") from exc


def _parse_task_llm(task: str, llm: LLMClient) -> TaskParseResult:
    """LLM 版：一次轻量 JSON 调用解析结构（含 resolution 决策）。"""
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
        valid = {d for d in dimensions_raw if d in _VALID_DIMENSIONS}
        dimensions = sorted(valid) if valid else None
    custom_sources = {
        str(k): str(v) for k, v in data.get("custom_sources", {}).items()
    }
    # LLM 决策 resolution；畸形/缺失回退默认 REGISTRY（不做规则推断）
    resolution = ResolutionDecision.REGISTRY
    res_raw = str(data.get("resolution", "")).strip().lower()
    for candidate in ResolutionDecision:
        if candidate.value == res_raw:
            resolution = candidate
            break
    return TaskParseResult(
        competitors=competitors,
        dimensions=dimensions,
        custom_sources=custom_sources,
        raw_task=task,
        resolution=resolution,
    )


__all__ = ["ResolutionDecision", "TaskParseResult", "parse_task"]
