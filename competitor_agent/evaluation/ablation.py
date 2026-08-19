"""消融 / 对比实验（设计文档 30 / 47）：有无 RAG / 有无 memory

AblationRunner 对同一批确定性评测用例逐变体跑 Benchmark，产出「变体 × 指标」对比表，
回答简历/面试必问：加 RAG / 加记忆到底有没有用。

- 组件开关：CompetitorAnalysisAPI(enable_rag / enable_memory)，默认开启行为不变；
- 变体矩阵（设计文档 47 删 no-llm-rule，主路径仅 LLM；设计文档 49 加 no-tools）：
  full / no-rag / no-memory / no-rag+no-memory / no-tools 共 5 组
  （no-tools = Lead 只 make_plan 后直接 Final Answer，不委派/不采集，测多 Agent 委派价值）；
- 按变体隔离并共享记忆与知识库：同一变体内跨用例累积（技能/成功率/检索片段），
  使 RAG / 记忆差分可测（no-rag 检索不到先前摄入的片段、no-memory 无技能提升）。
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.evaluation.benchmark import (
    ACCURACY_FIXTURE,
    FIXTURES_DIR,
    HARNESS_VERSION,
    STRATEGY_FIXTURE,
    Benchmark,
    BenchmarkExtractor,
    BenchmarkMockLLM,
    BenchmarkReport,
)
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.knowledge_base.competitor_store import CompetitorStore
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory.four_layer_memory import FourLayerMemory


@dataclass(frozen=True)
class AblationVariant:
    """一个消融配置：开关组合 + 名称"""

    name: str
    enable_rag: bool = True
    enable_memory: bool = True
    use_llm: bool = True
    no_tools: bool = False  # 设计文档 49：去掉委派/工具循环（测 LLM 主导编排的委派价值）


# 消融变体矩阵（设计文档 30 §2 / 47 / 49）：全链路 / 关 RAG / 关记忆 / 双关 / 无工具
DEFAULT_VARIANTS: tuple[AblationVariant, ...] = (
    AblationVariant("full"),
    AblationVariant("no-rag", enable_rag=False),
    AblationVariant("no-memory", enable_memory=False),
    AblationVariant("no-rag+no-memory", enable_rag=False, enable_memory=False),
    AblationVariant("no-tools", no_tools=True),
)

# 对比表行：显示名 / AblationResult 属性 / 是否越高越好（幻觉率与命中排名越低越好）
_METRIC_ROWS: list[tuple[str, str, bool]] = [
    ("字段准确率", "field_accuracy", True),
    ("幻觉率", "hallucination_rate", False),
    ("F1", "f1", True),
    ("工具选择准确率", "tool_selection_accuracy", True),
    ("成本效率", "cost_efficiency", True),
    ("平均命中排名", "avg_source_rank", False),
]


@dataclass
class AblationResult:
    """某变体下整批用例的评测结果 + 派生指标"""

    variant: AblationVariant
    report: BenchmarkReport

    @property
    def field_accuracy(self) -> float:
        return self.report.accuracy.field_accuracy

    @property
    def hallucination_rate(self) -> float:
        return self.report.accuracy.hallucination_rate

    @property
    def f1(self) -> float:
        return self.report.accuracy.f1

    @property
    def tool_selection_accuracy(self) -> float:
        return self.report.strategy.tool_selection_accuracy

    @property
    def cost_efficiency(self) -> float:
        return self.report.strategy.cost_efficiency

    @property
    def avg_source_rank(self) -> float:
        return self.report.strategy.avg_source_rank

    @property
    def n_cases(self) -> int:
        return self.report.n_cases

    def metrics(self) -> dict[str, float]:
        return {
            "field_accuracy": self.field_accuracy,
            "hallucination_rate": self.hallucination_rate,
            "f1": self.f1,
            "tool_selection_accuracy": self.tool_selection_accuracy,
            "cost_efficiency": self.cost_efficiency,
            "avg_source_rank": self.avg_source_rank,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": {
                "name": self.variant.name,
                "enable_rag": self.variant.enable_rag,
                "enable_memory": self.variant.enable_memory,
                "use_llm": self.variant.use_llm,
            },
            "n_cases": self.n_cases,
            "trace_completeness": self.report.trace_completeness,
            "metrics": self.metrics(),
            "per_case_accuracy": self.report.accuracy.per_case,
            "per_case_strategy": self.report.strategy.per_case,
            "hallucination_instances": self.report.accuracy.hallucination_instances,
        }


class AblationRunner:
    """逐变体构造 API（共享记忆/知识库按变体累积），对同一批用例真实执行。"""

    def __init__(
        self,
        fixtures_dir: Path | None = None,
        llm_mode: str = "mock",
        memory_dir: Path | None = None,
    ) -> None:
        self._dir = Path(fixtures_dir) if fixtures_dir else FIXTURES_DIR
        self._llm_mode = llm_mode
        # 记忆/知识库隔离目录：缺省用临时目录（不污染真实用户记忆），测试/CI 可注入 tmp_path
        self._memory_dir = Path(memory_dir) if memory_dir else Path(tempfile.mkdtemp(prefix="ablation_"))

    def run(self, variants: list[AblationVariant] | None = None) -> list[AblationResult]:
        variants = list(variants or DEFAULT_VARIANTS)
        results: list[AblationResult] = []
        for index, variant in enumerate(variants):
            memory = self._new_memory(variant, index)
            store = self._new_store(variant, index)
            bench = Benchmark(
                fixtures_dir=self._dir,
                llm_mode=self._llm_mode,
                build_api=lambda case, _v=variant, _mem=memory, _st=store: self._make_api(_v, case, _mem, _st),
            )
            results.append(AblationResult(variant=variant, report=bench.run()))
        return results

    def _make_api(
        self,
        variant: AblationVariant,
        case: object,
        memory: FourLayerMemory | None,
        store: CompetitorStore | None,
    ) -> CompetitorAnalysisAPI:
        """按变体构造 API：llm/use_llm 由变体决定，extractor 按用例取固定页面（确定性采集）。"""
        # 设计文档 47/49：主路径仅 LLM；mock ReAct-scripted，确定性取自用例
        if self._llm_mode == "mock":
            mock = BenchmarkMockLLM(
                competitor=str(getattr(case, "competitor", "")),
                dimension=str(getattr(case, "dimension", "")),
                page=str(getattr(case, "page", "") or ""),
                best_url=str(getattr(case, "best_url", "") or ""),
                fail_urls=list(getattr(case, "fail_urls", None) or ()),
                no_tools=variant.no_tools,
            )
            llm: LLMClient | None = LLMClient(call_func=mock.complete)
        elif self._llm_mode == "real":
            llm = LLMClient()
        else:
            llm = None
        # URL 守卫（DNS 解析）在无网络评测环境对所有真实域名抛错，会掩盖 fail_urls/page 的
        # 确定性分发；消融与 benchmark 同口径：由 BenchmarkExtractor 直接供给页面内容/失败。
        cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
        return CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(
                page=getattr(case, "page", ""),
                fail_urls=set(getattr(case, "fail_urls", None) or ()),
            ),
            llm=llm,
            use_llm=True,
            max_iterations=8,
            cost_limit=1.0,
            enable_rag=variant.enable_rag,
            enable_memory=variant.enable_memory,
            memory=memory,
            rag_store=store,
            config=cfg,
        )

    def _new_memory(self, variant: AblationVariant, index: int) -> FourLayerMemory | None:
        """记忆开启的变体给独立的四层记忆实例（跨用例累积技能/成功率）。"""
        if not variant.enable_memory:
            return None
        return FourLayerMemory(self._memory_dir / f"memory_{index}")

    def _new_store(self, variant: AblationVariant, index: int) -> CompetitorStore | None:
        """RAG 开启的变体给独立的共享知识库实例（跨用例累积可检索片段）。"""
        if not variant.enable_rag:
            return None
        return CompetitorStore(data_dir=self._memory_dir / f"kb_{index}")


def render_ablation_table(results: list[AblationResult]) -> str:
    """Markdown 对比表：行=指标，列=变体，每行标出最优（幻觉率/命中排名取小）。"""
    if not results:
        return "# 消融实验对比（设计文档 30）\n\n（无结果）\n"
    lines = [
        "# 消融 / 对比实验（设计文档 30）",
        f"\n> generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"> fixtures: {ACCURACY_FIXTURE} + {STRATEGY_FIXTURE} | cases: {results[0].n_cases} | harness v{HARNESS_VERSION}",
        "\n> 变体：full=完整链路 / no-rag=关 RAG / no-memory=关四层记忆 / no-rag+no-memory=双关（主路径仅 LLM）/ no-tools=Lead 不委派不采集。粗体=该行最优。",
        "\n| 指标 | " + " | ".join(r.variant.name for r in results) + " |",
        "|------|" + "------|" * len(results),
    ]
    for label, attr, higher in _METRIC_ROWS:
        values = [getattr(r, attr) for r in results]
        best = max(values) if higher else min(values)
        cells = []
        for v in values:
            s = f"{v:.4f}"
            cells.append(f"**{s}**" if v == best else s)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    if len(results) >= 2:
        full = results[0].hallucination_rate
        lines.append("\n## 幻觉率差分 vs full（门禁：full ≤ 各 no-* 变体，证明 RAG/记忆有效）")
        for r in results[1:]:
            diff = r.hallucination_rate - full
            mark = "[OK] 不差于 full" if diff <= 0 else f"[WARN] +{diff:.4f}"
            lines.append(f"- **{r.variant.name}**: {r.hallucination_rate:.4f}（{mark}）")
    return "\n".join(lines) + "\n"


def write_ablation_json(results: list[AblationResult], out: Path) -> None:
    """稳定 schema 落盘：variants（含逐 case 明细）/ metrics / harness_version。"""
    data: dict[str, Any] = {
        "harness_version": HARNESS_VERSION,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixtures": [ACCURACY_FIXTURE, STRATEGY_FIXTURE],
        "variants": [r.to_dict() for r in results],
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_ablation_report(results: list[AblationResult], out_dir: Path) -> list[Path]:
    """对比表 + JSON 一并落盘 <data_dir>/reports/ablation/ablation_<date>.md/.json。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    md_path = out_dir / f"ablation_{date}.md"
    json_path = out_dir / f"ablation_{date}.json"
    md_path.write_text(render_ablation_table(results), encoding="utf-8")
    write_ablation_json(results, json_path)
    return [md_path, json_path]


__all__ = [
    "DEFAULT_VARIANTS",
    "AblationResult",
    "AblationRunner",
    "AblationVariant",
    "render_ablation_table",
    "write_ablation_json",
    "write_ablation_report",
]
