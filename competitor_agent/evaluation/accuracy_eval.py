"""AccuracyEval — 字段准确率 / F1 / 幻觉率评测（3.3）

对标注用例算预测（prediction）vs 真值（ground_truth）的指标：
- field_accuracy = 字段级 exact-match 命中 / 字段总数
- f1 = 字段级平均 token-F1（precision/recall 调和）
- hallucination_rate = 预测字段缺乏真值支持的比例（比例幻觉）

prediction / ground_truth 均为 {field: value}。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCase:
    """单条评测用例"""
    task: str
    prediction: dict[str, Any]
    ground_truth: dict[str, Any]
    case_id: str = ""
    competitor: str = ""
    dimension: str = ""
    tags: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AccuracyMetrics:
    field_accuracy: float = 0.0
    hallucination_rate: float = 0.0
    f1: float = 0.0
    per_field: dict[str, dict[str, float]] = field(default_factory=dict)
    hallucination_instances: list[dict[str, Any]] = field(default_factory=list)
    # 逐 case 明细（设计文档 29：空数据"不编造"护栏按 case 独立门禁）
    per_case: list[dict[str, Any]] = field(default_factory=list)


def _normalize(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, set, tuple)):
        return " ".join(_normalize(v) for v in value)
    text = str(value).strip().lower()
    # 归一化：去货币符号、单位标准化、去标点
    text = text.replace("$", "").replace("¥", "").replace("€", "")
    text = text.replace("/month", " per month").replace("/月", " per month")
    text = text.replace("/year", " per year").replace("/年", " per year")
    text = text.replace("/user", " per user").replace("/人", " per user")
    text = text.replace("/mo", " per month")
    text = text.replace("/hour", " per hour").replace("/h", " per hour")
    text = text.replace(",", "").replace("，", "")
    # 去多余空格后分词重排（消除词序差异）
    return " ".join(text.split())


def _tokens(text: str) -> set[str]:
    return set(text.split())


def _f1(pred: str, truth: str) -> float:
    p = _tokens(pred)
    t = _tokens(truth)
    if p == t == set():
        return 1.0
    if not p or not t:
        return 0.0
    inter = p & t
    precision = len(inter) / len(p)
    recall = len(inter) / len(t)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


class AccuracyEvaluator:
    """计算字段准确率 / F1 / 幻觉率（prediction vs ground_truth）"""

    def evaluate(self, cases: list[EvalCase]) -> AccuracyMetrics:
        field_scores: list[float] = []
        f1s: list[float] = []
        per_field: dict[str, dict[str, float]] = {}
        total_pred = 0
        supported = 0
        hallucination_instances: list[dict[str, Any]] = []
        per_case: list[dict[str, Any]] = []

        for case in cases:
            case_hits = 0.0
            case_fields = 0
            case_pred = 0
            case_supported = 0
            for field_name, truth in case.ground_truth.items():
                pred = case.prediction.get(field_name, "")
                np_ = _normalize(pred)
                nt = _normalize(truth)
                is_match = np_ == nt
                field_scores.append(1.0 if is_match else 0.0)
                f1s.append(_f1(np_, nt))

                # 字段级 flag 聚合
                pf = per_field.setdefault(field_name, {"total": 0.0, "hits": 0.0, "f1": 0.0})
                pf["total"] += 1
                pf["hits"] += 1.0 if is_match else 0.0
                pf["f1"] += _f1(np_, nt)

                case_fields += 1
                case_hits += 1.0 if is_match else 0.0

                # 幻觉：预测了"真值里 token 完全没有"的字段
                if pred:
                    total_pred += 1
                    case_pred += 1
                    if np_ and set(np_.split()) & _tokens(nt):
                        supported += 1
                        case_supported += 1
                    else:
                        hallucination_instances.append(
                            {
                                "case_id": case.case_id,
                                "task": case.task,
                                "field": field_name,
                                "prediction": pred,
                                "ground_truth": truth,
                            }
                        )

            per_case.append(
                {
                    "case_id": case.case_id,
                    "task": case.task,
                    "dimension": case.dimension,
                    "field_accuracy": round(case_hits / case_fields, 4) if case_fields else 1.0,
                    "hallucination_rate": round((case_pred - case_supported) / case_pred, 4) if case_pred else 0.0,
                }
            )

        if not field_scores:
            return AccuracyMetrics()

        # 幻觉率 = 预测字段中无任何真值 token 支撑的比例
        halluc = (total_pred - supported) / total_pred if total_pred else 0.0

        per_field_summary = {
            k: {"accuracy": round(v["hits"] / v["total"], 4), "f1": round(v["f1"] / v["total"], 4)}
            for k, v in per_field.items()
        }

        return AccuracyMetrics(
            field_accuracy=round(sum(field_scores) / len(field_scores), 4),
            hallucination_rate=round(halluc, 4),
            f1=round(sum(f1s) / len(f1s), 4),
            per_field=per_field_summary,
            hallucination_instances=hallucination_instances,
            per_case=per_case,
        )


__all__ = ["AccuracyEvaluator", "AccuracyMetrics", "EvalCase"]