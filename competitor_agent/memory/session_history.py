"""会话级多轮历史（设计文档 65 §3.2/§3.4）— 按 session_id 持久化对话上下文

与竞品记忆（L1-L4）正交：前者是**会话对话上下文**（user task + assistant 结果，跨轮注入
LLM），后者是**竞品知识沉淀**。基于 ``JsonStore`` 落盘（data_dir/memory/chat_history.json），
刷新/重启不丢。

长期会话分层控制（设计文档 65 §3.4，作用域 = 单个 session_id）：
- **窗口保留**：最近 ``max_verbatim_turns`` 轮原文注入（"分析我上一个问题"可准确指代）；
- **远端折叠**：超过窗口的旧轮折叠为确定性规则摘要（无 LLM，一行一轮；
  可经 ``kb_recall`` 指针取回全文——本文档只产出摘要，指针由调用方配）；
- **总量上限**：注入总字符超 ``max_history_chars`` 时截断并加标记；
- **LRU 淘汰**：会话数超 ``max_sessions`` 时按最近访问淘汰最旧未访问的（防磁盘无界）。

语义：同一 session_id 内多次对话累积进同一份历史，持续受压缩；只有调用 ``drop``
（对应前端"新会话"换新 session_id）才断开——新 session_id 历史从空开始。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from competitor_agent.memory.json_store import JsonStore

_STORE_NAME = "chat_history"
_ROLE_USER = "user"
_ROLE_ASSISTANT = "assistant"
# 远端折叠时单条保留的字数（user / assistant 各截断到该上限）
_SUMMARY_PREVIEW_CHARS = 80
# 超限截断标记
_OVERFLOW_MARK = "（历史过长已截断）"


def _preview(text: str, limit: int = _SUMMARY_PREVIEW_CHARS) -> str:
    """单行折叠预览：压空白、截断到 limit 字。"""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


class SessionHistory:
    """按 session_id 的多轮会话历史存储 + 压缩（设计文档 65 §3.2）。"""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        *,
        max_verbatim_turns: int = 10,
        max_history_chars: int = 16_000,
        max_sessions: int = 200,
    ) -> None:
        self._store = JsonStore(_STORE_NAME, data_dir)
        self.max_verbatim_turns = max(1, int(max_verbatim_turns))
        self.max_history_chars = max(1, int(max_history_chars))
        self.max_sessions = max(1, int(max_sessions))
        self._touch: dict[str, float] = {}

    # ── 写 ────────────────────────────────────────────────────────────
    def append(self, session_id: str, role: str, content: str) -> None:
        """追加一条 {role, content, ts} 到该会话历史（追加式，绝不覆盖）。"""
        if role not in (_ROLE_USER, _ROLE_ASSISTANT):
            return
        entries = self._entries(session_id)
        entries.append(
            {
                "role": role,
                "content": str(content or ""),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        self._store.put(session_id, entries)
        self._store.save()
        self._touch[session_id] = time.monotonic()
        self._evict_lru()

    def drop(self, session_id: str) -> None:
        """显式清空（前端"新会话"换新 session_id 后旧历史可保留在磁盘供 /api/history 查）。"""
        self._store.remove(session_id)
        self._store.save()
        self._touch.pop(session_id, None)

    # ── 读 ────────────────────────────────────────────────────────────
    def messages(self, session_id: str) -> list[dict[str, str]]:
        """该会话历史 → [{role, content}]（压缩后，供注入 LLM）。"""
        entries = self._entries(session_id)
        self._touch[session_id] = time.monotonic()
        return self._compact(entries)

    def raw(self, session_id: str) -> list[dict[str, Any]]:
        """原始条目（含 ts，供 /api/history 展示；不含压缩）。"""
        return list(self._entries(session_id))

    def has(self, session_id: str) -> bool:
        return session_id in self._store

    # ── 内部 ──────────────────────────────────────────────────────────
    def _entries(self, session_id: str) -> list[dict[str, Any]]:
        raw = self._store.get(session_id)
        if isinstance(raw, list):
            return [e for e in raw if isinstance(e, dict) and e.get("role") in (_ROLE_USER, _ROLE_ASSISTANT)]
        return []

    def _compact(self, entries: list[dict[str, Any]]) -> list[dict[str, str]]:
        """长期压缩（设计文档 65 §3.4）：近端原文 + 远端折叠 + 总量上限。

        角色交替约束：丢弃尾部悬空 user（上轮未收尾被中断），防止 user/user 连续。
        """
        if not entries:
            return []
        out: list[dict[str, str]] = []
        n = len(entries)
        # 远端条目数（可被折叠的） = 总数 - 窗口轮数×2（一轮 = user+assistant 两条）；
        # 至少保底 1 条原文（兜底边界）
        fold_n = max(0, min(n - 1, n - self.max_verbatim_turns * 2))
        for idx, e in enumerate(entries):
            role = str(e.get("role") or "")
            content = str(e.get("content") or "")
            if idx < fold_n:
                out.append({"role": role, "content": f"[摘要] {_preview(content)}"})
            else:
                out.append({"role": role, "content": content})
        # 总量上限：超过则从最旧开始逐条折叠到放得下（仍保底最近一轮原文）
        total = sum(len(m["content"]) for m in out)
        budget = self.max_history_chars
        if total > budget:
            out = self._cap(out, budget)
        return self._alternate(out)

    def _cap(self, messages: list[dict[str, str]], budget: int) -> list[dict[str, str]]:
        """总量封顶：从最旧折叠为更短摘要，直到放得下；仍超则整体截断加标记。"""
        folded = 0
        while folded < len(messages) - 1:
            total = sum(len(m["content"]) for m in messages)
            if total <= budget:
                break
            m = messages[folded]
            messages[folded] = {"role": m["role"], "content": _preview(m["content"], 40)}
            folded += 1
        total = sum(len(m["content"]) for m in messages)
        if total <= budget:
            return messages
        # 折叠仍超：从头截断到剩最后一条（最新），并加标记
        last = messages[-1]
        out = [{"role": last["role"], "content": last["content"][: max(0, budget - len(_OVERFLOW_MARK))] + _OVERFLOW_MARK}]
        return out

    @staticmethod
    def _alternate(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """角色交替：确保首条 user、相邻不重复、末尾是 assistant。

        末尾悬空 user（上轮被中断、无 assistant 收尾）仅在有前文时丢弃；单条 user
        历史（会话刚起、首问未答）保留——它是可被重新问起的有效首轮。
        """
        if not messages:
            return []
        if messages[0]["role"] != _ROLE_USER:
            messages = [{"role": _ROLE_USER, "content": "（会话开始）"}] + messages
        result: list[dict[str, str]] = []
        prev: str | None = None
        for m in messages:
            if m["role"] == prev:
                continue
            result.append(m)
            prev = m["role"]
        if len(result) > 1 and result[-1]["role"] == _ROLE_USER:
            result.pop()
        return result

    def _evict_lru(self) -> None:
        """会话数上限 LRU 淘汰（防磁盘无界）：淘汰最近未访问的最旧会话。"""
        keys = self._store.keys()
        if len(keys) <= self.max_sessions:
            return
        touched = {k: self._touch.get(k, 0.0) for k in keys}
        for sid in sorted(touched, key=lambda k: touched[k])[: len(keys) - self.max_sessions]:
            self._store.remove(sid)
            self._touch.pop(sid, None)
        if self._store._dirty:
            self._store.save()


__all__ = ["SessionHistory"]
