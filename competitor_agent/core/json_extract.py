"""模型输出 JSON 提取/归一公共基建（设计文档 87 §3.1）

自 ``facade/react_report.py`` 纯平移（签名/语义/行为零变化），供全部解析路径复用：
路径① task_parser、路径② react_report 主链路、路径③ delegate_tool._collect_candidate、
路径④ benchmark 抽取（``coerce_str_list``）。``facade/react_report`` 保留旧名别名向后兼容。
"""
from __future__ import annotations

import json
import re
from typing import Any


def extract_json_block(text: str) -> dict[str, Any] | None:
    """从文本中提取首个平衡 JSON 对象（设计文档 65 §2.1 括号配平 + 字符串感知）。

    快路径：文本整体以 ``{`` 开头 → 直接 ``json.loads``（覆盖绝大多数场景，行为不变）。
    慢路径：定位首个 ``{`` 后逐字符扫描，维护深度；字符串字面量感知——命中 ``"`` 时
    进入字符串态并跳过 ``\\"`` 转义，防止 JSON 字符串内部的 ``{``/``}`` 干扰配平；
    深度归零处截取候选块 ``parse_json_candidate``（失败先轻修复再解析），成功且为
    dict → 返回。首个候选失败时再尝试 ``re.search`` 懒提取兜底。未闭合/无 JSON → None。

    设计文档 66 §3.3：候选块 ``json.loads`` 失败时先做两条轻修复（``"key": ,`` 空值 →
    null、``, ,``/``,]`` 空数组项）再试，兜住模型手滑畸形（``"details": ,`` 等）。
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = parse_json_candidate(stripped)
        if payload is not None:
            return payload
    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = stripped[start : i + 1]
                payload = parse_json_candidate(candidate)
                if payload is not None:
                    return payload
                break
    # 慢路径候选失败/未闭合 → 懒提取兜底（贪婪到最后一个 }，容忍尾部散文）
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        payload = parse_json_candidate(match.group(0))
        if payload is not None:
            return payload
    return None


def light_fix_json(candidate: str) -> str:
    """轻修复模型手滑畸形 JSON（设计文档 66 §3.3）：

    - ``"key": ,``（空值）→ ``"key": null,``；
    - ``, ,``（空数组项）/ `,]` / `,}`` → 去除多余逗号；
    - ``[,``（数组开头多余逗号）→ 去除（如 ``[ , , ]`` 叠代后残留）。
    修复后由调用方再次 ``json.loads``；仍失败才放弃（保守语义不变）。
    """
    fixed = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)":\s*,', r'"\1": null,', candidate)
    fixed = re.sub(r",\s*,", ",", fixed)
    fixed = re.sub(r",\s*\]", "]", fixed)
    fixed = re.sub(r",\s*\}", "}", fixed)
    fixed = re.sub(r"\[\s*,", "[", fixed)
    return fixed


def parse_json_candidate(candidate: str) -> dict[str, Any] | None:
    """解析候选 JSON 块；``json.loads`` 失败先 ``light_fix_json`` 轻修复再试一次。"""
    payload: Any = None
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        try:
            payload = json.loads(light_fix_json(candidate))
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(payload, dict) and payload:
        return payload
    return None


def coerce_str_list(value: object) -> list[str]:
    """类型归一（设计文档 87 §4）：None→[]；str→[str]（整体一项，不迭代字符）；
    list→保留非空 str 元素；其余→[]。

    治「模型把 list 字段返回成字符串时被按字符迭代成单字符垃圾」类 bug
    （task_parser competitors / react_report evidence_urls）。
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


__all__ = ["coerce_str_list", "extract_json_block", "light_fix_json", "parse_json_candidate"]
