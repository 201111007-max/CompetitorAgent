"""设计文档 78 §4.2 — CompetitorAnalysisAPI 公共签名冻结单测。

拆分前基线（``_api_signature_baseline_78.json``）由重构前的 api.py 生成；
本测试逐位比对公共方法/属性的 ``inspect.signature`` 与 kind（sync/async/property），
防止后续演进无意破坏 web/CLI/MCP/benchmark 四入口依赖的门面契约。
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from competitor_agent.facade.api import CompetitorAnalysisAPI

_BASELINE = Path(__file__).with_name("_api_signature_baseline_78.json")
_FACADE_DIR = Path(__file__).resolve().parents[3] / "facade"


def _snapshot() -> dict[str, dict[str, str]]:
    snap: dict[str, dict[str, str]] = {}
    baseline: dict[str, dict[str, str]] = json.loads(_BASELINE.read_text(encoding="utf-8"))
    for name in baseline:
        attr = inspect.getattr_static(CompetitorAnalysisAPI, name)
        fn = attr.fget if isinstance(attr, property) else getattr(CompetitorAnalysisAPI, name)
        kind = (
            "property"
            if isinstance(attr, property)
            else ("async" if inspect.iscoroutinefunction(fn) else "sync")
        )
        snap[name] = {"kind": kind, "signature": str(inspect.signature(fn))}
    return snap


def test_public_signatures_frozen_bit_for_bit() -> None:
    baseline: dict[str, dict[str, str]] = json.loads(_BASELINE.read_text(encoding="utf-8"))
    current = _snapshot()
    assert set(current) == set(baseline), "公共面成员集发生变化（新增/删除需显式更新基线）"
    for name, expected in baseline.items():
        assert current[name]["kind"] == expected["kind"], f"{name}: kind 漂移"
        sig_now = current[name]["signature"]
        sig_base = expected["signature"]
        assert sig_now == sig_base, f"{name}: 签名漂移（doc 78 §4.2 签名冻结被破坏）"


def test_no_reverse_import_of_api_in_services() -> None:
    """doc 78 §4.3：services 不 import api（循环依赖防护）。"""
    offenders: list[str] = []
    for py in ("analysis_service.py", "compare_service.py", "schedule_service.py", "assembly.py"):
        tree = ast.parse((_FACADE_DIR / py).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(".api"):
                offenders.append(py)
            if isinstance(node, ast.Import) and any(a.name.endswith(".api") for a in node.names):
                offenders.append(py)
    assert offenders == [], f"服务/装配层反向 import api: {offenders}"


def test_facade_file_size_budget() -> None:
    """doc 78 §4.3：api.py ≤ 320 行（300 基线 + doc96 新增 run_conversation 公共入口，设计文档 96）；
    analysis_service 豁免见迁移表——闭包组整体迁移。"""
    assert len((_FACADE_DIR / "api.py").read_text(encoding="utf-8").splitlines()) <= 320
    for py in ("compare_service.py", "schedule_service.py", "assembly.py"):
        assert len((_FACADE_DIR / py).read_text(encoding="utf-8").splitlines()) <= 600, py
