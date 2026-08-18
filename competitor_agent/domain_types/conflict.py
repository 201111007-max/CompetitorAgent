"""跨维度冲突检测（设计文档 49 §3.1）

同一事实键（如 ``monthly_price_usd`` / ``score``）在**不同维度**结论里，
若引用**同一来源**（同 ``content_hash``，即同源页面）却输出不同值 → 记一条
``CrossDimensionConflict``。与 ``FactValidator.arbitrate``（同维度多来源取优）
互补：这是**跨维度**的核对，把单条结论←单来源的证据链提升到编排层。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 跨维度共享的"事实键"：同一实体数值可在不同维度结论中出现（价格/得分/计数）。
# 只核对实体型数值（对齐 analyzers/base._VERIFY_NUMERIC_KEYS），避免比例型误伤。
_SHARED_CLAIM_KEYS = frozenset(
    {
        "monthly_price_usd",
        "annual_price_usd",
        "per_unit_price",
        "per_unit_usd",
        "stars",
        "commits_30d",
        "count",
        "score",
    }
)


def _value_key(value: Any) -> str:
    """值归一化为可比较的字符串（dict/list 用 repr，数值/字符串直用 str）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(value)


@dataclass
class CrossDimensionConflict:
    """一条跨维度冲突：同源（content_hash）同事实键，不同维度给不同值。"""

    claim_key: str
    dimension_a: str
    dimension_b: str
    value_a: Any
    value_b: Any
    evidence_hashes: list[str] = field(default_factory=list)
    severity: str = "warning"

    @property
    def summary(self) -> str:
        return (
            f"跨维度矛盾: {self.dimension_a}.{self.claim_key}={_value_key(self.value_a)} "
            f"vs {self.dimension_b}.{self.claim_key}={_value_key(self.value_b)}"
        )


class ConflictRegistry:
    """按 (claim_key × content_hash) 索引各维度结论，检测跨维度同源冲突。"""

    def __init__(self, claim_keys: frozenset[str] | None = None) -> None:
        self._claim_keys = claim_keys if claim_keys is not None else _SHARED_CLAIM_KEYS
        # (claim_key, content_hash) -> {dimension: value}
        self._index: dict[tuple[str, str], dict[str, Any]] = {}

    def register(self, result: object) -> None:
        """登记一个维度结论：从 details 收集事实键值对，按证据哈希索引。

        result duck-type 出 dimension / details / evidence_hashes，
        避免 domain 与 analyzers/team 之间的循环依赖。
        """
        dimension = str(getattr(result, "dimension", ""))
        if not dimension:
            return
        details = getattr(result, "details", None)
        hashes = [h for h in (getattr(result, "evidence_hashes", None) or []) if h]
        if not hashes:
            return
        for claim_key, value in self._collect_claims(details):
            for h in hashes:
                by_dim = self._index.setdefault((claim_key, h), {})
                # 同维度同源重复登记以最新值覆盖（不产生维度内自冲突）
                by_dim[dimension] = value

    def detect(self) -> list[CrossDimensionConflict]:
        """检测跨维度冲突：同源同键、不同维度值不同 → 冲突清单。"""
        conflicts: list[CrossDimensionConflict] = []
        for (claim_key, h), by_dim in self._index.items():
            if len(by_dim) < 2:
                continue
            unique: dict[str, list[str]] = {}
            for dimension, value in by_dim.items():
                unique.setdefault(_value_key(value), []).append(dimension)
            if len(unique) < 2:
                continue  # 各维度取值一致，无冲突
            # 取按维度名排序的前两个不同值作代表
            ordered = sorted(by_dim.items(), key=lambda kv: kv[0])
            dim_a, value_a = ordered[0]
            dim_b, value_b = next((d, v) for d, v in ordered if _value_key(v) != _value_key(value_a))
            conflicts.append(
                CrossDimensionConflict(
                    claim_key=claim_key,
                    dimension_a=dim_a,
                    dimension_b=dim_b,
                    value_a=value_a,
                    value_b=value_b,
                    evidence_hashes=[h],
                )
            )
        conflicts.sort(key=lambda c: (c.claim_key, c.dimension_a, c.dimension_b))
        return conflicts

    def _collect_claims(self, details: Any) -> list[tuple[str, Any]]:
        """扁平化 details：收集命中共享事实键的叶子值（支持嵌套 dict / list）。"""
        claims: list[tuple[str, Any]] = []
        if not isinstance(details, dict):
            return claims
        stack: list[Any] = [details]
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if (
                    key in self._claim_keys
                    and isinstance(value, (int, float, str))
                    and not isinstance(value, bool)
                ):
                    claims.append((key, value))
                elif isinstance(value, dict):
                    stack.append(value)
                elif isinstance(value, list):
                    stack.extend(item for item in value if isinstance(item, dict))
        return claims


__all__ = ["CrossDimensionConflict", "ConflictRegistry", "_SHARED_CLAIM_KEYS"]
