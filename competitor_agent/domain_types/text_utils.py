"""文本处理共享工具（设计文档 93 §2.3：knowledge_base ↔ memory 共享符号下沉）。

``tokenize`` 原定义于 ``knowledge_base.competitor_store``，memory.session_archive
顶层导入它形成 knowledge_base ↔ memory 包间互相引用（knowledge_base →
memory.json_store，memory.session_archive → knowledge_base）。下沉到
domain_types 后 memory 不再运行时依赖 knowledge_base，包间依赖单向化。
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9一-鿿]+")


def tokenize(text: str) -> list[str]:
    """中英文通用分词（小写 + 词元）"""
    return _WORD_RE.findall(text.lower())
