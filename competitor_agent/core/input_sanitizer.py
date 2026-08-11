"""入站浅清洗 — 对照 hermes cli.py:15216/15278、turn_context.py:205

`sanitize_task()` 组合执行全部清洗：
- strip_paste_wrappers：剥离 [Pasted text #N] 粘贴包装
- strip_terminal_leaks：剥离终端响应泄漏（^[[0m 等 ANSI/转义）
- expand_references：@file:path 引用 → 读取文件内容嵌入
- sanitize_surrogates：代理字符清理，防 json 序列化崩溃

其中 `sanitize_surrogates` 必须置于入站最早处，避免后续 json.dumps 崩溃。
同时承接提示注入的入站净化（架构 R16 三层防御第一层）。
"""
from __future__ import annotations

import re
from pathlib import Path

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted

# @file: 引用允许的数据目录（仅数据文件，禁止源码/配置/凭据，见风险 R25）
_ALLOWED_REF_DIRS: tuple[str, ...] = ("evaluation/cases", "reports/templates")
# 仅允许数据类扩展名，禁止 .py/.toml/.env 等源码或配置
_ALLOWED_REF_EXTENSIONS: frozenset[str] = frozenset({".md", ".txt", ".json", ".yaml"})
_MAX_REFERENCE_BYTES = 64 * 1024  # 64KB


def sanitize_surrogates(text: str) -> str:
    """清理孤立代理字符（U+D800-U+DFFF 单半个 surrogate，无法被 UTF-8 编码）。

    Python 字符串可含未配对代理位，json.dumps(ensure_ascii=False) 会崩溃。
    C0 控制字符一并清掉，避免终端/JSON 注入。
    """
    if not text:
        return text
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            out.append("\ufffd")
        elif code < 0x20 or code == 0x7F:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def strip_paste_wrappers(text: str) -> str:
    """剥离 [Pasted text #N] / [Pasted Text #N] 粘贴包装标记"""
    return re.sub(r"\[Pasted\s*text(?:\s+#\d+)?\]", "", text, flags=re.IGNORECASE)


def strip_terminal_leaks(text: str) -> str:
    """剥离终端响应泄漏：ANSI 转义序列（CSI/OSC 等）。"""
    # CSI 序列: ESC [ ... final byte (0x40-0x7E)；OSC: ESC ] ... ESC \\
    pattern = r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|P[^\x1b]*\x1b\\)"
    cleaned = re.sub(pattern, "", text)
    # 兜底：孤儿 ESC、BEL
    cleaned = re.sub(r"[\x1b\x07\x9b]", "", cleaned)
    return cleaned


def expand_references(text: str, base_dir: str | None = None) -> str:
    """展开 @file:path 引用：将本地数据文件内容作为分析上下文嵌入。

    仅允许读取白名单数据目录（evaluation/cases、reports/templates）内的
    数据类文件（.md/.txt/.json/.yaml），且大小不超过 64KB；源码/配置/凭据
    一律拒绝。路径以 base_dir 为根，防止路径穿越（R25）。读取内容包裹为
    不可信数据块（提示注入防护，见设计文档 06）。

    不合规、过大或不存在的引用静默跳过（保留原文，不读取、不报错），
    避免信息泄露。
    """
    if "@file:" not in text:
        return text

    pattern = re.compile(r"@file:([^\s]+)")
    root = Path(base_dir) if base_dir else Path.cwd()

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        try:
            path = Path(raw)
            if not path.is_absolute():
                path = root / path
            path = path.resolve()
            # 限定在数据白名单目录内，防穿越
            if not _within_allowed_dirs(path, root):
                return match.group(0)
            if path.suffix.lower() not in _ALLOWED_REF_EXTENSIONS:
                return match.group(0)
            if not path.is_file():
                return match.group(0)
            if path.stat().st_size > _MAX_REFERENCE_BYTES:
                return match.group(0)
            content = path.read_text(encoding="utf-8", errors="replace")
            return wrap_untrusted(content, source_url=str(path))
        except OSError:
            return match.group(0)

    return pattern.sub(_replace, text)


def _within_allowed_dirs(path: Path, root: Path) -> bool:
    root_resolved = root.resolve()
    for rel in _ALLOWED_REF_DIRS:
        candidate = (root_resolved / rel).resolve()
        try:
            path.relative_to(candidate)
            return True
        except ValueError:
            continue
    return False


def sanitize_task(task: str, base_dir: str | None = None) -> str:
    """组合全部入站浅清洗。

    顺序：粘贴包装/终端泄漏 先剥离（两者都需原始控制字符），再 surrogate 清理，
    最后 @file: 引用展开（读文件内容本身不再需要控制字符，且引用展开应在最后，
    避免展开出的内容再次被当作命令/引用处理）。

    Args:
        task: 原始用户输入
        base_dir: @file: 引用解析的基准目录（默认当前工作目录）
    """
    return expand_references(
        sanitize_surrogates(strip_terminal_leaks(strip_paste_wrappers(task))),
        base_dir=base_dir,
    )


__all__ = [
    "expand_references",
    "sanitize_surrogates",
    "sanitize_task",
    "strip_paste_wrappers",
    "strip_terminal_leaks",
]