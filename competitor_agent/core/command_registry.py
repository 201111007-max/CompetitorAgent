"""命令注册表 — 斜杠命令识别与路由（对照 hermes-agent)

识别逻辑沿用 hermes 的"前缀判定 + 注册表查表"，不写命令名 regex：
- `_looks_like_slash_command()`：以 / 开头且首词不含第二个 /（排除 /Users/foo 类路径）
- `resolve_command()`：lstrip('/') 后按 name / aliases 查表
- `command_dispatch()`：命中执行处理器；否则返回 False 走浅清洗 + 任务解析
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

HandlerType = Callable[[str], None]


@dataclass(frozen=True)
class CommandDef:
    """一个斜杠命令的定义"""

    name: str  # 命令名（不含 /）
    aliases: list[str]  # 别名
    handler: str  # 处理器标识（dispatch 表键），如 "analyze" / "history"
    args_hint: str = ""  # 帮助/提示用参数说明


COMMAND_REGISTRY: list[CommandDef] = [
    CommandDef("analyze", ["a"], "analyze", "[competitor]"),
    CommandDef("compare", ["c"], "compare", "A 和 B"),
    CommandDef("history", ["h"], "history", "[--competitor X]"),
    CommandDef("resume", ["r"], "resume", "[session_id]"),
    CommandDef("benchmark", ["b"], "benchmark", ""),
    CommandDef("help", ["?"], "help", "[command]"),
]

# handler 标识 → CommandDef 的查找索引（含别名）
_COMMAND_INDEX: dict[str, CommandDef] = {}
for _cmd in COMMAND_REGISTRY:
    _COMMAND_INDEX[_cmd.name] = _cmd
    for _alias in _cmd.aliases:
        _COMMAND_INDEX[_alias] = _cmd


def _looks_like_slash_command(text: str) -> bool:
    """前缀判定：以 / 开头且首词不含第二个 /（排除 /Users/foo 类路径）"""
    stripped = text.lstrip()
    if not stripped or not stripped.startswith("/"):
        return False
    # 取首词（到第一个空白为止），其若不含第二个 '/' 则视为命令
    first_word = stripped.split(maxsplit=1)[0]
    return "/" not in first_word[1:]


def resolve_command(token: str) -> CommandDef | None:
    """lstrip('/') 后按 name / aliases 查表"""
    name = token.lstrip("/").strip().lower()
    if not name:
        return None
    return _COMMAND_INDEX.get(name)


def _split_args(text: str) -> tuple[str, str]:
    """把 '命令名 + 参数' 拆成 (command_token, args)"""
    stripped = text.lstrip()
    parts = stripped.split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def command_dispatch(
    text: str,
    handlers: dict[str, HandlerType],
) -> bool:
    """路由一条输入：命中斜杠命令则执行处理器并返回 True；否则返回 False。

    Args:
        text: 用户原始输入
        handlers: handler 标识 → 处理函数（如 {"analyze": fn}）
    Returns:
        是否作为命令消费
    """
    if not _looks_like_slash_command(text):
        return False
    token, args = _split_args(text)
    cmd = resolve_command(token)
    if cmd is None:
        # 以 / 开头但非已知命令 —— 交由上层提示帮助 / 走清洗
        handlers.get("help", lambda _a: None)("help")
        return True
    handler = handlers.get(cmd.handler)
    if handler is None:
        return False
    handler(args)
    return True


__all__ = [
    "COMMAND_REGISTRY",
    "CommandDef",
    "HandlerType",
    "_looks_like_slash_command",
    "command_dispatch",
    "resolve_command",
]