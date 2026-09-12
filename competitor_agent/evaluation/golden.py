"""黄金断言评测（设计文档 76，工单 1）。

3 个固定任务 × 每任务 30~50 条人工核实断言（must_have / trap 两型），
新增 ``must_have 召回率`` 与 ``trap 通过率`` 两个指标，判定器**可注入**：
- mock/CI → ``KeywordGoldenJudge``（确定性关键词+数值匹配，无 LLM、无网络）；
- real → ``LLMGoldenJudge``（LLM 判定覆盖/矛盾）。

断言集落盘 ``evals/golden/*.yaml``（仓库根人工维护区，与代码资产解耦——
刻意偏离 FIXTURES_DIR 惯例，因为断言需人工季度核实）。
新指标先只记录不卡 CI（doc 75 §2 用户决策 ④）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import yaml

from competitor_agent.knowledge_base.competitor_store import tokenize

# 仓库根 evals/golden（evaluation/golden.py → competitor_agent 包 → 仓库根）
GOLDEN_DIR = Path(__file__).resolve().parents[2] / "evals" / "golden"

# verified_date 过期提醒阈值（doc 76 §2.1：每季度人工核实）
_STALE_DAYS = 90


class GoldenVerdict(Enum):
    """单条断言判定结果（doc 76 §2.2）。"""

    covered = "covered"  # 报告覆盖且语义一致（must_have）
    missing = "missing"  # 未覆盖（must_have 计入召回率分母）
    contradicted = "contradicted"  # 报告与 golden 矛盾（must_have 严重失败 + 幻觉口径参照）
    passed = "passed"  # trap：报告未复述该错误信息
    tripped = "tripped"  # trap：报告复述了（失败）


@dataclass
class GoldenAssertion:
    """单条断言：claim + 类型 + 真值来源 + 标签。"""

    id: str
    claim: str
    type: str  # "must_have" / "trap"
    source_of_truth: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class GoldenTask:
    """单个固定任务的断言集（一个 yaml 文件）。"""

    task_id: str
    task: str
    verified_date: str = ""  # "" = 待用户核实（触发 stale 提醒）
    assertions: list[GoldenAssertion] = field(default_factory=list)
    stale_note: str = ""  # verified_date 过期/缺失提醒（仅提醒不失败）


@dataclass
class GoldenResult:
    """黄金断言指标（挂 BenchmarkReport.golden，doc 76 §2.3）。"""

    must_have_recall: float = 0.0  # covered / (covered+missing+contradicted)
    trap_pass_rate: float = 0.0  # passed / (passed+tripped)
    contradicted_count: int = 0  # 矛盾数（幻觉率交叉参照）
    n_must_have: int = 0
    n_trap: int = 0
    n_tasks: int = 0
    per_task: dict[str, dict[str, float]] = field(default_factory=dict)
    stale_warnings: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.n_must_have + self.n_trap > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "must_have_recall": self.must_have_recall,
            "trap_pass_rate": self.trap_pass_rate,
            "contradicted_count": self.contradicted_count,
            "n_must_have": self.n_must_have,
            "n_trap": self.n_trap,
            "n_tasks": self.n_tasks,
            "per_task": self.per_task,
            "stale_warnings": self.stale_warnings,
        }


class GoldenJudge(Protocol):
    """判定器协议（可注入，doc 76 §2 决策 ③ 硬性要求）。"""

    def judge(self, report_text: str, assertion: GoldenAssertion) -> GoldenVerdict: ...


# 通用停用词（拉丁词元；CJK 由 bigram 匹配承担，不在此处理）
_GENERIC_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "in", "on", "at", "to", "for", "by", "with", "and", "or",
        "is", "are", "was", "were", "be", "been", "as", "it", "its", "this", "that",
    }
)

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# 产品名/别名词元：出现在几乎每份报告里，对判定零信息量，剔除（由注册表动态构建）
def _product_tokens() -> frozenset[str]:
    from competitor_agent.core.competitor_registry import COMPETITOR_REGISTRY

    tokens: set[str] = set()
    for canon, competitor in COMPETITOR_REGISTRY.items():
        tokens.update(tokenize(canon))
        for alias in competitor.aliases:
            tokens.update(tokenize(alias))
    return frozenset(tokens)


def _claim_units(claim: str, ignore: frozenset[str]) -> list[tuple[str, str]]:
    """claim 判定单元：拉丁/数字词元（去停用词）+ CJK 连续段（len≥2）。

    tokenize 口径下连续汉字为单一长 run（同 CompetitorStore），直接整串匹配无法
    容忍报告改写——CJK 段改用 bigram 匹配（检索常用口径）：任一相邻二字在报告中
    命中即视为该单元命中（等价于 claim 与报告存在 ≥2 字公共子串）。
    返回 [(kind, unit)]，kind ∈ {"latin", "cjk"}。
    """
    units: list[tuple[str, str]] = []
    for tok in tokenize(claim):
        if tok in ignore:
            continue
        if _CJK_RUN_RE.fullmatch(tok):
            if len(tok) >= 2:
                units.append(("cjk", tok))
        elif len(tok) > 1 and tok not in _GENERIC_STOPWORDS:
            units.append(("latin", tok))
    return units


def _unit_hit(kind: str, unit: str, text: str) -> bool:
    if kind == "latin":
        return unit in text
    return any(unit[i : i + 2] in text for i in range(len(unit) - 1))


class KeywordGoldenJudge:
    """CI/mock 默认判定器：确定性关键词+数值匹配（无 LLM、无网络、可复现）。

    判定单元（``_claim_units``）：拉丁/数字词元精确包含；CJK 连续段 bigram 命中
    （≥2 字公共子串，容忍报告改写/断句）。
    - must_have：命中率 ≥0.6 且 ≥2 个单元命中 → covered（claim 仅 1 个单元时命中即
      covered）；否则 missing。矛盾检测是语义任务，关键词判定器恒不产出 contradicted
      （由 real 模式 LLMGoldenJudge 补足）。
    - trap：≥2 个单元命中 → tripped（单一单元命中太易误报，如报告合理提到
      "Anthropic"）；claim 仅 1 个单元时命中即 tripped；否则 passed。
    同义改写识别不到是已知局限（doc 76 §2.2）——real 模式由 LLM 判定器补足。
    """

    def __init__(self, ignore_tokens: frozenset[str] | None = None) -> None:
        self._ignore = ignore_tokens if ignore_tokens is not None else _product_tokens()

    def judge(self, report_text: str, assertion: GoldenAssertion) -> GoldenVerdict:
        text = report_text.lower()
        units = _claim_units(assertion.claim, self._ignore)
        if not units:
            # 无判定单元可判：must_have 保守记 missing、trap 保守记 passed（不误判失败）
            return GoldenVerdict.missing if assertion.type == "must_have" else GoldenVerdict.passed
        hits = sum(1 for kind, unit in units if _unit_hit(kind, unit, text))
        if assertion.type == "must_have":
            if len(units) == 1:
                return GoldenVerdict.covered if hits == 1 else GoldenVerdict.missing
            ok = hits >= 2 and hits / len(units) >= 0.6
            return GoldenVerdict.covered if ok else GoldenVerdict.missing
        # trap
        if len(units) == 1:
            return GoldenVerdict.tripped if hits == 1 else GoldenVerdict.passed
        return GoldenVerdict.tripped if hits >= 2 else GoldenVerdict.passed


class LLMGoldenJudge:
    """real 模式判定器：LLM 判定覆盖/矛盾（prompt 含 claim + 报告全文相关段落）。

    解析失败 / LLM 异常 → 保守缺省（must_have→missing，trap→passed），不误判失败。
    """

    _PROMPT = (
        "你是评测判定器。给定报告正文与一条断言，判断报告对该断言的覆盖情况。\n"
        "断言类型 must_have（报告应覆盖的正确结论）可取: covered（覆盖且语义一致）/ "
        "missing（未覆盖）/ contradicted（报告内容与断言矛盾）。\n"
        "断言类型 trap（报告不得复述的错误/易过时信息）可取: passed（未复述）/ "
        "tripped（复述了该错误信息）。\n"
        '只输出 JSON: {{"verdict": "<判定>"}}\n\n断言（{atype}）: {claim}\n\n报告正文：\n{report}'
    )

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def judge(self, report_text: str, assertion: GoldenAssertion) -> GoldenVerdict:
        prompt = self._PROMPT.format(
            atype=assertion.type, claim=assertion.claim, report=report_text[:6000]
        )
        try:
            raw = self._llm.complete([{"role": "user", "content": prompt}], json_mode=True)
        except Exception:  # noqa: BLE001  # LLM 任何失败 → 保守缺省，不误判
            return self._fallback(assertion)
        match = re.search(r"\{.*\}", str(raw), re.DOTALL)
        if not match:
            return self._fallback(assertion)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return self._fallback(assertion)
        try:
            return GoldenVerdict(str(data.get("verdict", "")))
        except ValueError:
            return self._fallback(assertion)

    @staticmethod
    def _fallback(assertion: GoldenAssertion) -> GoldenVerdict:
        return GoldenVerdict.missing if assertion.type == "must_have" else GoldenVerdict.passed


def build_golden_judge(llm_mode: str, llm: Any = None) -> GoldenJudge:
    """mock → KeywordGoldenJudge（确定性，CI 可复现）；real → LLMGoldenJudge。"""
    if llm_mode == "real" and llm is not None:
        return LLMGoldenJudge(llm)
    return KeywordGoldenJudge()


def load_golden_tasks(
    golden_dir: Path | None = None,
    *,
    today: date | None = None,
) -> list[GoldenTask]:
    """读取 golden_dir 下全部 yaml 断言集，并产出 verified_date 过期提醒（仅提醒不失败）。"""
    directory = golden_dir or GOLDEN_DIR
    today = today or datetime.now(timezone.utc).date()
    tasks: list[GoldenTask] = []
    if not directory.is_dir():
        return tasks
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            data = None
        if not isinstance(data, dict) or not data.get("task") or not data.get("assertions"):
            continue
        assertions = [
            GoldenAssertion(
                id=str(a.get("id", "")),
                claim=str(a.get("claim", "")),
                type=str(a.get("type", "must_have")),
                source_of_truth=str(a.get("source_of_truth", "")),
                tags=[str(t) for t in (a.get("tags") or [])],
            )
            for a in (data.get("assertions") or [])
            if isinstance(a, dict)
        ]
        verified = str(data.get("verified_date", "") or "")
        task = GoldenTask(
            task_id=str(data.get("task_id", path.stem)),
            task=str(data.get("task", "")),
            verified_date=verified,
            assertions=assertions,
        )
        if not verified:
            task.stale_note = f"{task.task_id}: verified_date 待核实（用户核实后回填）"
        else:
            try:
                vdate = date.fromisoformat(verified)
            except ValueError:
                task.stale_note = f"{task.task_id}: verified_date 格式非法（{verified}），请修复"
            else:
                if today - vdate > timedelta(days=_STALE_DAYS):
                    task.stale_note = (
                        f"{task.task_id}: verified_date {verified} 距今 >{_STALE_DAYS} 天，请复核断言"
                    )
        tasks.append(task)
    return tasks


def _report_text(report: Any) -> str:
    """从 run() 产物提取可判定正文：CompetitorReport/ComparisonReport 取 markdown_report，
    ChatResult 取 answer，其余 str()。"""
    text = str(getattr(report, "markdown_report", "") or "")
    if not text:
        text = str(getattr(report, "answer", "") or report)
    return text


class GoldenTaskCase:
    """golden 任务的最小 case 形状（供 build_benchmark_api 的 mock 构造读取）。"""

    def __init__(self, task: str) -> None:
        self.task = task
        from competitor_agent.evaluation.benchmark import BenchmarkMockLLM

        names = BenchmarkMockLLM._registry_competitors(task)
        self.competitor = names[0] if len(names) == 1 else ""
        self.dimension = ""
        self.page = ""
        self.best_url = ""
        self.fail_urls: list[str] = []
        self.tags: list[str] = ["golden"]
        self.mode = "single"


class GoldenEvaluator:
    """黄金断言评测：3 个固定任务经 api.run() 真实生成报告 → 判定器逐条判定 → 指标聚合。"""

    def __init__(
        self,
        judge: GoldenJudge,
        build_api: Any,
        tasks: list[GoldenTask],
    ) -> None:
        self._judge = judge
        self._build_api = build_api
        self._tasks = tasks

    def run(self, on_task_done: Any = None) -> GoldenResult:
        result = GoldenResult(n_tasks=len(self._tasks))
        stale: list[str] = []
        total_must_covered = 0
        total_must = 0
        total_trap_passed = 0
        total_trap = 0
        contradicted = 0
        for task in self._tasks:
            stale.append(task.stale_note)
            if not task.task or not task.assertions:
                continue
            try:
                api = self._build_api(GoldenTaskCase(task.task))
                report = api.run(task.task)
                text = _report_text(report)
            except Exception:  # noqa: BLE001  # 单任务失败不影响其余任务（评测自身不炸流水线）
                text = ""
            m_covered = m_total = 0
            t_passed = t_total = 0
            for assertion in task.assertions:
                verdict = self._judge.judge(text, assertion)
                if assertion.type == "trap":
                    t_total += 1
                    if verdict == GoldenVerdict.passed:
                        t_passed += 1
                else:
                    m_total += 1
                    if verdict == GoldenVerdict.contradicted:
                        contradicted += 1
                    elif verdict == GoldenVerdict.covered:
                        m_covered += 1
            total_must += m_total
            total_must_covered += m_covered
            total_trap += t_total
            total_trap_passed += t_passed
            result.per_task[task.task_id] = {
                "must_have_recall": round(m_covered / m_total, 4) if m_total else 0.0,
                "trap_pass_rate": round(t_passed / t_total, 4) if t_total else 0.0,
                "n_must_have": float(m_total),
                "n_trap": float(t_total),
            }
            if on_task_done is not None:
                on_task_done(task.task_id)
        result.n_must_have = total_must
        result.n_trap = total_trap
        result.must_have_recall = round(total_must_covered / total_must, 4) if total_must else 0.0
        result.trap_pass_rate = round(total_trap_passed / total_trap, 4) if total_trap else 0.0
        result.contradicted_count = contradicted
        result.stale_warnings = [w for w in stale if w]
        return result
