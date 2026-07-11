"""CLI entry point for public-dataset evaluation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .datasets import (
    DATASETS,
    DatasetFormatError,
    export_coding_fixture,
    export_schemas,
    fetch_dataset,
    sha256_file,
    validate_dataset,
)
from .e2e import (
    COMMON_ANSWER_TRACK,
    RAW_RETRIEVAL_TRACK,
    load_answer_prediction_rows,
    run_end_to_end_evaluation,
    score_answer_predictions,
)
from .runner import load_prediction_rows, parse_k_values, run_evaluation, score_predictions


def _write_or_print(payload: dict[str, Any], output: str | None) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if output:
        path = Path(output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        print(json.dumps({"written": str(path), "bytes": path.stat().st_size, "status": payload.get("status")}, indent=2))
    else:
        print(serialized, end="")


def _paths_alias(first: Path, second: Path) -> bool:
    if first == second:
        return True
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def _require_distinct_paths(**paths: Path) -> None:
    items = list(paths.items())
    for index, (first_name, first_path) in enumerate(items):
        for second_name, second_path in items[index + 1 :]:
            if _paths_alias(first_path, second_path):
                raise DatasetFormatError(
                    f"Evaluation paths must be distinct; {first_name} and {second_name} both resolve to {first_path}."
                )


def handle_evaluate(args) -> None:
    action = str(getattr(args, "evaluate_action", "") or "")
    try:
        if action == "datasets":
            print(json.dumps({"datasets": {key: value.__dict__ for key, value in DATASETS.items()}}, indent=2, sort_keys=True))
            return
        if action == "fetch":
            payload = fetch_dataset(
                args.dataset,
                args.output_dir,
                accept_license=bool(args.accept_license),
                force=bool(args.force),
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return
        if action == "fixture":
            print(json.dumps(export_coding_fixture(args.output), indent=2, sort_keys=True))
            return
        if action == "schemas":
            print(json.dumps(export_schemas(args.output_dir), indent=2, sort_keys=True))
            return
        if action == "validate":
            if args.output:
                _require_distinct_paths(
                    input=Path(args.input).expanduser().resolve(),
                    validation_output=Path(args.output).expanduser().resolve(),
                )
            payload = validate_dataset(
                args.dataset,
                args.input,
                granularity=args.granularity,
                representation=args.representation,
                verify_checksum=not bool(args.allow_unverified_dataset),
            )
            _write_or_print(payload, args.output)
            if not payload.get("valid"):
                raise SystemExit(1)
            return
        if action == "score":
            validation = validate_dataset(
                args.dataset,
                args.input,
                granularity=args.granularity,
                representation=args.representation,
                verify_checksum=not bool(args.allow_unverified_dataset),
            )
            if not validation.get("valid"):
                raise DatasetFormatError("Dataset validation failed before scoring; verify the pinned checksum or opt in explicitly.")
            input_path = Path(args.input).expanduser().resolve()
            predictions_path = Path(args.predictions).expanduser().resolve()
            output_path = Path(args.output).expanduser().resolve() if args.output else None
            distinct = {"input": input_path, "predictions": predictions_path}
            if output_path is not None:
                distinct["score_output"] = output_path
            _require_distinct_paths(**distinct)
            if args.track == COMMON_ANSWER_TRACK:
                predictions = load_answer_prediction_rows(args.predictions)
                payload = score_answer_predictions(
                    dataset=args.dataset,
                    dataset_path=args.input,
                    granularity=args.granularity,
                    representation=args.representation,
                    predictions=predictions,
                )
            else:
                predictions = load_prediction_rows(args.predictions)
                prediction_tracks = {str(row.get("track") or "") for row in predictions}
                if prediction_tracks != {args.track}:
                    raise DatasetFormatError(
                        f"Retrieval prediction track mismatch: requested {args.track!r}, artifact declares {sorted(prediction_tracks)!r}."
                    )
                payload = score_predictions(
                    dataset=args.dataset,
                    dataset_path=args.input,
                    granularity=args.granularity,
                    representation=args.representation,
                    predictions=predictions,
                    k_values=parse_k_values(args.k),
                )
            payload["artifacts"].update(
                {
                    "source_predictions_path": str(predictions_path),
                    "source_predictions_sha256": sha256_file(predictions_path),
                }
            )
            _write_or_print(payload, args.output)
            if not payload["prediction_integrity"]["valid"]:
                raise SystemExit(1)
            return
        if action == "run":
            output = Path(args.output).expanduser().resolve() if args.output else Path.cwd() / "autopsy-external-eval.json"
            predictions = Path(args.predictions).expanduser().resolve() if args.predictions else output.with_suffix(".predictions.jsonl")
            distinct_paths = {
                "input": Path(args.input).expanduser().resolve(),
                "report": output,
                "predictions": predictions,
            }
            extractions = None
            answers = None
            if args.track != RAW_RETRIEVAL_TRACK:
                extractions = (
                    Path(args.extractions).expanduser().resolve()
                    if args.extractions else output.with_suffix(".extractions.jsonl")
                )
                distinct_paths["extractions"] = extractions
                if args.track == COMMON_ANSWER_TRACK:
                    answers = (
                        Path(args.answers).expanduser().resolve()
                        if args.answers else output.with_suffix(".answers.jsonl")
                    )
                    distinct_paths["answers"] = answers
                elif args.answers:
                    raise DatasetFormatError("--answers is only valid with --track common-answer.")
            elif args.extractions or args.answers:
                raise DatasetFormatError("--extractions and --answers require an end-to-end track.")
            _require_distinct_paths(**distinct_paths)
            validation = validate_dataset(
                args.dataset,
                args.input,
                granularity=args.granularity,
                representation=args.representation,
                verify_checksum=not bool(args.allow_unverified_dataset),
            )
            if not validation.get("valid"):
                _write_or_print({"status": "invalid_dataset", "validation": validation}, args.output)
                raise SystemExit(1)
            categories = {value.strip() for value in args.category or [] if value.strip()}
            if args.track == RAW_RETRIEVAL_TRACK:
                payload = run_evaluation(
                    dataset=args.dataset,
                    dataset_path=args.input,
                    granularity=args.granularity,
                    representation=args.representation,
                    route=args.route,
                    k_values=parse_k_values(args.k),
                    sample_size=args.sample_size,
                    seed=args.seed,
                    categories=categories or None,
                    repetitions=args.repetitions,
                    warmups=args.warmups,
                    temporal_policy=args.temporal_policy,
                    predictions_path=predictions,
                    store_dir=args.store_dir,
                    keep_store=bool(args.keep_store),
                    adapter_id=args.adapter,
                )
            else:
                assert extractions is not None
                payload = run_end_to_end_evaluation(
                    track=args.track,
                    dataset=args.dataset,
                    dataset_path=args.input,
                    granularity=args.granularity,
                    representation=args.representation,
                    route=args.route,
                    k_values=parse_k_values(args.k),
                    sample_size=args.sample_size,
                    seed=args.seed,
                    categories=categories or None,
                    repetitions=args.repetitions,
                    warmups=args.warmups,
                    temporal_policy=args.temporal_policy,
                    predictions_path=predictions,
                    extraction_artifacts_path=extractions,
                    answers_path=answers,
                    adapter_id=args.adapter,
                    extractor_id=args.extractor,
                    generator_id=args.generator,
                    store_dir=args.store_dir,
                    keep_store=bool(args.keep_store),
                )
            _write_or_print(payload, str(output))
            if payload.get("case_errors"):
                raise SystemExit(1)
            return
        raise DatasetFormatError(f"Unknown evaluate action: {action}")
    except (DatasetFormatError, FileNotFoundError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(2) from exc
