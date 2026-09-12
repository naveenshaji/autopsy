"""Private, deterministic evidence retrieval evaluation on a frozen local snapshot.

Run with python -m autopsy_memory.evaluation. No model judge or network calls.
Gold cases and reports belong outside the repository.
"""
import argparse
import hashlib
import json
import math
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def validate_suite(suite):
    cases = suite.get("cases")
    if suite.get("schema_version") != 1 or not isinstance(cases, list) or not cases:
        raise ValueError("Expected schema_version 1 and a nonempty cases list")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not case.get("id") or case["id"] in seen or not case.get("query"):
            raise ValueError("Each case needs a unique id and a query")
        seen.add(case["id"])
        expected = case.get("expected_any", [])
        forbidden = case.get("forbidden", [])
        if any(not isinstance(keys, list) or any(not isinstance(key, str) or not key for key in keys)
               for keys in (expected, forbidden)):
            raise ValueError("expected_any and forbidden must be stable-key lists")
        if bool(expected) == bool(case.get("must_abstain")) or set(expected).intersection(forbidden):
            raise ValueError("Specify expected_any or must_abstain, with disjoint forbidden keys")
    return cases


def score_case(case, payload, elapsed_s):
    retrieval = payload.get("retrieval") or {}
    items = retrieval.get("items") or []
    keys = [item.get("stable_key") for item in items]
    expected = set(case.get("expected_any") or [])
    rank = next((index + 1 for index, key in enumerate(keys) if key in expected), None)
    unsafe = sorted(set(keys).intersection(case.get("forbidden") or []))
    stale = [item.get("stable_key") for item in items if item.get("lineage", {}).get("current") is False]
    complete = bool(payload.get("workflow", {}).get("complete"))
    # Abstention requires no asserted evidence, even if a workflow flag is false.
    evidence_ok = not keys and not complete if case.get("must_abstain") else rank is not None
    block = payload.get("context_block") or ""
    return {
        "id": case["id"], "category": case.get("category", "uncategorized"),
        "passed": evidence_ok and not unsafe and (not stale or bool(case.get("allow_stale"))),
        "evidence_found": rank is not None, "reciprocal_rank": 1 / rank if rank else 0,
        "rank": rank, "retrieved_keys": keys, "forbidden_keys": unsafe, "stale_keys": stale,
        "workflow_complete": complete, "must_abstain": bool(case.get("must_abstain")),
        "latency_s": round(elapsed_s, 4), "context_chars": len(block),
        "context_truncated": bool(payload.get("context_budget", {}).get("truncated")),
        "context_evidence_found": any(f"[{key}]" in block for key in expected),
    }


def summarize(results):
    answerable = [result for result in results if not result["must_abstain"]]
    latencies = sorted(result["latency_s"] for result in results)
    return {
        "cases": len(results), "passed": sum(result["passed"] for result in results),
        "evidence_recall": sum(result["evidence_found"] for result in answerable) / len(answerable) if answerable else None,
        "mean_reciprocal_rank": statistics.mean(result["reciprocal_rank"] for result in answerable) if answerable else None,
        "context_evidence_recall": sum(result.get("context_evidence_found", False) for result in answerable) / len(answerable) if answerable else None,
        "forbidden_cases": sum(bool(result["forbidden_keys"]) for result in results),
        "stale_cases": sum(bool(result["stale_keys"]) for result in results),
        "latency_p50_s": statistics.median(latencies),
        "latency_p95_s": latencies[max(0, math.ceil(len(latencies) * .95) - 1)],
        "mean_context_chars": statistics.mean(result["context_chars"] for result in results),
    }


def add_arguments(parser):
    parser.add_argument("suite", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True, help="Verified Autopsy backup; never the live graph")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--frozen-db", type=Path, help="Optional previously restored evaluation graph; copied before use")
    parser.add_argument("--baseline", type=Path, help="Compare identical suite/snapshot and fail on newly failing cases")


