"""Deterministic retrieval, abstention, and latency metrics."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Any, Iterable


DEFAULT_K_VALUES = (1, 5, 10)


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def recall_any(ranked: Iterable[str], relevant: Iterable[str], k: int) -> float:
    gold = set(_dedupe(relevant))
    if not gold:
        return 0.0
    return float(bool(gold.intersection(_dedupe(ranked)[:k])))


def recall_all(ranked: Iterable[str], relevant: Iterable[str], k: int) -> float:
    gold = set(_dedupe(relevant))
    if not gold:
        return 0.0
    return float(gold.issubset(set(_dedupe(ranked)[:k])))


def evidence_recall(ranked: Iterable[str], relevant: Iterable[str], k: int) -> float:
    gold = set(_dedupe(relevant))
    if not gold:
        return 0.0
    return len(gold.intersection(_dedupe(ranked)[:k])) / len(gold)


def reciprocal_rank(ranked: Iterable[str], relevant: Iterable[str]) -> float:
    gold = set(_dedupe(relevant))
    for index, document_id in enumerate(_dedupe(ranked), start=1):
        if document_id in gold:
            return 1.0 / index
    return 0.0


def ndcg_at_k(ranked: Iterable[str], relevant: Iterable[str], k: int) -> float:
    gold = set(_dedupe(relevant))
    if not gold:
        return 0.0
    ranked_ids = _dedupe(ranked)[:k]
    dcg = sum((1.0 / math.log2(index + 2)) for index, document_id in enumerate(ranked_ids) if document_id in gold)
    ideal_count = min(len(gold), k)
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return dcg / ideal if ideal else 0.0


def upstream_longmemeval_ndcg_at_k(ranked: Iterable[str], relevant: Iterable[str], k: int) -> float:
    """Reproduce LongMemEval's published evaluator, including its discount quirk."""

    gold = set(_dedupe(relevant))
    if not gold:
        return 0.0
    relevance = [1.0 if value in gold else 0.0 for value in _dedupe(ranked)[:k]]

    def upstream_dcg(values: list[float]) -> float:
        if not values:
            return 0.0
        # Upstream uses log2(arange(2, n + 1)); rank two is therefore undiscounted.
        return values[0] + sum(value / math.log2(index) for index, value in enumerate(values[1:], start=2))

    ideal = [1.0] * min(len(gold), k) + [0.0] * max(0, k - len(gold))
    denominator = upstream_dcg(ideal)
    return upstream_dcg(relevance) / denominator if denominator else 0.0


def percentile(values: Iterable[float], percentile_value: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile_value
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def score_case(
    *,
    case_id: str,
    category: str,
    ranked_document_ids: Iterable[str],
    relevant_document_ids: Iterable[str],
    forbidden_document_ids: Iterable[str] = (),
    expected_abstain: bool,
    latency_seconds: float,
    k_values: Iterable[int] = DEFAULT_K_VALUES,
    retrieval_scorable: bool | None = None,
    exclusion_reason: str = "",
) -> dict[str, Any]:
    ranked = _dedupe(ranked_document_ids)
    relevant = _dedupe(relevant_document_ids)
    forbidden = set(_dedupe(forbidden_document_ids))
    predicted_abstain = len(ranked) == 0
    scorable = bool(expected_abstain or relevant) if retrieval_scorable is None else bool(retrieval_scorable)
    result: dict[str, Any] = {
        "case_id": case_id,
        "category": category,
        "ranked_document_ids": ranked,
        "relevant_document_ids": relevant,
        "forbidden_document_ids": sorted(forbidden),
        "expected_abstain": bool(expected_abstain),
        "predicted_abstain": predicted_abstain,
        "latency_seconds": float(latency_seconds),
        "retrieval_scorable": scorable,
        "exclusion_reason": str(exclusion_reason or ""),
    }
    cutoffs = sorted(set(int(value) for value in k_values if int(value) > 0))
    if scorable and relevant and not expected_abstain:
        maximum_cutoff = max(cutoffs)
        result[f"mrr@{maximum_cutoff}"] = reciprocal_rank(ranked[:maximum_cutoff], relevant)
        for k in cutoffs:
            result[f"recall_any@{k}"] = recall_any(ranked, relevant, k)
            result[f"recall_all@{k}"] = recall_all(ranked, relevant, k)
            result[f"evidence_recall@{k}"] = evidence_recall(ranked, relevant, k)
            result[f"ndcg@{k}"] = ndcg_at_k(ranked, relevant, k)
            result[f"upstream_longmemeval_ndcg@{k}"] = upstream_longmemeval_ndcg_at_k(ranked, relevant, k)
    for k in cutoffs:
        result[f"forbidden_exposure@{k}"] = float(bool(forbidden.intersection(ranked[:k])))
    return result


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if key in row]
    return mean(values) if values else None


def _abstention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in rows if row.get("retrieval_scorable")]
    tp = sum(1 for row in rows if row.get("expected_abstain") and row.get("predicted_abstain"))
    fp = sum(1 for row in rows if not row.get("expected_abstain") and row.get("predicted_abstain"))
    fn = sum(1 for row in rows if row.get("expected_abstain") and not row.get("predicted_abstain"))
    tn = sum(1 for row in rows if not row.get("expected_abstain") and not row.get("predicted_abstain"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "scored_cases": len(rows),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def aggregate_scores(rows: list[dict[str, Any]], *, k_values: Iterable[int]) -> dict[str, Any]:
    cutoffs = sorted(set(int(value) for value in k_values if int(value) > 0))
    metric_names = [f"mrr@{max(cutoffs)}"]
    for k in cutoffs:
        metric_names.extend(
            (
                f"recall_any@{k}",
                f"recall_all@{k}",
                f"evidence_recall@{k}",
                f"ndcg@{k}",
                f"upstream_longmemeval_ndcg@{k}",
                f"forbidden_exposure@{k}",
            )
        )
    metrics = {name: _mean_metric(rows, name) for name in metric_names}
    metrics = {name: value for name, value in metrics.items() if value is not None}
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[str(row.get("category") or "unknown")].append(row)
    category_metrics = {
        category: {
            "cases": len(category_rows),
            "metrics": {
                name: value
                for name in metric_names
                if (value := _mean_metric(category_rows, name)) is not None
            },
            "abstention": _abstention_metrics(category_rows),
        }
        for category, category_rows in sorted(by_category.items())
    }
    latencies = [float(row.get("latency_seconds") or 0.0) for row in rows]
    exclusion_counts: dict[str, int] = {}
    for row in rows:
        if row.get("retrieval_scorable"):
            continue
        reason = str(row.get("exclusion_reason") or "unspecified")
        exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
    return {
        "cases": len(rows),
        "retrieval_scored_cases": sum(1 for row in rows if row.get("relevant_document_ids") and not row.get("expected_abstain")),
        "abstention_scored_cases": sum(1 for row in rows if row.get("retrieval_scorable")),
        "unscored_retrieval_cases": sum(1 for row in rows if not row.get("retrieval_scorable")),
        "exclusions": dict(sorted(exclusion_counts.items())),
        "metrics": metrics,
        "abstention": _abstention_metrics(rows),
        "latency_seconds": {
            "mean": mean(latencies) if latencies else None,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "by_category": category_metrics,
    }
