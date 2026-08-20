"""Langfuse exporter（可选上报）— 设计文档 54 §2.3

只在 `LANGFUSE_HOST` + `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` 三者齐全
**且** ``langfuse`` SDK 可导入时才启用；否则 NoOp（JSONL 底座不受影响，启动不炸）。

- 映射：Trace→trace、Span→span、Generation→generation（tokens/cost/model 直搬）；
- 异步上报：有界队列 + 后台线程，不阻塞分析主链路；上报失败静默降级只记本地一条 warning；
- 依赖：``langfuse>=2,<3`` 为 optional extra（``.[langfuse]``），未装则 NoOp；
- 配置判定走 ``ObservabilityConfig.langfuse_enabled`` 派生属性（见 config/loader.py）。

风险缓解（设计文档 54 §7）：
- 问题 19「假亮点」：``langfuse_enabled`` 是派生属性，yaml 无死字段，单测覆盖各组合；
- SDK 版本漂移：锁 ``langfuse>=2,<3``，惰性 import + 失败 NoOp，升级先跑 exporter 单测。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("competitor_agent.observability.langfuse_exporter")

# Langfuse 启用需要齐备的三个环境变量（插件式 optional exporter）
_HOST_ENV = "LANGFUSE_HOST"
_PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
_SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"

# 有界队列容量 + 后台线程：sink 数量级为数百 span/会话，足够缓冲且不阻塞分析
_QUEUE_MAX = 1024


class LangfuseExporter:
    """把 span 完成记录异步上报到自托管 Langfuse server（sink 实现）。

    构造时静默探测依赖与三环境变量；不齐则构造为 ``available=False`` 的 NoOp——
    ``emit`` 直接丢弃（与 JsonlSink 底座解耦，未配置环境行为与现状一致）。
    """

    def __init__(self, client: Any = None) -> None:
        self._client = client
        self._queue: Any = None
        self._worker: Any = None
        if self._client is not None:
            self._start()
        else:
            self._client = self._build_client()  # 探不到即 None，emit no-op

    @staticmethod
    def _env_ready() -> bool:
        import os

        return bool(os.getenv(_HOST_ENV) and os.getenv(_PUBLIC_KEY_ENV) and os.getenv(_SECRET_KEY_ENV))

    def _build_client(self) -> Any:
        """惰性 import langfuse SDK；依赖缺失或三变量不齐 → None（NoOp）。"""
        if not self._env_ready():
            logger.debug("Langfuse 未启用：三环境变量不齐全（host/public_key/secret_key）")
            return None
        try:
            from langfuse import Langfuse  # type: ignore[import-untyped]

            # 三变量为构造必需；其余(host 已在 env)由 SDK 读取
            return Langfuse(public_key=self._getenv(_PUBLIC_KEY_ENV), secret_key=self._getenv(_SECRET_KEY_ENV))
        except Exception as exc:  # noqa: BLE001 - SDK 缺失/构造失败 → NoOp
            logger.warning("Langfuse SDK 不可用，启用 NoOp exporter: %s", exc)
            return None

    @staticmethod
    def _getenv(name: str) -> str:
        import os

        return os.getenv(name) or ""

    def _start(self) -> None:
        """启动后台上报线程 + 有界队列（仅 SDK 可用时）。"""
        import queue as queue_mod
        import threading

        self._queue: Any = queue_mod.Queue(maxsize=_QUEUE_MAX)
        self._worker = threading.Thread(
            target=self._run_loop, name="langfuse-exporter", daemon=True,
        )
        self._worker.start()

    def _run_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:  # 哨兵退出
                break
            try:
                self._sync_upload(item)
            except Exception as exc:  # noqa: BLE001 - 上报失败静默降级只记 warning
                logger.warning("Langfuse 上报失败（已本地降级）: %s", exc)

    def _sync_upload(self, record: dict[str, Any]) -> None:
        """同步把一条 span 完成记录映射为 Langfuse trace/span/generation 并上报。"""
        if self._client is None:
            return
        kind = record.get("kind")
        trace_id = str(record.get("trace_id"))
        name = str(record.get("name") or kind)
        start = record.get("start")
        end = record.get("end")
        input_ = record.get("input_brief")
        output = record.get("output_brief")
        status = record.get("status")
        if kind == "trace":
            # 根：建立名为 name 的 trace，终点用 status/错误标注
            self._client.trace(name=name, input=input_, output=output, status=status)
        elif kind == "llm":
            with self._client.start_as_observation(
                name=name, trace_id=trace_id,
                type="GENERATION", level=_level_of(status),
                input=input_, output=output,
                metadata={"attempts": record.get("attempts"), "retried": record.get("retried"),
                          "timed_out": record.get("timed_out")},
            ) as gen:
                gen.update(
                    model=str(record.get("model") or ""),
                    usage={
                        "input": int(record.get("prompt_tokens") or 0),
                        "output": int(record.get("completion_tokens") or 0),
                    },
                    cost=record.get("cost_usd"),
                )
        else:
            with self._client.start_as_observation(
                name=name, trace_id=trace_id,
                parent_observation_id=record.get("parent_span_id"),
                type="SPAN", level=_level_of(status),
                start_time=start, end_time=end, input=input_, output=output,
            ):
                pass

    def emit(self, record: dict[str, Any]) -> None:
        """把 span 记录入队异步上报；队列满/未启动则静默丢弃（不阻塞主链路）。"""
        if self._client is None or self._queue is None:
            return
        try:
            self._queue.put_nowait(record)
        except Exception:  # noqa: BLE001 - 队列满等异常静默丢弃
            logger.debug("Langfuse 队列满，丢弃一条上报")

    def flush(self) -> None:
        """尽力排空队列（进程退出前调用）；未启动/无工作线程则 no-op。"""
        if self._queue is None:
            return
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                self._sync_upload(item)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Langfuse flush 上报失败: %s", exc)


def _level_of(status: str | None) -> str:
    """Langfuse level：error/cancelled → ERROR，其余默认（该平台缺省 DEFAULT 可省字段）。"""
    if status in ("error", "cancelled"):
        return "ERROR"
    return "DEFAULT"


def build_langfuse_exporter() -> LangfuseExporter:
    """供 facade 构建可选 exporter：BundleConfig.langfuse_enabled 判定后调用。"""
    return LangfuseExporter()


__all__ = [
    "LangfuseExporter",
    "build_langfuse_exporter",
    "flush_langfuse",
]


def flush_langfuse() -> None:
    """进程退出前兜底排空 Langfuse 队列（幂等，供 CLI main / web 收尾调用）。"""
    try:
        from competitor_agent.observability.tracer import get_tracer

        for sink in get_tracer()._sinks if hasattr(get_tracer(), "_sinks") else []:
            if isinstance(sink, LangfuseExporter):
                sink.flush()
    except Exception:  # noqa: BLE001
        logger.debug("Langfuse flush 兜底异常忽略", exc_info=True)