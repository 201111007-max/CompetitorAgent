"""检索质量对照实验（设计文档 52 §2.3 / M3）：lexical / vector / hybrid recall@k 对比表

固定查询集从 benchmark fixtures（accuracy_cases.json）提炼：
- 语料：每个 case 的 page 文本作为一个 TextChunk（chunk_id=case_id）；
- 查询：case.task，按 (task, competitor, dimension) 去重（~18 条）；
- 标注相关条目：与查询同 (competitor, dimension) 的全部 chunk_id（topical 相关性）。

三模式复用生产检索路径 CompetitorStore.search_hybrid 的 alpha 扫描：
alpha=0 纯词袋 / alpha=1 纯向量 / alpha=0.5 生产默认融合，口径与线上一致。

embed_fn 默认 "hash"（确定性特征哈希，零网络，CI 可复现）；--embed auto 走真实
bge-small-zh（须先 `rag-warmup` 预缓存），对比表标注所用嵌入——hash 数据只验证
链路，真实结论以 bge 手动跑为准（设计文档 52 §7 风险 4）。
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.knowledge_base.vector_store import VectorStore
from competitor_agent.secret_vault import get_reports_dir

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "evaluation" / "fixtures"
ACCURACY_FIXTURE = "accuracy_cases.json"

# (模式名, alpha)：复用 search_hybrid 融合权重实现三模式，与生产检索同口径
MODES: tuple[tuple[str, float], ...] = (("lexical", 0.0), ("vector", 1.0), ("hybrid", 0.5))

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


@dataclass
class RetrievalCase:
    """一条对照查询：任务文本 + 标注相关条目（同竞品×维度的全部 chunk_id）。"""

    case_id: str
    query: str
    competitor: str
    dimension: str
    relevant_ids: list[str]


@dataclass
class ModeResult:
    """单模式召回结果：per_case recall@k；available=False 表示该模式未跑（记 n/a）。"""

    mode: str
    alpha: float
    per_case: dict[str, float]
    available: bool = True

    @property
    def mean(self) -> float | None:
        if not self.available or not self.per_case:
            return None
        return sum(self.per_case.values()) / len(self.per_case)


@dataclass
class CompareResult:
    top_k: int
    embed_label: str
    n_chunks: int
    cases: list[RetrievalCase]
    modes: list[ModeResult]


def load_cases(fixtures_dir: Path | None = None) -> tuple[list[TextChunk], list[RetrievalCase]]:
    """从 accuracy fixtures 提炼语料与固定查询集（确定性、可复核）。"""
    path = (Path(fixtures_dir) if fixtures_dir else FIXTURES_DIR) / ACCURACY_FIXTURE
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    chunks = [
        TextChunk(
            chunk_id=str(c["case_id"]),
            competitor=str(c["competitor"]),
            dimension=str(c["dimension"]),
            text=str(c["page"]),
            source_url=f"fixture://{c['case_id']}",
        )
        for c in raw
    ]
    relevant: dict[tuple[str, str], list[str]] = {}
    for c in raw:
        relevant.setdefault((str(c["competitor"]), str(c["dimension"])), []).append(
            str(c["case_id"])
        )
    cases: list[RetrievalCase] = []
    seen: set[tuple[str, str, str]] = set()
    for c in raw:
        key = (str(c["task"]), str(c["competitor"]), str(c["dimension"]))
        if key in seen:
            continue
        seen.add(key)
        cases.append(
            RetrievalCase(
                case_id=str(c["case_id"]),
                query=str(c["task"]),
                competitor=str(c["competitor"]),
                dimension=str(c["dimension"]),
                relevant_ids=relevant[(str(c["competitor"]), str(c["dimension"]))],
            )
        )
    return chunks, cases


def _chromadb_available() -> bool:
    try:
        import chromadb  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - 默认安装无 rag extra：向量/混合模式记 n/a
        return False


def run_compare(
    chunks: list[TextChunk],
    cases: list[RetrievalCase],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]] | str | None = "hash",
    top_k: int = 5,
    embed_label: str | None = None,
) -> CompareResult:
    """三模式跑固定查询集，返回逐查询 recall@k。语料库建在临时目录，不污染用户知识库。"""
    label = embed_label or (
        embed_fn
        if isinstance(embed_fn, str)
        else (DEFAULT_MODEL if embed_fn is None else str(getattr(embed_fn, "__name__", "custom")))
    )
    with tempfile.TemporaryDirectory(prefix="retrieval_compare_") as tmp:
        vs = VectorStore(embed_fn=embed_fn, data_dir=Path(tmp) / "vs")
        vector_ok = _chromadb_available() and vs.is_available()
        store = CompetitorStore(data_dir=tmp, vector_store=vs if vector_ok else None)
        store.add_many(chunks)
        modes: list[ModeResult] = []
        for name, alpha in MODES:
            if alpha > 0 and not vector_ok:
                modes.append(ModeResult(mode=name, alpha=alpha, per_case={}, available=False))
                continue
            per_case: dict[str, float] = {}
            for case in cases:
                hits = store.search_hybrid(case.query, top_k=top_k, alpha=alpha)
                recalled = {c.chunk_id for c, _s, _src in hits}
                rel = set(case.relevant_ids)
                per_case[case.case_id] = len(rel & recalled) / len(rel) if rel else 0.0
            modes.append(ModeResult(mode=name, alpha=alpha, per_case=per_case))
    return CompareResult(
        top_k=top_k, embed_label=label, n_chunks=len(chunks), cases=cases, modes=modes
    )


def render_compare_table(result: CompareResult) -> str:
    """Markdown 对比表：行=查询，列=三模式 recall@k，末行均值（最优加粗）。"""
    lines = [
        "# 检索质量对照：lexical / vector / hybrid（设计文档 52 §2.3）",
        f"\n> generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        (
            f"> fixtures: {ACCURACY_FIXTURE} | chunks: {result.n_chunks} | "
            f"queries: {len(result.cases)} | embed: {result.embed_label} | recall@{result.top_k}"
        ),
        (
            "\n> 模式：lexical=纯词袋（alpha=0）/ vector=纯向量（alpha=1）/ hybrid=生产默认融合"
            "（alpha=0.5），均走 CompetitorStore.search_hybrid 同一路径。"
            "相关条目=与查询同 (competitor, dimension) 的 fixture 片段；"
            "n/a=该模式不可用（chromadb 未安装或模型未缓存）。hash 嵌入仅验证链路，"
            "真实结论以 `--embed auto`（bge）手动跑为准。"
        ),
        "\n| 查询（case） | 竞品×维度 | 相关数 | "
        + " | ".join(f"{m.mode} recall" for m in result.modes)
        + " |",
        "|---|---|---|" + "---|" * len(result.modes),
    ]
    for case in result.cases:
        cells = []
        for m in result.modes:
            v = m.per_case.get(case.case_id)
            cells.append(f"{v:.2f}" if v is not None else "n/a")
        lines.append(
            f"| {case.case_id} | {case.competitor}×{case.dimension} | "
            f"{len(case.relevant_ids)} | " + " | ".join(cells) + " |"
        )
    means = [m.mean for m in result.modes]
    valid = [v for v in means if v is not None]
    best = max(valid) if valid else None
    cells = [
        (f"**{v:.4f}**" if v == best else f"{v:.4f}") if v is not None else "n/a"
        for v in means
    ]
    lines.append("| **均值** | — | — | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_compare_report(result: CompareResult, out_dir: Path | None = None) -> Path:
    """对比表落盘 <data_dir>/reports/retrieval_compare_<date>.md（仓库外）。"""
    out = Path(out_dir) if out_dir else get_reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = out / f"retrieval_compare_{date}.md"
    path.write_text(render_compare_table(result), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="retrieval_compare",
        description="检索质量对照：lexical/vector/hybrid recall@k 对比表（设计文档 52 M3）",
    )
    parser.add_argument(
        "--embed",
        choices=["hash", "auto"],
        default="hash",
        help="嵌入：hash=确定性特征哈希（默认，CI 可复现）；auto=真实 bge 模型（须先 rag-warmup）",
    )
    parser.add_argument("--top-k", type=int, default=5, help="recall@k 的 k（默认 5）")
    parser.add_argument("--fixtures-dir", type=Path, default=None, help="fixtures 目录（缺省 tests/evaluation/fixtures）")
    parser.add_argument("--out", type=Path, default=None, help="报告输出目录（缺省 <data_dir>/reports）")
    args = parser.parse_args(argv)

    embed_fn: Callable[[list[str]], list[list[float]]] | str | None = (
        "hash" if args.embed == "hash" else None
    )
    label = "hash（确定性特征哈希）" if args.embed == "hash" else f"sentence-transformers:{DEFAULT_MODEL}"
    chunks, cases = load_cases(args.fixtures_dir)
    result = run_compare(chunks, cases, embed_fn=embed_fn, top_k=args.top_k, embed_label=label)
    path = write_compare_report(result, args.out)
    print(f"查询集: {len(cases)} 条 | 语料: {result.n_chunks} chunks | embed: {result.embed_label}")
    for m in result.modes:
        mean = f"{m.mean:.4f}" if m.mean is not None else "n/a"
        print(f"  {m.mode:8s} recall@{result.top_k} 均值: {mean}")
    print(f"对比表已写入: {path}")
    return 0


__all__ = [
    "ACCURACY_FIXTURE",
    "FIXTURES_DIR",
    "MODES",
    "CompareResult",
    "ModeResult",
    "RetrievalCase",
    "load_cases",
    "main",
    "render_compare_table",
    "run_compare",
    "write_compare_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
