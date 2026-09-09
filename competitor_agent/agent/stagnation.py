"""停滞检测器（设计文档 81，ADR：自然收敛策略的停滞检测补充）。

``max_steps=None`` 自然收敛（doc 62 刻意决策）**保留为主路径**；本检测器只补充一个
**客观收敛信号**——LLM 反复调用相同工具/相同参数、工具结果高度重复时，向历史注入
收敛提示（最多 2 次，防提示本身成为循环源），不强制截断（截断权留给用户取消与预算）。

纯本地计算（transcript 已在内存）：零 LLM 成本、零网络依赖、确定性可测。

判定（窗口 = 最近 N 个工具步）：
- 同 ``signature = (tool_name, 规范化 args)`` 重复 ≥ ``sig_repeat`` 次；或
- 工具结果 ``tokenize`` jaccard 相似度均值 > ``dup_threshold`` 连续 2 轮。

提示文本只含统计证据（签名计数/重复率），不含工具结果原文——无注入面
（比设计的 wrap_untrusted 包裹更收敛：无不可信内容可包）。
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.stagnation")

# 注入提示模板：{evidence} 为统计证据段（签名计数/重复率，无工具原文）
_HINT_TEMPLATE = (
    "系统提示：最近 {window} 步工具调用与结果高度重复（{evidence}）。"
    "若无新增信息来源，请综合已有证据产出 Final Answer；"
    "若确需新信息，请更换工具、查询词或 URL（分页/翻页等正常连续采集不受影响）。"
)
_WARN_TEMPLATE = (
    "系统提示：停滞提示已注入 {hints} 次仍未收尾——线程与 token 仍在消耗。"
    "请立即综合现有证据收尾，或将剩余疑点记入『待核验』后收尾。"
)


@dataclass
class StagnationConfig:
    """停滞检测参数（doc 81 §5：阈值可配 + ignore_arg_keys 剔除噪声参数）。"""

    enabled: bool = True
    window: int = 8
    dup_threshold: float = 0.85
    sig_repeat: int = 3
    max_hints: int = 2
    ignore_arg_keys: tuple[str, ...] = ("ts", "_t", "nonce", "timestamp", "session_id")


@dataclass
class _StepRecord:
    signature: str
    tokens: frozenset[str]


class StagnationDetector:
    """每步统计窗口重复度 → 停滞时产出收敛提示（最多 max_hints 次）。"""

    def __init__(
        self,
        config: StagnationConfig | None = None,
        on_hint: Callable[[str, str], None] | None = None,  # (kind, evidence) kind ∈ hint|warn
    ) -> None:
        self._cfg = config or StagnationConfig()
        self._window: deque[_StepRecord] = deque(maxlen=max(2, self._cfg.window))
        self._hints = 0
        self._dup_streak = 0  # 连续超 dup_threshold 的轮数
        self._on_hint = on_hint

    @property
    def hints_issued(self) -> int:
        return self._hints

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def _signature(self, tool_name: str, args: dict[str, Any]) -> str:
        """(tool_name, 规范化 args)：剔除噪声键（时间戳/随机数）后排序序列化。"""
        clean = {
            k: v
            for k, v in (args or {}).items()
            if k not in self._cfg.ignore_arg_keys
        }
        try:
            canonical = json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            canonical = str(clean)
        return f"{tool_name}:{canonical}"

    @staticmethod
    def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union if union else 0.0

    def record_round(self, calls: list[tuple[str, dict[str, Any], str]]) -> str | None:
        """记录一回合的全部工具调用；停滞触发时返回注入提示文本（否则 None）。

        回合级（一轮可能含多个并行 tool_calls）统计，任一触发条件命中即产出提示；
        提示最多 ``max_hints`` 次——第 2 次触发改发警示文案（仍未收尾）。
        """
        if not self._cfg.enabled or not calls:
            return None
        from competitor_agent.knowledge_base.competitor_store import tokenize

        records: list[_StepRecord] = []
        for tool_name, args, result in calls:
            tokens = frozenset(tokenize(str(result or "")))
            records.append(_StepRecord(signature=self._signature(tool_name, args), tokens=tokens))
            self._window.append(records[-1])

        evidence_parts: list[str] = []
        stagnant = False
        # 条件 1：窗口内同 signature ≥ sig_repeat
        sig_counts: dict[str, int] = {}
        for rec in self._window:
            sig_counts[rec.signature] = sig_counts.get(rec.signature, 0) + 1
        top_sig, top_count = max(sig_counts.items(), key=lambda kv: kv[1])
        if top_count >= self._cfg.sig_repeat:
            stagnant = True
            tool = top_sig.split(":", 1)[0]
            evidence_parts.append(f"{tool} 同参数签名 ×{top_count}")
        # 条件 2：结果重复率（当前回合各结果与窗口内既有结果的 jaccard 均值）> 阈值连续 2 轮
        prev_records = list(self._window)[: -len(records)]
        round_rates: list[float] = []
        for rec in records:
            rates = [self._jaccard(rec.tokens, old.tokens) for old in prev_records]
            if rates:
                round_rates.append(sum(rates) / len(rates))
        round_rate = max(round_rates) if round_rates else 0.0
        if round_rate > self._cfg.dup_threshold:
            self._dup_streak += 1
        else:
            self._dup_streak = 0
        if self._dup_streak >= 2:
            stagnant = True
        if round_rates and self._dup_streak >= 1 and not evidence_parts:
            evidence_parts.append(f"结果重复率 {round_rate:.2f}")
        if not stagnant:
            return None
        if self._hints >= self._cfg.max_hints:
            return None  # 提示上限已到：不再注入（防提示成为新循环源）
        self._hints += 1
        evidence = "；".join(evidence_parts) or "窗口内调用高度重复"
        kind = "hint" if self._hints < self._cfg.max_hints else "warn"
        text = _WARN_TEMPLATE.format(hints=self._hints) if kind == "warn" else _HINT_TEMPLATE.format(
            window=self._cfg.window, evidence=evidence
        )
        if self._on_hint is not None:
            try:
                self._on_hint(kind, evidence)
            except Exception:
                logger.debug("停滞提示事件回调失败", exc_info=True)
        return text


__all__ = [
    "StagnationConfig",
    "StagnationDetector",
]
