"""数值真值核对（设计文档 34 §2.4 / 49 工具化）

details 中"应可回溯到原文"的实体型数值与证据原文交叉核对：
声称自原文的数值（非 0）在原文里找不到 → 计为冲突。供：
- ``validate_facts`` 复核工具（Lead/子 Agent 可调）；
- 报告组装收尾的代码强制复核兜底（不进 LLM）。
从 analyzers/base.py 迁出（原模块随 49 删除），行为与测试口径不变。
"""
from __future__ import annotations

from typing import Any

# 真值校验（设计文档 34 §2.4）：details 中"应可回溯到原文"的数值字段键名。
# 只核对这些实体型数值（价格/单价/数量/得分/计数），
# 比例型（polarity_ratio 的 pos/neg/neu）与 0 值缺省由计算/缺失语义豁免，避免误伤。
_VERIFY_NUMERIC_KEYS = frozenset(
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


def _num_str(value: float) -> str:
    """数值 → 用于原文匹配的字符串（20.0 → "20"）。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def count_numeric_conflicts(details: Any, raw_text: str) -> int:
    """details 中实体数值与原文证据交叉核对：值应出现在原文（忽略标点差异）。

    返回冲突数：声称自原文的数值（非 0）在原文里找不到 → 计数冲突。
    """
    if not isinstance(details, dict):
        return 0
    text = (raw_text or "").lower()
    text_flat = text.replace(",", "")  # "12,000 stars" ↔ 12000 视作一致
    conflicts = 0
    stack: list[Any] = [details]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key in _VERIFY_NUMERIC_KEYS
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and value != 0
                ):
                    needle = _num_str(value)
                    if needle not in text and needle not in text_flat:
                        conflicts += 1
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(item for item in node if isinstance(item, (dict, list)))
    return conflicts
