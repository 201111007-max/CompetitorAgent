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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from competitor_agent.domain_types.enums import ObservationStatus
from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.evaluation.accuracy_eval import AccuracyEvaluator, AccuracyMetrics, EvalCase
from competitor_agent.evaluation.strategy_eval import StrategyCase, StrategyEvaluator, StrategyMetrics
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.interfaces.exceptions import DataSourceUnavailableError
from competitor_agent.llm.client import LLMClient

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "evaluation" / "fixtures"

ACCURACY_FIXTURE = "accuracy_cases.json"
STRATEGY_FIXTURE = "strategy_cases.json"

# 评测 harness 版本：分数 = benchmark + subset + harness。任何评测输出必须带此版本号。
HARNESS_VERSION = "0.4.0"

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness_version": self.harness_version,
            "n_cases": self.n_cases,
            "trace_completeness": self.trace_completeness,
            "fixtures": self.loaded_fixtures,
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
        }


# ── 确定性采集（设计文档 §3.4：mock 采集保证可复现） ─────────────────


class BenchmarkExtractor:
    """确定性采集器：固定网页内容；fail_urls 中的 URL 抛故障（模拟首候选源失败）。

    供 BenchmarkMockLLM / 规则分析器消费同一份固定内容，保证 CI 无网络、无 Key 可复现。
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
    """确定性 mock LLM：按分析器 system prompt 维度从观测文本抽取规范化 JSON。

    输出结构对齐各分析器 prompt 的 JSON 契约（plans / features / benchmarks），
    顶层 tasks 解析 prompt 返回空竞品列表以触发规则版解析（保持规划确定性）。
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
    # 生态 / 口碑信号标记（对齐 analyzer 的规则降级关键词，保证确定性）
    _IDE_MARKERS = ("vscode", "jetbrains", "terminal")
    _PLUGIN_MARKERS = ("plugin", "extension", "marketplace")
    _POSITIVE_MARKERS = ("love", "great", "awesome", "fast", "recommend", "best", "好用", "好评", "推荐", "喜欢")
    _NEGATIVE_MARKERS = ("bug", "slow", "bad", "terrible", "crash", "worse", "难用", "差评", "吐槽", "失望", "贵", "限制")
    _RAG_MARKER = "[知识库参考片段"

    def complete(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        if not messages:
            return "{}"
        system = messages[0].get("content", "")
        user = self._user_text(messages)
        if "语义解析器" in system:
            # 规划解析 prompt：返回空竞品，令 parse_task 回退规则版（确定性）
            return json.dumps({"competitors": [], "dimensions": None, "custom_sources": {}})
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

    @staticmethod
    def _user_text(messages: list[dict[str, str]]) -> str:
        """取最后一条 user 消息，剥离 RAG 注入尾巴（外部事实依据不影响 mock 抽取）。"""
        user = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user = message.get("content", "")
                break
        idx = user.find(BenchmarkMockLLM._RAG_MARKER)
        return user[:idx] if idx >= 0 else user

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


def build_benchmark_api(case: object, llm_mode: str = "mock") -> CompetitorAnalysisAPI:
    """按用例配置构建 API：mock 用确定性 MockLLM（无 Key、无网络），real 用真实 LLMClient。"""
    llm: LLMClient | None = None
    use_llm = False
    if llm_mode == "mock":
        llm = LLMClient(call_func=BenchmarkMockLLM().complete)
        use_llm = True
    elif llm_mode == "real":
        llm = LLMClient()
        use_llm = True
    extractor = BenchmarkExtractor(
        page=getattr(case, "page", ""),
        fail_urls=set(getattr(case, "fail_urls", None) or ()),
    )
    return CompetitorAnalysisAPI(
        extractor=extractor,
        llm=llm,
        use_llm=use_llm,
        max_iterations=8,
        cost_limit=1.0,
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
    ) -> None:
        self._dir = fixtures_dir or FIXTURES_DIR
        self._llm_mode = llm_mode
        self._build_api = build_api or (lambda case: build_benchmark_api(case, llm_mode=self._llm_mode))
        self._accuracy = accuracy_eval or AccuracyEvaluator()
        self._strat = strategy_eval or StrategyEvaluator()

    def run(self) -> BenchmarkReport:
        acc_cases = self._load_accuracy(self._dir / ACCURACY_FIXTURE)
        strat_cases = self._load_strategy(self._dir / STRATEGY_FIXTURE)

        # 字段真实评测：逐 case 调用 api.analyze() → 从真实报告提取 prediction
        acc_eval_cases: list[EvalCase] = []
        for case in acc_cases:
            report = self._analyze(case)
            prediction = extract_prediction(report, case.dimension, case.ground_truth)
            acc_eval_cases.append(
                EvalCase(
                    task=case.task,
                    prediction=prediction,
                    ground_truth=case.ground_truth,
                    case_id=case.case_id,
                    competitor=case.competitor,
                    dimension=case.dimension,
                    tags=case.tags,
                    trace=real_trace(report),
                )
            )

        # 策略真实评测：真实证据（选中/降级 URL）反推命中与成本
        strat_eval_cases: list[StrategyCase] = []
        for case in strat_cases:
            report = self._analyze(case)
            urls, cost, complete = extract_strategy(report, case.best_url, case.fail_urls)
            strat_eval_cases.append(
                StrategyCase(
                    task=case.task,
                    chosen_sources=urls,
                    best_source=case.best_url,
                    total_cost=cost,
                    outcome_complete=complete,
                    depth=len(urls),
                    case_id=case.case_id,
                    tags=case.tags,
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

        return BenchmarkReport(
            accuracy=accuracy,
            strategy=self._strat.evaluate(strat_eval_cases),
            n_cases=len(acc_cases) + len(strat_cases),
            loaded_fixtures=[ACCURACY_FIXTURE, STRATEGY_FIXTURE],
            trace_completeness=self._trace_completeness(acc_eval_cases, strat_eval_cases),
            confusion_matrix=self._confusion_matrix(strat_eval_cases),
            accuracy_by_dimension=accuracy_by_dimension,
            hallucination_by_dimension=hallucination_by_dimension,
        )

    def _analyze(self, case: object) -> object:
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
        all_cases: list[object] = acc_cases + strat_cases
        if not all_cases:
            return 0.0
        with_trace = sum(1 for c in all_cases if getattr(c, "trace"))
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


# ── 报告输出（CSV / Markdown）─────────────────────────────────────────


def _write_csv(report: BenchmarkReport, out: Path) -> None:
    rows = [["harness_version", "metric", "value"]]
    acc = report.to_dict()["accuracy"]
    strat = report.to_dict()["strategy"]
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
    out.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")


def _write_markdown(report: BenchmarkReport, out: Path) -> None:
    """评测报告：均值 + 逐 case 明细 + 幻觉实例清单 + 混淆矩阵 + harness 版本号"""
    lines: list[str] = []
    lines.append(f"# Benchmark Report — harness v{report.harness_version}")
    lines.append(f"\n> generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"> fixtures: {', '.join(report.loaded_fixtures)} | cases: {report.n_cases} | trace completeness: {report.trace_completeness:.0%}")
    lines.append("\n## 指标汇总")
    lines.append("\n| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 字段准确率 | {report.accuracy.field_accuracy:.4f} |")
    lines.append(f"| 幻觉率 | {report.accuracy.hallucination_rate:.4f} |")
    lines.append(f"| F1 | {report.accuracy.f1:.4f} |")
    lines.append(f"| 工具选择准确率 | {report.strategy.tool_selection_accuracy:.4f} |")
    lines.append(f"| 成本效率 | {report.strategy.cost_efficiency:.4f} |")
    lines.append(f"| 平均命中排名 | {report.strategy.avg_source_rank:.2f} |")

    if report.accuracy_by_dimension:
        lines.append("\n## 按维度字段准确率（设计文档 29：生态/口碑/时间线覆盖盲区）")
        lines.append("\n| 维度 | 字段准确率 | 幻觉率 |")
        lines.append("|------|-----------|--------|")
        for dim in report.accuracy_by_dimension:
            lines.append(
                f"| {dim} | {report.accuracy_by_dimension[dim]:.4f} | {report.hallucination_by_dimension.get(dim, 0.0):.4f} |"
            )

    lines.append("\n## 逐 case 明细（accuracy）")
    lines.append("\n| case | dimension | field_accuracy | hallucination_rate |")
    lines.append("|------|-----------|----------------|--------------------|")
    for pc in report.accuracy.per_case:
        lines.append(
            f"| {pc['case_id'] or pc['task']} | {pc['dimension']} | {pc['field_accuracy']:.4f} | {pc['hallucination_rate']:.4f} |"
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

    lines.append("\n> 分数有效范围：harness v" + report.harness_version + "，改 fixture/依赖/harness 需更新版本号。")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark", description="competitor_agent 评测基准（真实执行）")
    parser.add_argument(
        "--llm",
        choices=["mock", "real"],
        default="mock",
        help="LLM 模式：mock=确定性评测（CI/无 Key），real=真实 LLM（评估真实质量）",
    )
    parser.add_argument("--out", type=Path, default=Path("reports/benchmark.csv"), help="CSV 输出路径")
    parser.add_argument("--report", type=Path, default=Path("reports/benchmark.md"), help="Markdown 报告路径")
    args = parser.parse_args(argv)

    report = Benchmark(llm_mode=args.llm).run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(report, args.out)
    _write_markdown(report, args.report)
    print(f"n_cases={report.n_cases} trace={report.trace_completeness:.0%} field_acc={report.accuracy.field_accuracy:.4f} "
          f"halluc={report.accuracy.hallucination_rate:.4f} tool_sel={report.strategy.tool_selection_accuracy:.4f} "
          f"cost_eff={report.strategy.cost_efficiency:.4f} harness_v{report.harness_version}")
    print(f"csv: {args.out}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "AccuracyCase",
    "ACCURACY_FIXTURE",
    "Benchmark",
    "BenchmarkExtractor",
    "BenchmarkMockLLM",
    "BenchmarkReport",
    "BenchStrategyCase",
    "extract_prediction",
    "extract_strategy",
    "HARNESS_VERSION",
    "real_trace",
    "STRATEGY_FIXTURE",
]