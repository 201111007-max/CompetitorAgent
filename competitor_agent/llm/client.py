"""LLM Client 抽象：驱动维度分析，LLM 不可用时降级

M1 提供：
- LLMClient：基于 openai SDK 的调用封装（parse/summarize 语义化方法）
- 可注入 mock，供测试与规则降级

可靠性（设计文档 36）：
- 可重试错误（429/408/5xx/连接/超时）指数退避重试（≤max_retries）
- 多模型 fallback 链：主模型重试耗尽自动切换 fallback_models
- 每次调用可配置超时（连接 + 读）
- 不可重试错误（401/400/404）直接抛、不浪费重试；全灭抛 LLMUnavailableError 降级规则

凭据与端点通过环境变量控制（不明文落码）：
- OPENAI_API_KEY：API Key（兼容 DEEPSEEK_API_KEY / LLM_API_KEY 别名）
- OPENAI_BASE_URL：OpenAI 兼容端点（DeepSeek 等），默认官方 OpenAI
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import random
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Callable

from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.observability.logger import emit_session_event

logger = logging.getLogger("competitor_agent.llm.client")

# 脱敏 LLM 调用日志的粗略计价（美元/千 token），仅用于可观测性展示
_PRICING_PER_1K = {"input": 0.0003, "output": 0.0006}  # DeepSeek 量级近似

# 可重试 HTTP 状态码：429 限流 / 408 请求超时 / 5xx 服务端错误
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
# 异常类名启发式（openai SDK 的 RateLimitError / APIConnectionError / APITimeoutError /
# InternalServerError 与内置 TimeoutError / ConnectionError 等）
_RETRYABLE_ERR_FRAGMENTS = (
    "ratelimit",
    "apiconnection",
    "apitimeout",
    "internalserver",
    "timeout",
    "connection",
)

# 结构化补全（设计文档 34）修复重试提示：回灌 schema 校验错误，要求只输出合法 JSON
_JSON_REPAIR_HINT = (
    "你上一次的输出未通过 JSON Schema 校验。请重新生成，只输出合法的 JSON 对象本身，"
    "不要包裹在 Markdown 代码块里。务必修正以下问题："
)

# 「端点/模型不支持 tools」特征片段（设计文档 53 Q4）：400 报错文本中出现即判定
_TOOLS_UNSUPPORTED_FRAGMENTS = ("tool_calls", "tool_choice", "tools", "function call")


@dataclass
class ToolCall:
    """原生 tool-calling 的单次工具调用（设计文档 53）。

    ``arguments`` 为解析后的 dict；arguments JSON 解析失败时不静默置空——
    ``args_error`` 携带可读原因供回灌（设计文档 38 语义），``arguments`` 为 {}。
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    args_error: str | None = None


