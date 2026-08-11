"""MessageBus — 多 Agent 协作的消息总线（结构化 Artifact 传递）

设计：轻量发布/订阅，topic 路由 + 载荷（Artifact）。
- publish() 同步分发到该 topic 的订阅者
- 记录消息日志（sequenced），便于审计/回放/历史
- threading.Lock 保证并行子代理并发安全
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

TopicHandler = Callable[[Any], None]

# 预定义 topics（多 Agent 流水线）
T_COLLECTED = "collected"  # CollectorAgent → AnalyzerAgent：观测
T_ANALYZED = "analyzed"  # AnalyzerAgent → ValidatorAgent：维度结论
T_VALIDATED = "validated"  # ValidatorAgent → ReporterAgent：校验后的结论
T_DRAFT = "draft"  # ReporterAgent 输出：草稿报告


class TopicError(KeyError):
    """订阅/发布到未知 topic"""


@dataclass
class Envelope:
    """一条消息"""

    sequence: int
    topic: str
    payload: Any


@dataclass
class MessageBus:
    """进程内发布/订阅总线"""

    handlers: dict[str, list[Callable[[Envelope], None]]] = field(default_factory=dict)
    _log: list[Envelope] = field(default_factory=list)
    _seq: itertools.count = field(default_factory=itertools.count)
    _lock: Lock = field(default_factory=Lock)

    def subscribe(self, topic: str, handler: Callable[[Envelope], None]) -> None:
        """注册 topic 订阅者。topic 为空字符串表示订阅所有。"""
        self.handlers.setdefault(topic, []).append(handler)

    def publish(self, topic: str, payload: Any) -> Envelope:
        """发布消息到 topic，同步分发到订阅者（含全局订阅者）。"""
        env = Envelope(sequence=next(self._seq), topic=topic, payload=payload)
        with self._lock:
            self._log.append(env)
            targets = list(self.handlers.get(topic, [])) + list(self.handlers.get("", []))
        for handler in targets:
            handler(env)
        return env

    def history(self, topic: str | None = None) -> list[Envelope]:
        """消息回放/审计。topic=None 返回全量。"""
        if topic is None:
            return list(self._log)
        return [env for env in self._log if env.topic == topic]


__all__ = [
    "T_ANALYZED",
    "T_COLLECTED",
    "T_DRAFT",
    "T_VALIDATED",
    "Envelope",
    "MessageBus",
]
