"""MessageBus — 多 Agent 协作的消息总线（结构化 Artifact 传递）

设计：轻量发布/订阅，topic 路由 + 载荷（Artifact）。
- publish() 同步分发到该 topic 的订阅者（向后兼容既有阶段埋点）
- subscribe_async() + publish_async()：异步订阅者 + 请求/响应语义
  - publish_async(..., await_result=True) 返回订阅者产出，供编排器收集各 Agent 结果
  - publish_async(..., timeout=...) 订阅者超时未确认 → 记 DEGRADED，不阻塞流水线
- 记录消息日志（sequenced），便于审计/回放/历史
- threading.Lock 保证并行子代理并发安全
"""
from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Awaitable, Callable

TopicHandler = Callable[[Any], None]
AsyncTopicHandler = Callable[["Envelope"], Awaitable[Any]]

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
class DegradedNotice:
    """异步订阅者超时/异常时的降级记录（不阻塞流水线）"""

    topic: str
    reason: str  # timeout / error: ...
    payload: Any


@dataclass
class MessageBus:
    """进程内发布/订阅总线（同步 + 异步订阅者）"""

    handlers: dict[str, list[Callable[[Envelope], None]]] = field(default_factory=dict)
    async_handlers: dict[str, list[AsyncTopicHandler]] = field(default_factory=dict)
    _log: list[Envelope] = field(default_factory=list)
    _degraded: list[DegradedNotice] = field(default_factory=list)
    _seq: itertools.count = field(default_factory=itertools.count)
    _lock: Lock = field(default_factory=Lock)

    def subscribe(self, topic: str, handler: Callable[[Envelope], None]) -> None:
        """注册 topic 订阅者。topic 为空字符串表示订阅所有。"""
        self.handlers.setdefault(topic, []).append(handler)

    def subscribe_async(self, topic: str, coro: AsyncTopicHandler) -> None:
        """注册异步订阅者（topic 为空字符串表示订阅所有）。

        coro 接收 Envelope，返回 awaitable 产出（供 await_result 收集）。
        """
        self.async_handlers.setdefault(topic, []).append(coro)

    def publish(self, topic: str, payload: Any) -> Envelope:
        """发布消息到 topic，同步分发到订阅者（含全局订阅者）。"""
        env = Envelope(sequence=next(self._seq), topic=topic, payload=payload)
        with self._lock:
            self._log.append(env)
            targets = list(self.handlers.get(topic, [])) + list(self.handlers.get("", []))
        for handler in targets:
            handler(env)
        return env

    async def publish_async(
        self,
        topic: str,
        payload: Any,
        await_result: bool = False,
        timeout: float | None = None,
    ) -> Any:
        """异步发布：同步订阅者立即分发，异步订阅者逐个 await。

        - await_result=True：返回异步订阅者产出列表（可能含 None=超时/异常），
          编排器可用 asyncio.gather 并行等待多个请求；
        - timeout：单个异步订阅者执行超时则记 DEGRADED 并返回 None，不阻塞流水线；
        - 无异步订阅者时返回 Envelope（await_result=True 时返回 [None]）。
        """
        env = Envelope(sequence=next(self._seq), topic=topic, payload=payload)
        with self._lock:
            self._log.append(env)
            sync_targets = list(self.handlers.get(topic, [])) + list(self.handlers.get("", []))
            async_targets = list(self.async_handlers.get(topic, [])) + list(
                self.async_handlers.get("", [])
            )
        for handler in sync_targets:
            handler(env)

        if not async_targets:
            return [None] if await_result else env

        results: list[Any] = []
        for coro in async_targets:
            try:
                task = coro(env)
                if timeout is not None:
                    results.append(await asyncio.wait_for(task, timeout=timeout))
                else:
                    results.append(await task)
            except asyncio.TimeoutError:
                self._record_degraded(env, "timeout")
                results.append(None)
            except Exception as exc:  # noqa: BLE001 —— 订阅者异常不阻塞流水线
                self._record_degraded(env, f"error: {type(exc).__name__}: {exc}")
                results.append(None)
        return results if await_result else env

    def _record_degraded(self, env: Envelope, reason: str) -> None:
        with self._lock:
            self._degraded.append(DegradedNotice(topic=env.topic, reason=reason, payload=env.payload))

    def degraded(self) -> list[DegradedNotice]:
        """异步分发中的降级记录（超时/异常），供审计与叙事。"""
        return list(self._degraded)

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
    "AsyncTopicHandler",
    "DegradedNotice",
    "Envelope",
    "MessageBus",
]
