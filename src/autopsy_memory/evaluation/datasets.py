"""Dataset acquisition and adapters for public memory benchmarks.

External data is deliberately not vendored. ``fetch_dataset`` downloads a pinned
artifact only after explicit license acceptance and verifies its SHA-256 digest.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import shutil
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .models import EvaluationCase, EvaluationDocument, EvaluationRelation


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    version: str
    source_url: str
    homepage: str
    license: str
    sha256: str
    filename: str
    notice: str


DATASETS: dict[str, DatasetSpec] = {
    "locomo": DatasetSpec(
        name="locomo",
        version="git-3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376",
        source_url=(
            "https://raw.githubusercontent.com/snap-research/locomo/"
            "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json"
        ),
        homepage="https://github.com/snap-research/locomo",
        license="CC-BY-NC-4.0",
        sha256="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
        filename="locomo10.json",
        notice="LoCoMo is non-commercial. Attribute the original authors and do not redistribute it with Autopsy.",
    ),
    "longmemeval-s": DatasetSpec(
        name="longmemeval-s",
        version="hf-98d7416c24c778c2fee6e6f3006e7a073259d48f",
        source_url=(
            "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/"
            "98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json"
        ),
        homepage="https://github.com/xiaowu0162/LongMemEval",
        license="MIT",
        sha256="d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
        filename="longmemeval_s_cleaned.json",
        notice="LongMemEval is distributed by its authors; preserve the upstream copyright and license notice.",
    ),
}


LOCOMO_CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial-abstention",
}


class DatasetFormatError(ValueError):
    pass


def _reject_json_constant(value: str) -> None:
    raise DatasetFormatError(f"Non-standard JSON constant is not allowed: {value}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetFormatError(f"Duplicate JSON object key is not allowed: {key}")
        result[key] = value
    return result


def bundled_coding_fixture_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "coding-memory-v1.jsonl"


def bundled_schema_dir() -> Path:
    return Path(__file__).resolve().parent / "schemas"


EVALUATION_SCHEMA_FILENAMES = {
    "answer-prediction-v1.schema.json",
    "answer-score-v1.schema.json",
    "coding-memory-case-v1.schema.json",
    "end-to-end-report-v1.schema.json",
    "extraction-artifact-v1.schema.json",
    "report-v1.schema.json",
    "retrieval-prediction-v1.schema.json",
    "score-report-v1.schema.json",
}


def export_schemas(output_dir: str | Path) -> dict[str, Any]:
    source_dir = bundled_schema_dir()
    sources = sorted(source_dir.glob("*.schema.json"))
    if {source.name for source in sources} != EVALUATION_SCHEMA_FILENAMES:
        raise DatasetFormatError("The installed package is missing external-evaluation schemas.")
    destination_dir = Path(output_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for source in sources:
        destination = destination_dir / source.name
        shutil.copyfile(source, destination)
        items.append({"path": str(destination), "sha256": sha256_file(destination)})
    return {"written": len(items), "output_dir": str(destination_dir), "schemas": items}


def export_coding_fixture(output: str | Path) -> dict[str, Any]:
    source = bundled_coding_fixture_path()
    if not source.exists():
        raise DatasetFormatError("The installed package is missing the coding-memory evaluation fixture.")
    destination = Path(output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {
        "written": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "schema": "autopsy-coding-memory-case/v1",
        "provenance": "controlled-synthetic-v1",
        "leaderboard_dataset": False,
    }


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_provenance(dataset: str, path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    spec = DATASETS.get(dataset)
    return {
        "dataset": dataset,
        "version": spec.version if spec else "user-supplied-v1",
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
        "expected_sha256": spec.sha256 if spec else None,
        "source_url": spec.source_url if spec else None,
        "homepage": spec.homepage if spec else None,
        "license": spec.license if spec else "user-supplied",
    }


def fetch_dataset(
    dataset: str,
    output_dir: str | Path,
    *,
    accept_license: bool,
    force: bool = False,
) -> dict[str, Any]:
    if dataset not in DATASETS:
        raise DatasetFormatError(f"No pinned download is available for dataset: {dataset}")
    if not accept_license:
        raise DatasetFormatError("Dataset download requires --accept-license after reviewing the upstream license.")
    spec = DATASETS[dataset]
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / spec.filename
    provenance_path = destination.with_suffix(destination.suffix + ".provenance.json")

    def write_provenance() -> None:
        payload = {
            "dataset": asdict(spec),
            "artifact": str(destination),
            "verified_sha256": spec.sha256,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary_provenance = provenance_path.with_suffix(provenance_path.suffix + ".tmp")
        temporary_provenance.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary_provenance, provenance_path)

    if destination.exists() and not force:
        actual = sha256_file(destination)
        if actual == spec.sha256:
            write_provenance()
            return {
                "downloaded": False,
                "verified": True,
                "path": str(destination),
                "provenance_path": str(provenance_path),
                "dataset": asdict(spec),
            }
        raise DatasetFormatError(
            f"Refusing to replace existing file with unexpected SHA-256 {actual}; pass --force to replace it."
        )
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        request = urllib.request.Request(spec.source_url, headers={"User-Agent": "autopsy-memory-external-eval/1"})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        actual = sha256_file(temporary)
        if actual != spec.sha256:
            raise DatasetFormatError(
                f"Downloaded {dataset} artifact failed SHA-256 verification: expected {spec.sha256}, got {actual}."
            )
        os.replace(temporary, destination)
        write_provenance()
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "downloaded": True,
        "verified": True,
        "path": str(destination),
        "provenance_path": str(provenance_path),
        "dataset": asdict(spec),
    }


def iter_json_array(path: str | Path, *, chunk_size: int = 1024 * 1024) -> Iterator[Any]:
    """Incrementally parse a top-level JSON array with only the standard library."""

    decoder = json.JSONDecoder(
        parse_constant=_reject_json_constant,
        object_pairs_hook=_strict_json_object,
    )
    buffer = ""
    started = False
    finished = False
    expect_value = True
    allow_end = True
    with Path(path).open("r", encoding="utf-8") as stream:
        while True:
            chunk = stream.read(chunk_size)
            eof = chunk == ""
            buffer += chunk
            while True:
                buffer = buffer.lstrip()
                if finished:
                    if buffer:
                        raise DatasetFormatError("Unexpected content after the JSON array.")
                    break
                if not started:
                    if not buffer:
                        break
                    if not buffer.startswith("["):
                        raise DatasetFormatError("Expected a top-level JSON array.")
                    buffer = buffer[1:]
                    started = True
                    continue
                buffer = buffer.lstrip()
                if not buffer:
                    break
                if expect_value:
                    if buffer.startswith("]"):
                        if not allow_end:
                            raise DatasetFormatError("A JSON array cannot end immediately after a comma.")
                        buffer = buffer[1:]
                        finished = True
                        continue
                    if buffer.startswith(","):
                        raise DatasetFormatError("A JSON array contains an unexpected comma.")
                    try:
                        value, offset = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        if eof:
                            raise DatasetFormatError("Truncated or malformed JSON array.")
                        break
                    yield value
                    buffer = buffer[offset:]
                    expect_value = False
                    allow_end = True
                    continue
                if buffer.startswith(","):
                    buffer = buffer[1:]
                    expect_value = True
                    allow_end = False
                    continue
                if buffer.startswith("]"):
                    buffer = buffer[1:]
                    finished = True
                    continue
                raise DatasetFormatError("Expected a comma or closing bracket in the JSON array.")
            if eof:
                if not finished:
                    raise DatasetFormatError("JSON array ended before a closing bracket.")
                return


def _natural_session_number(value: str) -> int:
    match = re.search(r"(\d+)$", str(value))
    return int(match.group(1)) if match else 0


def _canonical_locomo_dialog_id(value: str) -> str:
    text = str(value or "").strip().replace("(", "").replace(")", "")
    text = re.sub(r"^D:(\d+):(\d+)$", r"D\1:\2", text, flags=re.IGNORECASE)
    match = re.fullmatch(r"D0*(\d+):0*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"D{int(match.group(1))}:{int(match.group(2))}"
    return text


def _locomo_evidence_ids(values: Iterable[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        parts = re.findall(r"D:?\d+:\d+", text, flags=re.IGNORECASE)
        if not parts and text:
            parts = [text]
        for part in parts:
            canonical = _canonical_locomo_dialog_id(part)
            if canonical and re.fullmatch(r"D\d+:\d+", canonical):
                normalized.append(canonical)
    return tuple(dict.fromkeys(normalized))


def _turn_content(turn: dict[str, Any], *, strip: bool = True) -> str:
    content = turn.get("text", turn.get("content", ""))
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, sort_keys=True)
    return content.strip() if strip else content


def _turn_text(turn: dict[str, Any], *, timestamp: str = "") -> str:
    content = _turn_content(turn)
    speaker = str(turn.get("speaker") or turn.get("role") or "speaker")
    image_caption = str(turn.get("blip_caption") or "").strip()
    pieces = [piece for piece in (timestamp, f"{speaker}: {content}", image_caption) if piece]
    return "\n".join(pieces)


def normalize_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidates = (
        "%Y/%m/%d (%a) %H:%M",
        "%Y/%m/%d %H:%M",
        "%I:%M %p on %d %B, %Y",
        "%I:%M%p on %d %B, %Y",
        "%d %B %Y",
    )
    for pattern in candidates:
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return ""


def iter_locomo_cases(
    path: str | Path,
    *,
    granularity: str = "turn",
    representation: str = "audited",
) -> Iterator[EvaluationCase]:
    del representation
    if granularity not in {"turn", "session"}:
        raise DatasetFormatError("LoCoMo granularity must be turn or session.")
    for sample in iter_json_array(path):
        if not isinstance(sample, dict):
            raise DatasetFormatError("Every LoCoMo array item must be an object.")
        sample_id = str(sample.get("sample_id") or "").strip()
        conversation = sample.get("conversation")
        qas = sample.get("qa")
        if not sample_id or not isinstance(conversation, dict) or not isinstance(qas, list):
            raise DatasetFormatError("LoCoMo sample is missing sample_id, conversation, or qa.")
        session_keys = sorted(
            (key for key in conversation if re.fullmatch(r"session_\d+", str(key))),
            key=_natural_session_number,
        )
        documents: list[EvaluationDocument] = []
        for session_key in session_keys:
            session_number = _natural_session_number(session_key)
            session_id = f"D{session_number}"
            source_timestamp = str(conversation.get(f"{session_key}_date_time") or "")
            timestamp = normalize_timestamp(source_timestamp)
            turns = conversation.get(session_key)
            if not isinstance(turns, list):
                raise DatasetFormatError(f"LoCoMo {sample_id} {session_key} must be a list.")
            if granularity == "session":
                text = "\n".join(_turn_text(turn, timestamp=source_timestamp) for turn in turns if isinstance(turn, dict))
                documents.append(EvaluationDocument(session_id, text, timestamp=timestamp, session_id=session_id))
                continue
            for index, turn in enumerate(turns, start=1):
                if not isinstance(turn, dict):
                    continue
                document_id = _canonical_locomo_dialog_id(str(turn.get("dia_id") or f"{session_id}:{index}"))
                documents.append(
                    EvaluationDocument(
                        document_id,
                        _turn_text(turn, timestamp=source_timestamp),
                        timestamp=timestamp,
                        session_id=session_id,
                    )
                )
        document_ids = {document.document_id for document in documents}
        corpus_id = f"locomo:{sample_id}:{granularity}"
        shared_documents = tuple(documents)
        for index, qa in enumerate(qas):
            if not isinstance(qa, dict):
                continue
            category_number = int(qa.get("category") or 0)
            evidence = _locomo_evidence_ids(qa.get("evidence", []))
            expected_abstain = category_number == 5
            if granularity == "session":
                evidence_ids = tuple(dict.fromkeys(value.split(":", 1)[0] for value in evidence))
            else:
                evidence_ids = tuple(dict.fromkeys(evidence))
            unresolved = tuple(value for value in evidence_ids if value not in document_ids)
            resolved_evidence = tuple(value for value in evidence_ids if value in document_ids)
            scoring_excluded_reason = ""
            if not expected_abstain and unresolved:
                scoring_excluded_reason = "unresolved_source_evidence"
            elif not expected_abstain and not resolved_evidence:
                scoring_excluded_reason = "no_resolvable_source_evidence"
            relevant = () if expected_abstain or scoring_excluded_reason else resolved_evidence
            answer = str(qa.get("answer") or qa.get("adversarial_answer") or "")
            yield EvaluationCase(
                dataset="locomo",
                case_id=f"{sample_id}:qa:{index:04d}",
                corpus_id=corpus_id,
                category=LOCOMO_CATEGORY_NAMES.get(category_number, f"category-{category_number}"),
                query=str(qa.get("question") or ""),
                documents=shared_documents,
                relevant_document_ids=relevant,
                forbidden_document_ids=(),
                expected_abstain=expected_abstain,
                answer=answer,
                metadata={
                    "sample_id": sample_id,
                    "qa_index": index,
                    "category_number": category_number,
                    "source_evidence_ids": list(evidence_ids),
                    "resolved_evidence_ids": list(resolved_evidence),
                    "unresolved_evidence_ids": list(unresolved),
                    "scoring_excluded_reason": scoring_excluded_reason,
                },
            )


def iter_longmemeval_cases(
    path: str | Path,
    *,
    granularity: str = "session",
    representation: str = "audited",
) -> Iterator[EvaluationCase]:
    if granularity not in {"turn", "session"}:
        raise DatasetFormatError("LongMemEval granularity must be turn or session.")
    if representation not in {"audited", "upstream"}:
        raise DatasetFormatError("LongMemEval representation must be audited or upstream.")
    for entry in iter_json_array(path):
        if not isinstance(entry, dict):
            raise DatasetFormatError("Every LongMemEval array item must be an object.")
        case_id = str(entry.get("question_id") or "").strip()
        session_ids = entry.get("haystack_session_ids")
        sessions = entry.get("haystack_sessions")
        dates = entry.get("haystack_dates")
        if not case_id or not isinstance(session_ids, list) or not isinstance(sessions, list) or not isinstance(dates, list):
            raise DatasetFormatError("LongMemEval item is missing question_id or aligned haystack fields.")
        if not (len(session_ids) == len(sessions) == len(dates)):
            raise DatasetFormatError(f"LongMemEval {case_id} has unaligned session ids, sessions, and dates.")
        documents: list[EvaluationDocument] = []
        answer_turn_ids: list[str] = []
        relevant_session_document_ids: list[str] = []
        session_occurrences: Counter[str] = Counter()
        normalized_dates = [normalize_timestamp(value) for value in dates]
        timestamp_inversions = sum(
            1
            for previous, current in zip(normalized_dates, normalized_dates[1:])
            if previous and current and current < previous
        )
        question_date = normalize_timestamp(entry.get("question_date"))
        future_session_count = sum(1 for value in normalized_dates if value and question_date and value >= question_date)
        answer_session_ids = tuple(str(value) for value in entry.get("answer_session_ids", []) if value)
        for session_id_raw, turns, timestamp_raw in zip(session_ids, sessions, dates):
            raw_session_id = str(session_id_raw)
            session_occurrences[raw_session_id] += 1
            occurrence = session_occurrences[raw_session_id]
            session_id = raw_session_id if occurrence == 1 else f"{raw_session_id}#duplicate-{occurrence}"
            source_timestamp = str(timestamp_raw or "")
            timestamp = normalize_timestamp(source_timestamp)
            if not isinstance(turns, list):
                raise DatasetFormatError(f"LongMemEval {case_id} session {session_id} must be a list.")
            selected_turns = [
                turn
                for turn in turns
                if isinstance(turn, dict) and (representation == "audited" or str(turn.get("role") or "") == "user")
            ]
            if granularity == "session":
                if representation == "upstream":
                    # Match the released retriever corpus exactly: user content
                    # only, space-joined, with no role or timestamp prefixes.
                    text = " ".join(_turn_content(turn, strip=False) for turn in selected_turns)
                else:
                    text = "\n".join(_turn_text(turn, timestamp=source_timestamp) for turn in selected_turns)
                documents.append(
                    EvaluationDocument(
                        session_id,
                        text,
                        timestamp=timestamp,
                        session_id=raw_session_id,
                        metadata={"source_session_id": raw_session_id, "source_ordinal": occurrence},
                    )
                )
                if raw_session_id in answer_session_ids and any(
                    bool(turn.get("has_answer")) for turn in selected_turns
                ):
                    relevant_session_document_ids.append(session_id)
                continue
            for turn_index, turn in enumerate(turns, start=1):
                if not isinstance(turn, dict):
                    continue
                if representation == "upstream" and str(turn.get("role") or "") != "user":
                    continue
                document_id = f"{session_id}_{turn_index}"
                document_text = (
                    _turn_content(turn, strip=False)
                    if representation == "upstream"
                    else _turn_text(turn, timestamp=source_timestamp)
                )
                documents.append(
                    EvaluationDocument(
                        document_id,
                        document_text,
                        timestamp=timestamp,
                        session_id=raw_session_id,
                        metadata={"source_session_id": raw_session_id, "source_ordinal": occurrence},
                    )
                )
                if bool(turn.get("has_answer")):
                    answer_turn_ids.append(document_id)
        expected_abstain = case_id.endswith("_abs")
        if granularity == "session":
            if not relevant_session_document_ids and representation == "audited":
                relevant_session_document_ids = [
                    document.document_id
                    for document in documents
                    if document.session_id in answer_session_ids
                ]
            relevant = tuple(relevant_session_document_ids)
        else:
            relevant = tuple(answer_turn_ids)
        if expected_abstain:
            relevant = ()
        scoring_excluded_reason = ""
        if not expected_abstain and not relevant:
            scoring_excluded_reason = (
                "evidence_not_in_upstream_user_only_representation"
                if representation == "upstream"
                else "no_resolvable_source_evidence"
            )
        yield EvaluationCase(
            dataset="longmemeval-s",
            case_id=case_id,
            corpus_id=f"longmemeval-s:{case_id}:{granularity}",
            category=str(entry.get("question_type") or "unknown"),
            query=str(entry.get("question") or ""),
            documents=tuple(documents),
            relevant_document_ids=tuple(dict.fromkeys(relevant)),
            forbidden_document_ids=(),
            expected_abstain=expected_abstain,
            answer=str(entry.get("answer") or ""),
            as_of=question_date,
            metadata={
                "question_type": str(entry.get("question_type") or ""),
                "question_date": str(entry.get("question_date") or ""),
                "answer_session_ids": list(answer_session_ids),
                "duplicate_session_id_count": sum(count - 1 for count in session_occurrences.values() if count > 1),
                "timestamp_inversion_count": timestamp_inversions,
                "future_session_count": future_session_count,
                "representation": representation,
                "scoring_excluded_reason": scoring_excluded_reason,
            },
        )


def _parse_relation(raw: dict[str, Any]) -> EvaluationRelation:
    return EvaluationRelation(
        source_id=str(raw.get("source_id") or ""),
        target_id=str(raw.get("target_id") or ""),
        relation=str(raw.get("relation") or ""),
        fact_text=str(raw.get("fact_text") or ""),
        valid_at=str(raw.get("valid_at") or ""),
        invalid_at=str(raw.get("invalid_at") or ""),
        expired_at=str(raw.get("expired_at") or ""),
        fact_rating=float(raw.get("fact_rating", 1.0)),
    )


def iter_coding_trace_cases(
    path: str | Path,
    *,
    granularity: str = "turn",
    representation: str = "audited",
) -> Iterator[EvaluationCase]:
    del granularity, representation
    seen: set[str] = set()
    required_case_fields = {"schema", "case_id", "category", "query", "documents", "relevant_document_ids"}
    allowed_case_fields = required_case_fields | {
        "corpus_id",
        "expected_abstain",
        "answer",
        "as_of",
        "forbidden_document_ids",
        "relations",
        "metadata",
    }
    allowed_document_fields = {"id", "title", "text", "timestamp", "expired_at", "session_id", "metadata"}
    allowed_relation_fields = {
        "source_id",
        "target_id",
        "relation",
        "fact_text",
        "valid_at",
        "invalid_at",
        "expired_at",
        "fact_rating",
    }
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                raw = json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_strict_json_object,
                )
            except json.JSONDecodeError as exc:
                raise DatasetFormatError(f"Invalid coding trace JSONL line {line_number}: {exc}") from exc
            if not isinstance(raw, dict):
                raise DatasetFormatError(f"Coding trace line {line_number} must be a JSON object.")
            missing_fields = sorted(required_case_fields - set(raw))
            unknown_fields = sorted(set(raw) - allowed_case_fields)
            if missing_fields or unknown_fields:
                raise DatasetFormatError(
                    f"Coding trace line {line_number} has missing fields {missing_fields} or unsupported fields {unknown_fields}."
                )
            if raw.get("schema") != "autopsy-coding-memory-case/v1":
                raise DatasetFormatError(f"Coding trace line {line_number} has an unsupported schema.")
            if not isinstance(raw.get("case_id"), str):
                raise DatasetFormatError(f"Coding trace line {line_number} case_id must be a string.")
            if not isinstance(raw.get("category"), str) or not raw["category"].strip():
                raise DatasetFormatError(f"Coding trace line {line_number} must have a non-empty category.")
            if not isinstance(raw.get("query"), str) or not raw["query"].strip():
                raise DatasetFormatError(f"Coding trace line {line_number} must have a non-empty query.")
            if "expected_abstain" in raw and not isinstance(raw["expected_abstain"], bool):
                raise DatasetFormatError(f"Coding trace line {line_number} expected_abstain must be boolean.")
            if "corpus_id" in raw and (not isinstance(raw["corpus_id"], str) or not raw["corpus_id"]):
                raise DatasetFormatError(f"Coding trace line {line_number} corpus_id must be a non-empty string.")
            if "as_of" in raw and not isinstance(raw["as_of"], str):
                raise DatasetFormatError(f"Coding trace line {line_number} as_of must be a string.")
            if "answer" in raw and not isinstance(raw["answer"], (str, int, float, bool, type(None))):
                raise DatasetFormatError(f"Coding trace line {line_number} answer must be a scalar value.")
            metadata_raw = raw.get("metadata", {})
            if not isinstance(metadata_raw, dict):
                raise DatasetFormatError(f"Coding trace line {line_number} metadata must be an object.")
            documents_raw = raw.get("documents")
            relevant_raw = raw.get("relevant_document_ids")
            forbidden_raw = raw.get("forbidden_document_ids", [])
            relations_raw = raw.get("relations", [])
            if not isinstance(documents_raw, list) or not isinstance(relevant_raw, list) or not isinstance(forbidden_raw, list):
                raise DatasetFormatError(f"Coding trace line {line_number} document and judgment fields must be arrays.")
            if not isinstance(relations_raw, list):
                raise DatasetFormatError(f"Coding trace line {line_number} relations must be an array.")
            for document_index, document in enumerate(documents_raw):
                if not isinstance(document, dict):
                    raise DatasetFormatError(f"Coding trace line {line_number} document {document_index} must be an object.")
                if set(document) - allowed_document_fields or not {"id", "text"}.issubset(document):
                    raise DatasetFormatError(f"Coding trace line {line_number} document {document_index} violates the schema.")
                if not isinstance(document.get("id"), str) or not document["id"]:
                    raise DatasetFormatError(f"Coding trace line {line_number} document {document_index} must have a non-empty id.")
                if not isinstance(document.get("text"), str):
                    raise DatasetFormatError(f"Coding trace line {line_number} document {document_index} text must be a string.")
                for string_field in ("title", "timestamp", "expired_at", "session_id"):
                    if string_field in document and not isinstance(document[string_field], str):
                        raise DatasetFormatError(
                            f"Coding trace line {line_number} document {document_index} {string_field} must be a string."
                        )
                if "metadata" in document and not isinstance(document["metadata"], dict):
                    raise DatasetFormatError(f"Coding trace line {line_number} document {document_index} metadata must be an object.")
            for relation_index, relation_raw in enumerate(relations_raw):
                if not isinstance(relation_raw, dict):
                    raise DatasetFormatError(f"Coding trace line {line_number} relation {relation_index} must be an object.")
                if set(relation_raw) - allowed_relation_fields or not {"source_id", "target_id", "relation"}.issubset(relation_raw):
                    raise DatasetFormatError(f"Coding trace line {line_number} relation {relation_index} violates the schema.")
                for string_field in ("source_id", "target_id", "relation", "fact_text", "valid_at", "invalid_at", "expired_at"):
                    if string_field in relation_raw and not isinstance(relation_raw[string_field], str):
                        raise DatasetFormatError(
                            f"Coding trace line {line_number} relation {relation_index} {string_field} must be a string."
                        )
                if not all(relation_raw.get(key) for key in ("source_id", "target_id", "relation")):
                    raise DatasetFormatError(f"Coding trace line {line_number} relation {relation_index} requires non-empty ids and relation.")
                if "fact_rating" in relation_raw and (
                    isinstance(relation_raw["fact_rating"], bool)
                    or not isinstance(relation_raw["fact_rating"], (int, float))
                ):
                    raise DatasetFormatError(f"Coding trace line {line_number} relation {relation_index} fact_rating must be numeric.")
            case_id = str(raw.get("case_id") or "").strip()
            if not case_id or case_id in seen:
                raise DatasetFormatError(f"Coding trace line {line_number} has a missing or duplicate case_id: {case_id!r}")
            seen.add(case_id)
            documents = tuple(
                EvaluationDocument(
                    document_id=str(document.get("id") or ""),
                    title=str(document.get("title") or ""),
                    text=str(document.get("text") or ""),
                    timestamp=str(document.get("timestamp") or ""),
                    expired_at=str(document.get("expired_at") or ""),
                    session_id=str(document.get("session_id") or ""),
                    metadata=dict(document.get("metadata") or {}),
                )
                for document in documents_raw
            )
            document_ids = [document.document_id for document in documents]
            if not documents or any(not value for value in document_ids) or len(set(document_ids)) != len(document_ids):
                raise DatasetFormatError(f"Coding trace {case_id} must contain documents with unique non-empty ids.")
            if any(not isinstance(value, str) or not value for value in relevant_raw + forbidden_raw):
                raise DatasetFormatError(f"Coding trace {case_id} judgment ids must be non-empty strings.")
            relevant = tuple(relevant_raw)
            forbidden = tuple(forbidden_raw)
            if len(set(relevant)) != len(relevant) or len(set(forbidden)) != len(forbidden):
                raise DatasetFormatError(f"Coding trace {case_id} judgment ids must be unique.")
            if not forbidden:
                must_quarantine = metadata_raw.get("must_quarantine", [])
                if not isinstance(must_quarantine, list) or any(
                    not isinstance(value, str) or not value for value in must_quarantine
                ):
                    raise DatasetFormatError(f"Coding trace {case_id} must_quarantine must be an array of ids.")
                forbidden = tuple(must_quarantine)
            if len(set(forbidden)) != len(forbidden):
                raise DatasetFormatError(f"Coding trace {case_id} forbidden judgment ids must be unique.")
            expected_abstain = bool(raw.get("expected_abstain", False))
            if expected_abstain and relevant:
                raise DatasetFormatError(f"Coding trace {case_id} cannot both abstain and declare relevant documents.")
            if not expected_abstain and not relevant:
                raise DatasetFormatError(f"Coding trace {case_id} must declare relevant documents or expected_abstain=true.")
            overlap = sorted(set(relevant).intersection(forbidden))
            if overlap:
                raise DatasetFormatError(f"Coding trace {case_id} marks documents as both relevant and forbidden: {overlap}")
            unknown = sorted(set(relevant) - set(document_ids))
            if unknown:
                raise DatasetFormatError(f"Coding trace {case_id} references unknown relevant ids: {unknown}")
            unknown_forbidden = sorted(set(forbidden) - set(document_ids))
            if unknown_forbidden:
                raise DatasetFormatError(f"Coding trace {case_id} references unknown forbidden ids: {unknown_forbidden}")
            relations = tuple(_parse_relation(value) for value in relations_raw)
            for relation in relations:
                if not relation.relation or relation.source_id not in document_ids or relation.target_id not in document_ids:
                    raise DatasetFormatError(f"Coding trace {case_id} relation references an unknown document.")
                if not 0.0 <= relation.fact_rating <= 1.0:
                    raise DatasetFormatError(f"Coding trace {case_id} relation fact_rating must be between 0 and 1.")
            yield EvaluationCase(
                dataset="coding-traces",
                case_id=case_id,
                corpus_id=str(raw.get("corpus_id") or f"coding-traces:{case_id}"),
                category=raw["category"].strip(),
                query=raw["query"],
                documents=documents,
                relevant_document_ids=relevant,
                forbidden_document_ids=forbidden,
                expected_abstain=expected_abstain,
                answer=str(raw.get("answer") or ""),
                as_of=str(raw.get("as_of") or ""),
                relations=relations,
                metadata=dict(metadata_raw),
            )


def iter_cases(
    dataset: str,
    path: str | Path,
    *,
    granularity: str,
    representation: str = "audited",
) -> Iterator[EvaluationCase]:
    if dataset == "locomo":
        return iter_locomo_cases(path, granularity=granularity, representation=representation)
    if dataset == "longmemeval-s":
        return iter_longmemeval_cases(path, granularity=granularity, representation=representation)
    if dataset == "coding-traces":
        return iter_coding_trace_cases(path, granularity=granularity, representation=representation)
    raise DatasetFormatError(f"Unsupported evaluation dataset: {dataset}")


def _selection_score(seed: int, case_id: str) -> int:
    return int(hashlib.sha256(f"{seed}:{case_id}".encode("utf-8")).hexdigest(), 16)


def select_cases(
    cases: Iterable[EvaluationCase],
    *,
    sample_size: int,
    seed: int,
    categories: set[str] | None = None,
) -> Iterator[EvaluationCase]:
    """Select a stable, order-independent sample without loading a whole dataset."""

    filtered = (case for case in cases if not categories or case.category in categories)
    if sample_size <= 0:
        yield from filtered
        return
    heap: list[tuple[int, str, EvaluationCase]] = []
    for case in filtered:
        score = _selection_score(seed, case.case_id)
        entry = (-score, case.case_id, case)
        if len(heap) < sample_size:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
    selected = sorted((entry[2] for entry in heap), key=lambda case: (case.corpus_id, case.case_id))
    yield from selected


def validate_dataset(
    dataset: str,
    path: str | Path,
    *,
    granularity: str,
    representation: str = "audited",
    verify_checksum: bool = True,
) -> dict[str, Any]:
    provenance = dataset_provenance(dataset, path)
    checksum_matches = provenance.get("expected_sha256") in {None, provenance["sha256"]}
    categories: Counter[str] = Counter()
    corpus_ids: set[str] = set()
    case_ids: set[str] = set()
    document_count = 0
    documents_by_corpus: dict[str, int] = {}
    retrieval_scorable = 0
    abstention_count = 0
    unresolved_evidence = 0
    duplicate_session_ids = 0
    timestamp_inversions = 0
    future_sessions = 0
    cases_with_timestamp_inversions = 0
    cases_with_future_sessions = 0
    cases_with_duplicate_session_ids = 0
    duplicate_cases: list[str] = []
    scoring_exclusions: Counter[str] = Counter()
    for case in iter_cases(dataset, path, granularity=granularity, representation=representation):
        if case.case_id in case_ids:
            duplicate_cases.append(case.case_id)
        case_ids.add(case.case_id)
        corpus_ids.add(case.corpus_id)
        categories[case.category] += 1
        document_count += len(case.documents)
        documents_by_corpus.setdefault(case.corpus_id, len(case.documents))
        retrieval_scorable += int(case.retrieval_scorable)
        if not case.retrieval_scorable:
            scoring_exclusions[str(case.metadata.get("scoring_excluded_reason") or "unspecified")] += 1
        abstention_count += int(case.expected_abstain)
        unresolved_evidence += len(case.metadata.get("unresolved_evidence_ids", []))
        case_duplicate_sessions = int(case.metadata.get("duplicate_session_id_count") or 0)
        case_inversions = int(case.metadata.get("timestamp_inversion_count") or 0)
        case_future_sessions = int(case.metadata.get("future_session_count") or 0)
        duplicate_session_ids += case_duplicate_sessions
        timestamp_inversions += case_inversions
        future_sessions += case_future_sessions
        cases_with_duplicate_session_ids += int(case_duplicate_sessions > 0)
        cases_with_timestamp_inversions += int(case_inversions > 0)
        cases_with_future_sessions += int(case_future_sessions > 0)
        if not case.query.strip():
            raise DatasetFormatError(f"Evaluation case {case.case_id} has an empty query.")
    valid = bool(case_ids) and not duplicate_cases and (checksum_matches or not verify_checksum)
    return {
        "valid": valid,
        "dataset": dataset,
        "granularity": granularity,
        "representation": representation,
        "provenance": provenance,
        "checksum": {"verified": checksum_matches, "required": bool(verify_checksum)},
        "counts": {
            "cases": len(case_ids),
            "corpora": len(corpus_ids),
            "documents_across_cases": document_count,
            "unique_corpus_documents": sum(documents_by_corpus.values()),
            "retrieval_scorable": retrieval_scorable,
            "abstention": abstention_count,
            "unresolved_evidence": unresolved_evidence,
            "duplicate_session_ids": duplicate_session_ids,
            "timestamp_inversions": timestamp_inversions,
            "sessions_at_or_after_question": future_sessions,
            "cases_with_duplicate_session_ids": cases_with_duplicate_session_ids,
            "cases_with_timestamp_inversions": cases_with_timestamp_inversions,
            "cases_with_sessions_at_or_after_question": cases_with_future_sessions,
        },
        "categories": dict(sorted(categories.items())),
        "scoring_exclusions": dict(sorted(scoring_exclusions.items())),
        "duplicate_case_ids": duplicate_cases[:20],
        "empty_dataset": not bool(case_ids),
    }