@dataclass
class ToolCallReply:
    """``complete_with_tools`` 的返回：content + 结构化 tool_calls + usage。

    ``tool_calls`` 为空时 ``content`` 即最终回答（原生协议的终止信号）。
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Any = None


@dataclass
class StreamDelta:
    """流式增量（设计文档 63 §5）：``LLMClient.stream()`` 的产出单元。

    ``kind``：``"text"`` 实时叙述/回答正文，``"thinking"`` 模型暴露的推理链
    （deepseek 系 ``reasoning_content``）。模型不暴露推理链则只有 ``text``。
    ``model`` 记录实际产出该增量的模型（多模型 fallback 时区分）。
    """

    kind: str
    text: str
    model: str = ""
    message_id: str = ""  # 事件桥回填归属（M2+ 使用）


class _StreamMeter:
    """流式调用的收尾计量盒（设计文档 63 §5.4）：随 generator 透传到产出侧记录 usage/模型，
    由消费方在收尾时经 ``_log_stream`` 记 ``llm.call``。跨线程单次调用内使用，无需加锁。"""

    __slots__ = ("delivered", "final_model", "text_parts", "usage")

    def __init__(self) -> None:
        self.usage: Any = None
        self.final_model: str = ""
        self.delivered: bool = False
        self.text_parts: list[str] = []

    def add(self, delta: StreamDelta) -> None:
        """仅累加正文字增量（thinking 不计入 completion 文本估算；SDK 有真实 usage 时以其为准）。"""
        if delta.kind == "text":
            self.text_parts.append(delta.text)


def _estimate_tokens(texts: list[str]) -> int:
    return sum(len(t) // 4 for t in texts)


def _parse_arguments(raw_args: Any) -> dict[str, Any]:
    """解析 tool_call 的 arguments：合法 JSON 对象 → dict；非法 → args_error 可读原因。

    不静默置空（设计文档 38/53 语义）：解析失败时 ``args_error`` 供回灌自恢复。
    """
    if raw_args is None:
        return {"arguments": {}}
    if isinstance(raw_args, dict):
        return {"arguments": raw_args}
    try:
        parsed = json.loads(str(raw_args))
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "arguments": {},
            "args_error": f"arguments 不是合法 JSON: {exc}；原始内容: {str(raw_args)[:200]}",
        }
    if not isinstance(parsed, dict):
        return {
            "arguments": {},
            "args_error": f"arguments 期望 JSON 对象，实际 {type(parsed).__name__}",
        }
    return {"arguments": parsed}


# 兼容别名链：OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY
_API_KEY_ENVS = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY")
_BASE_URL_ENV = "OPENAI_BASE_URL"


class LLMClient:
    """统一 LLM 调用封装（可注入 callable 便于测试）

    可靠性（设计文档 36）：可重试错误指数退避重试 → 多模型 fallback 链 →
    全灭抛 LLMUnavailableError 降级规则；不可重试错误（401/400/404）直接抛。
    """

    def __init__(
        self,
        call_func: Callable[..., str] | None = None,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str | None = None,
        fallback_models: list[str] | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
        backoff: float = 1.0,
        pricing_per_1k: dict[str, float] | None = None,
        tracer: Any = None,  # 设计文档 54：链路追踪 generation hook（None 跳过）
    ) -> None:
        # call_func: (messages, **kwargs) -> str；默认走 openai SDK（惰性导入）
        self._call = call_func
        self._tracer = tracer
        self._model = model
        self._fallback_models = list(fallback_models) if fallback_models else []
        self._timeout = timeout
        self._max_retries = max(1, int(max_retries))
        self._backoff = max(0.0, float(backoff))
        # 计价（设计文档 46 §3.3）：config 注入优先，无配置沿用 DeepSeek 量级近似（行为不变）
        if pricing_per_1k:
            self._pricing_per_1k = {
                "input": float(pricing_per_1k["input"]),
                "output": float(pricing_per_1k["output"]),
            }
        else:
            self._pricing_per_1k = dict(_PRICING_PER_1K)
        # 显式传入优先，否则读环境变量（不明文硬编码）
        self._api_key = api_key or self._read_env_key()
        self._base_url = base_url or os.getenv(_BASE_URL_ENV)
        # 累计调用成本（设计文档 37：真实评测报告成本核算，复用 _log_call 的 cost_usd）
        self.total_cost_usd = 0.0
        # 成本累计锁：并行编排（设计文档 33）多线程并发调用时原子累加
        self._cost_lock = threading.Lock()

    @staticmethod
    def has_api_key() -> bool:
        """是否有可用的 API Key（真实评测前置校验，设计文档 37）。"""
        return LLMClient._read_env_key() is not None

    @staticmethod
    def _read_env_key() -> str | None:
        for name in _API_KEY_ENVS:
            value = os.getenv(name)
            if value:
                return value.strip()
        return None

    def complete(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        """最通用：返回原始文本（带重试 + 多模型 fallback + 超时）。

        json_mode（设计文档 34）：SDK 路径附加 ``response_format={"type": "json_object"}``
        软性约束结构化输出；注入 call_func 路径透传 messages 不动（mock 由调用方保证 JSON）。
        """
        started = time.monotonic()
        if self._call is not None:
            call = self._call
            return self._attempt_models(
                messages,
                started,
                lambda model: call(messages=messages, model=model),
            )

        try:
            from openai import OpenAI  # 惰性导入，避免无 key 环境失败
        except ImportError as exc:
            raise LLMUnavailableError("openai SDK 未安装") from exc

        if not self._api_key:
            raise LLMUnavailableError(
                "缺少 LLM API Key，请设置环境变量 OPENAI_API_KEY（或 DEEPSEEK_API_KEY / LLM_API_KEY）"
            )

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = OpenAI(**kwargs)

        def attempt(model: str) -> Any:
            create_kwargs: dict[str, Any] = {"model": model, "messages": messages}
            if json_mode:
                create_kwargs["response_format"] = {"type": "json_object"}
            if self._timeout is not None:
                create_kwargs["timeout"] = self._timeout
            return client.chat.completions.create(**create_kwargs)

        return self._attempt_models(messages, started, attempt)

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Any = None,
        *,
        stream_sink: Callable[[StreamDelta], None] | None = None,
        message_id: str = "",
    ) -> ToolCallReply:
        """原生 function calling 通道（设计文档 53 M1 / 63 §5.5）。

        ``stream_sink`` 缺省（None）→ 走非流式 ``_complete_with_tools``，行为逐字节不变
        （54 个既有调用方不传 stream_sink）。传入时 → 流式旁路：逐增量产出
        ``thinking_delta``/``text_delta`` 到 ``stream_sink``，并从流式增量重构出与
        非流式等价的 ``ToolCallReply``（仅 Lead 走此旁路，子 Agent 不流式，主旨2）。

        非流式路径语义（沿用）：SDK 传 ``tools``/``tool_choice`` 复用 ``_attempt_models``
        重试/多模型 fallback/计价/埋点；注入 ``call_func`` 透传 kwargs（mock 双形态）。
        """
        if stream_sink is None:
            return self._complete_with_tools(messages, tools, tool_choice)
        started = time.monotonic()
        meter = _StreamMeter()
        reply = ToolCallReply()
        tool_acc: list[dict[str, Any]] = []
        producer = lambda model, meter: self._stream_tool_call(
            messages, model, tools, tool_choice, meter, reply, tool_acc
        )
        try:
            for delta in self._stream_with_retry(messages, producer, meter):
                self._sink_delta(stream_sink, delta, message_id)
        finally:
            self._log_stream(messages, started, meter)
        self._finalize_stream_calls(tool_acc, reply)
        return reply

    def _complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Any = None,
    ) -> ToolCallReply:
        """非流式 function calling（complete_with_tools 的默认路径，语义见文档注释）。"""
        started = time.monotonic()
        if self._call is not None:
            call = self._call
            return self._attempt_models(
                messages,
                started,
                lambda model: call(
                    messages=messages, model=model, tools=tools, tool_choice=tool_choice
                ),
                extract=self._extract_tool_reply,
            )

        try:
            from openai import OpenAI  # 惰性导入，避免无 key 环境失败
        except ImportError as exc:
            raise LLMUnavailableError("openai SDK 未安装") from exc

        if not self._api_key:
            raise LLMUnavailableError(
                "缺少 LLM API Key，请设置环境变量 OPENAI_API_KEY（或 DEEPSEEK_API_KEY / LLM_API_KEY）"
            )

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = OpenAI(**kwargs)

        def attempt(model: str) -> Any:
            create_kwargs: dict[str, Any] = {"model": model, "messages": messages, "tools": tools}
            if tool_choice is not None:
                create_kwargs["tool_choice"] = tool_choice
            if self._timeout is not None:
                create_kwargs["timeout"] = self._timeout
            try:
                return client.chat.completions.create(**create_kwargs)
            except Exception as exc:
                if self._is_tools_unsupported(exc):
                    raise LLMUnavailableError(
                        f"模型 {model} 不支持 tool_calls（原生 function calling），"
                        "请更换支持工具调用的模型（设计文档 60：单协议，无文本降级）"
                    ) from exc
                raise

        return self._attempt_models(messages, started, attempt, extract=self._extract_tool_reply)

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
    ) -> Iterator[StreamDelta]:
        """流式分词（设计文档 63 §5，Option C 核心）：逐增量 yield ``StreamDelta``。

        顺序即下游 ``text_delta``/``thinking_delta`` 的投递顺序；**不返回完整字符串**，
        完整文本由调用方消费时自行累加。

        可靠性（§5.3）：流式是 generator，重试语义改为「**首个增量到达前**判定 +
        必要时切换 fallback 模型」。首个增量一经产出交给调用方，后续异常直接向调用方
        上抛（不强制回滚已下发文本）；多模型 × max_retries 全灭抛 ``LLMUnavailableError``。

        计价（§5.4）：流式收尾按 SDK 返回的 ``usage``（无则正文估算）记 ``llm.call``，
        成本核算与 ``complete()`` 一致；调用方提前中断也记已产出部分。
        """
        started = time.monotonic()
        meter = _StreamMeter()
        producer = lambda model, meter: self._stream_once(messages, model, json_mode, meter)
        try:
            yield from self._stream_with_retry(messages, producer, meter)
        finally:
            self._log_stream(messages, started, meter)

    def _stream_with_retry(
        self,
        messages: list[dict[str, str]],
        producer: Callable[[str, _StreamMeter], Iterator[StreamDelta]],
        meter: _StreamMeter,
    ) -> Iterator[StreamDelta]:
        """流式重试驱动：逐模型 × max_retries，首个增量到达前重试/fallback，
        首个增量产出后直通调用方（不在流中重试，避免回滚已显示文本）。"""
        models = [self._model, *self._fallback_models]
        last_cause: Exception | None = None
        for model in models:
            for _attempt in range(1, self._max_retries + 1):
                try:
                    gen = producer(model, meter)
                    first = next(gen)
                except StopIteration:
                    # 空流：模型返回 0 增量，视为正常完成（无可输出文本）
                    return
                except Exception as exc:
                    last_cause = exc
                    if self._should_retry(exc):
                        continue  # 重试同一模型下一次
                    raise LLMUnavailableError(f"流式调用失败（模型 {model}）: {exc}") from exc
                meter.final_model = model
                meter.delivered = True
                meter.add(first)
                yield first
                for delta in gen:
                    meter.add(delta)
                    yield delta
                return
        raise LLMUnavailableError(
            f"流式失败：{len(models)} 个模型 × {self._max_retries} 次重试全部耗尽"
        ) from last_cause

    def _log_stream(self, messages: list[dict[str, str]], started: float, meter: _StreamMeter) -> None:
        """流式收尾记账：仅当确有增量产出（delivered）时报 ``llm.call``。"""
        if not meter.delivered:
            return
        self._log_call(
            messages,
            started,
            "".join(meter.text_parts),
            usage=meter.usage,
            final_model=meter.final_model,
        )

    def _stream_once(
        self,
        messages: list[dict[str, str]],
        model: str,
        json_mode: bool,
        meter: _StreamMeter | None = None,
    ) -> Iterator[StreamDelta]:
        """单次流式产出的生产器：注入 call_func 或 openai SDK 两种路径。

        注入 call_func 为生成器函数 → 逐条透传（把 str 统一为 ``text`` delta）；
        非生成器 → 一次性包装为单个 ``text`` delta（兼容既有注入 mock）。
        SDK 路径 ``create(stream=True)``：逐 chunk 抽取 ``reasoning_content``（thinking）
        与 ``content``（text），并把末 chunk 的 ``usage`` 记入 ``meter``（§5.4 计价）。
        """
        if meter is None:
            meter = _StreamMeter()
        if self._call is not None:
            if inspect.isgeneratorfunction(self._call):
                for rec in self._call(messages=messages, model=model):
                    yield self._coerce_delta(rec, model)
            else:
                text = self._call(messages=messages, model=model)
                yield StreamDelta(kind="text", text=str(text), model=model)
            return

        try:
            from openai import OpenAI  # 惰性导入，避免无 key 环境失败
        except ImportError as exc:
            raise LLMUnavailableError("openai SDK 未安装") from exc
        if not self._api_key:
            raise LLMUnavailableError(
                "缺少 LLM API Key，请设置环境变量 OPENAI_API_KEY（或 DEEPSEEK_API_KEY / LLM_API_KEY）"
            )

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = OpenAI(**kwargs)
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}
        if self._timeout is not None:
            create_kwargs["timeout"] = self._timeout
        resp = client.chat.completions.create(**create_kwargs)
        for chunk in resp:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                meter.usage = usage
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            if not choice or not getattr(choice, "delta", None):
                continue
            delta = choice.delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield StreamDelta(kind="thinking", text=reasoning, model=model)
            content = getattr(delta, "content", None)
            if content:
                yield StreamDelta(kind="text", text=content, model=model)

    def _stream_tool_call(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]],
        tool_choice: Any,
        meter: _StreamMeter,
        reply: ToolCallReply,
        tool_acc: list[dict[str, Any]],
    ) -> Iterator[StreamDelta]:
        """流式 function calling 生产器（M2 仅 Lead 旁路，设计文档 63 §5.5）。

        逐 chunk 抽取 ``reasoning_content``（thinking）/``content``（text）产出增量，
        并把 ``delta.tool_calls`` 片段归并进 ``tool_acc``（供收尾重构 ToolCallReply）。
        """
        try:
            from openai import OpenAI  # 惰性导入，避免无 key 环境失败
        except ImportError as exc:
            raise LLMUnavailableError("openai SDK 未安装") from exc
        if not self._api_key:
            raise LLMUnavailableError(
                "缺少 LLM API Key，请设置环境变量 OPENAI_API_KEY（或 DEEPSEEK_API_KEY / LLM_API_KEY）"
            )

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = OpenAI(**kwargs)
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": True,
        }
        if tool_choice is not None:
            create_kwargs["tool_choice"] = tool_choice
        if self._timeout is not None:
            create_kwargs["timeout"] = self._timeout
        try:
            resp = client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            if self._is_tools_unsupported(exc):
                raise LLMUnavailableError(
                    f"模型 {model} 不支持 tool_calls（原生 function calling），"
                    "请更换支持工具调用的模型（设计文档 60：单协议，无文本降级）"
                ) from exc
            raise
        for chunk in resp:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                meter.usage = usage
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            if not choice or not getattr(choice, "delta", None):
                continue
            delta = choice.delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield StreamDelta(kind="thinking", text=reasoning, model=model)
            content = getattr(delta, "content", None)
            if content:
                reply.content += content
                yield StreamDelta(kind="text", text=content, model=model)
            delta_calls = getattr(delta, "tool_calls", None)
            if delta_calls:
                self._accum_tool_fragments(delta_calls, tool_acc)

    @staticmethod
    def _accum_tool_fragments(delta_calls: Any, tool_acc: list[dict[str, Any]]) -> None:
        """把流式 ``delta.tool_calls`` 片段按 index 归并进累积器（id/name 出现即写、
        arguments 为跨 chunk 追加的 JSON 字符串片段）。"""
        for frag in delta_calls:
            index = getattr(frag, "index", None)
            if index is None:
                index = len(tool_acc)
            while len(tool_acc) <= index:
                tool_acc.append({"id": "", "name": "", "arguments": ""})
            entry = tool_acc[index]
            frag_id = getattr(frag, "id", None)
            if frag_id:
                entry["id"] = str(frag_id)
            func = getattr(frag, "function", None)
            if func is not None:
                frag_name = getattr(func, "name", None)
                if frag_name:
                    entry["name"] = str(frag_name)
                frag_args = getattr(func, "arguments", None)
                if frag_args:
                    entry["arguments"] += str(frag_args)

    def _finalize_stream_calls(
        self, tool_acc: list[dict[str, Any]], reply: ToolCallReply
    ) -> None:
        """收尾把累积的工具片段重构为 ``ToolCall``（arguments JSON 解析失败走 args_error）。"""
        for idx, entry in enumerate(tool_acc):
            reply.tool_calls.append(
                ToolCall(
                    id=entry["id"] or f"call_stream_{idx}",
                    name=entry["name"],
                    **_parse_arguments(entry["arguments"]),
                )
            )

    @staticmethod
    def _sink_delta(
        sink: Callable[[StreamDelta], None], delta: StreamDelta, message_id: str
    ) -> None:
        """把增量交给调用方 sink；``message_id`` 非空时重寄归属（事件桥回填）。"""
        if not message_id:
            sink(delta)
            return
        sink(
            StreamDelta(
                kind=delta.kind, text=delta.text, model=delta.model, message_id=message_id
            )
        )

    def _coerce_delta(self, rec: Any, model: str) -> StreamDelta:
        """把注入生成器产出的条目规整为 ``StreamDelta``：已含 kind 的原样补 model，
        裸字符串视作 ``text`` 增量。"""
        if isinstance(rec, StreamDelta):
            rec.model = rec.model or model
            return rec
        return StreamDelta(kind="text", text=str(rec), model=model)

    def _attempt_models(
        self,
        messages: list[dict[str, Any]],
        started: float,
        attempt_fn: Callable[[str], Any],
        extract: Callable[[Any], tuple[Any, Any]] | None = None,
    ) -> Any:
        """逐模型 × 逐次重试：可重试错误退避重试 → 下一个 fallback 模型 → 全灭抛错。

        ``extract``：从原始响应抽取 (payload, usage)，缺省 ``_extract_text_and_usage``
        （payload=文本）；原生 tool-calling 传 ``_extract_tool_reply``（payload=ToolCallReply）。
        """
        extract_fn = extract or self._extract_text_and_usage
        models = [self._model, *self._fallback_models]
        last_exc: Exception | None = None
        saw_timeout = False
        total_attempts = 0
        for model in models:
            for attempt in range(1, self._max_retries + 1):
                total_attempts += 1
                try:
                    raw = attempt_fn(model)
                    payload, usage = extract_fn(raw)
                    log_text = payload.content if isinstance(payload, ToolCallReply) else str(payload)
                    self._log_call(
                        messages,
                        started,
                        log_text,
                        usage=usage,
                        attempts=total_attempts,
                        final_model=model,
                        retried=total_attempts > 1,
                        timed_out=saw_timeout,
                    )
                    return payload
                except Exception as exc:
                    last_exc = exc
                    if self._is_timeout(exc):
                        saw_timeout = True
                    if not self._should_retry(exc):
                        raise
                    if attempt < self._max_retries:
                        self._sleep_backoff(attempt)
        raise LLMUnavailableError(
            f"LLM 调用失败：{len(models)} 个模型 × {self._max_retries} 次重试全部耗尽"
        ) from last_exc

    @staticmethod
    def _extract_text_and_usage(raw: Any) -> tuple[str, Any]:
        """从注入 call_func 的 str 或 openai SDK 响应对象中抽取文本与用量。"""
        if isinstance(raw, str):
            return raw, None
        if isinstance(raw, dict):
            choices = raw.get("choices") or []
            content = (choices[0].get("message", {}).get("content") if choices else None) or ""
            return content, raw.get("usage")
        if getattr(raw, "choices", None) is not None:
            content = getattr(raw.choices[0], "message", None)
            content = getattr(content, "content", None) or ""
            return content, getattr(raw, "usage", None)
        raise LLMUnavailableError(f"LLM 返回无法解析的类型: {type(raw).__name__}")

    @staticmethod
    def _extract_tool_reply(raw: Any) -> tuple[ToolCallReply, Any]:
        """从 mock 双形态 / dict / openai SDK 响应抽取 ToolCallReply 与 usage（设计文档 53）。"""
        if isinstance(raw, ToolCallReply):
            return raw, raw.usage
        if isinstance(raw, str):
            return ToolCallReply(content=raw), None
        if isinstance(raw, dict):
            choices = raw.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            reply = ToolCallReply(
                content=message.get("content") or "",
                tool_calls=LLMClient._parse_tool_calls(message.get("tool_calls") or []),
            )
            return reply, raw.get("usage")
        if getattr(raw, "choices", None) is not None:
            message = getattr(raw.choices[0], "message", None)
            reply = ToolCallReply(
                content=getattr(message, "content", None) or "",
                tool_calls=LLMClient._parse_tool_calls(getattr(message, "tool_calls", None) or []),
            )
            return reply, getattr(raw, "usage", None)
        raise LLMUnavailableError(f"LLM 返回无法解析的类型: {type(raw).__name__}")

    @staticmethod
    def _parse_tool_calls(items: list[Any]) -> list[ToolCall]:
        """把 SDK/dict 形态的 tool_calls 规整为 ToolCall；arguments 非法 JSON → args_error。"""
        calls: list[ToolCall] = []
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                call_id = str(item.get("id") or f"call_{idx}")
                func = item.get("function") or {}
                name = str(func.get("name") or "")
                raw_args = func.get("arguments")
            else:
                call_id = str(getattr(item, "id", None) or f"call_{idx}")
                func = getattr(item, "function", None)
                name = str(getattr(func, "name", "") or "")
                raw_args = getattr(func, "arguments", None)
            calls.append(ToolCall(id=call_id, name=name, **_parse_arguments(raw_args)))
        return calls

    @staticmethod
    def _is_tools_unsupported(exc: Exception) -> bool:
        """「端点/模型不支持 tools」判定（设计文档 53 Q4）：400 + 报错文本含工具特征片段。"""
        status = getattr(exc, "status_code", None)
        if status != 400:
            return False
        text = str(exc).lower()
        return any(frag in text for frag in _TOOLS_UNSUPPORTED_FRAGMENTS)

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """可重试判定：429/408/5xx 状态码，或异常类名启发式（限流/连接/超时/服务端）。"""
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            return status in _RETRYABLE_STATUS or 500 <= status < 600
        name = type(exc).__name__.lower()
        return any(frag in name for frag in _RETRYABLE_ERR_FRAGMENTS)

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status == 408:
            return True
        return "timeout" in type(exc).__name__.lower()

    def _sleep_backoff(self, attempt: int) -> None:
        """指数退避 + 抖动（attempt 从 1 起：1s, 2s, 4s…）。"""
        delay = self._backoff * (2 ** (attempt - 1))
        time.sleep(delay + random.uniform(0, delay * 0.25))

    def _log_call(
        self,
        messages: list[dict[str, str]],
        started: float,
        text: str,
        usage: Any,
        attempts: int = 1,
        final_model: str | None = None,
        retried: bool = False,
        timed_out: bool = False,
    ) -> None:
        """脱敏调用日志：只记 model/base_url/tokens/耗时/成本，不落 prompt 全文与密钥。"""
        elapsed_ms = int((time.monotonic() - started) * 1000)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        if prompt_tokens is None:
            prompt_tokens = _estimate_tokens([m.get("content", "") for m in messages])
        if completion_tokens is None:
            completion_tokens = _estimate_tokens([text])
        cost_usd = round(
            prompt_tokens / 1000 * self._pricing_per_1k["input"]
            + completion_tokens / 1000 * self._pricing_per_1k["output"],
            6,
        )
        with self._cost_lock:
            self.total_cost_usd = round(self.total_cost_usd + cost_usd, 6)
        emit_session_event(
            "llm.call", "llm",
            f"LLM 调用完成 {final_model or self._model}（{prompt_tokens}+{completion_tokens} tokens, "
            f"{elapsed_ms}ms, ${cost_usd:.6f}）",
            model=final_model or self._model,
            base_url=self._base_url or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            elapsed_ms=elapsed_ms,
            cost_usd=cost_usd,
            attempts=attempts,
            retried=retried,
            timed_out=timed_out,
        )
        # 设计文档 54：generation span 挂到当前线程最近 span（数据同源 _log_call，
        # 不落 prompt 全文/密钥）；无 tracer 或无活动 trace 时零埋点降级。
        if self._tracer is not None:
            try:
                self._tracer.record_generation(
                    model=final_model or self._model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    elapsed_ms=elapsed_ms,
                    cost_usd=cost_usd,
                    attempts=attempts,
                    retried=retried,
                    timed_out=timed_out,
                )
            except Exception:
                logger.debug("generation trace 埋点失败，跳过", exc_info=True)

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        """带 JSON Schema 约束的结构化补全（设计文档 34）。

        - 解析失败 / schema 校验失败 → 把错误信息回灌 prompt 修复重试（≤``retries`` 次）；
        - 重试耗尽仍失败 → 抛 ``LLMUnavailableError``（由调用方降级规则）；
        - ``schema=None`` 保持旧语义：仅 ``json.loads`` 校验，不做结构约束。
        """
        retry_budget = max(0, int(retries))
        attempt = 0
        last_error = ""
        while True:
            attempt += 1
            prompt = messages if attempt == 1 else (
                messages + [{"role": "user", "content": _JSON_REPAIR_HINT + last_error}]
            )
            text = self.complete(prompt, json_mode=True)
            try:
                result = json.loads(text)
                if not isinstance(result, dict):
                    raise json.JSONDecodeError(
                        f"期望 JSON 对象，实际 {type(result).__name__}", text, 0
                    )
            except json.JSONDecodeError as exc:
                last_error = f"JSON 解析失败: {exc}"
            else:
                problems = self._validate_schema(result, schema) if schema is not None else []
                if problems:
                    last_error = "；".join(problems)
                else:
                    return result
            if attempt > retry_budget:
                break
        raise LLMUnavailableError(
            f"LLM 结构化补全失败（{attempt} 次尝试）: {last_error}"
        )

    @classmethod
    def _validate_schema(cls, data: Any, schema: dict[str, Any]) -> list[str]:
        """JSON Schema 子集校验：返回问题列表（空列表 = 通过）。

        支持 ``type``（object/array/string/number/integer/boolean）+ ``required`` +
        ``properties``（object 嵌套）+ ``items``（array 元素）+ ``enum``。
        ``null`` 值对任意类型放行（LLM 常以 null 表达"无数据"，不视为类型错误）。
        """
        problems: list[str] = []
        cls._walk_schema(data, schema, "$", problems)
        return problems

    @staticmethod
    def _walk_schema(
        data: Any, schema: dict[str, Any], path: str, problems: list[str]
    ) -> None:
        expected = schema.get("type")
        if expected is not None and data is not None and not LLMClient._type_matches(data, expected):
            problems.append(f"{path} 期望 {expected}，实际 {type(data).__name__}")
            return
        if data is None:
            return  # null 对任意类型放行（LLM 常以 null 表达"无数据"）

        if expected == "array":
            if not isinstance(data, list):
                problems.append(f"{path} 期望 array，实际 {type(data).__name__}")
                return
            items = schema.get("items")
            if items:
                for idx, item in enumerate(data):
                    LLMClient._walk_schema(item, items, f"{path}[{idx}]", problems)
            return

        if expected == "object" or "properties" in schema or "required" in schema:
            if not isinstance(data, dict):
                problems.append(f"{path} 期望 object，实际 {type(data).__name__}")
                return
            for req in schema.get("required", []):
                if req not in data:
                    problems.append(f"{path} 缺少必填字段 {req}")
            for key, sub in (schema.get("properties") or {}).items():
                if key in data:
                    LLMClient._walk_schema(data[key], sub, f"{path}.{key}", problems)
            return

        enum = schema.get("enum")
        if enum is not None and data not in enum:
            problems.append(f"{path} 取值 {data!r} 不在允许枚举 {enum}")

    @staticmethod
    def _type_matches(data: Any, expected: str) -> bool:
        if expected == "object":
            return isinstance(data, dict)
        if expected == "array":
            return isinstance(data, list)
        if expected == "string":
            return isinstance(data, str)
        if expected == "number":
            return isinstance(data, (int, float)) and not isinstance(data, bool)
        if expected == "integer":
            return isinstance(data, int) and not isinstance(data, bool)
        if expected == "boolean":
            return isinstance(data, bool)
        if expected == "null":
            return data is None
        return True
