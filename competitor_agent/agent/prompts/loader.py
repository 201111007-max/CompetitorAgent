"""PromptAsset — 全局提示词资产（设计文档 72：类 CLAUDE.md 的 Agent.md 常驻指令）

复用 skills.loader 的 frontmatter/reload + env 覆盖模式：
- 资产目录：``PROMPTS_DIR``（env）优先，缺省包内 ``agent/prompts/assets/``；
- ``render("Agent")`` 读 ``assets/Agent.md`` 正文并做 ``{{key}}`` 逐键替换，缺失/异常 → ""；
- 可选扩展 B：``PROMPTS_USER_FILE``（env）指向用户级 md，``render`` 时追加为"个人偏爱"段。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_PROMPTS_DIR_ENV = "PROMPTS_DIR"
_PROMPTS_USER_FILE_ENV = "PROMPTS_USER_FILE"
_DEFAULT_PROMPTS_DIR = Path(__file__).parent / "assets"


def _prompts_dir() -> Path:
    """资产目录：环境变量 PROMPTS_DIR 优先，缺省包内 assets/。"""
    override = os.environ.get(_PROMPTS_DIR_ENV)
    return Path(override) if override else _DEFAULT_PROMPTS_DIR


def _user_file() -> Path | None:
    """用户级 md 路径（扩展 B）：环境变量 PROMPTS_USER_FILE，未设返回 None。"""
    override = os.environ.get(_PROMPTS_USER_FILE_ENV)
    return Path(override) if override else None


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 markdown frontmatter（与 skills.loader 语义对齐）：

    ---
    key: value
    ---
    body...
    """
    if not text:
        return {}, ""
    normalized = text.replace("\r\n", "\n")
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", normalized, re.DOTALL)
    if not match:
        return {}, normalized.strip()
    meta_raw = match.group(1).strip()
    body = match.group(2).strip()
    meta: dict[str, str] = {}
    for line in meta_raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def _substitute(text: str, context: dict[str, str] | None) -> str:
    """``{{key}}`` 逐键替换；无 context（None/空）时原样返回。"""
    if not context:
        return text
    for key, value in context.items():
        text = text.replace("{{" + key + "}}", value)
    return text


class PromptAsset:
    """从 prompts/*.md（YAML frontmatter + 正文）加载全局提示词资产，按文件名 stem 索引。"""

    def __init__(
        self,
        prompts_dir: Path | str | None = None,
        user_file: Path | str | None = None,
    ) -> None:
        self.prompts_dir = Path(prompts_dir) if prompts_dir is not None else _prompts_dir()
        user = Path(user_file) if user_file is not None else _user_file()
        self.user_file: Path | None = user if user else None
        self.assets: dict[str, dict[str, str | dict[str, str]]] = {}
        self._user_body = ""
        self.reload()

    def reload(self) -> None:
        """重读资产目录下所有 *.md + 用户偏爱文件（缺目录/读失败静默跳过）。"""
        self.assets = {}
        if self.prompts_dir.exists():
            for path in sorted(self.prompts_dir.glob("*.md")):
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                meta, body = _parse_frontmatter(text)
                self.assets[path.stem] = {"meta": meta, "body": body}
        self._user_body = ""
        if self.user_file is not None and self.user_file.exists():
            try:
                text = self.user_file.read_text(encoding="utf-8")
            except OSError:
                self._user_body = ""
            else:
                _, self._user_body = _parse_frontmatter(text)

    def get(self, stem: str) -> str | None:
        """直接取正文（缺失/解析失败 → None，注入点据此静默跳过）。"""
        asset = self.assets.get((stem or "").strip())
        if not asset:
            return None
        body = str(asset.get("body") or "").strip()
        return body or None

    def version(self, stem: str) -> str | None:
        """资产 frontmatter.version（无 frontmatter/缺失 → None）。"""
        asset = self.assets.get((stem or "").strip())
        if not asset:
            return None
        raw_meta = asset.get("meta")
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        return str(meta.get("version") or "") or None

    def render(self, stem: str, context: dict[str, str] | None = None) -> str:
        """渲染：资产正文（逐键替换）+ 可选用户偏爱段（追加在资产之后）。"""
        parts: list[str] = []
        body = self.get(stem)
        if body:
            parts.append(_substitute(body, context))
        if self._user_body:
            parts.append(_substitute(self._user_body, context))
        return "\n\n".join(p for p in parts if p)


_asset: PromptAsset | None = None


def get_prompt_asset(prompts_dir: Path | str | None = None) -> PromptAsset:
    """模块级单例（懒加载 + 缓存）；显式传目录时绕过缓存建新实例（测试用）。"""
    global _asset
    if prompts_dir is not None:
        return PromptAsset(prompts_dir=prompts_dir)
    if _asset is None:
        _asset = PromptAsset()
    return _asset


def reset_prompt_asset() -> None:
    """清空模块单例（环境变量覆盖后重载用，仿 SKILLS_DIR 语义）。"""
    global _asset
    _asset = None