def run(args):
    suite_bytes = args.suite.read_bytes()
    suite = json.loads(suite_bytes)
    cases = validate_suite(suite)
    from . import cli
    snapshot = cli.load_restore_json(str(args.snapshot))
    available = {item["stable_key"] for item in snapshot["items"]}
    for case in cases:
        missing = set(case.get("expected_any", []) + case.get("forbidden", [])) - available
        if missing:
            raise ValueError(f"Case {case['id']} refers to absent snapshot keys: {sorted(missing)}")
    results = []
    cli.configure_falkordblite_runtime()
    with tempfile.TemporaryDirectory(prefix="autopsy-private-evaluation-") as temporary:
        database = Path(temporary) / "evaluation.db"
        if args.frozen_db:
            shutil.copy2(args.frozen_db, database)
        client = cli.load_falkordblite()(str(database))
        try:
            graph = client.select_graph("evaluation")
            workspace = {"id": "evaluation", "root_path": temporary, "slug": "evaluation", "title": "Private evaluation"}
            cli.ensure_runtime_indexes(graph)
            if not args.frozen_db:
                cli.restore_memory_payload(graph, workspace=workspace, input_path=str(args.snapshot), payload=snapshot,
                                           dry_run=False, replace=False, include_operational=True)
            before = cli.export_memory_payload(graph, workspace=workspace, include_operational=True)
            from collections import Counter
            def canonical(payload):
                return ({item["stable_key"]: {key: value for key, value in item.items() if key != "entity_id"}
                         for item in payload["items"]},
                        Counter(json.dumps(edge, sort_keys=True) for edge in payload["relations"]),
                        Counter(json.dumps(edge, sort_keys=True) for edge in payload["structural_edges"]))
            if canonical(before) != canonical(snapshot):
                raise ValueError("Frozen database does not match snapshot content and relationships")
            with patch.object(cli, "record_memory_access", return_value={"updated": 0, "evaluation": True}):
                for case in cases:
                    start = time.perf_counter()
                    payload = cli.build_context_payload(
                        graph, tool=cli.FalkorToolShim, workspace=workspace, config=dict(cli.EMBEDDINGS_CONFIG_DEFAULT),
                        query=case["query"], limit=8, inspect_limit=8, status_limit=6, section_limit=3,
                        recent_days=21, max_chars=6000, route="lexical", scope=case.get("scope", "system"),
                        repository_root_path=case.get("repo"), as_of=suite.get("as_of"),
                        metadata=case.get("metadata"),
                    )
                    results.append(score_case(case, payload, time.perf_counter() - start))
                    print(f"{len(results)}/{len(cases)} {case['id']}: {'PASS' if results[-1]['passed'] else 'FAIL'}", flush=True)
            after = cli.export_memory_payload(graph, workspace=workspace, include_operational=True)
            for section in ("items", "relations", "structural_edges"):
                if before[section] != after[section]:
                    raise RuntimeError(f"Evaluation mutated {section}")
        finally:
            client.close()
    report = {
        "schema_version": 1, "policy": "frozen_lexical_evidence_v1", "answer_accuracy_measured": False,
        "implementation_sha256": hashlib.sha256(Path(cli.__file__).read_bytes()).hexdigest(),
        "gold_review": suite.get("gold_review", "unreviewed"),
        "limitations": ["Evidence retrieval, not generated-answer accuracy", "Lexical route; semantic embeddings not evaluated",
                        "Agent-authored gold needs user review; no model judge"],
        "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
        "snapshot_sha256": hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
        "summary": summarize(results),
        "categories": {category: summarize([result for result in results if result["category"] == category])
                       for category in sorted({result["category"] for result in results})},
        "results": results,
    }
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        for field in ("policy", "suite_sha256", "snapshot_sha256"):
            if baseline.get(field) != report[field]:
                raise ValueError(f"Baseline has a different {field}; comparison would be misleading")
        prior = {result["id"]: result for result in baseline["results"]}
        report["comparison"] = {
            "new_failures": [result["id"] for result in results if prior[result["id"]]["passed"] and not result["passed"]],
            "new_passes": [result["id"] for result in results if not prior[result["id"]]["passed"] and result["passed"]],
            "baseline_summary": baseline["summary"],
            "mean_reciprocal_rank_delta": report["summary"]["mean_reciprocal_rank"] - baseline["summary"]["mean_reciprocal_rank"]
                if report["summary"]["mean_reciprocal_rank"] is not None and baseline["summary"]["mean_reciprocal_rank"] is not None else None,
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    args.report.chmod(0o600)
    print(json.dumps(report["summary"], indent=2))
    if report.get("comparison", {}).get("new_failures"):
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
