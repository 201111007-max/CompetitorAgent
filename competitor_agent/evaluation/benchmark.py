"""Benchmark — 评测基准（3.5）— 真实执行版

设计文档 03（benchmark_design.md）：修正 benchmark 读手写 fixture 的 prediction 自证问题。
- Benchmark.run() 对每个评测用例真实调用 `CompetitorAnalysisAPI.analyze()`（真实 LLM 或 mock LLM），
  从真实报告提取可比对字段，与标注 ground_truth 计算字段准确率 / F1 / 幻觉率、工具选择 / 成本效率。
- 确定性：采集层注入 `BenchmarkExtractor`（固定网页内容 + 首候选源可模拟故障），
  LLM 层支持 `--llm mock|real`（CI 用 mock 断言链路正确，本地/发布用 real 评估真实质量）。
- 策略指标从真实证据（evidence.url）反推：系统实际选中/降级到的 URL，成本 = 尝试源数 × 单次成本。

每个分数必须附带 harness 版本号（benchmark + subset + harness），防"上个数字误导"。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from competitor_agent.collector.web_extractor import WebExtractor
from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.domain_types.enums import ObservationStatus
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.evaluation.accuracy_eval import AccuracyEvaluator, AccuracyMetrics, EvalCase
from competitor_agent.evaluation.behavior_eval import (
    BehaviorMetrics,
    FoldRecallEvaluator,
    RecoveryEvaluator,
    RetrievalEvaluator,
)
from competitor_agent.evaluation.failure import FailureRecord, FailureType, classify_case
from competitor_agent.evaluation.strategy_eval import StrategyCase, StrategyEvaluator, StrategyMetrics
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.llm.client import LLMClient, ToolCallReply
from competitor_agent.memory.timeline_memory import TimelineMemory
from competitor_agent.secret_vault import get_reports_dir

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "evaluation" / "fixtures"

ACCURACY_FIXTURE = "accuracy_cases.json"
STRATEGY_FIXTURE = "strategy_cases.json"

# 评测 harness 版本：分数 = benchmark + subset + harness。任何评测输出必须带此版本号。
# 0.4.0 → 0.5.0：新增失败类型分类与聚合（设计文档 31）。
# 0.5.0 → 0.6.0：新增真实 LLM 评测报告字段（llm_mode / cost_usd / per_case_cost，设计文档 37）。
# 0.6.0 → 0.7.0：主路径 ReAct 化（设计文档 47/49）——mock LLM 改 ReAct-scripted
#   （make_plan → delegate → 子 Agent web_extract → Final Answer REPORT_SCHEMA），
#   门禁基于多 Agent 链路真实输出重定。
# 0.7.0 → 0.8.0：协议对照实验（native 默认，门禁对默认 native 重定，设计文档 53）。
# 0.8.0 → 0.9.0：删除文本 ReAct 协议，只保留 function calling（设计文档 60）——
#   mock 单形态、无 --protocol/对照表，门禁对唯一协议重定。
# 0.9.0 → 0.10.0：设计文档 62 全链路编排收敛——候选子 Agent 注册（competitor 命名空间）、
#   delegate 候选委派、aggregate_report 聚合工具、统一 run() 入口、删 execution.mode。
# 0.10.0 → 0.11.0：run() 单 Lead 统一（设计文档 62 §6 M3/M4）——mock 增 DISCOVERY/COMPARE
#   ReAct-scripted 分支（make_plan(competitors+resolution) → web_search_candidates →
#   delegate(候选) → aggregate_report → Final comparison JSON）；候选子 Agent 确定性返回
#   标准多维度 dimensions[]；Lead 按 resolution 分型收尾。
HARNESS_VERSION = "0.11.0"

# 门禁阈值单一来源（设计文档 55 M1）：--gate CLI、test_benchmark_integration、
# test_behavior_eval 全部引用本组常量，不新造第二份数值。
# 口径：field_accuracy / hallucination / tool_selection / trace（benchmark_design §5/§8）
# + 行为门禁（设计文档 42：自恢复率下限 + hybrid 不劣于 lexical）。
GATE_FIELD_ACCURACY_MIN = 0.90
GATE_HALLUCINATION_MAX = 0.05
GATE_TOOL_SELECTION_MIN = 0.85
GATE_TRACE_COMPLETENESS = 1.0
GATE_RECOVERY_RATE_MIN = 0.9
# 设计文档 56 M3：折叠后重复抓取门禁（可逆压缩闭环：取回替代重抓）
GATE_REFETCH_AFTER_FOLD_MAX = 0

# 单次采集/工具的估算成本（与主流程 IterationBudget 单次 0.01 对齐）
UNIT_COST = 0.01

# 维度 → 默认字段抽取方式（设计文档 §3.1：extract_prediction 按维度抽取可比对字段）
# 设计文档 29：扩展 ecosystem / sentiment / roadmap（timeline）三维度覆盖
DIMENSION_KINDS: dict[str, str] = {
    "pricing": "plan_price",
    "feature": "feature_present",
    "performance": "benchmark_score",
    "ecosystem": "ecosystem_signal",
    "sentiment": "sentiment_signal",
    "roadmap": "timeline_event",
}


# ── fixture 用例数据模型 ──────────────────────────────────────────────


@dataclass
class AccuracyCase:
    """真实执行版字段评测用例：只含 task + ground_truth + 确定性采集配置"""
    task: str
    competitor: str
    dimension: str
    ground_truth: dict[str, Any]
    case_id: str = ""
    tags: list[str] = field(default_factory=list)
    mode: str = "single"  # single / team：走单 Agent 或多 Agent 流水线
    page: str = ""  # 固定网页内容（确定性采集）
    fail_urls: list[str] = field(default_factory=list)


@dataclass
class BenchStrategyCase:
    """真实执行版策略评测用例：校验系统实际选源/降级是否命中标注最优源"""
    task: str
    competitor: str
    dimension: str
    best_url: str  # 该任务应首选（或降级后应命中）的源 URL
    case_id: str = ""
    tags: list[str] = field(default_factory=list)
    mode: str = "single"
    page: str = ""
    fail_urls: list[str] = field(default_factory=list)  # 模拟首候选源故障


@dataclass
class BenchmarkReport:
    accuracy: AccuracyMetrics = field(default_factory=AccuracyMetrics)
    strategy: StrategyMetrics = field(default_factory=StrategyMetrics)
    n_cases: int = 0
    loaded_fixtures: list[str] = field(default_factory=list)
    harness_version: str = HARNESS_VERSION
    trace_completeness: float = 0.0  # 有完整 trace（真实证据）的 case / 总 case
    confusion_matrix: dict[str, dict[str, int]] = field(default_factory=dict)
    # 设计文档 29：按维度拆分指标（生态/口碑/时间线覆盖盲区可独立门禁）
    accuracy_by_dimension: dict[str, float] = field(default_factory=dict)
    hallucination_by_dimension: dict[str, float] = field(default_factory=dict)
    # 设计文档 31：失败类型统计——{type: count} + 逐条样本
    failure_stats: dict[str, int] = field(default_factory=dict)
    failure_records: list[dict[str, Any]] = field(default_factory=list)
    # 设计文档 37：真实 LLM 评测报告——模式标注 + 成本核算 + 成本护栏中止
    llm_mode: str = "mock"  # "mock" / "real"
    cost_usd: float = 0.0  # 累计 LLM 调用成本（复用 llm._log_call 的 cost_usd）
    per_case_cost: dict[str, float] = field(default_factory=dict)  # case_id/task → cost
    cost_limit_usd: float | None = None  # 真实评测成本护栏上限（None=不限）
    budget_aborted: bool = False  # 是否因成本护栏超限中止
    # 设计文档 42：行为级评测——工具自恢复率 + 检索命中率（hybrid vs lexical）
    behavior: BehaviorMetrics = field(default_factory=BehaviorMetrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness_version": self.harness_version,
            "n_cases": self.n_cases,
            "trace_completeness": self.trace_completeness,
            "fixtures": self.loaded_fixtures,
            "llm_mode": self.llm_mode,
            "cost_usd": self.cost_usd,
            "cost_limit_usd": self.cost_limit_usd,
            "budget_aborted": self.budget_aborted,
            "per_case_cost": self.per_case_cost,
            "accuracy": {
                "field_accuracy": self.accuracy.field_accuracy,
                "hallucination_rate": self.accuracy.hallucination_rate,
                "f1": self.accuracy.f1,
                "hallucination_instances": self.accuracy.hallucination_instances,
                "per_case": self.accuracy.per_case,
            },
            "accuracy_by_dimension": self.accuracy_by_dimension,
            "hallucination_by_dimension": self.hallucination_by_dimension,
            "strategy": {
                "tool_selection_accuracy": self.strategy.tool_selection_accuracy,
                "cost_efficiency": self.strategy.cost_efficiency,
                "avg_source_rank": self.strategy.avg_source_rank,
            },
            "confusion_matrix": self.confusion_matrix,
            "failure_stats": self.failure_stats,
            "failure_records": self.failure_records,
            "behavior": {
                "react_recovery_rate": self.behavior.react_recovery_rate,
                "recovery_n": self.behavior.recovery_n,
                "retrieval_hit_hybrid": self.behavior.retrieval_hit_hybrid,
                "retrieval_hit_lexical": self.behavior.retrieval_hit_lexical,
                "retrieval_n": self.behavior.retrieval_n,
                "refetch_after_fold": self.behavior.refetch_after_fold,
            },
        }


# ── 确定性采集（设计文档 §3.4：mock 采集保证可复现） ─────────────────


class BenchmarkExtractor(WebExtractor):
    """确定性采集器：固定网页内容；fail_urls 中的 URL 抛故障（模拟首候选源失败）。

    供 BenchmarkMockLLM / 规则分析器消费同一份固定内容，保证 CI 无网络、无 Key 可复现。
    继承 WebExtractor 以满足 API ``extractor`` 参数（共享 fetch 契约），仅重写确定性取数。
    """

    source_name = "web_extractor"

    def __init__(self, page: str = "", fail_urls: set[str] | None = None) -> None:
        self._page = page
        self._fail_urls = frozenset(fail_urls or ())

    def fetch(self, gap: object, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url", ""))
        if url in self._fail_urls:
            raise DataSourceUnavailableError(f"benchmark 模拟抓取失败（首候选源）: {url}")
        text = self._page or f"{getattr(gap, 'field', 'content')} content of {url}"
        evidence = SourceEvidence(
            source_name=self.source_name,
            url=url,
            content_hash=str(abs(hash(text))),
            trust_level=0.9,
        )
        return Observation(
            gap_field=getattr(gap, "field", ""),
            source=self.source_name,
            raw_text=text,
            evidence=evidence,
            status=ObservationStatus.OK if len(text) > 5 else ObservationStatus.DEGRADED,
        )


# ── 确定性 mock LLM（设计文档 §3.4：CI 用 mock 断言链路正确） ─────────


class BenchmarkMockLLM:
    """确定性 mock LLM：ReAct-scripted（设计文档 47/49）——在 Lead/子 Agent ReAct 会话上
    脚本化回放决策序列（make_plan → delegate → 子 Agent web_extract → Final Answer
    REPORT_SCHEMA/SUBAGENT_RESULT_SCHEMA JSON），CI 无 Key 仍可复现完整多 Agent 链路。

    设计文档 47：确定性从"规则版降级"转移到 mock 固定返回——解析/规划/分析/委派
    都走 LLM 版代码路径（make_plan 校验、delegate 后台并发、react_report 组装），
    确定性由 mock 在 ReAct 会话上"固定脚本化决策"承担：
    - 任务解析 prompt → 从任务文本提取竞品/分辨率（mock 即固定 oracle，非主路径规则）；
    - Lead 会话（系统提示含 "Lead Agent"）→ make_plan → delegate → Final Answer
      REPORT_SCHEMA JSON（从 delegate 回填块聚合各子 Agent 结果）；
    - 子 Agent 会话（系统提示含 "维度子 Agent"）→ web_extract（首选源失败则回退
      best_url）→ Final Answer SUBAGENT_RESULT_SCHEMA JSON（按维度抽取固定页面）；
    - 历史分析 prompt（"定价"/"功能"/... 标记）→ 维持"按维度抽取规范化 JSON"兼容分支。
    """

    _PLAN_RE = re.compile(
        r"(?P<name>[^\s$][^$\n]{0,30}?)\s+\$(?P<price>\d+(?:\.\d+)?)\s*(?:/|per\s)?"
        r"(?P<period>month|mo|user|seat|year|hour)?",
        re.IGNORECASE,
    )
    _FEATURE_MARKERS = (
        "support", "integration", "cli", "agent", "terminal", "multimodal",
        "rag", "mcp", "code", "review", "deploy", "token",
    )
    # 生态 / 口碑信号标记（对齐 analyzer 的 prompt 契约，保证确定性）
    _IDE_MARKERS = ("vscode", "jetbrains", "terminal")
    _PLUGIN_MARKERS = ("plugin", "extension", "marketplace")
    _POSITIVE_MARKERS = ("love", "great", "awesome", "fast", "recommend", "best", "好用", "好评", "推荐", "喜欢")
    _NEGATIVE_MARKERS = ("bug", "slow", "bad", "terrible", "crash", "worse", "难用", "差评", "吐槽", "失望", "贵", "限制")
    _RAG_MARKER = "[知识库参考片段"
    _MEMORY_MARKER = "[历史经验参考"  # 设计文档 35：记忆召回块，同样不影响 mock 抽取
    # 任务解析 mock 的分辨率推断（原规则逻辑移入 mock 作为固定 oracle）
    _DISCOVERY_MARKERS = (
        "所有", "全部", "有哪些", "哪些", "盘点", "市场", "市面上", "现在市场上的",
        "帮我找", "帮我寻找", "discover", "find all", "list all",
    )
    _COMPARE_MARKERS = ("对比", "比较", "compare", "vs")

    def __init__(
        self,
        competitor: str = "",
        dimension: str = "",
        *,
        page: str = "",
        best_url: str = "",
        fail_urls: list[str] | None = None,
        no_tools: bool = False,
    ) -> None:
        """competitor/dimension 取自评测用例；page/best_url/fail_urls 供子 Agent 脚本化。

        - ``best_url``：应命中的来源 URL（strategy 用例标注最优源）；
        - ``fail_urls``：模拟首候选源故障的 URL（子 Agent 先试失败再回退 best_url）；
        - ``no_tools``：消融变体——Lead 只 make_plan 后直接 Final Answer（不委派/不采集）。
        """
        self._competitor = (competitor or "").strip()
        self._dimensions = [dimension] if dimension else []
        self._page = page or ""
        self._best_url = best_url or ""
        self._fail_urls = list(fail_urls or ())
        self._no_tools = no_tools
        self._parsed_competitors: list[str] = []
        self._parsed_dimensions: list[str] | None = None

    def complete(self, messages: list[dict[str, str]], model: str | None = None, **kwargs: Any) -> Any:
        """调用入口（设计文档 60：单协议）：``complete_with_tools`` 传 ``tools=`` →
        返回 ToolCallReply；``llm.complete``（任务解析/单发 JSON）返回文本。

        脚本化文本输出（Action/Args/Final Answer）由 ``_to_tool_reply`` 映射为等价
        tool_calls / 纯 content，同一脚本 fixture 可跑，CI 确定性不变。
        """
        text = self._complete_text(messages)
        if kwargs.get("tools"):
            return self._to_tool_reply(text)
        return text

    def _to_tool_reply(self, text: str) -> ToolCallReply:
        """把脚本化文本输出映射为 ToolCallReply（设计文档 53 Q3）。

        - ``Final Answer: <json>`` → 纯 content（无 tool_calls = 原生协议终止信号）;
        - ``Action: <name> / Args: <json>`` → ToolCall（scripts 同 fixture 一致性保持）。
        """
        from competitor_agent.llm.client import ToolCall, ToolCallReply

        if text.startswith("Final Answer: "):
            return ToolCallReply(content=text[len("Final Answer: "):])
        action = re.search(r"Action:\s*(\w+)", text)
        if not action:
            return ToolCallReply(content=text)
        arguments: dict[str, Any] = {}
        args_raw = re.search(r"Args:\s*(\{.*\})", text, re.DOTALL)
        if args_raw:
            try:
                parsed = json.loads(args_raw.group(1))
                if isinstance(parsed, dict):
                    arguments = parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return ToolCallReply(
            tool_calls=[ToolCall(id="call_0", name=action.group(1), arguments=arguments)]
        )

    @staticmethod
    def _first_call_url(call: Any) -> str:
        """从 native assistant 的 tool_call 提取 url（用于 _tried_urls 去重）。"""
        fn = call.get("function", {}) if isinstance(call, dict) else getattr(call, "function", {})
        raw = fn.get("arguments", "") if isinstance(fn, dict) else getattr(fn, "arguments", "")
        if isinstance(raw, dict):
            return str(raw.get("url") or "")
        try:
            parsed = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            return ""
        return str(parsed.get("url") or "") if isinstance(parsed, dict) else ""

    def _complete_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        if not messages:
            return "{}"
        system = messages[0].get("content", "")
        user = self._user_text(messages)
        if "语义解析器" in system:
            # 任务解析 prompt：从任务文本提取竞品 + 分辨率（mock 固定 oracle）
            return self._parse_task(user)
        if "Lead Agent" in system:
            # 主路径 Lead 会话（先于"维度子 Agent"判定——Lead 提示也含该词）
            return self._lead_step(messages)
        if "维度子 Agent" in system:
            # 维度子 Agent 会话（独立完整 agent 自己的 ReAct 会话）
            return self._subagent_step(messages, user, system)
        if "候选竞品「" in system:
            # 候选竞品子 Agent（设计文档 62 §3.4）：标准多维度 dimensions[]（REPORT_SCHEMA）
            return self._candidate_subagent_step(messages, user, system)
        if "战略规划器" in system:
            # 设计文档 47 规划 prompt：返回合法 PLAN_SCHEMA（competitor 优先取自用例）
            competitor = self._competitor or self._infer_competitor(user)
            return json.dumps({"competitor": competitor, "dimensions": self._dimensions})
        if "竞品发现助手" in system:
            # 竞品去重 prompt：原样回显候选（确定性去重 = 保序直通）
            try:
                data = json.loads(user)
            except (json.JSONDecodeError, TypeError):
                return "[]"
            return json.dumps(data, ensure_ascii=False) if isinstance(data, list) else "[]"
        if "路线图" in system:
            return json.dumps(
                {"summary": "路线图数据有限", "details": {"releases": [], "upcoming": []}, "confidence": 0.3}
            )
        if "定价" in system:
            plans = self._plans(user)
            return json.dumps(
                {"summary": f"检测到 {len(plans)} 个定价条目", "details": {"plans": plans}, "confidence": 0.8}
            )
        if "功能" in system:
            features = self._features(user)
            return json.dumps(
                {"summary": f"检测到 {len(features)} 个功能相关描述", "details": {"features": features}, "confidence": 0.8}
            )
        if "基准" in system:
            benchmarks = self._benchmarks(user)
            return json.dumps(
                {"summary": f"检测到 {len(benchmarks)} 条性能记录", "details": {"benchmarks": benchmarks}, "confidence": 0.8}
            )
        if "生态" in system:
            details = self._ecosystem(user)
            return json.dumps(
                {"summary": f"生态盘点：MCP {len(details['mcp_servers'])} 个、插件 {details['plugins']['count']} 条、IDE {', '.join(details['ide_support']) or '未知'}",
                 "details": details, "confidence": 0.7}
            )
        if "口碑" in system:
            details, confidence = self._sentiment(user)
            return json.dumps(
                {"summary": details["verdict"], "details": details, "confidence": confidence}
            )
        return json.dumps({"summary": user[:120], "details": {}, "confidence": 0.5})

    @classmethod
    def _registry_competitors(cls, text: str) -> list[str]:
        """任务文本中的注册表竞品名（按任务中首次出现位置排序、去重，mock 固定 oracle）。

        按出现位置排序贴近真实 LLM parse 的输入顺序（多竞品对比按用户列举次序），
        而非注册表字典序——保证 compare("Cursor","Windsurf","Copilot") 输出与输入同序。
        """
        from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY

        lowered = text.lower()
        found: list[tuple[int, str]] = []
        for canon, competitor in COMPETITOR_REGISTRY.items():
            positions: list[int] = []
            if canon in lowered:
                positions.append(lowered.index(canon))
            for alias in competitor.aliases:
                if alias in lowered:
                    positions.append(lowered.index(alias))
            if positions:
                found.append((min(positions), competitor.name))
        found.sort(key=lambda item: item[0])
        return [name for _, name in found]

    def _infer_competitor(self, text: str) -> str:
        """规划 mock：注册表命中优先；否则取任务段首 ASCII 词作为规范名（mock oracle）。

        规划 prompt 已含"用户任务：<task>"，只从任务段推断，避免被 prompt 指令文本污染。
        """
        from competitor_agent.core.competitor_registry import canonicalize

        marker = "用户任务："
        idx = text.find(marker)
        if idx >= 0:
            text = text[idx + len(marker):]
        names = self._registry_competitors(text)
        if names:
            return names[0]
        ascii_parts = "".join(c for c in text if c.isascii() and (c.isalnum() or c.isspace()))
        return canonicalize(ascii_parts) or "unknown"

    @staticmethod
    def _user_text(messages: list[dict[str, str]]) -> str:
        """取最后一条 user 消息，剥离注入尾巴（RAG/记忆参考块不影响 mock 抽取）。"""
        user = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user = message.get("content", "")
                break
        idx = user.find(BenchmarkMockLLM._RAG_MARKER)
        if idx >= 0:
            return user[:idx]
        idx = user.find(BenchmarkMockLLM._MEMORY_MARKER)
        return user[:idx] if idx >= 0 else user

    # ── ReAct-scripted 主路径（设计文档 49 §3.5）────────────────────────

    def _parse_task(self, user: str) -> str:
        """任务解析 prompt：提取竞品 + 分辨率（mock 固定 oracle），并缓存供 Lead 规划复用。"""
        competitors = self._registry_competitors(user)
        self._parsed_competitors = list(competitors)
        self._parsed_dimensions = None
        resolution = "compare" if len(competitors) >= 2 else (
            "discovery" if any(m in user.lower() for m in self._DISCOVERY_MARKERS) else "registry"
        )
        return json.dumps(
            {"resolution": resolution, "competitors": competitors, "dimensions": None, "custom_sources": {}}
        )

    def _lead_step(self, messages: list[dict[str, str]]) -> str:
        """Lead 会话状态机：make_plan → (registry 维度委派 | DISCOVERY/COMPARE 编排) → Final Answer。

        阶段由会话消息内容推导（不依赖跨调用持久状态）：共享同一 mock 实例的
        并行 compare / 复用分析中，多个 analyze 同任务时会话内容各自独立，
        ``_convs`` 持久状态会在不同 analyze 运行间泄漏（首步跳过 make_plan →
        plan-first 回灌 → 预算耗尽）。``no_tools`` 消融变体：make_plan 后直接
        Final Answer（无工具循环，测委派价值）。

        设计文档 62 §6 M3：registry（单竞品）走 make_plan → delegate(维度) → Final Answer
        REPORT_SCHEMA；compare/discovery 走同一单 Lead loop 内的 ReAct-scripted 编排
        （web_search_candidates → delegate(候选) → aggregate_report → Final comparison
        JSON），由 ``_orchestration_step`` 驱动（Obs 回填即阶段信号）。
        """
        obs = self._last_observation(messages)
        if self._no_tools:
            return self._lead_final(messages)
        if not obs:
            return self._make_plan_action(messages)
        if self._session_resolution(messages) in ("compare", "discovery"):
            return self._orchestration_step(messages)
        if "维度子 Agent 结果" in obs:
            return self._lead_final(messages)
        return self._delegate_action(messages)

    def _lead_task_competitor(self, messages: list[dict[str, str]]) -> str:
        """本会话竞品：用例标注优先，否则从任务文本解析。

        不读共享 ``_parsed_competitors``——并行 compare 共享同一 mock 实例时，
        多会话并发 parse 会互相覆盖该字段（各 Lead 误用他人竞品）。
        """
        if self._competitor:
            return self._competitor
        task = self._task_text(messages)
        names = self._registry_competitors(task)
        return names[0] if names else self._infer_competitor(task)

    def _make_plan_action(self, messages: list[dict[str, str]]) -> str:
        from competitor_agent.agent.react_schemas import DIMENSIONS

        dimensions = self._dimensions or self._parsed_dimensions or list(DIMENSIONS)
        plan: dict[str, Any] = {
            "dimensions": dimensions,
            "budget": {"max_steps": 8},
            "custom_sources": {},
        }
        resolution = self._session_resolution(messages)
        if resolution in ("compare", "discovery"):
            # 设计文档 62 §3.1：多竞品 plan 用 competitors + resolution + scheduling
            plan["resolution"] = resolution
            plan["competitors"] = self._session_competitors(messages)
            plan["scheduling"] = {"parallel": True, "reason": "候选多需并行"}
        else:
            plan["competitor"] = self._lead_task_competitor(messages)
        return (
            "Thought: 规划分析策略\nAction: make_plan\n"
            f"Args: {json.dumps({'plan_json': plan}, ensure_ascii=False)}"
        )

    def _delegate_action(self, messages: list[dict[str, str]]) -> str:
        from competitor_agent.agent.react_schemas import DIMENSIONS

        dimensions = self._dimensions or self._parsed_dimensions or list(DIMENSIONS)
        # task 透传会话任务：子 Agent 会话标识据此区分（并行 compare 隔离状态）
        task = self._task_text(messages)
        return (
            "Thought: 委派维度子 Agent 并行采集\nAction: delegate\n"
            f"Args: {json.dumps({'dimensions': dimensions, 'task': task}, ensure_ascii=False)}"
        )

    def _lead_final(self, messages: list[dict[str, str]]) -> str:
        """Final Answer：把 delegate 回填块中各子 Agent 结果聚合成 REPORT_SCHEMA JSON。"""
        obs = self._last_observation(messages)
        dimensions: list[dict[str, Any]] = []
        for name, body in self._subagent_blocks(obs):
            item = self._extract_json_block(body)
            if not isinstance(item, dict) or str(item.get("dimension") or "") != name:
                item = {
                    "dimension": name,
                    "summary": f"{name} 分析完成（子 Agent 结果未解析）",
                    "details": {},
                    "confidence": 0.5,
                }
            dimensions.append(item)
        competitor = self._lead_task_competitor(messages)
        return "Final Answer: " + json.dumps(
            {"competitor": competitor, "dimensions": dimensions}, ensure_ascii=False
        )

    # ── DISCOVERY/COMPARE 单 Lead 编排（设计文档 62 §6 M3）──────────────────

    def _session_resolution(self, messages: list[dict[str, str]]) -> str:
        """本会话的编排分辨率（mock 固定 oracle）：注册表≥2 → compare；发现标记 → discovery；否则 registry。"""
        user = self._task_text(messages)
        competitors = self._registry_competitors(user)
        if len(competitors) >= 2:
            return "compare"
        if any(m in user.lower() for m in self._DISCOVERY_MARKERS):
            return "discovery"
        return "registry"

    def _session_competitors(self, messages: list[dict[str, str]]) -> list[str]:
        """本会话任务文本中的注册表竞品（保序去重）；DISCOVERY 候选未知时为 []。"""
        return self._registry_competitors(self._task_text(messages))

    def _orchestration_step(self, messages: list[dict[str, str]]) -> str:
        """compare/discovery 单 Lead loop 的 ReAct-scripted 编排状态机（Obs 即阶段信号）。

        make_plan(plan JSON) → discovery: web_search_candidates(候选清单) → delegate(候选) →
        aggregate_report → Final comparison JSON；compare 跳过枚举直接 delegate(已知竞品)。
        工具结果经 ``wrap_untrusted`` 包裹（设计文档 06/41），先剥壳再判断候选清单形态。
        """
        obs = self._last_observation(messages)
        stripped = self._page_from_observation(obs).strip()
        if "aggregate_report 决策" in obs or "未发现候选竞品" in obs:
            # 聚合后收尾 / 候选为空 → 优雅收尾（空矩阵 + 结论，不无限重试）
            return self._comparison_final(messages)
        if "[维度子 Agent 结果" in obs:
            return self._aggregate_action(messages)
        if stripped.startswith("["):
            # web_search_candidates 回填的候选清单 → delegate
            return self._delegate_candidates_action(messages, self._candidates_from_obs(stripped))
        if self._session_resolution(messages) == "discovery":
            return self._web_search_candidates_action(messages)
        return self._delegate_candidates_action(messages, self._session_competitors(messages))

    def _web_search_candidates_action(self, messages: list[dict[str, str]]) -> str:
        task = self._task_text(messages)
        return (
            "Thought: 联网枚举候选竞品清单\nAction: web_search_candidates\n"
            f"Args: {json.dumps({'scope': task}, ensure_ascii=False)}"
        )

    def _delegate_candidates_action(self, messages: list[dict[str, str]], candidates: list[str]) -> str:
        task = self._task_text(messages)
        return (
            "Thought: 委派候选子 Agent 并行分析\nAction: delegate\n"
            f"Args: {json.dumps({'dimensions': candidates, 'task': task, 'parallel': True, 'reason': '候选多需并行'}, ensure_ascii=False)}"
        )

    def _aggregate_action(self, messages: list[dict[str, str]]) -> str:
        kind = "compare" if self._session_resolution(messages) == "compare" else "position"
        return (
            "Thought: 聚合候选结论，产出市场格局核心结论\nAction: aggregate_report\n"
            f"Args: {json.dumps({'parts': '候选分析完成，回填各候选维度结论', 'kind': kind}, ensure_ascii=False)}"
        )

    def _comparison_final(self, messages: list[dict[str, str]]) -> str:
        """Final Answer：comparison JSON（Lead 结论段，矩阵由组装器渲染）。"""
        from competitor_agent.agent.react_schemas import DIMENSIONS

        competitors = self._session_competitors(messages)
        if not competitors:
            conclusion = "未发现候选竞品（联网枚举无结果），请缩小或调整范围后再试。"
        else:
            conclusion = (
                "整体最佳 Cursor（best_per_dimension：pricing→Cursor、feature→Windsurf、"
                "performance→Cursor、ecosystem→Windsurf、sentiment→Cursor、roadmap→Windsurf）。"
                "趋势：AI 编辑器市场竞争加剧，生态与定价是主要分水岭；替代关系：Windsurf 与 "
                "Cursor 互为直接替代。"
            )
        return "Final Answer: " + json.dumps(
            {
                "competitors": competitors,
                "kind": "compare",
                "dimensions": list(DIMENSIONS),
                "conclusion": conclusion,
                "best_per_dimension": {"pricing": "cursor", "feature": "windsurf"},
                "gaps": [],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _candidates_from_obs(obs: str) -> list[str]:
        """从 web_search_candidates 的候选清单 Obs（JSON 列表）提取候选名。"""
        text = obs.strip()
        if not text.startswith("["):
            return []
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return []
        names: list[str] = []
        for item in data:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    names.append(name)
            elif isinstance(item, str) and item.strip():
                names.append(item)
        return names

    @staticmethod
    def _candidate_from_system(system: str) -> str:
        """从候选子 Agent 系统提示取候选竞品名：「分析候选竞品「cursor」」。"""
        import re as _re

        match = _re.search(r"分析候选竞品「([^」]+)」", system)
        return match.group(1) if match else ""

    def _candidate_url(self, candidate: str) -> str:
        """候选子 Agent 兜底抓取 URL（评测未标注 best_url 时，确定性可复现假源）。"""
        return self._best_url or f"https://example.com/{candidate}/home"

    def _candidate_subagent_step(self, messages: list[dict[str, str]], user: str, system: str) -> str:
        """候选子 Agent 状态机：web_extract → Final Answer 标准多维度 dimensions[]（REPORT_SCHEMA）。

        与维度子 Agent 同构（首步抓取候选官方页 → 收尾），但输出对齐 REPORT_SCHEMA 的
        ``{competitor, dimensions: [...]}``（逐维度条目）+ official_links，供聚合/组装引用。
        """
        candidate = self._candidate_from_system(system) or "unknown"
        tried = self._tried_urls(messages)
        last_obs = self._last_observation(messages)
        if not tried:
            return self._web_extract_action(self._candidate_url(candidate))
        if "抓取失败" in last_obs:
            url = self._candidate_url(candidate)
            if url not in tried:
                return self._web_extract_action(url)
        return self._candidate_subagent_final(candidate, messages, tried)

    def _candidate_subagent_final(self, candidate: str, messages: list[dict[str, str]], tried: list[str]) -> str:
        from competitor_agent.agent.react_schemas import DIMENSIONS

        page = self._page or self._page_from_observation(self._last_observation(messages))
        dims = [self._dimension_payload(dim, page, tried) for dim in DIMENSIONS]
        return "Final Answer: " + json.dumps(
            {
                "competitor": candidate,
                "dimensions": dims,
                "official_links": {"home": f"https://example.com/{candidate}"},
            },
            ensure_ascii=False,
        )

    def _subagent_step(self, messages: list[dict[str, str]], user: str, system: str) -> str:
        """子 Agent 会话状态机：web_extract（首候选源失败则回退 best_url）→ Final Answer。

        阶段由会话消息内容推导（``tried`` 从 assistant Action 的 Args URL 提取，
        不依赖跨调用持久状态）——共享 mock 实例的并行 compare 中多会话内容各自独立。
        独立 LLM 子 Agent 走与 Lead 相同的 ReAct 代码路径；本 mock 只负责确定性地
        脚本化工具选择与收尾 JSON（SUBAGENT_RESULT_SCHEMA）。
        """
        # 维度取系统提示（跨轮稳定）：后续轮的 user 是 Observation，不含维度标记
        dim = self._subagent_dimension_from_system(system) or self._subagent_dimension(user)
        tried = self._tried_urls(messages)
        last_obs = self._last_observation(messages)
        if not tried:
            # 首步：模拟"首候选源"——标注 fail_urls 先试故障源（降级恢复路径）；
            # 否则首选最优源 best_url（rumor 低信任源拒绝，改用官方兜底 URL）
            return self._web_extract_action(self._preferred_url(dim))
        if "抓取失败" in last_obs:
            # 上一步失败 → 回退到标注最优源/兜底 URL
            url = self._best_url or self._target_url(dim)
            if url not in tried:
                return self._web_extract_action(url)
        return self._subagent_final(dim, tried, last_obs)

    def _subagent_final(self, dim: str, tried: list[str], last_obs: str) -> str:
        page = self._page or self._page_from_observation(last_obs)
        return "Final Answer: " + json.dumps(
            self._dimension_payload(dim, page, tried), ensure_ascii=False
        )

    def _dimension_payload(self, dim: str, page: str, tried: list[str]) -> dict[str, Any]:
        """单维度结果载荷（SUBAGENT_RESULT_SCHEMA）：维度子 Agent 与候选子 Agent 共用。"""
        if dim == "pricing":
            plans = self._plans(page)
            details: dict[str, Any] = {"plans": plans}
            summary = f"检测到 {len(plans)} 个定价条目"
            confidence = 0.8
        elif dim == "feature":
            features = self._features(page)
            details = {"features": features}
            summary = f"检测到 {len(features)} 个功能相关描述"
            confidence = 0.8
        elif dim == "performance":
            benchmarks = self._benchmarks(page)
            details = {"benchmarks": benchmarks}
            summary = f"检测到 {len(benchmarks)} 条性能记录"
            confidence = 0.8
        elif dim == "ecosystem":
            details = self._ecosystem(page)
            summary = (
                f"生态盘点：MCP {len(details['mcp_servers'])} 个、"
                f"插件 {details['plugins']['count']} 条、IDE {', '.join(details['ide_support']) or '未知'}"
            )
            confidence = 0.7
        elif dim == "sentiment":
            details, confidence = self._sentiment(page)
            summary = details["verdict"]
        elif dim == "roadmap":
            details = {"events": [], "releases": [], "upcoming": []}
            summary = "路线图数据有限（首轮无基线，不产生时间线事件）"
            confidence = 0.3
        else:
            details, summary, confidence = {}, "", 0.5
        return {
            "dimension": dim,
            "summary": summary,
            "details": details,
            "confidence": confidence,
            # 证据只含成功来源（最后一次成功抓取的 URL），不含失败的首候选源
            "evidence_urls": list(tried[-1:]),
        }

    def _preferred_url(self, dim: str) -> str:
        """子 Agent 首选源：标注 fail_urls 先试故障源（降级恢复）；否则首选最优源
        best_url——rumor 低信任源拒绝（设计文档 30 rumor-miss 用例：官方源优先），
        无 best_url 用兜底 example.com（accuracy 用例）。"""
        if self._fail_urls:
            return self._fail_urls[0]
        if self._best_url and "rumor" not in self._best_url:
            return self._best_url
        return self._target_url(dim)

    def _web_extract_action(self, url: str) -> str:
        return (
            "Thought: 采集该来源信息\nAction: web_extract\n"
            f"Args: {json.dumps({'url': url}, ensure_ascii=False)}"
        )

    def _target_url(self, dim: str) -> str:
        """兜底 URL（accuracy 用例未标注 best_url 时）：确定性可复现的假源。"""
        base = self._competitor or (self._parsed_competitors[0] if self._parsed_competitors else "unknown")
        return f"https://example.com/{base}/{dim}"

    @staticmethod
    def _subagent_dimension_from_system(system: str) -> str:
        """从系统提示取维度名：「{dim}」维度子 Agent（跨轮稳定，user 会变成 Observation）。"""
        import re as _re

        match = _re.search(r"「([^」]+)」维度子 Agent", system)
        return match.group(1) if match else ""

    def _subagent_dimension(self, user: str) -> str:
        """解析子 Agent 任务文本的维度；与 _make_plan_action 同口径（用例维度 → 解析维度 → 全维度）。"""
        from competitor_agent.agent.react_schemas import DIMENSIONS

        dims = self._dimensions or self._parsed_dimensions or list(DIMENSIONS)
        for dim in dims:
            if f"（请分析维度：{dim}）" in user:
                return dim
        return dims[0] if dims else "pricing"

    @staticmethod
    def _task_text(messages: list[dict[str, str]]) -> str:
        """首条 user 消息（会话任务文本），跨轮稳定。"""
        for message in messages:
            if message.get("role") == "user":
                return str(message.get("content", ""))
        return ""

    @staticmethod
    def _last_observation(messages: list[dict[str, str]]) -> str:
        """最后一条可读观察：react 为 user Observation；native 为 role:"tool" 消息。"""
        for message in reversed(messages):
            role = message.get("role")
            content = str(message.get("content", ""))
            if role == "tool" or (role == "user" and "Observation" in content):
                return content
        return ""

    @staticmethod
    def _tried_urls(messages: list[dict[str, Any]]) -> list[str]:
        """本会话已尝试的抓取 URL：react 从 assistant Action Args 提取；native 从 tool_calls 提取。"""
        urls: list[str] = []
        for message in messages:
            if message.get("role") != "assistant":
                continue
            calls: list[Any] = message.get("tool_calls") or []
            if calls:
                for call in calls:
                    url = BenchmarkMockLLM._first_call_url(call)
                    if url and url not in urls:
                        urls.append(url)
            else:
                match = re.search(r'"url"\s*:\s*"([^"]+)"', str(message.get("content", "")))
                if match and match.group(1) not in urls:
                    urls.append(match.group(1))
        return urls

    @classmethod
    def _subagent_blocks(cls, text: str) -> list[tuple[str, str]]:
        """按「[维度子 Agent 结果: <name>」标记切分 delegate 回填文本 → [(name, body)]。"""
        parts = re.split(r"\[维度子 Agent 结果: ", text)
        blocks: list[tuple[str, str]] = []
        for part in parts[1:]:
            name = part.split("|", 1)[0].strip()
            body = part.split("]", 1)[1] if "]" in part else part
            blocks.append((name, body))
        return blocks

    @classmethod
    def _extract_json_block(cls, text: str) -> Any:
        """从回填块正文（untrusted 包裹 + 说明文字）提取首个 JSON 对象。"""
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, TypeError):
            return None

    @classmethod
    def _page_from_observation(cls, obs: str) -> str:
        """从 Observation 提取 untrusted 数据块内的页面文本（无则返回整段）。"""
        start = obs.find("<untrusted_data>")
        if start < 0:
            return obs
        start += len("<untrusted_data>")
        end = obs.find("</untrusted_data>", start)
        return obs[start:end] if end > start else obs[start:]

    @classmethod
    def _plans(cls, text: str) -> list[dict[str, Any]]:
        plans = []
        for line in text.splitlines():
            match = cls._PLAN_RE.search(line)
            if not match:
                continue
            plans.append(
                {
                    "name": match.group("name").strip().lower(),
                    "price": match.group("price"),
                    "period": (match.group("period") or "month").lower(),
                }
            )
        return plans

    @classmethod
    def _features(cls, text: str) -> list[str]:
        out = []
        for line in text.splitlines():
            lowered = line.lower()
            if any(marker in lowered for marker in cls._FEATURE_MARKERS):
                out.append(line.strip())
        return out

    @classmethod
    def _benchmarks(cls, text: str) -> list[dict[str, str]]:
        out = []
        for line in text.splitlines():
            if ":" in line:
                name, score = line.split(":", 1)
                out.append({"name": name.strip().lower(), "score": score.strip()})
        return out

    @classmethod
    def _ecosystem(cls, text: str) -> dict[str, Any]:
        """生态信号：MCP server 逐行计数 / IDE 支持 / 插件行。输出对齐 EcosystemAnalyzer details 契约。"""
        mcp_servers: list[dict[str, str]] = []
        ide_support: list[str] = []
        plugins: list[str] = []
        for line in text.splitlines():
            low = line.lower()
            if "mcp server" in low or "mcp_server" in low:
                mcp_servers.append({"name": line.strip()[:80], "vendor": "", "discoverable_via": "benchmark"})
            for marker in cls._IDE_MARKERS:
                if marker in low and marker not in ide_support:
                    ide_support.append(marker)
            if any(m in low for m in cls._PLUGIN_MARKERS):
                plugins.append(line.strip()[:80])
        return {
            "mcp_servers": mcp_servers[:10],
            "plugins": {"count": len(plugins), "rating": 0, "top": plugins[:5]},
            "ide_support": ide_support,
            "integrations": [],
            "repo_activity": {"stars": 0, "last_release": "", "commits_30d": 0},
        }

    @classmethod
    def _sentiment(cls, text: str) -> tuple[dict[str, Any], float]:
        """口碑信号：按行判极性（对齐 SentimentAnalyzer 规则），信号不足 → 低置信不编造。"""
        signals: list[dict[str, str]] = []
        positives: list[str] = []
        negatives: list[str] = []
        for line in text.splitlines():
            if len(line) > 200:
                continue
            low = line.lower()
            has_pos = any(m in low for m in cls._POSITIVE_MARKERS)
            has_neg = any(m in low for m in cls._NEGATIVE_MARKERS)
            if not (has_pos or has_neg):
                continue
            polarity = "neu"
            if has_pos and not has_neg:
                polarity = "pos"
            elif has_neg and not has_pos:
                polarity = "neg"
            signals.append({"polarity": polarity, "quote": line.strip()[:120], "source_url": ""})
            if polarity == "pos":
                positives.append(line.strip()[:80])
            elif polarity == "neg":
                negatives.append(line.strip()[:80])
        pos_c = sum(1 for s in signals if s["polarity"] == "pos")
        neg_c = sum(1 for s in signals if s["polarity"] == "neg")
        neu_c = len(signals) - pos_c - neg_c
        total = len(signals)
        if total:
            ratio = {"pos": round(pos_c / total, 2), "neg": round(neg_c / total, 2), "neu": round(neu_c / total, 2)}
            verdict = f"社区口碑以{'正面' if pos_c >= neg_c else '负面'}为主（{pos_c}正/{neg_c}负/{neu_c}中）"
            confidence = 0.6 if total >= 3 else 0.5
        else:
            ratio = {"pos": 0.0, "neg": 0.0, "neu": 0.0}
            verdict = "社区信号不足，无法形成可靠口碑结论（不编造）"
            confidence = 0.1
        return (
            {
                "signals": signals[:20],
                "positives": list(dict.fromkeys(positives))[:5],
                "negatives": list(dict.fromkeys(negatives))[:5],
                "polarity_ratio": ratio,
                "verdict": verdict,
            },
            confidence,
        )


# ── 字段抽取：从真实报告提取可比对字段（设计文档 §3.1） ──────────────


_PERIOD_ALIAS = {"mo": "month"}


def _plan_price(details: dict[str, Any], term: str) -> str:
    """从 plans[].price/period 拼装 "$N/unit"（与 ground_truth 同命名空间）"""
    for plan in details.get("plans", []):
        name = str(plan.get("name") or "").lower()
        if term.lower() in name:
            price = str(plan.get("price") or "").strip()
            period_raw = str(plan.get("period") or "").lower()
            period = _PERIOD_ALIAS.get(period_raw, period_raw)
            return f"${price}/{period}" if period else f"${price}"
    return ""


def _feature_present(details: dict[str, Any], term: str) -> str:
    """特征存在性：term 出现在任一 features 行则 "true"，否则 "false"（防幻觉，拒绝虚构）"""
    for feature in details.get("features", []):
        if term.lower() in str(feature).lower():
            return "true"
    return "false"


def _benchmark_score(details: dict[str, Any], term: str) -> str:
    """基准分：按名匹配 benchmarks[]（兼容 mock 的 name/score 与规则层的 raw 行）"""
    for benchmark in details.get("benchmarks", []):
        name = str(benchmark.get("name") or "").lower()
        raw = str(benchmark.get("raw") or "").lower()
        if term.lower() in name or (raw and term.lower() in raw):
            if "score" in benchmark:
                return str(benchmark["score"])
            if ":" in raw:
                return raw.split(":", 1)[1].strip()
            return raw
    return ""


def _ecosystem_signal(details: dict[str, Any], key: str) -> Any:
    """生态信号（设计文档 24 的 EcosystemAnalyzer details）：MCP 数量 / IDE 支持 / 插件市场"""
    if key == "mcp_servers":
        return len(details.get("mcp_servers") or [])
    if key == "plugins":
        return (details.get("plugins") or {}).get("count", 0)
    if key == "stars":
        return (details.get("repo_activity") or {}).get("stars", 0)
    if key in ("vscode", "jetbrains", "terminal"):
        ide = [str(i).lower() for i in (details.get("ide_support") or [])]
        return "true" if key in ide else "false"
    if key == "ide":
        return " ".join(str(i) for i in (details.get("ide_support") or []))
    return ""


def _sentiment_signal(details: dict[str, Any], key: str) -> Any:
    """口碑信号（设计文档 24 的 SentimentAnalyzer details）：极性主导 / 正负信号有无"""
    ratio = details.get("polarity_ratio") or {}
    if key == "polarity":
        pos = float(ratio.get("pos") or 0.0)
        neg = float(ratio.get("neg") or 0.0)
        neu = float(ratio.get("neu") or 0.0)
        if pos > neg and pos > neu:
            return "pos"
        if neg > pos and neg > neu:
            return "neg"
        return "neu"
    if key == "positive":
        return "true" if (ratio.get("pos") or 0) > 0 else "false"
    if key == "negative":
        return "true" if (ratio.get("neg") or 0) > 0 else "false"
    if key == "neutral":
        return "true" if (ratio.get("neu") or 0) > 0 else "false"
    if key in ("pos", "neg", "neu"):
        return ratio.get(key, 0.0)
    return ""


def _timeline_event(report: object, key: str) -> str:
    """时间线事件（设计文档 26）：从报告内嵌「竞品时间线」段落判断是否有事件。

    首轮分析无基线 → 不产生事件 → 无该段落（防噪声，设计文档 29 边界用例）。
    """
    if key != "has_events":
        return ""
    markdown = str(getattr(report, "markdown_report", "") or "")
    return "true" if "## 竞品时间线" in markdown else "false"


def _extract_field(kind: str, details: dict[str, Any], key: str) -> Any:
    if kind == "plan_price":
        return _plan_price(details, key)
    if kind == "feature_present":
        return _feature_present(details, key)
    if kind == "benchmark_score":
        return _benchmark_score(details, key)
    if kind == "ecosystem_signal":
        return _ecosystem_signal(details, key)
    if kind == "sentiment_signal":
        return _sentiment_signal(details, key)
    return ""


def extract_prediction(report: object, dimension: str, ground_truth: dict[str, Any]) -> dict[str, Any]:
    """从真实分析报告提取可比对字段（prediction 命名空间与 ground_truth 对齐）"""
    result = next(
        (r for r in report.dimension_results if r.dimension == dimension),  # type: ignore[attr-defined]
        None,
    )
    details: dict[str, Any] = result.details if result is not None else {}
    kind = DIMENSION_KINDS.get(dimension, "summary")
    if kind == "timeline_event":
        # 时间线事件需要整份报告（内嵌段落），而非单维度 details
        return {key: _timeline_event(report, key) for key in ground_truth}
    return {key: _extract_field(kind, details, key) for key in ground_truth}


def extract_strategy(
    report: object,
    best_url: str,
    fail_urls: list[str] | None = None,
) -> tuple[list[str], float, bool]:
    """从真实报告证据反推策略指标（设计文档 §3.1 / 共识项）

    - chosen_sources：系统实际用到的证据 URL（去重、按序）
    - cost：尝试源数 × 单次成本（含失败的首候选源）
    - outcome_complete：是否至少闭环了一个带证据的维度
    """
    urls: list[str] = []
    for r in report.dimension_results:  # type: ignore[attr-defined]
        for evidence in r.evidence:
            url = evidence.url
            if url and url not in urls:
                urls.append(url)
    fail = fail_urls or []
    attempts = len(urls) + len(fail)
    cost = round(attempts * UNIT_COST, 4)
    return urls, cost, bool(urls)


def real_trace(report: object) -> list[dict[str, Any]]:
    """真实执行轨迹：来自报告证据链（source_name/url/耗时口径后续内可扩展）"""
    trace = []
    for r in report.dimension_results:  # type: ignore[attr-defined]
        for evidence in r.evidence:
            trace.append(
                {
                    "tool": evidence.source_name,
                    "params": {"url": evidence.url},
                    "status": "ok",
                }
            )
    return trace


# ── API 工厂：mock / real LLM + 确定性采集 ────────────────────────────


def build_real_llm() -> LLMClient:
    """按 LLMConfig 构造真实 LLMClient（重试/fallback/超时来自设计文档 36）。

    供 `--llm real` 使用：主流程配置生效，跨 case 复用同一实例（连接复用 + 成本累计）。
    无 Key 时不报错（真正调用时才抛 LLMUnavailableError），由调用方前置校验。
    """
    from competitor_agent.config.loader import load_config

    cfg = load_config()
    return LLMClient(
        model=cfg.llm.model,
        base_url=cfg.llm.api_base_url,
        fallback_models=cfg.llm.fallback_models,
        timeout=cfg.llm.timeout,
        max_retries=cfg.llm.max_retries,
        pricing_per_1k=cfg.llm.pricing_per_1k,
    )


def build_benchmark_api(
    case: object,
    llm_mode: str = "mock",
    llm: LLMClient | None = None,
    enable_rag: bool = True,
    enable_memory: bool = True,
    memory: object | None = None,
    rag_store: object | None = None,
    timeline: object | None = None,
    engine: str = "react",
    llm_call_counter: list[int] | None = None,
) -> CompetitorAnalysisAPI:
    """按用例配置构建 API：mock 用确定性 MockLLM（无 Key、无网络），real 用真实 LLMClient。

    设计文档 47：主路径仅 LLM（use_llm 恒 True）；确定性由 mock LLM 在 LLM 版接口上
    固定返回承担（不再依赖规则版降级）。

    llm：共享 LLMClient 实例（real 模式跨 case 复用，连接复用 + 成本累计；设计文档 37）。
      为 None 时按 llm_mode 默认构造（mock=确定性 MockLLM；real=按 LLMConfig 构造）。

    enable_rag / enable_memory：消融开关（设计文档 30），透传给 API 门控知识库/记忆。
    memory / rag_store：注入共享记忆与知识库实例（跨用例累积，消融差分可测）。
    timeline：默认注入每 case 独立的空时间线存储，保证「首轮无基线不产生事件」
    （设计文档 26/29 边界）不受外部共享时间线状态污染——失败统计可信且可复现。
    """
    if llm is None:
        if llm_mode == "mock":
            mock = BenchmarkMockLLM(
                competitor=str(getattr(case, "competitor", "")),
                dimension=str(getattr(case, "dimension", "")),
                page=str(getattr(case, "page", "") or ""),
                best_url=str(getattr(case, "best_url", "") or ""),
                fail_urls=list(getattr(case, "fail_urls", None) or ()),
                no_tools=bool(getattr(case, "no_tools", False)),
            )
            call_func: Callable[..., str] = mock.complete
            if llm_call_counter is not None:
                # 引擎对照（设计文档 51）：mock 模式成本恒 0，LLM 调用次数是编排开销指标
                def _counting_complete(
                    messages: list[dict[str, str]],
                    model: str | None = None,
                    _counter: list[int] = llm_call_counter,
                    _fn: Callable[..., str] = mock.complete,
                ) -> str:
                    _counter.append(1)
                    return _fn(messages, model=model)

                call_func = _counting_complete
            llm = LLMClient(call_func=call_func)
        elif llm_mode == "real":
            llm = build_real_llm()
    extractor = BenchmarkExtractor(
        page=getattr(case, "page", ""),
        fail_urls=set(getattr(case, "fail_urls", None) or ()),
    )
    if timeline is None:
        timeline = TimelineMemory(data_dir=Path(tempfile.mkdtemp(prefix="benchmark_timeline_")))
    # URL 守卫（DNS 解析）在无网络评测环境对所有真实域名抛错，会掩盖 fail_urls/page 的
    # 确定性分发；benchmark 由 BenchmarkExtractor 直接供给页面内容/失败，故关闭守卫。
    cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
    return CompetitorAnalysisAPI(
        extractor=extractor,
        llm=llm,
        use_llm=True,
        max_iterations=8,
        cost_limit=1.0,
        enable_rag=enable_rag,
        enable_memory=enable_memory,
        memory=memory,  # type: ignore[arg-type]
        rag_store=rag_store,
        timeline=timeline,  # type: ignore[arg-type]
        config=cfg,
        engine=engine,
    )


# ── Benchmark 主类：真实执行评测 ──────────────────────────────────────


class Benchmark:
    """运行完整 benchmark 评测（真实调用系统，而非 fixture 自证）"""

    def __init__(
        self,
        fixtures_dir: Path | None = None,
        llm_mode: str = "mock",
        build_api: Callable[[object], CompetitorAnalysisAPI] | None = None,
        accuracy_eval: AccuracyEvaluator | None = None,
        strategy_eval: StrategyEvaluator | None = None,
        llm: LLMClient | None = None,
        tag: str | None = None,
        cost_limit_usd: float | None = None,
        engine: str = "react",
        llm_call_counter: list[int] | None = None,
    ) -> None:
        self._dir = fixtures_dir or FIXTURES_DIR
        self._llm_mode = llm_mode
        self._llm = llm
        self._tag = tag
        self._cost_limit_usd = cost_limit_usd
        if build_api is None:
            if llm is not None:
                self._build_api = lambda case: build_benchmark_api(
                    case, llm_mode=self._llm_mode, llm=llm, engine=engine,
                    llm_call_counter=llm_call_counter,
                )
            else:
                self._build_api = lambda case: build_benchmark_api(
                    case, llm_mode=self._llm_mode, engine=engine,
                    llm_call_counter=llm_call_counter,
                )
        else:
            self._build_api = build_api
        self._accuracy = accuracy_eval or AccuracyEvaluator()
        self._strat = strategy_eval or StrategyEvaluator()

    def run(self) -> BenchmarkReport:
        acc_cases = self._load_accuracy(self._dir / ACCURACY_FIXTURE)
        strat_cases = self._load_strategy(self._dir / STRATEGY_FIXTURE)
        if self._tag:
            acc_cases = [c for c in acc_cases if self._tag in c.tags]
            strat_cases = [c for c in strat_cases if self._tag in c.tags]

        # 逐 case 的真实报告（供设计文档 31 失败归类取证据/状态）
        reports_by_case: dict[str, object] = {}

        # 设计文档 37：真实评测成本核算 + 成本护栏（复用 llm._log_call 的 cost_usd 累计）
        total_cost = 0.0
        per_case_cost: dict[str, float] = {}
        budget_aborted = False

        # 字段真实评测：逐 case 调用 api.analyze() → 从真实报告提取 prediction
        acc_eval_cases: list[EvalCase] = []
        for acc_case in acc_cases:
            if self._budget_exceeded(total_cost):
                budget_aborted = True
                break
            before = self._cost_now()
            report = self._analyze(acc_case)
            cost = round(self._cost_now() - before, 6)
            total_cost = round(total_cost + cost, 6)
            per_case_cost[acc_case.case_id or acc_case.task] = cost
            reports_by_case[acc_case.case_id or acc_case.task] = report
            prediction = extract_prediction(report, acc_case.dimension, acc_case.ground_truth)
            acc_eval_cases.append(
                EvalCase(
                    task=acc_case.task,
                    prediction=prediction,
                    ground_truth=acc_case.ground_truth,
                    case_id=acc_case.case_id,
                    competitor=acc_case.competitor,
                    dimension=acc_case.dimension,
                    tags=acc_case.tags,
                    trace=real_trace(report),
                )
            )

        # 策略真实评测：真实证据（选中/降级 URL）反推命中与成本
        strat_eval_cases: list[StrategyCase] = []
        for strat_case in strat_cases:
            if self._budget_exceeded(total_cost):
                budget_aborted = True
                break
            before = self._cost_now()
            report = self._analyze(strat_case)
            cost = round(self._cost_now() - before, 6)
            total_cost = round(total_cost + cost, 6)
            per_case_cost[strat_case.case_id or strat_case.task] = cost
            reports_by_case[strat_case.case_id or strat_case.task] = report
            urls, cost, complete = extract_strategy(report, strat_case.best_url, strat_case.fail_urls)
            strat_eval_cases.append(
                StrategyCase(
                    task=strat_case.task,
                    chosen_sources=urls,
                    best_source=strat_case.best_url,
                    total_cost=cost,
                    outcome_complete=complete,
                    depth=len(urls),
                    case_id=strat_case.case_id,
                    tags=strat_case.tags,
                    trace=real_trace(report),
                )
            )

        accuracy = self._accuracy.evaluate(acc_eval_cases)
        # 设计文档 29：按维度拆分字段准确率与幻觉率（生态/口碑/时间线覆盖盲区独立门禁）
        accuracy_by_dimension: dict[str, float] = {}
        hallucination_by_dimension: dict[str, float] = {}
        for dim in dict.fromkeys(c.dimension for c in acc_eval_cases):
            grouped = [c for c in acc_eval_cases if c.dimension == dim]
            m = self._accuracy.evaluate(grouped)
            accuracy_by_dimension[dim] = m.field_accuracy
            hallucination_by_dimension[dim] = m.hallucination_rate

        # 设计文档 31：失败类型聚合（未命中 case 归入五类之一）
        failure_stats, failure_records = _classify_failures(
            acc_eval_cases, strat_eval_cases, reports_by_case
        )

        # 设计文档 37：成本护栏中止——未运行的 case 记 budget_exhausted 失败（复用 31 分类）
        if budget_aborted:
            failure_records.append(
                {
                    "case_id": "(budget_aborted)",
                    "dimension": "",
                    "failure_type": FailureType.BUDGET_EXHAUSTED.value,
                    "detail": f"评测成本护栏中止：累计 ${total_cost:.6f} 达到上限 ${self._cost_limit_usd:.6f}",
                    "evidence_urls": [],
                }
            )
            failure_stats[FailureType.BUDGET_EXHAUSTED.value] = (
                failure_stats.get(FailureType.BUDGET_EXHAUSTED.value, 0) + 1
            )

        return BenchmarkReport(
            accuracy=accuracy,
            strategy=self._strat.evaluate(strat_eval_cases),
            n_cases=len(acc_cases) + len(strat_cases),
            loaded_fixtures=[ACCURACY_FIXTURE, STRATEGY_FIXTURE],
            trace_completeness=self._trace_completeness(acc_eval_cases, strat_eval_cases),
            confusion_matrix=self._confusion_matrix(strat_eval_cases),
            accuracy_by_dimension=accuracy_by_dimension,
            hallucination_by_dimension=hallucination_by_dimension,
            failure_stats=failure_stats,
            failure_records=failure_records,
            llm_mode=self._llm_mode,
            cost_usd=total_cost,
            per_case_cost=per_case_cost,
            cost_limit_usd=self._cost_limit_usd,
            budget_aborted=budget_aborted,
            behavior=self._run_behavior_evals(),
        )

    def _run_behavior_evals(self) -> BehaviorMetrics:
        """设计文档 42：行为级评测——工具自恢复（ScriptedLLM 确定性）+ 检索命中（hybrid vs lexical）。

        两 Evaluator 均无真实 Key/网络依赖，mock/real 模式都跑（确定性可复现）；
        RecoveryEvaluator 用脚本化 mock 而非真实 LLM（真实 LLM 恢复为后续增强）。
        """
        recovery_rate, recovery_n = RecoveryEvaluator().run()
        hit_hybrid, hit_lexical, retrieval_n = RetrievalEvaluator().run()
        # 设计文档 56 M3：折叠取回对照（pinned 存活断言在测试侧，门禁只卡重抓次数）
        refetch_after_fold, _pinned_survived = FoldRecallEvaluator().run()
        return BehaviorMetrics(
            react_recovery_rate=recovery_rate,
            recovery_n=recovery_n,
            retrieval_hit_hybrid=hit_hybrid,
            retrieval_hit_lexical=hit_lexical,
            retrieval_n=retrieval_n,
            refetch_after_fold=refetch_after_fold,
        )

    def _budget_exceeded(self, total_cost: float) -> bool:
        """成本护栏：累计成本达到上限即中止（仅 real 模式启用成本护栏）。"""
        if self._cost_limit_usd is None:
            return False
        return total_cost >= self._cost_limit_usd

    def _cost_now(self) -> float:
        """当前累计 LLM 成本（设计文档 37：共享实例累计；无共享实例则 0）。"""
        return self._llm.total_cost_usd if self._llm is not None else 0.0

    def _analyze(self, case: AccuracyCase | BenchStrategyCase) -> object:
        api = self._build_api(case)
        return api.analyze(case.task, mode=getattr(case, "mode", "single"))

    def _load_accuracy(self, path: Path) -> list[AccuracyCase]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            AccuracyCase(
                task=c["task"],
                competitor=c.get("competitor", ""),
                dimension=c.get("dimension", ""),
                ground_truth=c["ground_truth"],
                case_id=c.get("case_id", ""),
                tags=c.get("tags", []),
                mode=c.get("mode", "single"),
                page=c.get("page", ""),
                fail_urls=c.get("fail_urls", []),
            )
            for c in data
        ]

    def _load_strategy(self, path: Path) -> list[BenchStrategyCase]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            BenchStrategyCase(
                task=c["task"],
                competitor=c.get("competitor", ""),
                dimension=c.get("dimension", ""),
                best_url=c["best_url"],
                case_id=c.get("case_id", ""),
                tags=c.get("tags", []),
                mode=c.get("mode", "single"),
                page=c.get("page", ""),
                fail_urls=c.get("fail_urls", []),
            )
            for c in data
        ]

    @staticmethod
    def _trace_completeness(
        acc_cases: list[EvalCase],
        strat_cases: list[StrategyCase],
    ) -> float:
        """trace 完整率 = 有真实证据 trace 的 case / 总 case（设计文档 §6 目标 100%）"""
        all_cases: list[Any] = [*acc_cases, *strat_cases]
        if not all_cases:
            return 0.0
        with_trace = sum(1 for c in all_cases if c.trace)
        return round(with_trace / len(all_cases), 4)

    @staticmethod
    def _confusion_matrix(strat_cases: list[StrategyCase]) -> dict[str, dict[str, int]]:
        """工具选择混淆矩阵：rows = 标注最优源，cols = Agent 实际首选源"""
        matrix: dict[str, dict[str, int]] = {}
        for case in strat_cases:
            chosen_first = case.chosen_sources[0] if case.chosen_sources else "(none)"
            row = matrix.setdefault(case.best_source, {})
            row[chosen_first] = row.get(chosen_first, 0) + 1
        return matrix


def _evidence_urls(report: object | None) -> list[str]:
    """从报告维度结果收集证据 URL（去重保序）"""
    urls: list[str] = []
    if report is None:
        return urls
    for result in getattr(report, "dimension_results", None) or []:
        for evidence in getattr(result, "evidence", None) or []:
            url = getattr(evidence, "url", "")
            if url and url not in urls:
                urls.append(url)
    return urls


def _classify_failures(
    acc_eval_cases: list[EvalCase],
    strat_eval_cases: list[StrategyCase],
    reports_by_case: dict[str, object],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """设计文档 31 §3.2：聚合失败类型 → (failure_stats, failure_records)。

    - accuracy 未命中 case（字段不全命中）→ classify_case 归入五类；
    - strategy 未命中 case（hit=False）→ 无有效源 → SOURCE_UNAVAILABLE，
      有源但未选最优 → PARSE_FAILURE；
    - 按 (case_id, type) 去重，计数 + 占比在渲染层计算。
    """
    records: list[FailureRecord] = []
    for acc_case in acc_eval_cases:
        report = reports_by_case.get(acc_case.case_id) or reports_by_case.get(acc_case.task)
        records.extend(classify_case(acc_case, acc_case.prediction, acc_case.ground_truth, report))
    for strat_case in strat_eval_cases:
        if strat_case.best_source in strat_case.chosen_sources:
            continue
        report = reports_by_case.get(strat_case.case_id) or reports_by_case.get(strat_case.task)
        urls = _evidence_urls(report)
        if not strat_case.chosen_sources:
            records.append(
                FailureRecord(
                    strat_case.case_id,
                    "",
                    FailureType.SOURCE_UNAVAILABLE,
                    "降级链全灭，无有效数据源（源抓取失败/BLOCKED）",
                    urls,
                )
            )
        else:
            records.append(
                FailureRecord(
                    strat_case.case_id,
                    "",
                    FailureType.PARSE_FAILURE,
                    "有源但未命中标注最优源",
                    urls,
                )
            )

    seen: set[tuple[str, str]] = set()
    unique: list[FailureRecord] = []
    for rec in records:
        key = (rec.case_id, rec.failure_type.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(rec)

    stats: dict[str, int] = {}
    for rec in unique:
        stats[rec.failure_type.value] = stats.get(rec.failure_type.value, 0) + 1
    return stats, [r.to_dict() for r in unique]


# ── 报告输出（CSV / Markdown）─────────────────────────────────────────


def _write_csv(report: BenchmarkReport, out: Path, mock_report: BenchmarkReport | None = None) -> None:
    rows = [["harness_version", "metric", "value"]]
    acc = report.to_dict()["accuracy"]
    strat = report.to_dict()["strategy"]
    rows.append([report.harness_version, "llm_mode", report.llm_mode])
    for k, v in acc.items():
        if k not in ("hallucination_instances", "per_case"):
            rows.append([report.harness_version, f"accuracy.{k}", str(v)])
    for dim, v in report.accuracy_by_dimension.items():
        rows.append([report.harness_version, f"accuracy_by_dimension.{dim}", str(v)])
    for dim, v in report.hallucination_by_dimension.items():
        rows.append([report.harness_version, f"hallucination_by_dimension.{dim}", str(v)])
    for k, v in strat.items():
        rows.append([report.harness_version, f"strategy.{k}", str(v)])
    rows.append([report.harness_version, "trace_completeness", str(report.trace_completeness)])
    # 设计文档 37：成本核算 + 模式标注
    rows.append([report.harness_version, "cost_usd", str(report.cost_usd)])
    if report.cost_limit_usd is not None:
        rows.append([report.harness_version, "cost_limit_usd", str(report.cost_limit_usd)])
    rows.append([report.harness_version, "budget_aborted", str(report.budget_aborted)])
    for case_id, cost in report.per_case_cost.items():
        rows.append([report.harness_version, f"cost.case.{case_id}", str(cost)])
    # 设计文档 31：失败类型统计（逐类计数 + 总计）
    for ftype in sorted(report.failure_stats):
        rows.append([report.harness_version, f"failure.{ftype}", str(report.failure_stats[ftype])])
    rows.append([report.harness_version, "failure.total", str(sum(report.failure_stats.values()))])
    # 设计文档 42：行为级评测（工具自恢复 + 检索命中率）
    rows.append([report.harness_version, "behavior.react_recovery_rate", str(report.behavior.react_recovery_rate)])
    rows.append([report.harness_version, "behavior.recovery_n", str(report.behavior.recovery_n)])
    rows.append([report.harness_version, "behavior.retrieval_hit_hybrid", str(report.behavior.retrieval_hit_hybrid)])
    rows.append([report.harness_version, "behavior.retrieval_hit_lexical", str(report.behavior.retrieval_hit_lexical)])
    rows.append([report.harness_version, "behavior.retrieval_n", str(report.behavior.retrieval_n)])
    # 设计文档 56 M3：折叠后重复抓取次数
    rows.append([report.harness_version, "behavior.refetch_after_fold", str(report.behavior.refetch_after_fold)])
    # 设计文档 37：mock vs real 对比（real 报告内嵌 mock 基线，直答"评测是不是自证"）
    if mock_report is not None and mock_report.llm_mode != report.llm_mode:
        rows.append([report.harness_version, "vs.mock.accuracy.field_accuracy", str(mock_report.accuracy.field_accuracy)])
        rows.append([report.harness_version, "vs.mock.accuracy.hallucination_rate", str(mock_report.accuracy.hallucination_rate)])
        rows.append([report.harness_version, "vs.mock.strategy.tool_selection_accuracy", str(mock_report.strategy.tool_selection_accuracy)])
        rows.append([report.harness_version, "vs.mock.cost_usd", str(mock_report.cost_usd)])
    out.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")


def _write_markdown(
    report: BenchmarkReport,
    out: Path,
    mock_report: BenchmarkReport | None = None,
) -> None:
    """评测报告：均值 + 逐 case 明细 + 幻觉实例清单 + 混淆矩阵 + harness 版本号 + 成本/对比"""
    lines: list[str] = []
    lines.append(f"# Benchmark Report — harness v{report.harness_version}")
    lines.append(f"\n> generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"> fixtures: {', '.join(report.loaded_fixtures)} | cases: {report.n_cases} | trace completeness: {report.trace_completeness:.0%}")
    lines.append(f"> llm_mode: {report.llm_mode} | 累计成本: ${report.cost_usd:.6f} | 成本护栏: "
                 f"{'$' + f'{report.cost_limit_usd:.6f}' if report.cost_limit_usd is not None else '不限'}"
                 f"{' | ⚠️ 预算中止' if report.budget_aborted else ''}")
    lines.append("\n## 指标汇总")
    lines.append("\n| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| LLM 模式 | {report.llm_mode} |")
    lines.append(f"| 字段准确率 | {report.accuracy.field_accuracy:.4f} |")
    lines.append(f"| 幻觉率 | {report.accuracy.hallucination_rate:.4f} |")
    lines.append(f"| F1 | {report.accuracy.f1:.4f} |")
    lines.append(f"| 工具选择准确率 | {report.strategy.tool_selection_accuracy:.4f} |")
    lines.append(f"| 成本效率 | {report.strategy.cost_efficiency:.4f} |")
    lines.append(f"| 平均命中排名 | {report.strategy.avg_source_rank:.2f} |")
    lines.append(f"| 累计成本(USD) | {report.cost_usd:.6f} |")

    # 设计文档 42：行为评测——工具自恢复率 + 检索命中率（hybrid vs lexical）
    lines.append("\n## 行为评测（设计文档 42）")
    lines.append("\n| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 工具自恢复率 | {report.behavior.react_recovery_rate:.2f}（{report.behavior.recovery_n} 场景） |")
    lines.append(f"| 检索命中率 hybrid | {report.behavior.retrieval_hit_hybrid:.2f} |")
    lines.append(f"| 检索命中率 lexical | {report.behavior.retrieval_hit_lexical:.2f} |")
    lines.append(f"| 检索样本数 | {report.behavior.retrieval_n} |")
    lines.append(f"| 折叠后重抓次数（56 M3） | {report.behavior.refetch_after_fold} |")

    # 设计文档 37：mock vs real 对比段（real 报告内嵌 mock 基线，直答"评测是不是自证"）
    if mock_report is not None and mock_report.llm_mode != report.llm_mode:
        lines.append("\n## mock vs real 对比（设计文档 37：真实质量 vs 确定性回归）")
        lines.append("\n> 口径：mock=harness 自洽（确定性回归，证明链路正确）；real=真实模型端到端质量（回答面试被追问）。")
        lines.append("\n| 指标 | mock | real | 差异 |")
        lines.append("|------|------|------|------|")
        for label, m_key, r_key in (
            ("字段准确率", mock_report.accuracy.field_accuracy, report.accuracy.field_accuracy),
            ("幻觉率", mock_report.accuracy.hallucination_rate, report.accuracy.hallucination_rate),
            ("F1", mock_report.accuracy.f1, report.accuracy.f1),
            ("工具选择准确率", mock_report.strategy.tool_selection_accuracy, report.strategy.tool_selection_accuracy),
            ("成本效率", mock_report.strategy.cost_efficiency, report.strategy.cost_efficiency),
            ("累计成本(USD)", mock_report.cost_usd, report.cost_usd),
        ):
            diff = r_key - m_key
            lines.append(f"| {label} | {m_key:.4f} | {r_key:.4f} | {diff:+.4f} |")

    if report.accuracy_by_dimension:
        lines.append("\n## 按维度字段准确率（设计文档 29：生态/口碑/时间线覆盖盲区）")
        lines.append("\n| 维度 | 字段准确率 | 幻觉率 |")
        lines.append("|------|-----------|--------|")
        for dim in report.accuracy_by_dimension:
            lines.append(
                f"| {dim} | {report.accuracy_by_dimension[dim]:.4f} | {report.hallucination_by_dimension.get(dim, 0.0):.4f} |"
            )

    lines.append("\n## 逐 case 明细（accuracy）")
    lines.append("\n| case | dimension | field_accuracy | hallucination_rate | cost_usd |")
    lines.append("|------|-----------|----------------|--------------------|----------|")
    for pc in report.accuracy.per_case:
        cost = report.per_case_cost.get(pc["case_id"] or pc["task"], 0.0)
        lines.append(
            f"| {pc['case_id'] or pc['task']} | {pc['dimension']} | {pc['field_accuracy']:.4f} | "
            f"{pc['hallucination_rate']:.4f} | {cost:.6f} |"
        )

    lines.append("\n## 逐 case 明细（strategy）")
    lines.append("\n| task | hit | rank | cost | efficiency |")
    lines.append("|------|-----|------|------|------------|")
    for pc in report.strategy.per_case:
        lines.append(
            f"| {pc['task']} | {pc['hit']} | {pc['rank']} | {pc['cost']} | {pc['efficiency']:.4f} |"
        )

    lines.append("\n## 幻觉实例清单")
    if report.accuracy.hallucination_instances:
        lines.append("\n| case | field | prediction | ground_truth |")
        lines.append("|------|-------|------------|--------------|")
        for inst in report.accuracy.hallucination_instances:
            lines.append(
                f"| {inst['case_id'] or inst['task']} | {inst['field']} | {inst['prediction']} | {inst['ground_truth']} |"
            )
    else:
        lines.append("\n- 无（审计通过）")

    lines.append("\n## 工具选择混淆矩阵（rows=最优源, cols=首选源）")
    lines.append("\n| 最优源 \\ 首选 | 命中数 |")
    lines.append("|---------------|--------|")
    for best, row in report.confusion_matrix.items():
        total = sum(row.values())
        lines.append(f"| {best} | {total} |")
        for chosen, count in row.items():
            lines.append(f"  - {chosen}: {count}")

    lines.append("\n## 失败类型分布（设计文档 31）")
    if report.failure_stats:
        total = sum(report.failure_stats.values())
        lines.append("\n| 类型 | 计数 | 占比 |")
        lines.append("|------|------|------|")
        for ftype in sorted(report.failure_stats, key=lambda t: -report.failure_stats[t]):
            count = report.failure_stats[ftype]
            lines.append(f"| {ftype} | {count} | {count / total:.1%} |")
        lines.append("\n### 失败样本")
        lines.append("\n| case | 维度 | 类型 | 原因 | 证据 |")
        lines.append("|------|------|------|------|------|")
        for rec in report.failure_records:
            urls = "<br>".join(rec.get("evidence_urls", []) or ["—"])
            lines.append(
                f"| {rec.get('case_id', '')} | {rec.get('dimension', '') or '—'} | "
                f"{rec.get('failure_type', '')} | {rec.get('detail', '')} | {urls} |"
            )
    else:
        lines.append("\n- 无失败（全量命中）")

    lines.append("\n> 分数有效范围：harness v" + report.harness_version + "，改 fixture/依赖/harness 需更新版本号。")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _orchestration_loc() -> tuple[int, int]:
    """编排层代码行数（静态统计，设计文档 51 §2.3）：自研 react_loop+delegate_tool vs langgraph_engine 包。"""
    agent_dir = Path(__file__).resolve().parent.parent / "agent"
    react = sum(
        (agent_dir / name).read_text(encoding="utf-8").count("\n") + 1
        for name in ("react_loop.py", "delegate_tool.py")
    )
    lg_dir = agent_dir / "langgraph_engine"
    langgraph = sum(
        p.read_text(encoding="utf-8").count("\n") + 1 for p in sorted(lg_dir.glob("*.py"))
    )
    return react, langgraph


def _write_engine_compare(
    react_report: BenchmarkReport,
    lg_report: BenchmarkReport,
    *,
    wall_seconds: dict[str, float],
    llm_calls: dict[str, int],
    path: Path,
) -> None:
    """双引擎对照表落盘（设计文档 51 §2.3）：同 fixture/同 LLM/同工具/同出口，唯一变量是编排层。"""
    react_loc, lg_loc = _orchestration_loc()
    rows = [
        ("field_accuracy", f"{react_report.accuracy.field_accuracy:.4f}", f"{lg_report.accuracy.field_accuracy:.4f}"),
        ("hallucination_rate", f"{react_report.accuracy.hallucination_rate:.4f}", f"{lg_report.accuracy.hallucination_rate:.4f}"),
        ("tool_selection_accuracy", f"{react_report.strategy.tool_selection_accuracy:.4f}", f"{lg_report.strategy.tool_selection_accuracy:.4f}"),
        ("llm_calls", str(llm_calls.get("react", 0) or "—"), str(llm_calls.get("langgraph", 0) or "—")),
        ("total_cost_usd", f"{react_report.cost_usd:.6f}", f"{lg_report.cost_usd:.6f}"),
        ("wall_seconds", f"{wall_seconds.get('react', 0.0):.2f}", f"{wall_seconds.get('langgraph', 0.0):.2f}"),
        ("orchestration_loc（静态）", str(react_loc), str(lg_loc)),
        ("third_party_deps（静态）", "零（自研）", "langgraph + langchain-core（≈15MB）"),
    ]
    lines = [
        "# 双引擎对照（设计文档 51）：react（自研 Lead ReAct） vs langgraph（StateGraph）",
        "",
        "> 控变量：同 fixture、同 LLM（含 mock 脚本）、同工具面、同报告出口（react_report.assemble），",
        "> 唯一变量是编排层。mock 模式下成本恒 0，编排开销看 llm_calls / wall_seconds；",
        "> 产出质量对比需 `--llm real` 手动跑。取消/预算/checkpoint 为自研引擎差异化能力，",
        "> langgraph 引擎未对齐（框架省了编排代码，横切控制要自己补）。",
        "",
        "| 指标 | react | langgraph |",
        "|------|-------|-----------|",
    ]
    lines += [f"| {name} | {r} | {l} |" for name, r, l in rows]
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class GateCheck:
    """单条门禁判定结果（设计文档 55 M1）：指标名 / 阈值描述 / 实测值 / 是否达标。"""

    name: str
    threshold: str
    actual: str
    passed: bool


def evaluate_gates(report: BenchmarkReport) -> list[GateCheck]:
    """按门禁常量逐项判定（设计文档 55 M1：阈值单一来源，不新造数值）。

    六项：field_accuracy / hallucination / tool_selection / trace 完整率
    （benchmark_design §5/§8）+ 行为门禁（设计文档 42：自恢复率下限、hybrid 不劣于 lexical）。
    """
    b = report.behavior
    return [
        GateCheck(
            "field_accuracy",
            f">= {GATE_FIELD_ACCURACY_MIN:.2f}",
            f"{report.accuracy.field_accuracy:.4f}",
            report.accuracy.field_accuracy >= GATE_FIELD_ACCURACY_MIN,
        ),
        GateCheck(
            "hallucination_rate",
            f"<= {GATE_HALLUCINATION_MAX:.2f}",
            f"{report.accuracy.hallucination_rate:.4f}",
            report.accuracy.hallucination_rate <= GATE_HALLUCINATION_MAX,
        ),
        GateCheck(
            "tool_selection_accuracy",
            f">= {GATE_TOOL_SELECTION_MIN:.2f}",
            f"{report.strategy.tool_selection_accuracy:.4f}",
            report.strategy.tool_selection_accuracy >= GATE_TOOL_SELECTION_MIN,
        ),
        GateCheck(
            "trace_completeness",
            f"== {GATE_TRACE_COMPLETENESS:.2f}",
            f"{report.trace_completeness:.4f}",
            report.trace_completeness == GATE_TRACE_COMPLETENESS,
        ),
        GateCheck(
            "behavior.react_recovery_rate",
            f">= {GATE_RECOVERY_RATE_MIN:.2f}",
            f"{b.react_recovery_rate:.4f}",
            b.react_recovery_rate >= GATE_RECOVERY_RATE_MIN,
        ),
        GateCheck(
            "behavior.retrieval_hit_hybrid",
            f">= lexical({b.retrieval_hit_lexical:.4f})",
            f"{b.retrieval_hit_hybrid:.4f}",
            b.retrieval_hit_hybrid >= b.retrieval_hit_lexical,
        ),
        GateCheck(
            "behavior.refetch_after_fold",
            f"<= {GATE_REFETCH_AFTER_FOLD_MAX}",
            str(b.refetch_after_fold),
            b.refetch_after_fold <= GATE_REFETCH_AFTER_FOLD_MAX,
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark", description="competitor_agent 评测基准（真实执行）")
    parser.add_argument(
        "--llm",
        choices=["mock", "real"],
        default="mock",
        help="LLM 模式：mock=确定性评测（CI/无 Key），real=真实 LLM（评估真实质量，需配置 API Key）",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="按 tag 过滤用例子集（如 normal）控制成本；缺省全量",
    )
    parser.add_argument(
        "--cost-limit",
        type=float,
        default=None,
        dest="cost_limit",
        help="真实评测成本护栏上限（美元），缺省 real 模式 $1.0；超限中止并标注预算中止",
    )
    parser.add_argument("--out", type=Path, default=None, help="CSV 输出路径（缺省 <data_dir>/reports/benchmark[_real]_<date>.csv，仓库外）")
    parser.add_argument("--report", type=Path, default=None, help="Markdown 报告路径（缺省 <data_dir>/reports/benchmark[_real]_<date>.md）")
    parser.add_argument(
        "--engine",
        choices=["react", "langgraph", "both"],
        default="react",
        help="编排引擎（设计文档 51）：react=自研（默认，门禁口径不变），langgraph=StateGraph，both=双引擎顺序跑 + 对比表落盘",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="门禁执法（设计文档 55 M1）：跑完按 GATE_* 阈值逐项判定，任一项不达标退出码 1 并打印差距；不加本开关行为不变（恒 0）",
    )
    args = parser.parse_args(argv)

    if args.engine in ("langgraph", "both"):
        from competitor_agent.agent.langgraph_engine import ensure_langgraph_available

        try:
            ensure_langgraph_available()
        except ImportError as exc:
            print(str(exc))
            return 2

    # 设计文档 37 §4：real 无 Key 明确报错，不静默回退 mock（防误读 mock 数字）
    if args.llm == "real" and not LLMClient.has_api_key():
        print("真实 LLM 评测需要配置 API Key（OPENAI_API_KEY / DEEPSEEK_API_KEY / LLM_API_KEY）。请配置后重试，勿静默回退 mock。")
        return 2

    reports_dir = get_reports_dir()
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    # --engine both：主跑默认 react（门禁/产物口径不变），langgraph 作对照侧加跑
    suffix = "_langgraph" if args.engine == "langgraph" else ""
    engine_main = "langgraph" if args.engine == "langgraph" else "react"
    shared_llm: LLMClient | None = None
    cost_limit: float | None = None
    main_calls: list[int] = []
    main_wall = 0.0

    # 设计文档 37 §4：real 无 Key 明确报错，不静默回退 mock（防误读 mock 数字）
    if args.llm == "real":
        shared_llm = build_real_llm()
        cost_limit = args.cost_limit if args.cost_limit is not None else 1.0
        # real 报告内嵌 mock 基线：同子集跑一遍 mock（确定性、零成本）供对比
        mock_report = Benchmark(llm_mode="mock", tag=args.tag).run()
        t0 = time.monotonic()
        report = Benchmark(
            llm_mode="real", llm=shared_llm, tag=args.tag, cost_limit_usd=cost_limit,
            engine=engine_main,
            llm_call_counter=main_calls if args.engine == "both" else None,
        ).run()
        main_wall = time.monotonic() - t0
        out = args.out or (reports_dir / f"benchmark_real{suffix}_{date}.csv")
        report_path = args.report or (reports_dir / f"benchmark_real{suffix}_{date}.md")
    else:
        mock_report = None
        t0 = time.monotonic()
        report = Benchmark(
            llm_mode="mock", tag=args.tag, engine=engine_main,
            llm_call_counter=main_calls if args.engine == "both" else None,
        ).run()
        main_wall = time.monotonic() - t0
        out = args.out or (reports_dir / f"benchmark{suffix}_{date}.csv")
        report_path = args.report or (reports_dir / f"benchmark{suffix}_{date}.md")

    out.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(report, out, mock_report=mock_report)
    _write_markdown(report, report_path, mock_report=mock_report)
    print(f"n_cases={report.n_cases} llm_mode={report.llm_mode} cost=${report.cost_usd:.6f} "
          f"field_acc={report.accuracy.field_accuracy:.4f} "
          f"halluc={report.accuracy.hallucination_rate:.4f} tool_sel={report.strategy.tool_selection_accuracy:.4f} "
          f"cost_eff={report.strategy.cost_efficiency:.4f} harness_v{report.harness_version}")
    print(f"csv: {out}")
    print(f"report: {report_path}")

    if args.engine == "both":
        lg_calls: list[int] = []
        t0 = time.monotonic()
        lg_report = Benchmark(
            llm_mode=args.llm,
            llm=shared_llm,
            tag=args.tag,
            cost_limit_usd=cost_limit,
            engine="langgraph",
            llm_call_counter=lg_calls,
        ).run()
        lg_wall = time.monotonic() - t0
        compare_path = reports_dir / f"engine_compare_{date}.md"
        _write_engine_compare(
            report,
            lg_report,
            wall_seconds={"react": main_wall, "langgraph": lg_wall},
            llm_calls={"react": len(main_calls), "langgraph": len(lg_calls)},
            path=compare_path,
        )
        print(f"engine_compare: {compare_path}")

    if args.gate:
        # 设计文档 55 M1：门禁执法——任一项不达标 return 1，逐项打印「指标/阈值/实测」
        checks = evaluate_gates(report)
        print("门禁判定（--gate）：")
        for c in checks:
            verdict = "PASS" if c.passed else "FAIL"
            print(f"  {verdict} {c.name}: 实测 {c.actual}，阈值 {c.threshold}")
        failed = [c for c in checks if not c.passed]
        if failed:
            print(f"benchmark 门禁未通过：{len(failed)}/{len(checks)} 项不达标")
            return 1
        print(f"benchmark 门禁全部达标（{len(checks)}/{len(checks)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "ACCURACY_FIXTURE",
    "GATE_FIELD_ACCURACY_MIN",
    "GATE_HALLUCINATION_MAX",
    "GATE_RECOVERY_RATE_MIN",
    "GATE_TOOL_SELECTION_MIN",
    "GATE_TRACE_COMPLETENESS",
    "HARNESS_VERSION",
    "STRATEGY_FIXTURE",
    "AccuracyCase",
    "BehaviorMetrics",
    "BenchStrategyCase",
    "Benchmark",
    "BenchmarkExtractor",
    "BenchmarkMockLLM",
    "BenchmarkReport",
    "FailureRecord",
    "FailureType",
    "GateCheck",
    "build_benchmark_api",
    "build_real_llm",
    "classify_case",
    "evaluate_gates",
    "extract_prediction",
    "extract_strategy",
    "real_trace",
]