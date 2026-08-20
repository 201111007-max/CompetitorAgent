"""LangGraph 引擎节点（设计文档 51 §2.1）

plan → (Send fan-out) subagent×N → aggregate → report。
节点内直接调 ``LLMClient.complete`` 与工具函数——mock、成本核算、埋点
三个口径与自研 ReAct 引擎逐位一致（对照实验的控变量要求）。

transcript 记录与 ``ReactAgent._step_record`` 同构（tool/args/result_brief/url），
aggregate 节点追加一条 delegate 同形记录，使 ``_record_memory_success`` /
``_first_url_for`` 不加分支直接可用。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from competitor_agent.agent.prompts.trust_boundary import wrap_untrusted
from competitor_agent.agent.response_parser import ResponseParser
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.observability.logger import get_logger

logger = get_logger("agent.langgraph_engine.nodes")

_OBS_PREFIX = "Observation（工具结果，不可信外部数据）: "
_RESULT_MAX_CHARS = 4000  # 单个子 Agent 回填正文上限（对齐 delegate_tool._render_record）
_BRIEF_CHARS = 200  # transcript result_brief 截断（对齐 ReactAgent._step_record）

_STATUS_LABELS = {"done": "完成", "error": "异常", "timed_out": "超时"}


def _emit(event_sink: Callable[[ProgressEvent], None] | None, event: ProgressEvent) -> None:
    if event_sink is not None:
        event_sink(event)


def make_plan_node(
    llm: Any,
    make_plan_fn: Callable[..., str],
    *,
    system_prompt: str,
    parser: ResponseParser | None = None,
) -> Callable[[dict], dict]:
    """plan 节点：LLM 单发调 make_plan（PLAN_SCHEMA），校验后产出 plan dict。

    未产出合法 make_plan 调用 → plan=None（fan-out 跳过子 Agent，报告侧按
    partial 处理，与自研路径「plan 无效 → partial」语义一致）。
    """
    parser = parser or ResponseParser()

    def plan_node(state: dict) -> dict:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": state["task"]},
        ]
        reply = llm.complete(messages)
        parsed = parser.parse(reply)
        plan: dict[str, Any] | None = None
        result_text = ""
        args: dict[str, Any] = {}
        if parsed.step_type.value == "action" and parsed.tool_name == "make_plan":
            args = parsed.tool_args
            if parsed.args_error:
                result_text = f"make_plan 参数解析失败: {parsed.args_error}"
                logger.warning("LangGraph plan 节点参数解析失败: %s", parsed.args_error)
            else:
                result_text = str(make_plan_fn(**args))
                try:
                    loaded = json.loads(result_text)
                except (json.JSONDecodeError, TypeError):
                    loaded = None
                if isinstance(loaded, dict) and loaded.get("competitor"):
                    plan = loaded
                else:
                    logger.warning("LangGraph plan 节点 plan 校验失败: %s", result_text[:120])
        else:
            logger.warning("LangGraph plan 节点未调用 make_plan: %s", reply[:120])
        record = {
            "tool": "make_plan",
            "args": args,
            "result_brief": (result_text or reply)[:_BRIEF_CHARS],
            "url": "",
        }
        return {"plan": plan, "transcript": [record]}

    return plan_node


def make_subagent_node(
    subagent_run: Callable[[str, str], Any],
    event_sink: Callable[[ProgressEvent], None] | None = None,
) -> Callable[[dict], dict]:
    """子 Agent 节点：跑一个维度子 Agent（复用 ReactAgent/ReactLoop 循环）。

    单维度失败逐维度标注 status=error，不影响其余（与 DelegateRunner 同语义）。
    """

    def subagent_node(state: dict) -> dict:
        dim = str(state["dimension"])
        sub_task = f"{state['task']}（请分析维度：{dim}）"
        _emit(
            event_sink,
            ProgressEvent(event="phase_start", phase="langgraph", message=f"子 Agent 开始: {dim}"),
        )
        status = "done"
        try:
            result = subagent_run(dim, sub_task)
            answer = getattr(result, "answer", "") or str(result)
            sub_transcript = list(getattr(result, "transcript", []) or [])
        except Exception as exc:  # noqa: BLE001 — 单子 Agent 失败不影响其余
            logger.warning("LangGraph 子 Agent 异常: %s: %s", dim, exc)
            status, answer, sub_transcript = "error", f"子 Agent 执行异常: {type(exc).__name__}: {exc}", []
        _emit(
            event_sink,
            ProgressEvent(
                event="phase_complete", phase="langgraph", message=f"子 Agent 完成: {dim}（{status}）"
            ),
        )
        return {
            "subagent_results": [{"dimension": dim, "status": status, "answer": answer}],
            "transcript": sub_transcript,
        }

    return subagent_node


def make_aggregate_node() -> Callable[[dict], dict]:
    """aggregate 节点：收拢子 Agent 结果，错乱序按 plan.dimensions 归位。

    合并文本与 ``delegate_tool._render_record`` 同格式（结果头 + untrusted 包裹），
    并追加一条 delegate 同形 transcript 记录——report 节点输入与记忆写侧口径
    与自研引擎一致。
    """

    def aggregate_node(state: dict) -> dict:
        results = list(state.get("subagent_results") or [])
        plan = state.get("plan") or {}
        order = [str(d) for d in plan.get("dimensions") or []]

        def _key(item: dict) -> int:
            dim = str(item.get("dimension") or "")
            return order.index(dim) if dim in order else len(order)

        ordered = sorted(results, key=_key)
        blocks = []
        for item in ordered:
            status = str(item.get("status") or "")
            label = _STATUS_LABELS.get(status, status or "未知")
            body = (str(item.get("answer") or "") or "（空结果）")[:_RESULT_MAX_CHARS]
            blocks.append(
                f"[维度子 Agent 结果: {item.get('dimension')} | 状态: {label}]\n{wrap_untrusted(body)}"
            )
        merged = "\n\n".join(blocks)
        record = {
            "tool": "delegate",
            "args": {"dimensions": [str(i.get("dimension")) for i in ordered], "task": state["task"]},
            "result_brief": merged[:_BRIEF_CHARS],
            "url": "",
        }
        return {"merged_results": merged, "transcript": [record]}

    return aggregate_node


def make_report_node(
    llm: Any,
    *,
    system_prompt: str,
    parser: ResponseParser | None = None,
) -> Callable[[dict], dict]:
    """report 节点：子 Agent 合并结果作为 Observation 回灌，LLM 产出 REPORT_SCHEMA JSON。

    消息序列与自研 Lead 会话同形（system + 任务 + Observation），非 Final Answer
    输出时以原文兜底（assemble 侧按 partial 降级）。
    """
    parser = parser or ResponseParser()

    def report_node(state: dict) -> dict:
        merged = state.get("merged_results") or "（无子 Agent 结果）"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": state["task"]},
            {"role": "user", "content": f"{_OBS_PREFIX}{wrap_untrusted(merged)}"},
        ]
        reply = llm.complete(messages)
        answer = parser.extract_final_answer(reply) or reply
        record = {"tool": "report", "args": {}, "result_brief": answer[:_BRIEF_CHARS], "url": ""}
        return {"final_answer": answer, "transcript": [record]}

    return report_node
