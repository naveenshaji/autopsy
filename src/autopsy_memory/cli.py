#!/usr/bin/env python3
import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cli_parser import CommandHandlers, build_parser as build_cli_parser, normalized_cli_args
from .doctor import import_check, installed_autopsy_command_check, python_version_check
from .init import cmd_init, instruction_targets, target_status
from .metadata import cmd_instructions, cmd_version, package_version


APP_SUPPORT_DIR_DEFAULT = Path(os.environ.get("AUTOPSY_APP_SUPPORT_DIR") or Path.home() / "Library" / "Application Support" / "Autopsy")
FALKORDB_LITE_PATH_DEFAULT = APP_SUPPORT_DIR_DEFAULT / "FalkorDB" / "autopsy-memory.db"
GLOBAL_MEMORY_SETTINGS_DEFAULT = APP_SUPPORT_DIR_DEFAULT / "Config" / "memory-settings.json"
UNIFIED_MEMORY_ROOT_DEFAULT = Path.home() / "github" / "codex"
STATUS_WINDOW_DAYS_DEFAULT = 21

SEARCHABLE_KINDS = {
    "decision",
    "open_question",
    "preference",
    "attempt",
    "plan",
    "summary",
    "timeline",
    "timeline_event",
    "memory_note",
}

COMMON_QUERY_TOKENS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "autopsy",
    "be",
    "by",
    "can",
    "current",
    "do",
    "does",
    "for",
    "from",
    "get",
    "give",
    "how",
    "in",
    "is",
    "it",
    "me",
    "memories",
    "memory",
    "need",
    "of",
    "on",
    "or",
    "our",
    "show",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "we",
    "what",
    "when",
    "where",
    "with",
}

OBSOLETE_MEMORY_TOKENS = {"fallback", "sql" + "ite", "legacy"}

_GRAPH_VECTOR_AVAILABILITY: dict[str, bool] = {}
_GRAPH_SEMANTIC_ITEM_COUNT: dict[str, int] = {}
_FALKORDB_LITE_CLIENTS: dict[str, Any] = {}
_EMBEDDING_MODEL_CACHE: dict[tuple[str, str], Any] = {}
_RERANKER_MODEL_CACHE: dict[tuple[str, str], Any] = {}
EMBEDDINGS_CONFIG_DEFAULT = {
    "enabled": True,
    "provider": "sentence_transformers",
    "model": "BAAI/bge-base-en-v1.5",
    "device": "cpu",
    "batch_size": 16,
    "candidate_limit": 48,
    "vector_candidate_limit": 64,
    "token_overlap_scan_max_items": 2000,
    "fast_lexical_min_hits": 3,
    "fast_lexical_min_score": 14.0,
    "rerank_min_candidates": 3,
    "reranker": {
        "enabled": True,
        "provider": "sentence_transformers",
        "model": "BAAI/bge-reranker-base",
        "device": "cpu",
        "batch_size": 8,
        "candidate_limit": 24,
        "min_score": 0.05,
        "embedding_min_score": 0.62,
    },
}

OPERATIONAL_KINDS = {
    "workspace",
    "repository",
    "thread",
    "worktree",
    "branch",
}

ADJACENT_CONTEXT_KINDS = {
    "episode",
}

STATUS_HINTS = (
    "what's active right now",
    "whats active right now",
    "active right now",
    "what do you know so far",
    "where did we leave off",
    "status",
    "current state",
)

STRUCTURAL_EDGE_TYPES = (
    "BELONGS_TO",
    "ABOUT",
    "ATTACHED_TO",
    "CAPTURED_IN",
    "CAPTURES",
    "UPDATES",
    "FORKED_FROM",
    "PART_OF",
)

def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def workflow_step(name: str, reason: str, command: str | None = None) -> dict[str, Any]:
    payload = {"name": name, "reason": reason}
    if command:
        payload["command"] = command
    return payload


def cli_quote(value: Any) -> str:
    return shlex.quote(str(value))


def normalize_workspace_slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def unified_memory_enabled() -> bool:
    raw_value = os.environ.get("AUTOPSY_UNIFIED_MEMORY")
    if raw_value is None or str(raw_value).strip() == "":
        return True
    value = str(raw_value).strip().lower()
    return value not in {"", "0", "false", "no", "off"}


def unified_memory_root_path() -> str:
    raw = str(os.environ.get("AUTOPSY_UNIFIED_MEMORY_ROOT") or "").strip()
    if not raw:
        raw = str(UNIFIED_MEMORY_ROOT_DEFAULT)
    return os.path.realpath(os.path.expanduser(raw))


def resolve_workspace_reference(selector: str | None, cwd: str) -> dict[str, Any]:
    if unified_memory_enabled():
        root_path = unified_memory_root_path()
    else:
        root_path = os.path.realpath(os.path.expanduser(selector or cwd))
    title = Path(root_path).name or "Autopsy Memory"
    slug = normalize_workspace_slug(title) or "autopsy-memory"
    return {
        "id": root_path,
        "workspace_key": root_path,
        "slug": slug,
        "title": title,
        "root_path": root_path,
    }


def workspace_payload(workspace: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": workspace.get("id"),
        "workspace_key": workspace.get("workspace_key"),
        "slug": workspace.get("slug"),
        "title": workspace.get("title"),
        "root_path": workspace.get("root_path"),
    }


def build_read_workflow(
    workspace_root: str,
    *,
    command: str,
    query: str | None = None,
    thread_id: str | None = None,
    hits: list[dict[str, Any]] | None = None,
    inspected_items: list[dict[str, Any]] | None = None,
    current_only: bool = False,
    as_of: str | None = None,
) -> dict[str, Any]:
    hits = hits or []
    inspected_items = inspected_items or []
    first_hit_key = next((item.get("stable_key") for item in inspected_items if item.get("stable_key")), None)
    current_clause = " --current-only" if current_only else ""
    as_of_clause = f" --as-of {as_of}" if as_of else ""
    if not hits:
        suggested = []
        if query and command != "consult":
            suggested.append(workflow_step(
                "fallback-search",
                "No strong memory hits were found. Fall back to keyword search before assuming no prior context exists.",
                f"autopsy search {cli_quote(query)}{current_clause}{as_of_clause}",
            ))
        if thread_id:
            suggested.append(workflow_step(
                "inspect-thread-neighbors",
                "Check thread-scoped semantic memory before concluding there is no relevant prior context.",
                f"autopsy neighbors --thread-id {cli_quote(thread_id)}{current_clause}{as_of_clause}",
            ))
        return {
            "status": "empty",
            "coverage": "none",
            "complete": False,
            "next_step": "fallback" if suggested else "conclude",
            "message": "No graph memory hits were found for this read." if command != "consult" else "No graph memory hits were found after relaxed retrieval.",
            "suggested_next_steps": suggested,
        }

    if inspected_items:
        suggested = []
        if first_hit_key:
            suggested.append(workflow_step(
                "inspect-lineage",
                "If the retrieved memory may have changed over time, inspect its timeline before relying on it.",
                f"autopsy timeline {cli_quote(first_hit_key)}",
            ))
            suggested.append(workflow_step(
                "inspect-neighbors",
                "Use neighbors when the answer depends on nearby related facts or state transitions.",
                f"autopsy neighbors --stable-key {cli_quote(first_hit_key)}",
            ))
        return {
            "status": "ok",
            "coverage": "strong",
            "complete": True,
            "next_step": "done",
            "message": "High-signal memory was retrieved and inspected.",
            "suggested_next_steps": suggested,
        }

    suggested = []
    if first_hit_key:
        suggested.append(workflow_step(
            "inspect-item",
            "Inspect the top memory hit before relying on it.",
            f"autopsy item {cli_quote(first_hit_key)}",
        ))
    return {
        "status": "needs_inspection",
        "coverage": "partial",
        "complete": False,
        "next_step": "inspect" if suggested else "review_hits",
        "message": "Memory hits were found, but no item was inspected yet.",
        "suggested_next_steps": suggested,
    }


def load_global_memory_settings() -> dict[str, Any]:
    if not GLOBAL_MEMORY_SETTINGS_DEFAULT.exists():
        return {}
    try:
        raw = json.loads(GLOBAL_MEMORY_SETTINGS_DEFAULT.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def load_embeddings_config(root_dir: Path) -> dict[str, Any]:
    config_path = root_dir / "memory" / "config" / "autopsy_embeddings.json"
    config = copy.deepcopy(EMBEDDINGS_CONFIG_DEFAULT)
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            reranker_raw = raw.get("reranker")
            if isinstance(reranker_raw, dict):
                config["reranker"].update(reranker_raw)
            for key, value in raw.items():
                if key == "reranker":
                    continue
                config[key] = value
    settings = load_global_memory_settings()
    memory = settings.get("memory") if isinstance(settings, dict) else None
    reranker = memory.get("reranker") if isinstance(memory, dict) else None
    if isinstance(reranker, dict) and "enabled" in reranker:
        config.setdefault("reranker", {})
        config["reranker"]["enabled"] = bool(reranker.get("enabled"))
    return config


def reranker_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    payload = config.get("reranker")
    return payload if isinstance(payload, dict) else {}


def embedding_provider_available(config: dict[str, Any]) -> tuple[bool, str | None]:
    provider = str(config.get("provider") or "").strip().lower()
    if not config.get("enabled", True):
        return False, "disabled"
    if provider != "sentence_transformers":
        return False, f"unsupported provider: {provider}"
    try:
        __import__("sentence_transformers")
    except Exception as exc:
        return False, f"sentence-transformers unavailable: {exc}"
    return True, None


def reranker_provider_available(config: dict[str, Any] | None) -> tuple[bool, str | None]:
    reranker = reranker_config(config)
    if not reranker.get("enabled", False):
        return False, "disabled"
    provider = str(reranker.get("provider") or "").strip().lower()
    if provider != "sentence_transformers":
        return False, f"unsupported provider: {provider}"
    try:
        __import__("sentence_transformers")
    except Exception as exc:
        return False, f"sentence-transformers unavailable: {exc}"
    return True, None


def load_sentence_transformer(model_name: str, device: str):
    key = (model_name, device)
    model = _EMBEDDING_MODEL_CACHE.get(key)
    if model is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name, device=device)
        _EMBEDDING_MODEL_CACHE[key] = model
    return model


def load_cross_encoder(model_name: str, device: str):
    key = (model_name, device)
    model = _RERANKER_MODEL_CACHE.get(key)
    if model is None:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(model_name, device=device)
        _RERANKER_MODEL_CACHE[key] = model
    return model


def embed_texts_with_provider(texts: list[str], config: dict[str, Any]) -> list[list[float]]:
    provider = str(config.get("provider") or "").strip().lower()
    model_name = str(config.get("model") or "").strip()
    if provider != "sentence_transformers":
        raise RuntimeError(f"Unsupported embeddings provider: {provider}")
    if not model_name:
        raise RuntimeError("Embeddings config missing model")
    model = load_sentence_transformer(model_name, str(config.get("device") or "cpu"))
    vectors = model.encode(
        texts,
        batch_size=max(1, int(config.get("batch_size", 16))),
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return [vector.tolist() for vector in vectors]


def rerank_candidates(query: str, candidates: list[dict[str, Any]], config: dict[str, Any] | None) -> list[dict[str, Any]]:
    reranker = reranker_config(config)
    if not candidates:
        return []
    available, _ = reranker_provider_available(config)
    if not available:
        return candidates
    model_name = str(reranker.get("model") or "").strip()
    if not model_name:
        return candidates
    candidate_limit = min(len(candidates), max(1, int(reranker.get("candidate_limit", 24))))
    shortlist = candidates[:candidate_limit]
    texts = [
        "\n".join(
            part.strip()
            for part in (
                str(item.get("title") or item.get("entity_label") or ""),
                str(item.get("preview") or item.get("entity_summary") or ""),
                str(item.get("fact_text") or ""),
            )
            if part and part.strip()
        )
        for item in shortlist
    ]
    model = load_cross_encoder(model_name, str(reranker.get("device") or "cpu"))
    scores = model.predict(
        [[query, text] for text in texts],
        batch_size=max(1, int(reranker.get("batch_size", 8))),
        show_progress_bar=False,
    )
    ranked = []
    for item, score in zip(shortlist, scores):
        normalized = dict(item)
        normalized["reranker_score"] = float(score)
        reasons = set(normalized.get("retrieval_reasons", []))
        reasons.add("reranker")
        normalized["retrieval_reasons"] = sorted(reasons)
        ranked.append(normalized)
    return sort_candidates(ranked + candidates[candidate_limit:])


def filter_low_relevance_candidates(query: str, candidates: list[dict[str, Any]], config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not candidates:
        return []
    reranker = reranker_config(config)
    min_score = float(reranker.get("min_score", 0.05))
    embedding_min_score = float(reranker.get("embedding_min_score", 0.62))
    reranker_observed = any(
        "reranker_score" in item or "reranker" in set(item.get("retrieval_reasons", []))
        for item in candidates
    )
    filtered = []
    for item in candidates:
        reasons = set(item.get("retrieval_reasons", []))
        if {"lexical", "exact", "token_overlap"} & reasons:
            filtered.append(item)
            continue
        reranker_score = item.get("reranker_score")
        if reranker_score is not None:
            if float(reranker_score) >= min_score:
                filtered.append(item)
            continue
        if reranker_observed:
            continue
        embedding_score = item.get("embedding_score")
        if embedding_score is None or float(embedding_score) < embedding_min_score:
            continue
        filtered.append(item)
    return filtered


def candidate_final_score(item: dict[str, Any]) -> float:
    score = 0.0
    if item.get("reranker_score") is not None:
        score += float(item.get("reranker_score") or 0.0) * 100.0
    score += float(item.get("lexical_rank_score") or 0.0)
    score += float(item.get("exact_match_boost") or 0.0)
    score += float(item.get("token_overlap_score") or 0.0) * 2.0
    score += float(item.get("lexical_score") or 0.0)
    score += float(item.get("embedding_score") or 0.0) * 10.0
    score += float(item.get("query_penalty") or 0.0)
    return score


def sort_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            -candidate_final_score(item),
            item.get("rank", 1_000_000),
            item.get("stable_key") or "",
        ),
    )


def apply_query_sensitive_scoring(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_tokens = set(query_signal_tokens(query))
    query_mentions_obsolete = bool(query_tokens & OBSOLETE_MEMORY_TOKENS)
    scored = []
    for item in items:
        normalized = dict(item)
        title = str(normalized.get("title") or "")
        preview = str(normalized.get("preview") or "")
        stable_key = str(normalized.get("stable_key") or "")
        normalized["token_overlap_score"] = max(
            float(normalized.get("token_overlap_score") or 0.0),
            title_summary_overlap_score(query, title=title, summary=preview, stable_key=stable_key),
        )
        if not query_mentions_obsolete:
            obsolete_hits = set(normalized_tokens(f"{title} {preview}")) & OBSOLETE_MEMORY_TOKENS
            if obsolete_hits:
                normalized["query_penalty"] = float(normalized.get("query_penalty") or 0.0) - 30.0
        scored.append(normalized)
    return sort_candidates(scored)


class FalkorToolShim:
    STATUS_WINDOW_DAYS_DEFAULT = STATUS_WINDOW_DAYS_DEFAULT
    workflow_step = staticmethod(workflow_step)
    workspace_payload = staticmethod(workspace_payload)
    build_read_workflow = staticmethod(build_read_workflow)
    embedding_provider_available = staticmethod(embedding_provider_available)
    embed_texts_with_provider = staticmethod(embed_texts_with_provider)
    rerank_candidates = staticmethod(rerank_candidates)
    filter_low_relevance_candidates = staticmethod(filter_low_relevance_candidates)


def reranker_enabled_for_current_process(config: dict[str, Any] | None) -> bool:
    reranker = reranker_config(config)
    if not reranker.get("enabled", False):
        return False
    if str(os.environ.get("AUTOPSY_MEMORY_CLI_MODE") or "").strip() == "1":
        return str(os.environ.get("AUTOPSY_MEMORY_CLI_RERANK") or "").strip() == "1"
    return True


def load_falkordb():
    try:
        from falkordb import FalkorDB
    except ImportError:
        raise RuntimeError(
            "falkordb is not installed. Install it with: python3 -m venv /tmp/falkordb-py-venv && "
            "source /tmp/falkordb-py-venv/bin/activate && pip install falkordb redis"
        )
    return FalkorDB


def load_falkordblite():
    try:
        from redislite.falkordb_client import FalkorDB
    except ImportError:
        raise RuntimeError(
            "embedded FalkorDB requires FalkorDBLite. Install it with: python3 -m pip install falkordblite"
        )
    return FalkorDB


def tokenize_query(query: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9_]+", query) if len(token) >= 2]


def normalized_tokens(value: str) -> list[str]:
    normalized: list[str] = []
    for token in tokenize_query(value):
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token).split()
        if len(parts) > 1:
            normalized.extend(part.lower() for part in parts if len(part) >= 2)
        normalized.append(token.lower())
    return normalized


def query_signal_tokens(value: str) -> list[str]:
    tokens = []
    seen: set[str] = set()
    for token in normalized_tokens(value):
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    filtered = [token for token in tokens if token not in COMMON_QUERY_TOKENS]
    return filtered or tokens


def query_has_unlikely_identifier(value: str) -> bool:
    for token in query_signal_tokens(value):
        if token.startswith("nohit"):
            return True
        if len(token) >= 20:
            return True
        if re.fullmatch(r"[0-9a-f]{12,}", token):
            return True
    return False


def title_summary_overlap_score(query: str, *, title: str, summary: str, stable_key: str) -> float:
    query_tokens = query_signal_tokens(query)
    if not query_tokens:
        return 0.0
    title_tokens = set(normalized_tokens(title))
    summary_tokens = set(normalized_tokens(summary))
    stable_key_tokens = set(normalized_tokens(stable_key))
    overlap = 0.0
    for token in query_tokens:
        if token in title_tokens:
            overlap += 8.0
        elif token in summary_tokens:
            overlap += 3.0
        elif token in stable_key_tokens:
            overlap += 2.0
    if title and query.strip().lower() in title.lower():
        overlap += 40.0
    return overlap


def rerank_lexical_hits(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lowered_query = query.strip().lower()
    reranked: list[dict[str, Any]] = []
    query_tokens = set(query_signal_tokens(query))
    query_mentions_obsolete = bool(query_tokens & OBSOLETE_MEMORY_TOKENS)
    for item in items:
        normalized = dict(item)
        title = str(normalized.get("title") or "")
        preview = str(normalized.get("preview") or "")
        stable_key = str(normalized.get("stable_key") or "")
        overlap_score = title_summary_overlap_score(query, title=title, summary=preview, stable_key=stable_key)
        maintenance_penalty = 0.0
        title_tokens = set(normalized_tokens(title))
        if query_tokens.isdisjoint({"memory", "falkor", "ladybug", "retrieval", "consult", "latency", "worker"}):
            if title_tokens & {"memory", "falkor", "ladybug", "retrieval", "consult", "latency", "worker"}:
                maintenance_penalty -= 12.0
        if not query_mentions_obsolete:
            obsolete_hits = set(normalized_tokens(f"{title} {preview}")) & OBSOLETE_MEMORY_TOKENS
            if obsolete_hits:
                maintenance_penalty -= 30.0
        normalized["token_overlap_score"] = overlap_score
        normalized["lexical_rank_score"] = overlap_score + float(normalized.get("exact_match_boost", 0.0)) + float(normalized.get("lexical_score", 0.0)) + maintenance_penalty
        if lowered_query and lowered_query in preview.lower() and lowered_query not in title.lower():
            normalized["lexical_rank_score"] -= 10.0
        reranked.append(normalized)
    reranked.sort(
        key=lambda item: (
            -(float(item.get("lexical_rank_score", 0.0))),
            -(float(item.get("token_overlap_score", 0.0))),
            item.get("rank", 0),
            item.get("stable_key", ""),
        )
    )
    return reranked


def lexical_minimum_rank_score(query: str) -> float:
    token_count = len(set(query_signal_tokens(query)))
    if token_count <= 2:
        return 2.0
    if token_count <= 5:
        return 3.0
    return 4.0


def lexical_minimum_token_matches(query: str) -> int:
    token_count = len(set(query_signal_tokens(query)))
    if token_count <= 2:
        return 1
    if token_count <= 5:
        return 2
    return 3


def filter_weak_lexical_hits(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    minimum = lexical_minimum_rank_score(query)
    minimum_matches = lexical_minimum_token_matches(query)
    query_tokens = set(query_signal_tokens(query))
    filtered = []
    for item in items:
        exact_boost = float(item.get("exact_match_boost", 0.0))
        token_overlap = float(item.get("token_overlap_score", 0.0))
        rank_score = float(item.get("lexical_rank_score", exact_boost + token_overlap + float(item.get("lexical_score", 0.0))))
        item_tokens = set(
            normalized_tokens(
                " ".join(
                    [
                        str(item.get("title") or ""),
                        str(item.get("preview") or ""),
                        str(item.get("stable_key") or ""),
                    ]
                )
            )
        )
        matched_tokens = len(query_tokens & item_tokens)
        if exact_boost >= 10.0 or (matched_tokens >= minimum_matches and token_overlap >= minimum and rank_score >= minimum):
            filtered.append(item)
    return filtered


def strong_lexical_hit_count(items: list[dict[str, Any]], config: dict[str, Any] | None) -> int:
    threshold = float((config or {}).get("fast_lexical_min_score", EMBEDDINGS_CONFIG_DEFAULT["fast_lexical_min_score"]))
    return sum(1 for item in items if candidate_final_score(item) >= threshold)


def lexical_results_are_strong(items: list[dict[str, Any]], *, limit: int, config: dict[str, Any] | None) -> bool:
    if not items:
        return False
    min_hits = max(1, int((config or {}).get("fast_lexical_min_hits", EMBEDDINGS_CONFIG_DEFAULT["fast_lexical_min_hits"])))
    return strong_lexical_hit_count(items[: max(limit, min_hits)], config) >= min(min_hits, max(limit, 1))


def sanitize_query_for_fts(query: str) -> str:
    tokens = tokenize_query(query)
    if not tokens:
        return query.strip()
    return " | ".join(tokens)


def classify_query(query: str) -> str:
    lowered = query.strip().lower()
    if any(hint in lowered for hint in STATUS_HINTS):
        return "status"
    tokens = tokenize_query(query)
    if "`" in query or '"' in query or "'" in query:
        return "lexical"
    if any(sep in query for sep in ("::", "/", "_", "-")) and len(tokens) <= 8:
        return "lexical"
    if any(re.search(r"[a-z][A-Z]", token) for token in tokens) and len(tokens) <= 8:
        return "lexical"
    if len(tokens) <= 4:
        return "lexical"
    return "hybrid"


def escape(value: str) -> str:
    return json.dumps(value)


def vec_literal(vector: list[float]) -> str:
    return "vecf32([" + ",".join(f"{float(value):.8f}" for value in vector) + "])"


def kind_to_label(kind: str) -> str:
    parts = [part for part in kind.split("_") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Unknown"


def node_labels_for_kind(kind: str) -> list[str]:
    labels = ["MemoryNode"]
    if kind in SEARCHABLE_KINDS:
        labels.append("SemanticItem")
    elif kind in OPERATIONAL_KINDS:
        labels.append("OperationalNode")
    elif kind in ADJACENT_CONTEXT_KINDS:
        labels.append("ContextNode")
    labels.append(kind_to_label(kind))
    return labels


def labels_clause(labels: list[str]) -> str:
    return "".join(f":{label}" for label in labels)


def structural_edge_label(relation: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", relation.strip()).strip("_")
    return normalized.upper() if normalized else "MEMORY_EDGE"


def workspace_graph_name(base_graph_name: str, workspace: dict[str, Any]) -> str:
    record = dict(workspace)
    workspace_key = str(record.get("workspace_key") or record.get("root_path") or record.get("id") or "workspace")
    workspace_slug = str(record.get("slug") or Path(workspace_key).name or "workspace")
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", workspace_slug).strip("_") or "workspace"
    suffix = hashlib.sha1(workspace_key.encode("utf-8")).hexdigest()[:10]
    return f"{base_graph_name}_{slug}_{suffix}"


def ensure_graph(host: str, port: int, graph_name: str, lite_path: str | None = None):
    if lite_path:
        FalkorDBLite = load_falkordblite()
        resolved_path = str(Path(lite_path).expanduser())
        Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)
        client = _FALKORDB_LITE_CLIENTS.get(resolved_path)
        if client is None:
            client = FalkorDBLite(resolved_path)
            _FALKORDB_LITE_CLIENTS[resolved_path] = client
        return client.select_graph(graph_name)
    FalkorDB = load_falkordb()
    client = FalkorDB(host=host, port=port)
    return client.select_graph(graph_name)


def reset_falkordb_lite_client(lite_path: str | None) -> None:
    if not lite_path:
        return
    resolved_path = str(Path(lite_path).expanduser())
    client = _FALKORDB_LITE_CLIENTS.pop(resolved_path, None)
    shutdown = getattr(client, 'shutdown', None)
    if callable(shutdown):
        try:
            shutdown()
        except Exception:
            pass


def result_rows(result) -> list[list[Any]]:
    return result.result_set or []


def invalidate_graph_caches(graph) -> None:
    graph_name = getattr(graph, "name", "graph")
    _GRAPH_SEMANTIC_ITEM_COUNT.pop(graph_name, None)
    _GRAPH_VECTOR_AVAILABILITY.pop(graph_name, None)


def semantic_item_count(graph) -> int:
    graph_name = getattr(graph, "name", "graph")
    cached = _GRAPH_SEMANTIC_ITEM_COUNT.get(graph_name)
    if cached is not None:
        return cached
    value = int(scalar_query(graph, "MATCH (:SemanticItem) RETURN count(*)") or 0)
    _GRAPH_SEMANTIC_ITEM_COUNT[graph_name] = value
    return value


def token_overlap_scan_max_items(config: dict[str, Any] | None) -> int:
    if isinstance(config, dict):
        return max(0, int(config.get("token_overlap_scan_max_items", EMBEDDINGS_CONFIG_DEFAULT["token_overlap_scan_max_items"])))
    return int(EMBEDDINGS_CONFIG_DEFAULT["token_overlap_scan_max_items"])


def should_use_token_overlap_scan(item_count: int, config: dict[str, Any] | None) -> bool:
    limit = token_overlap_scan_max_items(config)
    return limit > 0 and item_count <= limit


def fetch_node_lexical(graph, query: str, *, limit: int) -> tuple[list[dict[str, Any]], float]:
    parsed = sanitize_query_for_fts(query)
    started = time.perf_counter()
    result = graph.query(
        """
        CALL db.idx.fulltext.queryNodes('SemanticItem', $query)
        YIELD node, score
        RETURN
          node.entity_id,
          node.stable_key,
          node.kind,
          node.label,
          node.summary,
          node.updated_at,
          coalesce(node.source_kind, ''),
          coalesce(node.detail_content, ''),
          score
        LIMIT $limit
        """,
        params={"query": parsed, "limit": max(limit * 4, 24)},
    )
    elapsed = time.perf_counter() - started
    items = []
    query_lower = query.strip().lower()
    for rank, row in enumerate(result_rows(result)):
        kind = str(row[2] or "")
        if kind not in SEARCHABLE_KINDS:
            continue
        stable_key = str(row[1] or "")
        source_kind = str(row[6] or "")
        detail_content = str(row[7] or "")
        # Keep provenance-heavy episode/outcome nodes out of the hot lexical set.
        if stable_key.startswith("turn-outcome:"):
            continue
        if kind == "memory_note" and source_kind == "graph_episode":
            continue
        title = str(row[3] or "")
        summary = str(row[4] or "")
        lexical_score = float(row[8])
        exact_match_boost = 0.0
        if query_lower:
            if query_lower in title.lower():
                exact_match_boost += 100.0
            if title.lower().startswith(query_lower):
                exact_match_boost += 40.0
            if query_lower in summary.lower():
                exact_match_boost += 15.0
            if detail_content and query_lower in detail_content.lower():
                exact_match_boost += 10.0
        if source_kind == "graph_note":
            exact_match_boost += 5.0
        items.append(
            {
                "entity_id": int(row[0]),
                "stable_key": stable_key,
                "kind": kind,
                "title": title,
                "preview": summary[:280],
                "updated_at": str(row[5] or ""),
                "activity_at": str(row[5] or ""),
                "source_kind": source_kind,
                "lexical_score": lexical_score,
                "exact_match_boost": exact_match_boost,
                "retrieval_reasons": ["lexical"],
                "rank": rank,
            }
        )
    items.sort(
        key=lambda item: (
            -(float(item.get("exact_match_boost", 0.0)) + float(item.get("lexical_score", 0.0))),
            item.get("rank", 0),
            item.get("stable_key", ""),
        )
    )
    return items, elapsed


def fetch_exact_text_candidates(graph, query: str, *, limit: int) -> tuple[list[dict[str, Any]], float]:
    normalized = query.strip().lower()
    if not normalized:
        return [], 0.0
    started = time.perf_counter()
    result = graph.query(
        """
        MATCH (node:SemanticItem)
        WHERE (
            toLower(coalesce(node.label, '')) CONTAINS $query
            OR toLower(coalesce(node.stable_key, '')) CONTAINS $query
        )
        RETURN
          node.entity_id,
          node.stable_key,
          node.kind,
          node.label,
          node.summary,
          node.updated_at,
          coalesce(node.source_kind, '')
        LIMIT $limit
        """,
        params={"query": normalized, "limit": max(limit * 4, 24)},
    )
    elapsed = time.perf_counter() - started
    items = []
    for rank, row in enumerate(result_rows(result)):
        kind = str(row[2] or "")
        if kind not in SEARCHABLE_KINDS:
            continue
        stable_key = str(row[1] or "")
        source_kind = str(row[6] or "")
        if stable_key.startswith("turn-outcome:"):
            continue
        if source_kind == "graph_episode":
            continue
        title = str(row[3] or "")
        summary = str(row[4] or "")
        boost = 0.0
        if normalized == title.lower():
            boost += 200.0
        if normalized in title.lower():
            boost += 120.0
        if title.lower().startswith(normalized):
            boost += 40.0
        if normalized in summary.lower():
            boost += 20.0
        if source_kind == "graph_note":
            boost += 5.0
        items.append(
            {
                "entity_id": int(row[0]),
                "stable_key": stable_key,
                "kind": kind,
                "title": title,
                "preview": summary[:280],
                "updated_at": str(row[5] or ""),
                "activity_at": str(row[5] or ""),
                "source_kind": source_kind,
                "lexical_score": boost,
                "exact_match_boost": boost,
                "retrieval_reasons": ["exact"],
                "rank": rank,
            }
        )
    items.sort(
        key=lambda item: (
            -(float(item.get("exact_match_boost", 0.0))),
            item.get("rank", 0),
            item.get("stable_key", ""),
        )
    )
    return items, elapsed


def fetch_relationship_lexical(graph, query: str, *, limit: int) -> tuple[list[dict[str, Any]], float]:
    parsed = sanitize_query_for_fts(query)
    started = time.perf_counter()
    result = graph.query(
        """
        CALL db.idx.fulltext.queryRelationships('FACT_EDGE', $query)
        YIELD relationship, score
        RETURN relationship.fact_text, relationship.relation, relationship.predicate, score
        LIMIT $limit
        """,
        params={"query": parsed, "limit": max(limit * 2, 12)},
    )
    elapsed = time.perf_counter() - started
    items = []
    for row in result_rows(result):
        items.append(
            {
                "fact_text": str(row[0] or ""),
                "relation": str(row[1] or ""),
                "predicate": str(row[2] or ""),
                "score": float(row[3]),
            }
        )
    return items, elapsed


def fetch_token_overlap_candidates(graph, query: str, *, limit: int) -> tuple[list[dict[str, Any]], float]:
    tokens = [token.lower() for token in query_signal_tokens(query) if len(token) >= 3]
    if not tokens:
        return [], 0.0
    token_limit = min(len(tokens), 6)
    min_token_hits = 2 if token_limit <= 3 else max(3, int(round(token_limit * 0.5)))
    clauses = []
    score_parts = []
    params: dict[str, Any] = {"limit": max(limit * 24, 240)}
    for index, token in enumerate(tokens[:token_limit]):
        key = f"token_{index}"
        params[key] = token
        match_expression = (
            f"toLower(coalesce(node.label, '')) CONTAINS ${key} OR "
            f"toLower(coalesce(node.summary, '')) CONTAINS ${key} OR "
            f"toLower(coalesce(node.stable_key, '')) CONTAINS ${key} OR "
            f"toLower(coalesce(node.search_text, '')) CONTAINS ${key}"
        )
        clauses.append(match_expression)
        score_parts.append(f"CASE WHEN {match_expression} THEN 1 ELSE 0 END")
    score_expression = " + ".join(score_parts) if score_parts else "0"
    started = time.perf_counter()
    result = graph.query(
        f"""
        MATCH (node:SemanticItem)
        WHERE {' OR '.join(f'({clause})' for clause in clauses)}
        RETURN
          node.entity_id,
          node.stable_key,
          node.kind,
          node.label,
          coalesce(node.summary, ''),
          coalesce(node.updated_at, node.created_at),
          coalesce(node.source_kind, ''),
          {score_expression} AS token_hits
        ORDER BY token_hits DESC, coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params=params,
    )
    elapsed = time.perf_counter() - started
    items = []
    for rank, row in enumerate(result_rows(result)):
        if float(row[7] or 0.0) < min_token_hits:
            continue
        kind = str(row[2] or "")
        if kind not in SEARCHABLE_KINDS:
            continue
        stable_key = str(row[1] or "")
        source_kind = str(row[6] or "")
        if stable_key.startswith("turn-outcome:"):
            continue
        if source_kind == "graph_episode":
            continue
        items.append(
            {
                "entity_id": int(row[0]),
                "stable_key": stable_key,
                "kind": kind,
                "title": str(row[3] or ""),
                "preview": str(row[4] or "")[:280],
                "updated_at": str(row[5] or ""),
                "activity_at": str(row[5] or ""),
                "source_kind": source_kind,
                "lexical_score": float(row[7] or 0.0),
                "retrieval_reasons": ["token_overlap"],
                "rank": rank,
            }
        )
    return filter_weak_lexical_hits(query, rerank_lexical_hits(query, items)), elapsed


def fetch_vector_candidates(graph, tool, query: str, config: dict[str, Any], *, limit: int) -> tuple[list[dict[str, Any]], float]:
    provider_ok, _ = tool.embedding_provider_available(config)
    if not provider_ok:
        return [], 0.0
    graph_name = getattr(graph, "name", "graph")
    has_vectors = _GRAPH_VECTOR_AVAILABILITY.get(graph_name)
    if has_vectors is None:
        try:
            probe = graph.query(
                """
                MATCH (node:SemanticItem)
                WHERE node.embedding IS NOT NULL
                RETURN count(node)
                LIMIT 1
                """
            )
            rows = result_rows(probe)
            has_vectors = bool(rows and int(rows[0][0] or 0) > 0)
        except Exception:
            has_vectors = False
        _GRAPH_VECTOR_AVAILABILITY[graph_name] = has_vectors
    if not has_vectors:
        return [], 0.0
    vector = tool.embed_texts_with_provider([query], config)[0]
    if not vector:
        return [], 0.0
    started = time.perf_counter()
    try:
        candidate_limit = max(limit * 4, int(config.get("vector_candidate_limit") or config.get("candidate_limit") or 48))
        result = graph.query(
            f"""
            CALL db.idx.vector.queryNodes('SemanticItem', 'embedding', $limit, {vec_literal(vector)})
            YIELD node, score
            RETURN
              node.entity_id,
              node.stable_key,
              node.kind,
              node.label,
              node.summary,
              node.updated_at,
              coalesce(node.source_kind, ''),
              score
            """,
            params={
                "limit": candidate_limit,
            },
        )
    except Exception:
        _GRAPH_VECTOR_AVAILABILITY[graph_name] = False
        return [], 0.0
    elapsed = time.perf_counter() - started
    items = []
    for rank, row in enumerate(result_rows(result)):
        kind = str(row[2] or "")
        if kind not in SEARCHABLE_KINDS:
            continue
        stable_key = str(row[1] or "")
        if stable_key.startswith("turn-outcome:"):
            continue
        source_kind = str(row[6] or "")
        if source_kind == "graph_episode":
            continue
        items.append(
            {
                "entity_id": int(row[0]),
                "stable_key": stable_key,
                "kind": kind,
                "title": str(row[3] or ""),
                "preview": str(row[4] or "")[:280],
                "updated_at": str(row[5] or ""),
                "activity_at": str(row[5] or ""),
                "source_kind": source_kind,
                "embedding_score": float(row[7]),
                "retrieval_reasons": ["embedding"],
                "rank": rank,
            }
        )
    return items, elapsed


def resolve_seed(graph, *, stable_key: str | None, entity_id: int | None, thread_id: str | None) -> dict[str, Any]:
    if entity_id is not None:
        result = graph.query(
            """
            MATCH (e:MemoryNode {entity_id: $entity_id})
            RETURN e.entity_id, e.stable_key, e.kind, e.label
            LIMIT 1
            """,
            params={"entity_id": entity_id},
        )
    else:
        lookup_key = stable_key or thread_id
        if not lookup_key:
            fail("expected one of --stable-key, --entity-id, or --thread-id", 2)
        result = graph.query(
            """
            MATCH (e:MemoryNode {stable_key: $stable_key})
            RETURN e.entity_id, e.stable_key, e.kind, e.label
            LIMIT 1
            """,
            params={"stable_key": lookup_key},
        )
    rows = result_rows(result)
    if not rows:
        fail("graph item not found", 2)
    row = rows[0]
    return {
        "entity_id": int(row[0]),
        "stable_key": str(row[1]),
        "kind": str(row[2] or ""),
        "title": str(row[3] or ""),
    }


def fetch_item(graph, stable_key: str) -> dict[str, Any]:
    result = graph.query(
        """
        MATCH (e:MemoryNode {stable_key: $stable_key})
        RETURN
          e.entity_id,
          e.stable_key,
          e.kind,
          e.label,
          e.detail_content,
          coalesce(e.confidence, 1.0),
          e.source_kind,
          e.created_at,
          e.updated_at
        LIMIT 1
        """,
        params={"stable_key": stable_key},
    )
    rows = result_rows(result)
    if not rows:
        fail(f"Graph item not found: {stable_key}", 2)
    row = rows[0]
    links_result = graph.query(
        """
        MATCH (center:MemoryNode {stable_key: $stable_key})-[edge]->(related:MemoryNode)
        WHERE type(edge) IN $edge_types
          AND related.kind IN ['workspace', 'repository', 'thread', 'worktree', 'branch', 'episode']
        RETURN coalesce(edge.relation, toLower(type(edge))), related.entity_id, related.kind, related.stable_key, related.label
        ORDER BY edge.updated_at DESC
        """,
        params={"stable_key": stable_key, "edge_types": list(STRUCTURAL_EDGE_TYPES)},
    )
    relations_result = graph.query(
        """
        MATCH (center:MemoryNode {stable_key: $stable_key})-[fact:FACT_EDGE]-(related:MemoryNode)
        RETURN
          fact.relation,
          fact.predicate,
          CASE WHEN fact.from_entity_id = center.entity_id THEN 'outgoing' ELSE 'incoming' END,
          related.entity_id,
          related.kind,
          related.stable_key,
          related.label,
          fact.fact_text,
          fact.valid_at,
          fact.invalid_at,
          fact.expired_at,
          fact.updated_at
        ORDER BY fact.updated_at DESC, related.updated_at DESC
        """,
        params={"stable_key": stable_key},
    )
    relations = []
    center_entity_id = int(row[0])
    for relation_row in result_rows(relations_result):
        direction = str(relation_row[2] or "")
        if not direction:
            direction = "outgoing"
        relations.append(
            {
                "relation": str(relation_row[0] or ""),
                "predicate": str(relation_row[1] or relation_row[0] or ""),
                "direction": direction,
                "entity_id": int(relation_row[3]),
                "entity_kind": str(relation_row[4] or ""),
                "entity_stable_key": str(relation_row[5] or ""),
                "entity_label": str(relation_row[6] or ""),
                "fact_text": str(relation_row[7] or ""),
                "valid_at": str(relation_row[8] or ""),
                "invalid_at": str(relation_row[9] or ""),
                "expired_at": str(relation_row[10] or ""),
                "updated_at": str(relation_row[11] or ""),
            }
        )
    return {
        "entity_id": center_entity_id,
        "stable_key": str(row[1] or ""),
        "kind": str(row[2] or ""),
        "title": str(row[3] or ""),
        "content": str(row[4] or ""),
        "confidence": float(row[5] or 1.0),
        "source_kind": str(row[6] or ""),
        "created_at": str(row[7] or ""),
        "updated_at": str(row[8] or ""),
        "links": [
            {
                "relation": str(link_row[0] or ""),
                "entity_id": int(link_row[1]),
                "entity_kind": str(link_row[2] or ""),
                "entity_stable_key": str(link_row[3] or ""),
                "entity_label": str(link_row[4] or ""),
            }
            for link_row in result_rows(links_result)
        ],
        "relations": relations,
    }


def fetch_neighbors(graph, seed: dict[str, Any], *, limit: int, semantic_only: bool) -> list[dict[str, Any]]:
    relationship_filter = ":FACT_EDGE" if semantic_only else ""
    direct_result = graph.query(
        f"""
        MATCH (seed:MemoryNode {{entity_id: $entity_id}})-[rel{relationship_filter}]-(candidate:MemoryNode)
        WHERE candidate.entity_id <> seed.entity_id
        RETURN DISTINCT
          candidate.entity_id AS entity_id,
          candidate.kind AS kind,
          candidate.stable_key AS stable_key,
          candidate.label AS label,
          coalesce(candidate.summary, '') AS summary,
          1 AS depth,
          coalesce(candidate.updated_at, candidate.created_at) AS updated_at,
          coalesce(candidate.updated_at, candidate.created_at) AS activity_at,
          coalesce(candidate.source_kind, '') AS source_kind
        ORDER BY updated_at DESC
        LIMIT $limit
        """,
        params={"entity_id": seed["entity_id"], "limit": max(limit * 3, 24)},
    )
    second_result = graph.query(
        f"""
        MATCH (seed:MemoryNode {{entity_id: $entity_id}})-[rel1{relationship_filter}]-(middle:MemoryNode)-[rel2{relationship_filter}]-(candidate:MemoryNode)
        WHERE candidate.entity_id <> seed.entity_id
          AND candidate.entity_id <> middle.entity_id
        RETURN DISTINCT
          candidate.entity_id AS entity_id,
          candidate.kind AS kind,
          candidate.stable_key AS stable_key,
          candidate.label AS label,
          coalesce(candidate.summary, '') AS summary,
          2 AS depth,
          coalesce(candidate.updated_at, candidate.created_at) AS updated_at,
          coalesce(candidate.updated_at, candidate.created_at) AS activity_at,
          coalesce(candidate.source_kind, '') AS source_kind
        ORDER BY updated_at DESC
        LIMIT $limit
        """,
        params={"entity_id": seed["entity_id"], "limit": max(limit * 3, 24)},
    )
    merged: dict[int, dict[str, Any]] = {}
    for row in result_rows(direct_result) + result_rows(second_result):
        entity_id = int(row[0])
        item = {
            "id": entity_id,
            "kind": str(row[1] or ""),
            "stable_key": str(row[2] or ""),
            "label": str(row[3] or ""),
            "summary": str(row[4] or ""),
            "depth": int(row[5]),
            "updated_at": str(row[6] or ""),
            "activity_at": str(row[7] or ""),
            "source_episode_kind": str(row[8] or ""),
        }
        existing = merged.get(entity_id)
        if existing is None or item["depth"] < existing["depth"]:
            merged[entity_id] = item
    items = sorted(
        merged.values(),
        key=lambda item: (
            int(item.get("depth", 9)),
            -(0 if not item.get("updated_at") else 1),
            item.get("updated_at", ""),
            item.get("stable_key", ""),
        ),
        reverse=False,
    )
    if semantic_only:
        items = [
            item
            for item in items
            if item["kind"] in SEARCHABLE_KINDS
            and not str(item.get("stable_key") or "").startswith("turn-outcome:")
            and item.get("source_episode_kind") != "graph_episode"
        ]
    return items[:limit]


def fetch_timeline(graph, stable_key: str) -> dict[str, Any]:
    item = fetch_item(graph, stable_key)
    result = graph.query(
        """
        MATCH (center:MemoryNode {stable_key: $stable_key})-[fact:FACT_EDGE]-(related:MemoryNode)
        RETURN
          fact.relation,
          fact.predicate,
          CASE WHEN fact.from_entity_id = center.entity_id THEN 'outgoing' ELSE 'incoming' END AS direction,
          coalesce(fact.invalid_at, fact.updated_at, fact.created_at) AS event_time,
          related.stable_key,
          related.kind,
          related.label,
          fact.fact_text,
          fact.valid_at,
          fact.invalid_at,
          fact.expired_at
        ORDER BY event_time ASC
        """,
        params={"stable_key": stable_key},
    )
    events = []
    for row in result_rows(result):
        events.append(
            {
                "relation": str(row[0] or ""),
                "predicate": str(row[1] or row[0] or ""),
                "direction": str(row[2] or ""),
                "event_time": str(row[3] or ""),
                "entity_stable_key": str(row[4] or ""),
                "entity_kind": str(row[5] or ""),
                "entity_label": str(row[6] or ""),
                "fact_text": str(row[7] or ""),
                "valid_at": str(row[8] or ""),
                "invalid_at": str(row[9] or ""),
                "expired_at": str(row[10] or ""),
            }
        )
    return {"item": item, "events": events}


def fetch_snapshot(graph, stable_key: str, *, limit: int) -> dict[str, Any]:
    fact_result = graph.query(
        """
        MATCH (center:MemoryNode {stable_key: $stable_key})-[fact:FACT_EDGE]-(neighbor:MemoryNode)
        RETURN
          center.entity_id, center.stable_key, center.kind, center.label,
          neighbor.entity_id, neighbor.stable_key, neighbor.kind, neighbor.label,
          fact.relation, fact.predicate, fact.fact_text
        LIMIT $limit
        """,
        params={"stable_key": stable_key, "limit": max(limit, 1)},
    )
    struct_result = graph.query(
        """
        MATCH (center:MemoryNode {stable_key: $stable_key})-[edge]-(neighbor:MemoryNode)
        WHERE type(edge) IN $edge_types
        RETURN
          center.entity_id, center.stable_key, center.kind, center.label,
          neighbor.entity_id, neighbor.stable_key, neighbor.kind, neighbor.label,
          coalesce(edge.relation, toLower(type(edge))) AS relation,
          coalesce(edge.relation, toLower(type(edge))) AS predicate,
          '' AS fact_text
        LIMIT $limit
        """,
        params={"stable_key": stable_key, "limit": max(limit, 1), "edge_types": list(STRUCTURAL_EDGE_TYPES)},
    )
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for row in result_rows(fact_result) + result_rows(struct_result):
        center_key = str(row[1] or "")
        neighbor_key = str(row[5] or "")
        nodes[center_key] = {
            "entity_id": int(row[0]),
            "stable_key": center_key,
            "kind": str(row[2] or ""),
            "label": str(row[3] or ""),
        }
        nodes[neighbor_key] = {
            "entity_id": int(row[4]),
            "stable_key": neighbor_key,
            "kind": str(row[6] or ""),
            "label": str(row[7] or ""),
        }
        edges.append(
            {
                "from": center_key,
                "to": neighbor_key,
                "relation": str(row[8] or ""),
                "predicate": str(row[9] or row[8] or ""),
                "fact_text": str(row[10] or ""),
            }
        )
    return {
        "seed_stable_key": stable_key,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def fetch_recent_episodes(graph, *, limit: int, thread_id: str | None = None) -> list[dict[str, Any]]:
    if thread_id:
        result = graph.query(
            """
            MATCH (thread:Thread {stable_key: $thread_id})-[*1..2]-(episode:Episode)
            OPTIONAL MATCH (episode)-[:ABOUT|BELONGS_TO*1..2]-(repo:Repository)
            RETURN DISTINCT
              episode.entity_id AS episode_id,
              episode.kind AS episode_kind,
              episode.label AS episode_label,
              coalesce(episode.summary, '') AS episode_summary,
              coalesce(episode.updated_at, episode.created_at) AS event_time,
              thread.label AS thread_label,
              repo.label AS repository_label
            ORDER BY coalesce(episode.updated_at, episode.created_at) DESC
            LIMIT $limit
            """,
            params={"thread_id": thread_id, "limit": max(limit, 1)},
        )
    else:
        result = graph.query(
            """
            MATCH (episode:Episode)
            OPTIONAL MATCH (episode)-[:ABOUT|BELONGS_TO*1..2]-(repo:Repository)
            RETURN
              episode.entity_id AS episode_id,
              episode.kind AS episode_kind,
              episode.label AS episode_label,
              coalesce(episode.summary, '') AS episode_summary,
              coalesce(episode.updated_at, episode.created_at) AS event_time,
              null AS thread_label,
              repo.label AS repository_label
            ORDER BY coalesce(episode.updated_at, episode.created_at) DESC
            LIMIT $limit
            """,
            params={"limit": max(limit, 1)},
        )
    items: list[dict[str, Any]] = []
    for row in result_rows(result):
        items.append(
            {
                "id": int(row[0]),
                "kind": str(row[1] or ""),
                "title": str(row[2] or ""),
                "summary": str(row[3] or ""),
                "eventTime": str(row[4] or ""),
                "threadTitle": row[5],
                "repositoryName": row[6],
            }
        )
    return items


def fetch_semantic_nodes_for_workspace(graph, *, limit: int) -> list[dict[str, Any]]:
    result = graph.query(
        """
        MATCH (node:SemanticItem)
        RETURN
          node.entity_id AS entity_id,
          node.kind AS kind,
          node.label AS label,
          coalesce(node.summary, '') AS summary,
          coalesce(node.source_kind, '') AS source_kind,
          node.stable_key AS stable_key,
          coalesce(node.updated_at, node.created_at) AS updated_at
        ORDER BY coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(limit, 1)},
    )
    return [dict(
        id=int(row[0]),
        kind=str(row[1] or ""),
        label=str(row[2] or ""),
        summary=str(row[3] or ""),
        sourceKind=str(row[4] or ""),
        stableKey=str(row[5] or ""),
        updatedAt=str(row[6] or ""),
    ) for row in result_rows(result)]


def fetch_semantic_nodes_for_thread(graph, thread_id: str, *, limit: int) -> tuple[str, list[dict[str, Any]]]:
    thread_result = graph.query(
        """
        MATCH (thread:Thread {stable_key: $thread_id})
        RETURN thread.label
        LIMIT 1
        """,
        params={"thread_id": thread_id},
    )
    thread_rows = result_rows(thread_result)
    scope_title = str(thread_rows[0][0] or "Thread Graph") if thread_rows else "Thread Graph"
    result = graph.query(
        """
        MATCH (thread:Thread {stable_key: $thread_id})-[*1..3]-(node:SemanticItem)
        RETURN DISTINCT
          node.entity_id AS entity_id,
          node.kind AS kind,
          node.label AS label,
          coalesce(node.summary, '') AS summary,
          coalesce(node.source_kind, '') AS source_kind,
          node.stable_key AS stable_key,
          coalesce(node.updated_at, node.created_at) AS updated_at
        ORDER BY coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params={"thread_id": thread_id, "limit": max(limit, 1)},
    )
    nodes = [dict(
        id=int(row[0]),
        kind=str(row[1] or ""),
        label=str(row[2] or ""),
        summary=str(row[3] or ""),
        sourceKind=str(row[4] or ""),
        stableKey=str(row[5] or ""),
        updatedAt=str(row[6] or ""),
    ) for row in result_rows(result)]
    return scope_title, nodes


def build_graph_nodes(rows: list[dict[str, Any]], *, focus_stable_key: str | None = None) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for row in rows:
        stable_key = str(row.get("stableKey") or "")
        nodes.append(
            {
                "id": int(row["id"]),
                "kind": str(row.get("kind") or ""),
                "label": str(row.get("label") or ""),
                "summary": str(row.get("summary") or "") or None,
                "stateFlags": [],
                "isFocus": stable_key == focus_stable_key if focus_stable_key else False,
                "sourceKind": str(row.get("sourceKind") or "") or None,
                "sourceRef": stable_key or None,
            }
        )
    return nodes


def fetch_connections(graph, node_ids: list[int], *, limit: int | None = None) -> list[dict[str, Any]]:
    if not node_ids:
        return []
    params = {"node_ids": node_ids}
    fact_limit_clause = ""
    if limit is not None:
        params["limit"] = max(limit, 1)
        fact_limit_clause = "\n        LIMIT $limit"
    fact_result = graph.query(
        f"""
        MATCH (src:MemoryNode)-[fact:FACT_EDGE]->(dst:MemoryNode)
        WHERE src.entity_id IN $node_ids AND dst.entity_id IN $node_ids
        RETURN
          fact.edge_id AS edge_id,
          fact.relation AS relation,
          fact.predicate AS predicate,
          src.entity_id AS from_id,
          dst.entity_id AS to_id,
          src.label AS from_label,
          src.kind AS from_kind,
          dst.label AS to_label,
          dst.kind AS to_kind,
          fact.fact_text AS fact_text
        ORDER BY fact.edge_id ASC
        {fact_limit_clause}
        """,
        params=params,
    )
    structural_limit_clause = ""
    if limit is not None:
        structural_limit_clause = "\n        LIMIT $limit"
    structural_result = graph.query(
        f"""
        MATCH (src:MemoryNode)-[edge]->(dst:MemoryNode)
        WHERE src.entity_id IN $node_ids
          AND dst.entity_id IN $node_ids
          AND type(edge) IN $edge_types
        RETURN
          edge.edge_id AS edge_id,
          coalesce(edge.relation, toLower(type(edge))) AS relation,
          coalesce(edge.relation, toLower(type(edge))) AS predicate,
          src.entity_id AS from_id,
          dst.entity_id AS to_id,
          src.label AS from_label,
          src.kind AS from_kind,
          dst.label AS to_label,
          dst.kind AS to_kind,
          '' AS fact_text
        ORDER BY edge.edge_id ASC
        {structural_limit_clause}
        """,
        params={**params, "edge_types": list(STRUCTURAL_EDGE_TYPES)},
    )
    connections: list[dict[str, Any]] = []
    for row in result_rows(fact_result) + result_rows(structural_result):
        connections.append(
            {
                "id": int(row[0]),
                "relation": str(row[1] or ""),
                "predicate": str(row[2] or row[1] or ""),
                "fromNodeID": int(row[3]),
                "toNodeID": int(row[4]),
                "subjectLabel": str(row[5] or "") or None,
                "subjectKind": str(row[6] or "") or None,
                "objectLabel": str(row[7] or "") or None,
                "objectKind": str(row[8] or "") or None,
                "factText": str(row[9] or "") or None,
                "explanation": None,
                "overlapTerms": [],
                "isExplicit": True,
                "predicateDefinition": None,
            }
        )
    return connections


def build_status_payload(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    thread_id: str | None,
    limit: int,
    section_limit: int,
    recent_days: int,
) -> dict[str, Any]:
    operational_semantic_result = graph.query(
        """
        MATCH (node:SemanticItem)
        WHERE coalesce(node.source_kind, '') <> 'memory_doc'
        RETURN
          node.entity_id AS entity_id,
          node.stable_key AS stable_key,
          node.kind AS kind,
          node.label AS label,
          coalesce(node.summary, '') AS summary,
          coalesce(node.updated_at, node.created_at) AS updated_at,
          coalesce(node.source_kind, '') AS source_kind
        ORDER BY coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(limit * 4, section_limit * 6, 36)},
    )
    durable_semantic_result = graph.query(
        """
        MATCH (node:SemanticItem)
        RETURN
          node.entity_id AS entity_id,
          node.stable_key AS stable_key,
          node.kind AS kind,
          node.label AS label,
          coalesce(node.summary, '') AS summary,
          coalesce(node.updated_at, node.created_at) AS updated_at,
          coalesce(node.source_kind, '') AS source_kind
        ORDER BY coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(limit * 3, section_limit * 4, 24)},
    )

    def row_to_semantic_item(row: list[Any]) -> dict[str, Any]:
        return {
            "id": int(row[0]),
            "stable_key": str(row[1] or ""),
            "kind": str(row[2] or ""),
            "title": str(row[3] or ""),
            "summary": str(row[4] or ""),
            "updated_at": str(row[5] or ""),
            "activity_at": str(row[5] or ""),
            "source_kind": str(row[6] or ""),
        }

    operational_semantic_items = [
        item for item in (row_to_semantic_item(row) for row in result_rows(operational_semantic_result))
        if not str(item["stable_key"]).startswith("turn-outcome:")
        and str(item.get("source_kind") or "") != "graph_episode"
    ]
    durable_semantic_items = [row_to_semantic_item(row) for row in result_rows(durable_semantic_result)]

    thread_result = graph.query(
        """
        MATCH (thread:Thread)
        OPTIONAL MATCH (thread)-[:ABOUT]->(repository:Repository)
        RETURN
          thread.entity_id AS entity_id,
          thread.stable_key AS stable_key,
          thread.label AS thread_label,
          coalesce(thread.updated_at, thread.created_at) AS updated_at,
          coalesce(repository.label, '') AS repository_label
        ORDER BY coalesce(thread.updated_at, thread.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(section_limit * 3, 8)},
    )
    recent_threads: list[dict[str, Any]] = []
    seen_threads: set[str] = set()
    for row in result_rows(thread_result):
        stable_key = str(row[1] or "")
        if thread_id and stable_key != thread_id:
            continue
        if not stable_key or stable_key in seen_threads:
            continue
        seen_threads.add(stable_key)
        recent_threads.append(
            {
                "kind": "thread",
                "stable_key": stable_key,
                "title": str(row[2] or ""),
                "label": str(row[2] or ""),
                "summary": None,
                "repository_name": str(row[4] or "") or None,
                "updated_at": str(row[3] or ""),
                "activity_at": str(row[3] or ""),
            }
        )

    def pick(candidates: list[dict[str, Any]], kinds: set[str], max_items: int) -> list[dict[str, Any]]:
        picked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            if item["kind"] not in kinds:
                continue
            stable_key = item["stable_key"]
            if stable_key in seen:
                continue
            seen.add(stable_key)
            picked.append(item)
            if len(picked) >= max_items:
                break
        return picked

    active_now = pick(operational_semantic_items, {"plan", "attempt", "summary", "open_question"}, section_limit)
    open_loops = pick(operational_semantic_items, {"attempt", "plan", "open_question"}, section_limit)
    open_questions = pick(operational_semantic_items, {"open_question"}, section_limit)
    recent_activity = pick(operational_semantic_items, {"attempt", "summary", "plan", "decision"}, section_limit)
    recent_decisions = pick(
        durable_semantic_items,
        {"decision", "preference"},
        max(1, min(section_limit, 3))
    )
    recent_threads = recent_threads[:section_limit]

    combined: list[dict[str, Any]] = []
    seen_combined: set[str] = set()
    for section in (recent_threads, active_now, open_loops, open_questions, recent_activity, recent_decisions):
        for item in section:
            stable_key = str(item.get("stable_key") or "")
            if stable_key and stable_key in seen_combined:
                continue
            if stable_key:
                seen_combined.add(stable_key)
            combined.append(item)
            if len(combined) >= limit:
                break
        if len(combined) >= limit:
            break

    summary_bits: list[str] = []
    if active_now:
        summary_bits.append(f"{len(active_now)} active items")
    if open_questions:
        summary_bits.append(f"{len(open_questions)} open questions")
    if recent_activity:
        summary_bits.append(f"{len(recent_activity)} recent activity items")
    if recent_decisions:
        summary_bits.append(f"{len(recent_decisions)} recent decisions")
    if recent_threads:
        summary_bits.append(f"{len(recent_threads)} recent threads")
    summary = ", ".join(summary_bits) if summary_bits else "No current operational memory state was found."

    suggestions = []
    first_item = next((item for item in combined if item.get("stable_key")), None)
    if first_item:
        first_key = str(first_item["stable_key"])
        workspace_arg = cli_quote(workspace["root_path"])
        suggestions.append(tool.workflow_step(
            "inspect-item",
            "Inspect the top current-state item when you need the full underlying fact details.",
            f"autopsy item {first_key} --workspace {workspace_arg}"
        ))
        suggestions.append(tool.workflow_step(
            "inspect-timeline",
            "Inspect timeline when the current state may depend on recent supersession or invalidation.",
            f"autopsy timeline {first_key} --workspace {workspace_arg}"
        ))

    return {
        "workspace": tool.workspace_payload(workspace),
        "thread_id": thread_id,
        "current_only": True,
        "as_of": None,
        "status": {
            "summary": summary,
            "active_now": active_now,
            "open_loops": open_loops,
            "open_questions": open_questions,
            "recent_decisions": recent_decisions,
            "recent_activity": recent_activity,
            "recent_threads": recent_threads,
            "candidates_considered": len(operational_semantic_items) + len(durable_semantic_items),
            "recent_days": recent_days,
        },
        "items": combined,
        "workflow": {
            "status": "ok" if combined else "empty",
            "coverage": "strong" if combined else "none",
            "complete": bool(combined),
            "next_step": "done" if combined else "conclude",
            "message": summary,
            "suggested_next_steps": suggestions,
        },
    }


def build_graph_item_detail_payload(graph, *, tool, workspace: dict[str, Any], stable_key: str) -> dict[str, Any]:
    item = fetch_item(graph, stable_key)
    return {
        "workspace": tool.workspace_payload(workspace),
        "item": {
            "id": item["entity_id"],
            "stableKey": item["stable_key"],
            "kind": item["kind"],
            "title": item["title"],
            "content": item["content"],
            "confidence": float(item.get("confidence") or 1.0),
            "sourceKind": item["source_kind"],
            "updatedAt": item["updated_at"],
        },
    }


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def summary_snippet(text: str, limit: int = 280) -> str:
    collapsed = " ".join(str(text or "").split())
    return collapsed[:limit]


def scalar_query(graph, query: str, params: dict[str, Any] | None = None) -> Any:
    rows = result_rows(graph.query(query, params=params or {}))
    if not rows:
        return None
    return rows[0][0]


def graph_memory_node_count(graph) -> int:
    return int(scalar_query(graph, "MATCH (node:MemoryNode) RETURN count(node)") or 0)


def next_entity_id(graph) -> int:
    current = scalar_query(graph, "MATCH (node:MemoryNode) RETURN coalesce(max(node.entity_id), 0)")
    return int(current or 0) + 1


def next_edge_id(graph) -> int:
    current = scalar_query(graph, "MATCH ()-[edge]->() RETURN coalesce(max(edge.edge_id), 0)")
    return int(current or 0) + 1


def lookup_node_by_stable_key(graph, stable_key: str) -> dict[str, Any] | None:
    result = graph.query(
        """
        MATCH (node:MemoryNode {stable_key: $stable_key})
        RETURN node.entity_id, node.stable_key, node.kind, node.label
        LIMIT 1
        """,
        params={"stable_key": stable_key},
    )
    rows = result_rows(result)
    if not rows:
        return None
    row = rows[0]
    return {
        "entity_id": int(row[0]),
        "stable_key": str(row[1] or ""),
        "kind": str(row[2] or ""),
        "label": str(row[3] or ""),
    }


def create_memory_node(
    graph,
    *,
    entity_id: int,
    kind: str,
    stable_key: str,
    label: str,
    summary: str,
    detail_content: str,
    confidence: float,
    source_kind: str,
    created_at: str,
    updated_at: str,
    origin: str,
) -> None:
    label_clause = labels_clause(node_labels_for_kind(kind))
    search_text = "\n".join(
        part.strip()
        for part in (kind.replace("_", " "), label, summary, detail_content)
        if part and part.strip()
    )
    graph.query(
        f"""
        CREATE ({label_clause} {{
            entity_id: $entity_id,
            stable_key: $stable_key,
            kind: $kind,
            label: $label,
            summary: $summary,
            detail_content: $detail_content,
            confidence: $confidence,
            search_text: $search_text,
            source_kind: $source_kind,
            created_at: $created_at,
            updated_at: $updated_at,
            origin: $origin,
            embedding: null
        }})
        """,
        params={
            "entity_id": entity_id,
            "stable_key": stable_key,
            "kind": kind,
            "label": label,
            "summary": summary,
            "detail_content": detail_content,
            "confidence": confidence,
            "search_text": search_text,
            "source_kind": source_kind,
            "created_at": created_at,
            "updated_at": updated_at,
            "origin": origin,
        },
    )


def create_structural_edge(
    graph,
    *,
    from_entity_id: int,
    to_entity_id: int,
    relation: str,
    timestamp: str,
    origin: str,
) -> None:
    edge_id = next_edge_id(graph)
    edge_label = structural_edge_label(relation)
    graph.query(
        f"""
        MATCH (src:MemoryNode {{entity_id: $from_id}}), (dst:MemoryNode {{entity_id: $to_id}})
        CREATE (src)-[:{edge_label} {{
            edge_id: $edge_id,
            relation: $relation,
            from_entity_id: $from_id,
            to_entity_id: $to_id,
            created_at: $timestamp,
            updated_at: $timestamp,
            origin: $origin
        }}]->(dst)
        """,
        params={
            "edge_id": edge_id,
            "relation": relation,
            "from_id": from_entity_id,
            "to_id": to_entity_id,
            "timestamp": timestamp,
            "origin": origin,
        },
    )


def create_fact_edge(
    graph,
    *,
    from_entity_id: int,
    to_entity_id: int,
    relation: str,
    predicate: str,
    fact_text: str,
    timestamp: str,
    origin: str,
) -> None:
    edge_id = next_edge_id(graph)
    graph.query(
        """
        MATCH (src:MemoryNode {entity_id: $from_id}), (dst:MemoryNode {entity_id: $to_id})
        CREATE (src)-[:FACT_EDGE {
            edge_id: $edge_id,
            relation: $relation,
            predicate: $predicate,
            fact_text: $fact_text,
            from_entity_id: $from_id,
            to_entity_id: $to_id,
            created_at: $timestamp,
            updated_at: $timestamp,
            origin: $origin
        }]->(dst)
        """,
        params={
            "edge_id": edge_id,
            "relation": relation,
            "predicate": predicate,
            "fact_text": fact_text,
            "from_id": from_entity_id,
            "to_id": to_entity_id,
            "timestamp": timestamp,
            "origin": origin,
        },
    )


def upsert_fact_edge(
    graph,
    *,
    from_stable_key: str,
    to_stable_key: str,
    relation: str,
    predicate: str,
    fact_text: str,
    timestamp: str,
    origin: str,
) -> str:
    existing = graph.query(
        """
        MATCH (src:MemoryNode {stable_key: $from_key})-[fact:FACT_EDGE]->(dst:MemoryNode {stable_key: $to_key})
        WHERE coalesce(fact.relation, '') = $relation
          AND coalesce(fact.predicate, '') = $predicate
        RETURN fact.edge_id
        LIMIT 1
        """,
        params={
            "from_key": from_stable_key,
            "to_key": to_stable_key,
            "relation": relation,
            "predicate": predicate,
        },
    )
    rows = result_rows(existing)
    if rows:
        graph.query(
            """
            MATCH (src:MemoryNode {stable_key: $from_key})-[fact:FACT_EDGE]->(dst:MemoryNode {stable_key: $to_key})
            WHERE coalesce(fact.relation, '') = $relation
              AND coalesce(fact.predicate, '') = $predicate
            SET fact.fact_text = $fact_text,
                fact.updated_at = $timestamp,
                fact.origin = $origin
            """,
            params={
                "from_key": from_stable_key,
                "to_key": to_stable_key,
                "relation": relation,
                "predicate": predicate,
                "fact_text": fact_text,
                "timestamp": timestamp,
                "origin": origin,
            },
        )
        return "updated"
    src = lookup_node_by_stable_key(graph, from_stable_key)
    dst = lookup_node_by_stable_key(graph, to_stable_key)
    if src is None or dst is None:
        return "missing_endpoint"
    create_fact_edge(
        graph,
        from_entity_id=int(src["entity_id"]),
        to_entity_id=int(dst["entity_id"]),
        relation=relation,
        predicate=predicate,
        fact_text=fact_text,
        timestamp=timestamp,
        origin=origin,
    )
    return "created"


def branch_stable_key(repository_root_path: str, branch_name: str) -> str:
    return f"{repository_root_path}::{branch_name}"


def repository_title_for_root(root_path: str) -> str:
    normalized = str(root_path or "").strip()
    if not normalized:
        return "Repository"
    return Path(normalized).name or normalized


def update_memory_node(
    graph,
    *,
    stable_key: str,
    kind: str,
    label: str,
    summary: str,
    detail_content: str,
    confidence: float,
    source_kind: str,
    updated_at: str,
    origin: str,
) -> None:
    search_text = "\n".join(
        part.strip()
        for part in (kind.replace("_", " "), label, summary, detail_content)
        if part and part.strip()
    )
    graph.query(
        """
        MATCH (node:MemoryNode {stable_key: $stable_key})
        SET node.kind = $kind,
            node.label = $label,
            node.summary = $summary,
            node.detail_content = $detail_content,
            node.confidence = $confidence,
            node.search_text = $search_text,
            node.source_kind = $source_kind,
            node.updated_at = $updated_at,
            node.origin = $origin
        """,
        params={
            "stable_key": stable_key,
            "kind": kind,
            "label": label,
            "summary": summary,
            "detail_content": detail_content,
            "confidence": confidence,
            "search_text": search_text,
            "source_kind": source_kind,
            "updated_at": updated_at,
            "origin": origin,
        },
    )


def upsert_memory_node(
    graph,
    *,
    kind: str,
    stable_key: str,
    label: str,
    summary: str,
    detail_content: str,
    confidence: float,
    source_kind: str,
    timestamp: str,
    origin: str,
) -> int:
    existing = lookup_node_by_stable_key(graph, stable_key)
    if existing is not None:
        update_memory_node(
            graph,
            stable_key=stable_key,
            kind=kind,
            label=label,
            summary=summary,
            detail_content=detail_content,
            confidence=confidence,
            source_kind=source_kind,
            updated_at=timestamp,
            origin=origin,
        )
        return int(existing["entity_id"])
    entity_id = next_entity_id(graph)
    create_memory_node(
        graph,
        entity_id=entity_id,
        kind=kind,
        stable_key=stable_key,
        label=label,
        summary=summary,
        detail_content=detail_content,
        confidence=confidence,
        source_kind=source_kind,
        created_at=timestamp,
        updated_at=timestamp,
        origin=origin,
    )
    return entity_id


def delete_outgoing_structural_edges(graph, *, from_stable_key: str, relations: list[str]) -> None:
    for relation in relations:
        edge_label = structural_edge_label(relation)
        graph.query(
            f"""
            MATCH (src:MemoryNode {{stable_key: $stable_key}})-[edge:{edge_label}]->(:MemoryNode)
            DELETE edge
            """,
            params={"stable_key": from_stable_key},
        )


def sync_outgoing_structural_edges(
    graph,
    *,
    from_stable_key: str,
    relation: str,
    desired_to_stable_keys: list[str],
    timestamp: str,
    origin: str,
) -> None:
    edge_label = structural_edge_label(relation)
    existing_result = graph.query(
        f"""
        MATCH (:MemoryNode {{stable_key: $from_key}})-[edge:{edge_label}]->(dst:MemoryNode)
        RETURN dst.stable_key AS stable_key
        """,
        params={"from_key": from_stable_key},
    )
    existing_rows = result_rows(existing_result)
    existing_keys = {
        str(row[0] if isinstance(row, (list, tuple)) and row else row).strip()
        for row in existing_rows
        if str(row[0] if isinstance(row, (list, tuple)) and row else row).strip()
    }
    desired_keys = {str(key or "").strip() for key in desired_to_stable_keys if str(key or "").strip()}

    stale_keys = existing_keys - desired_keys
    for stale_key in stale_keys:
        graph.query(
            f"""
            MATCH (:MemoryNode {{stable_key: $from_key}})-[edge:{edge_label}]->(:MemoryNode {{stable_key: $to_key}})
            DELETE edge
            """,
            params={"from_key": from_stable_key, "to_key": stale_key},
        )

    for desired_key in desired_keys:
        upsert_structural_edge(
            graph,
            from_stable_key=from_stable_key,
            to_stable_key=desired_key,
            relation=relation,
            timestamp=timestamp,
            origin=origin,
        )


def upsert_structural_edge(
    graph,
    *,
    from_stable_key: str,
    to_stable_key: str,
    relation: str,
    timestamp: str,
    origin: str,
) -> None:
    edge_label = structural_edge_label(relation)
    existing = graph.query(
        f"""
        MATCH (src:MemoryNode {{stable_key: $from_key}})-[edge:{edge_label}]->(dst:MemoryNode {{stable_key: $to_key}})
        RETURN edge.edge_id
        LIMIT 1
        """,
        params={"from_key": from_stable_key, "to_key": to_stable_key},
    )
    rows = result_rows(existing)
    if rows:
        graph.query(
            f"""
            MATCH (src:MemoryNode {{stable_key: $from_key}})-[edge:{edge_label}]->(dst:MemoryNode {{stable_key: $to_key}})
            SET edge.updated_at = $timestamp,
                edge.origin = $origin,
                edge.relation = $relation
            """,
            params={
                "from_key": from_stable_key,
                "to_key": to_stable_key,
                "timestamp": timestamp,
                "origin": origin,
                "relation": relation,
            },
        )
        return
    src = lookup_node_by_stable_key(graph, from_stable_key)
    dst = lookup_node_by_stable_key(graph, to_stable_key)
    if src is None or dst is None:
        return
    create_structural_edge(
        graph,
        from_entity_id=int(src["entity_id"]),
        to_entity_id=int(dst["entity_id"]),
        relation=relation,
        timestamp=timestamp,
        origin=origin,
    )


def workspace_stable_key(workspace: dict[str, Any]) -> str:
    record = dict(workspace)
    return str(record.get("id") or record.get("workspace_key") or record.get("root_path") or "")


def ensure_workspace_node(graph, workspace: dict[str, Any], *, timestamp: str, origin: str) -> str:
    record = dict(workspace)
    stable_key = workspace_stable_key(record)
    upsert_memory_node(
        graph,
        kind="workspace",
        stable_key=stable_key,
        label=str(record.get("title") or record.get("name") or Path(stable_key).name or "Workspace"),
        summary=str(record.get("root_path") or stable_key),
        detail_content="",
        confidence=1.0,
        source_kind="autopsy_workspace",
        timestamp=timestamp,
        origin=origin,
    )
    return stable_key


def ensure_repository_node(graph, repository: dict[str, Any], *, timestamp: str, origin: str) -> str:
    stable_key = str(repository.get("rootPath") or repository.get("root_path") or "").strip()
    if not stable_key:
        return ""
    upsert_memory_node(
        graph,
        kind="repository",
        stable_key=stable_key,
        label=str(repository.get("displayName") or repository.get("display_name") or repository_title_for_root(stable_key)),
        summary=str(repository.get("displayPath") or repository.get("display_path") or stable_key),
        detail_content="",
        confidence=1.0,
        source_kind="autopsy_repository",
        timestamp=timestamp,
        origin=origin,
    )
    return stable_key


def ensure_branch_node(graph, repository_root_path: str, branch_name: str, *, summary: str, timestamp: str, origin: str) -> str:
    stable_key = branch_stable_key(repository_root_path, branch_name)
    upsert_memory_node(
        graph,
        kind="branch",
        stable_key=stable_key,
        label=branch_name,
        summary=summary,
        detail_content="",
        confidence=1.0,
        source_kind="autopsy_branch",
        timestamp=timestamp,
        origin=origin,
    )
    return stable_key


def ensure_worktree_node(graph, worktree: dict[str, Any], *, timestamp: str, origin: str) -> str:
    stable_key = str(worktree.get("rootPath") or worktree.get("root_path") or "").strip()
    if not stable_key:
        return ""
    upsert_memory_node(
        graph,
        kind="worktree",
        stable_key=stable_key,
        label=str(worktree.get("displayName") or worktree.get("display_name") or Path(stable_key).name or "Worktree"),
        summary=str(worktree.get("displayPath") or worktree.get("display_path") or stable_key),
        detail_content="",
        confidence=1.0,
        source_kind="autopsy_worktree",
        timestamp=timestamp,
        origin=origin,
    )
    return stable_key


def ensure_thread_node(graph, summary: dict[str, Any], *, timestamp: str, origin: str) -> str:
    stable_key = str(summary.get("id") or "").strip()
    if not stable_key:
        return ""
    label = str(summary.get("name") or "").strip() or str(summary.get("preview") or "").strip()[:88] or stable_key
    upsert_memory_node(
        graph,
        kind="thread",
        stable_key=stable_key,
        label=label,
        summary=str(summary.get("preview") or ""),
        detail_content="",
        confidence=1.0,
        source_kind="autopsy_thread",
        timestamp=timestamp,
        origin=origin,
    )
    return stable_key


def create_episode_node(
    graph,
    *,
    kind: str,
    title: str,
    summary: str,
    timestamp: str,
    origin: str,
) -> str:
    stable_key = f"episode:{hashlib.sha1(f'{kind}|{title}|{summary}|{timestamp}|{time.time_ns()}'.encode('utf-8')).hexdigest()[:32]}"
    upsert_memory_node(
        graph,
        kind="episode",
        stable_key=stable_key,
        label=title,
        summary=summary,
        detail_content="",
        confidence=1.0,
        source_kind=kind,
        timestamp=timestamp,
        origin=origin,
    )
    return stable_key


def extract_context_links(item: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    workspace_key = None
    repository_key = None
    thread_key = None
    for link in item.get("links", []):
        kind = str(link.get("entity_kind") or "")
        stable_key = str(link.get("entity_stable_key") or "") or None
        if kind == "workspace" and workspace_key is None:
            workspace_key = stable_key
        elif kind == "repository" and repository_key is None:
            repository_key = stable_key
        elif kind == "thread" and thread_key is None:
            thread_key = stable_key
    return workspace_key, repository_key, thread_key


def markdown_list_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    current: str | None = None

    def flush() -> None:
        nonlocal current
        if current and current.strip():
            items.append(current.strip())
        current = None

    for raw_line in lines:
        line = str(raw_line or "")
        stripped = line.strip()
        if re.match(r"^[-*+]\s+.+", stripped):
            flush()
            current = re.sub(r"^[-*+]\s+", "", stripped)
            continue
        if re.match(r"^\d+\.\s+.+", stripped):
            flush()
            current = re.sub(r"^\d+\.\s+", "", stripped)
            continue
        if current is not None and stripped:
            current += f" {stripped}"
    flush()
    return items


def slugify_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "item"


def project_slug_for_relative_doc_path(relative_path: str) -> str | None:
    parts = Path(relative_path).parts
    if len(parts) >= 3 and parts[0] == "projects":
        return parts[1]
    return None


def semantic_document_kind(relative_path: str) -> str:
    file_name = Path(relative_path).name.lower()
    if file_name == "decisions.md":
        return "decision"
    if file_name == "open_questions.md":
        return "open_question"
    if file_name in {"brief.md", "assistant_memory.md", "user_profile.md"}:
        return "summary"
    if file_name == "timeline.md":
        return "timeline"
    return "memory_note"


def semantic_entry_kind(category: str, tags: list[str]) -> str:
    lowered_category = str(category or "").strip().lower()
    lowered_tags = {str(tag or "").strip().lower() for tag in tags}
    if any(tag in lowered_tags for tag in {"type:architecture", "type:protocol"}):
        return "decision"
    if "type:planning" in lowered_tags or lowered_category == "planning":
        return "plan"
    if "type:ux" in lowered_tags or lowered_category == "ux":
        return "preference"
    if any(tag in lowered_tags for tag in {"type:bugfix", "type:correctness"}):
        return "attempt"
    return "memory_note"


def semantic_document_title(relative_path: str, fallback_title: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 3 and parts[0] == "projects":
        project = parts[1].replace("-", " ").title()
        leaf = Path(relative_path).stem.replace("_", " ").title()
        return f"{project} {leaf}"
    return fallback_title.replace("_", " ").title()


def parse_memory_tags(raw: str) -> list[str]:
    return [
        part.strip().lower()
        for part in str(raw or "").split(",")
        if part.strip()
    ]


def extract_semantic_document_sections(relative_path: str, content: str) -> list[dict[str, str]]:
    file_name = Path(relative_path).name.lower()
    lines = str(content or "").splitlines()
    items = markdown_list_items(lines)
    if not items:
        return []
    if file_name == "decisions.md":
        kind = "decision"
        max_items = 80
    elif file_name == "open_questions.md":
        kind = "open_question"
        max_items = 80
    elif file_name == "brief.md":
        kind = "summary"
        max_items = 40
    elif file_name == "timeline.md":
        kind = "timeline_event"
        max_items = 60
    else:
        return []
    result: list[dict[str, str]] = []
    for index, item in enumerate(items[-max_items:]):
        result.append(
            {
                "kind": kind,
                "stable_suffix": f"{slugify_text(item)[:48]}-{index}",
                "label": summary_snippet(item, limit=88) or item,
                "content": item,
            }
        )
    return result


def find_repository_by_project_slug(graph, project_slug: str | None) -> str | None:
    if not project_slug:
        return None
    result = graph.query(
        """
        MATCH (repo:Repository)
        RETURN repo.stable_key, repo.label
        """
    )
    for row in result_rows(result):
        stable_key = str(row[0] or "")
        label = str(row[1] or "")
        if slugify_text(label) == project_slug or slugify_text(Path(stable_key).name) == project_slug:
            return stable_key
    return None


def import_semantic_memory_payload(
    graph,
    *,
    workspace: dict[str, Any],
    documents: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    timestamp = utc_now_iso()
    origin = "falkor"
    workspace_key = ensure_workspace_node(graph, workspace, timestamp=timestamp, origin=origin)
    document_count = 0
    section_count = 0
    entry_count = 0

    for document in documents:
        relative_path = str(document.get("relativePath") or document.get("relative_path") or "")
        title = str(document.get("title") or Path(relative_path).stem or "Document")
        content = str(document.get("content") or "")
        kind = semantic_document_kind(relative_path)
        stable_key = f"doc:{relative_path}"
        repository_key = find_repository_by_project_slug(graph, project_slug_for_relative_doc_path(relative_path))
        upsert_memory_node(
            graph,
            kind=kind,
            stable_key=stable_key,
            label=semantic_document_title(relative_path, title),
            summary=summary_snippet(content) or "",
            detail_content=content,
            confidence=0.98,
            source_kind="memory_doc",
            timestamp=timestamp,
            origin=origin,
        )
        if repository_key:
            upsert_structural_edge(graph, from_stable_key=stable_key, to_stable_key=repository_key, relation="about", timestamp=timestamp, origin=origin)
        else:
            upsert_structural_edge(graph, from_stable_key=stable_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin=origin)
        document_count += 1

        for section in extract_semantic_document_sections(relative_path, content):
            section_key = f"{stable_key}#{section['stable_suffix']}"
            upsert_memory_node(
                graph,
                kind=str(section["kind"]),
                stable_key=section_key,
                label=str(section["label"]),
                summary=summary_snippet(str(section["content"])) or "",
                detail_content=str(section["content"]),
                confidence=0.94,
                source_kind="memory_doc",
                timestamp=timestamp,
                origin=origin,
            )
            upsert_structural_edge(graph, from_stable_key=section_key, to_stable_key=stable_key, relation="part_of", timestamp=timestamp, origin=origin)
            if repository_key:
                upsert_structural_edge(graph, from_stable_key=section_key, to_stable_key=repository_key, relation="about", timestamp=timestamp, origin=origin)
            else:
                upsert_structural_edge(graph, from_stable_key=section_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin=origin)
            section_count += 1

    for entry in entries:
        entry_id = int(entry.get("entryID") or entry.get("id") or 0)
        if entry_id <= 0:
            continue
        tags = parse_memory_tags(str(entry.get("tags") or ""))
        project_tag = next((tag.split(":", 1)[1] for tag in tags if tag.startswith("project:")), None)
        repository_key = find_repository_by_project_slug(graph, project_tag)
        stable_key = f"entry:{entry_id}"
        content = str(entry.get("content") or "")
        upsert_memory_node(
            graph,
            kind=semantic_entry_kind(str(entry.get("category") or ""), tags),
            stable_key=stable_key,
            label=str(entry.get("title") or stable_key),
            summary=summary_snippet(content) or "",
            detail_content=content,
            confidence=float(entry.get("confidence") or 1.0),
            source_kind="memory_entry",
            timestamp=timestamp,
            origin=origin,
        )
        if repository_key:
            upsert_structural_edge(graph, from_stable_key=stable_key, to_stable_key=repository_key, relation="about", timestamp=timestamp, origin=origin)
        else:
            upsert_structural_edge(graph, from_stable_key=stable_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin=origin)
        entry_count += 1

    return {
        "synced": True,
        "documents": document_count,
        "sections": section_count,
        "entries": entry_count,
    }


def sync_workspace_payload(graph, *, workspace: dict[str, Any]) -> dict[str, Any]:
    timestamp = utc_now_iso()
    ensure_workspace_node(graph, workspace, timestamp=timestamp, origin="falkor")
    return {"synced": True}


def sync_repositories_payload(graph, *, workspace: dict[str, Any], repositories: list[dict[str, Any]]) -> dict[str, Any]:
    timestamp = utc_now_iso()
    workspace_key = ensure_workspace_node(graph, workspace, timestamp=timestamp, origin="falkor")
    count = 0
    for repository in repositories:
        repository_key = ensure_repository_node(graph, repository, timestamp=timestamp, origin="falkor")
        if not repository_key:
            continue
        upsert_structural_edge(graph, from_stable_key=repository_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
        branch_name = str(repository.get("branch") or "").strip()
        if branch_name:
            branch_key = ensure_branch_node(
                graph,
                repository_root_path=repository_key,
                branch_name=branch_name,
                summary=str(repository.get("displayName") or repository_title_for_root(repository_key)),
                timestamp=timestamp,
                origin="falkor",
            )
            upsert_structural_edge(graph, from_stable_key=branch_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
        count += 1
    return {"synced": True, "repositories": count}


def sync_worktrees_payload(graph, *, workspace: dict[str, Any], worktrees: list[dict[str, Any]]) -> dict[str, Any]:
    timestamp = utc_now_iso()
    ensure_workspace_node(graph, workspace, timestamp=timestamp, origin="falkor")
    count = 0
    for worktree in worktrees:
        repository_root = str(worktree.get("repositoryRootPath") or worktree.get("repository_root_path") or "").strip()
        if not repository_root:
            continue
        repository_key = ensure_repository_node(
            graph,
            {
                "rootPath": repository_root,
                "displayName": repository_title_for_root(repository_root),
                "displayPath": repository_root,
            },
            timestamp=timestamp,
            origin="falkor",
        )
        worktree_key = ensure_worktree_node(graph, worktree, timestamp=timestamp, origin="falkor")
        if not worktree_key:
            continue
        upsert_structural_edge(graph, from_stable_key=worktree_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
        branch_name = str(worktree.get("branch") or "").strip()
        if branch_name:
            branch_key = ensure_branch_node(
                graph,
                repository_root_path=repository_root,
                branch_name=branch_name,
                summary=str(worktree.get("displayName") or Path(worktree_key).name or "Worktree"),
                timestamp=timestamp,
                origin="falkor",
            )
            upsert_structural_edge(graph, from_stable_key=branch_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
            upsert_structural_edge(graph, from_stable_key=worktree_key, to_stable_key=branch_key, relation="attached_to", timestamp=timestamp, origin="falkor")
        count += 1
    return {"synced": True, "worktrees": count}


def sync_thread_summary_payload(graph, *, workspace: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    timestamp = utc_now_iso()
    workspace_key = ensure_workspace_node(graph, workspace, timestamp=timestamp, origin="falkor")
    thread_key = ensure_thread_node(graph, summary, timestamp=timestamp, origin="falkor")
    delete_outgoing_structural_edges(graph, from_stable_key=thread_key, relations=["belongs_to", "about"])
    upsert_structural_edge(graph, from_stable_key=thread_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
    repository = summary.get("repository")
    if isinstance(repository, dict):
        repository_key = ensure_repository_node(graph, repository, timestamp=timestamp, origin="falkor")
        if repository_key:
            upsert_structural_edge(graph, from_stable_key=repository_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
            upsert_structural_edge(graph, from_stable_key=thread_key, to_stable_key=repository_key, relation="about", timestamp=timestamp, origin="falkor")
            branch_name = str(summary.get("gitBranch") or repository.get("branch") or "").strip()
            if branch_name:
                branch_key = ensure_branch_node(
                    graph,
                    repository_root_path=repository_key,
                    branch_name=branch_name,
                    summary=str(summary.get("preview") or ""),
                    timestamp=timestamp,
                    origin="falkor",
                )
                upsert_structural_edge(graph, from_stable_key=branch_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
    return {"synced": True}


def sync_thread_context_payload(graph, *, summary: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    timestamp = utc_now_iso()
    workspace = context.get("workspace") or {}
    workspace_key = ensure_workspace_node(graph, workspace, timestamp=timestamp, origin="falkor")
    thread_key = ensure_thread_node(graph, summary, timestamp=timestamp, origin="falkor")
    about_targets: list[str] = []
    attached_targets: list[str] = []

    repository = context.get("effectiveRepository") or context.get("effective_repository") or summary.get("repository")
    if isinstance(repository, dict):
        repository_key = ensure_repository_node(graph, repository, timestamp=timestamp, origin="falkor")
        if repository_key:
            upsert_structural_edge(graph, from_stable_key=repository_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
            about_targets.append(repository_key)
            branch_name = str(
                (context.get("attachedWorktree") or context.get("attached_worktree") or {}).get("branch")
                or repository.get("branch")
                or summary.get("gitBranch")
                or ""
            ).strip()
            if branch_name:
                branch_key = ensure_branch_node(
                    graph,
                    repository_root_path=repository_key,
                    branch_name=branch_name,
                    summary=str(summary.get("preview") or ""),
                    timestamp=timestamp,
                    origin="falkor",
                )
                upsert_structural_edge(graph, from_stable_key=branch_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")

    worktree = context.get("attachedWorktree") or context.get("attached_worktree")
    if isinstance(worktree, dict):
        worktree_key = ensure_worktree_node(graph, worktree, timestamp=timestamp, origin="falkor")
        if worktree_key:
            attached_targets.append(worktree_key)
            repository_root = str(worktree.get("repositoryRootPath") or worktree.get("repository_root_path") or "").strip()
            if repository_root:
                repository_key = ensure_repository_node(
                    graph,
                    {
                        "rootPath": repository_root,
                        "displayName": repository_title_for_root(repository_root),
                        "displayPath": repository_root,
                    },
                    timestamp=timestamp,
                    origin="falkor",
                )
                upsert_structural_edge(graph, from_stable_key=worktree_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
                branch_name = str(worktree.get("branch") or "").strip()
                if branch_name:
                    branch_key = ensure_branch_node(
                        graph,
                        repository_root_path=repository_root,
                        branch_name=branch_name,
                        summary=str(worktree.get("displayName") or Path(worktree_key).name or "Worktree"),
                        timestamp=timestamp,
                        origin="falkor",
                    )
                    upsert_structural_edge(graph, from_stable_key=branch_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
                    upsert_structural_edge(graph, from_stable_key=worktree_key, to_stable_key=branch_key, relation="attached_to", timestamp=timestamp, origin="falkor")
    sync_outgoing_structural_edges(
        graph,
        from_stable_key=thread_key,
        relation="belongs_to",
        desired_to_stable_keys=[workspace_key],
        timestamp=timestamp,
        origin="falkor",
    )
    sync_outgoing_structural_edges(
        graph,
        from_stable_key=thread_key,
        relation="about",
        desired_to_stable_keys=about_targets,
        timestamp=timestamp,
        origin="falkor",
    )
    sync_outgoing_structural_edges(
        graph,
        from_stable_key=thread_key,
        relation="attached_to",
        desired_to_stable_keys=attached_targets,
        timestamp=timestamp,
        origin="falkor",
    )
    return {"synced": True}


def record_episode_payload(
    graph,
    *,
    workspace: dict[str, Any],
    repository_root_path: str | None,
    branch_name: str | None,
    worktree_root_path: str | None,
    thread_id: str | None,
    kind: str,
    title: str,
    summary: str,
    semantic_capture: dict[str, Any] | None,
) -> dict[str, Any]:
    timestamp = utc_now_iso()
    workspace_key = ensure_workspace_node(graph, workspace, timestamp=timestamp, origin="falkor")
    episode_key = create_episode_node(graph, kind=kind, title=title, summary=summary, timestamp=timestamp, origin="falkor")
    upsert_structural_edge(graph, from_stable_key=episode_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")

    repository_key = None
    if repository_root_path:
        repository_key = ensure_repository_node(
            graph,
            {"rootPath": repository_root_path, "displayName": repository_title_for_root(repository_root_path), "displayPath": repository_root_path},
            timestamp=timestamp,
            origin="falkor",
        )
        upsert_structural_edge(graph, from_stable_key=repository_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
        upsert_structural_edge(graph, from_stable_key=episode_key, to_stable_key=repository_key, relation="about", timestamp=timestamp, origin="falkor")
    if branch_name and repository_root_path:
        branch_key = ensure_branch_node(
            graph,
            repository_root_path=repository_root_path,
            branch_name=branch_name,
            summary=title,
            timestamp=timestamp,
            origin="falkor",
        )
        if repository_key:
            upsert_structural_edge(graph, from_stable_key=branch_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
            upsert_structural_edge(graph, from_stable_key=episode_key, to_stable_key=branch_key, relation="attached_to", timestamp=timestamp, origin="falkor")
    if worktree_root_path:
        worktree_key = ensure_worktree_node(
            graph,
            {
                "rootPath": worktree_root_path,
                "repositoryRootPath": repository_root_path or "",
                "displayName": Path(worktree_root_path).name or "Worktree",
                "displayPath": worktree_root_path,
                "branch": branch_name,
            },
            timestamp=timestamp,
            origin="falkor",
        )
        if repository_key:
            upsert_structural_edge(graph, from_stable_key=worktree_key, to_stable_key=repository_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
        upsert_structural_edge(graph, from_stable_key=episode_key, to_stable_key=worktree_key, relation="attached_to", timestamp=timestamp, origin="falkor")
    if thread_id:
        thread_key = ensure_thread_node(graph, {"id": thread_id, "preview": summary, "name": title}, timestamp=timestamp, origin="falkor")
        upsert_structural_edge(graph, from_stable_key=thread_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
        upsert_structural_edge(graph, from_stable_key=episode_key, to_stable_key=thread_key, relation="about", timestamp=timestamp, origin="falkor")

    if semantic_capture:
        note_key = str(semantic_capture.get("stableKey") or semantic_capture.get("stable_key") or "").strip()
        if note_key:
            upsert_memory_node(
                graph,
                kind=str(semantic_capture.get("kind") or "memory_note"),
                stable_key=note_key,
                label=str(semantic_capture.get("title") or title),
                summary=summary_snippet(str(semantic_capture.get("content") or summary)) or summary,
                detail_content=str(semantic_capture.get("content") or ""),
                confidence=1.0,
                source_kind="graph_episode",
                timestamp=timestamp,
                origin="falkor",
            )
            upsert_structural_edge(graph, from_stable_key=note_key, to_stable_key=episode_key, relation="captured_in", timestamp=timestamp, origin="falkor")
            upsert_structural_edge(graph, from_stable_key=episode_key, to_stable_key=note_key, relation="captures", timestamp=timestamp, origin="falkor")
            upsert_structural_edge(graph, from_stable_key=note_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
            if repository_key:
                upsert_structural_edge(graph, from_stable_key=note_key, to_stable_key=repository_key, relation="about", timestamp=timestamp, origin="falkor")
            if thread_id:
                upsert_structural_edge(graph, from_stable_key=note_key, to_stable_key=thread_id, relation="about", timestamp=timestamp, origin="falkor")
    return {"recorded": True, "episode_stable_key": episode_key}


def semantic_outcome_from_turn(turn: dict[str, Any], thread_title: str) -> dict[str, str] | None:
    items = turn.get("items") or []
    assistant_messages = [
        str(item.get("text") or "").strip()
        for item in items
        if str(item.get("kind") or "") == "agentMessage" and str(item.get("text") or "").strip()
    ]
    final_assistant_message = assistant_messages[-1] if assistant_messages else None
    file_changes = [item for item in items if str(item.get("kind") or "") == "fileChange"]
    commands = [item for item in items if str(item.get("kind") or "") == "commandExecution"]
    tool_calls = [item for item in items if str(item.get("kind") or "") == "toolCall"]
    searches = [item for item in items if str(item.get("kind") or "") == "webSearch"]
    status = str(turn.get("status") or "")
    kind = "attempt" if status in {"failed", "errored", "error", "interrupted", "cancelled", "canceled"} else "memory_note"
    summary_base = summary_snippet(final_assistant_message or "", limit=88) or f"{thread_title} · {status}"
    title_prefix = "Attempt" if kind == "attempt" else "Outcome"
    activity_summary = " · ".join(
        part for part in [
            f"{len(file_changes)} file changes" if file_changes else None,
            f"{len(commands)} commands" if commands else None,
            f"{len(tool_calls)} tools" if tool_calls else None,
            f"{len(searches)} searches" if searches else None,
        ]
        if part
    )
    content_parts = [
        f"Thread: {thread_title}",
        f"Turn status: {status}",
        f"Activity: {activity_summary}" if activity_summary else None,
        f"Assistant outcome:\n{final_assistant_message}" if final_assistant_message else None,
    ]
    return {
        "stable_key": f"turn-outcome:{turn.get('id')}:{status}",
        "kind": kind,
        "title": f"{title_prefix}: {summary_base}",
        "summary": summary_base,
        "content": "\n\n".join(part for part in content_parts if part),
    }


def capture_thread_outcomes_payload(graph, *, thread: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    summary = thread.get("summary") or {}
    thread_title = str(summary.get("name") or "").strip() or str(summary.get("preview") or "").strip()[:88] or str(thread.get("id") or "Thread")
    captured = 0
    for turn in thread.get("turns") or []:
        status = str(turn.get("status") or "")
        if status not in {"completed", "interrupted", "failed", "errored", "error", "cancelled", "canceled"}:
            continue
        outcome = semantic_outcome_from_turn(turn, thread_title)
        if not outcome:
            continue
        if lookup_node_by_stable_key(graph, outcome["stable_key"]) is not None:
            continue
        record_episode_payload(
            graph,
            workspace=context.get("workspace") or {},
            repository_root_path=(context.get("effectiveRepository") or context.get("effective_repository") or {}).get("rootPath"),
            branch_name=((context.get("attachedWorktree") or context.get("attached_worktree") or {}).get("branch") or (context.get("effectiveRepository") or context.get("effective_repository") or {}).get("branch") or summary.get("gitBranch")),
            worktree_root_path=(context.get("attachedWorktree") or context.get("attached_worktree") or {}).get("rootPath"),
            thread_id=str(thread.get("id") or summary.get("id") or ""),
            kind="thread_turn_completed",
            title=outcome["title"],
            summary=outcome["summary"],
            semantic_capture={
                "stableKey": outcome["stable_key"],
                "kind": outcome["kind"],
                "title": outcome["title"],
                "content": outcome["content"],
            },
        )
        captured += 1
    return {"captured": captured}


def record_thread_fork_payload(
    graph,
    *,
    parent_thread_id: str,
    child_summary: dict[str, Any],
    child_context: dict[str, Any],
) -> dict[str, Any]:
    sync_thread_context_payload(graph, summary=child_summary, context=child_context)
    timestamp = utc_now_iso()
    workspace = child_context.get("workspace") or {}
    workspace_key = ensure_workspace_node(graph, workspace, timestamp=timestamp, origin="falkor")
    parent_key = ensure_thread_node(graph, {"id": parent_thread_id, "preview": parent_thread_id, "name": parent_thread_id}, timestamp=timestamp, origin="falkor")
    child_key = ensure_thread_node(graph, child_summary, timestamp=timestamp, origin="falkor")
    upsert_structural_edge(graph, from_stable_key=parent_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
    upsert_structural_edge(graph, from_stable_key=child_key, to_stable_key=workspace_key, relation="belongs_to", timestamp=timestamp, origin="falkor")
    upsert_structural_edge(graph, from_stable_key=child_key, to_stable_key=parent_key, relation="forked_from", timestamp=timestamp, origin="falkor")
    record_episode_payload(
        graph,
        workspace=workspace,
        repository_root_path=(child_context.get("effectiveRepository") or child_context.get("effective_repository") or {}).get("rootPath"),
        branch_name=((child_context.get("attachedWorktree") or child_context.get("attached_worktree") or {}).get("branch") or (child_context.get("effectiveRepository") or child_context.get("effective_repository") or {}).get("branch") or child_summary.get("gitBranch")),
        worktree_root_path=(child_context.get("attachedWorktree") or child_context.get("attached_worktree") or {}).get("rootPath"),
        thread_id=str(child_summary.get("id") or ""),
        kind="thread_forked",
        title="Thread forked",
        summary=f"Forked from {parent_thread_id} to {child_summary.get('id')}",
        semantic_capture={
            "stableKey": f"thread-fork:{child_summary.get('id')}",
            "kind": "plan",
            "title": f"Forked thread {str(child_summary.get('name') or child_summary.get('preview') or child_summary.get('id') or '').strip()[:88]}",
            "content": f"Forked from {parent_thread_id} into {child_summary.get('id')}.",
        },
    )
    return {"recorded": True}


def create_graph_note_payload(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    kind: str,
    title: str,
    content: str,
    repository_root_path: str | None,
    thread_id: str | None,
) -> dict[str, Any]:
    created_at = utc_now_iso()
    stable_key = f"graph-note:{hashlib.sha1(f'{title}|{created_at}|{time.time_ns()}'.encode('utf-8')).hexdigest()[:32]}"
    note_id = next_entity_id(graph)
    episode_id = note_id + 1
    episode_key = f"episode:{episode_id}"
    summary = summary_snippet(content)
    workspace_record = dict(workspace)
    workspace_key = str(workspace_record.get("root_path") or workspace_record.get("workspace_key") or "")
    workspace_node = lookup_node_by_stable_key(graph, workspace_key)
    repository_node = lookup_node_by_stable_key(graph, repository_root_path) if repository_root_path else None
    thread_node = lookup_node_by_stable_key(graph, thread_id) if thread_id else None

    create_memory_node(
        graph,
        entity_id=note_id,
        kind=kind,
        stable_key=stable_key,
        label=title,
        summary=summary,
        detail_content=content,
        confidence=1.0,
        source_kind="graph_note",
        created_at=created_at,
        updated_at=created_at,
        origin="falkor",
    )
    create_memory_node(
        graph,
        entity_id=episode_id,
        kind="episode",
        stable_key=episode_key,
        label=title,
        summary=summary,
        detail_content="",
        confidence=1.0,
        source_kind="graph_episode",
        created_at=created_at,
        updated_at=created_at,
        origin="falkor",
    )
    if workspace_node:
        create_structural_edge(graph, from_entity_id=note_id, to_entity_id=workspace_node["entity_id"], relation="belongs_to", timestamp=created_at, origin="falkor")
        create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=workspace_node["entity_id"], relation="belongs_to", timestamp=created_at, origin="falkor")
    if repository_node:
        create_structural_edge(graph, from_entity_id=note_id, to_entity_id=repository_node["entity_id"], relation="about", timestamp=created_at, origin="falkor")
        create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=repository_node["entity_id"], relation="about", timestamp=created_at, origin="falkor")
    if thread_node:
        create_structural_edge(graph, from_entity_id=note_id, to_entity_id=thread_node["entity_id"], relation="about", timestamp=created_at, origin="falkor")
        create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=thread_node["entity_id"], relation="about", timestamp=created_at, origin="falkor")
    create_structural_edge(graph, from_entity_id=note_id, to_entity_id=episode_id, relation="captured_in", timestamp=created_at, origin="falkor")
    create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=note_id, relation="captures", timestamp=created_at, origin="falkor")
    invalidate_graph_caches(graph)
    return build_graph_item_detail_payload(graph, tool=tool, workspace=workspace, stable_key=stable_key)


def update_graph_item_payload(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    stable_key: str,
    kind: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    existing = fetch_item(graph, stable_key)
    created_at = utc_now_iso()
    summary = summary_snippet(content)
    graph.query(
        """
        MATCH (node:MemoryNode {stable_key: $stable_key})
        SET node.kind = $kind,
            node.label = $label,
            node.summary = $summary,
            node.detail_content = $detail_content,
            node.confidence = $confidence,
            node.source_kind = $source_kind,
            node.search_text = $search_text,
            node.updated_at = $updated_at,
            node.origin = $origin
        """,
        params={
            "stable_key": stable_key,
            "kind": kind,
            "label": title,
            "summary": summary,
            "detail_content": content,
            "confidence": float(existing.get("confidence") or 1.0),
            "source_kind": str(existing.get("source_kind") or "graph_note"),
            "search_text": "\n".join(part for part in (kind.replace("_", " "), title, summary, content) if part),
            "updated_at": created_at,
            "origin": "falkor",
        },
    )
    workspace_key, repository_key, thread_key = extract_context_links(existing)
    episode_id = next_entity_id(graph)
    episode_key = f"episode:{episode_id}"
    create_memory_node(
        graph,
        entity_id=episode_id,
        kind="episode",
        stable_key=episode_key,
        label=title,
        summary=summary,
        detail_content="",
        confidence=1.0,
        source_kind="graph_episode",
        created_at=created_at,
        updated_at=created_at,
        origin="falkor",
    )
    if workspace_key:
        workspace_node = lookup_node_by_stable_key(graph, workspace_key)
        if workspace_node:
            create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=workspace_node["entity_id"], relation="belongs_to", timestamp=created_at, origin="falkor")
    if repository_key:
        repo_node = lookup_node_by_stable_key(graph, repository_key)
        if repo_node:
            create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=repo_node["entity_id"], relation="about", timestamp=created_at, origin="falkor")
    if thread_key:
        thread_node = lookup_node_by_stable_key(graph, thread_key)
        if thread_node:
            create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=thread_node["entity_id"], relation="about", timestamp=created_at, origin="falkor")
    create_structural_edge(graph, from_entity_id=existing["entity_id"], to_entity_id=episode_id, relation="captured_in", timestamp=created_at, origin="falkor")
    create_structural_edge(graph, from_entity_id=episode_id, to_entity_id=existing["entity_id"], relation="updates", timestamp=created_at, origin="falkor")
    invalidate_graph_caches(graph)
    return build_graph_item_detail_payload(graph, tool=tool, workspace=workspace, stable_key=stable_key)


def resolve_graph_conflict_payload(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    current_stable_key: str,
    superseded_stable_keys: list[str],
    relation: str,
    summary: str | None,
) -> dict[str, Any]:
    if relation not in {"supersedes", "reverts", "answers"}:
        fail(f"Unsupported conflict resolution relation {relation}", 2)
    current = fetch_item(graph, current_stable_key)
    timestamp = utc_now_iso()
    predicate = relation.upper()
    fact_summary = summary or f"{current_stable_key} {relation} {', '.join(superseded_stable_keys)}"
    for target_key in superseded_stable_keys:
        target = fetch_item(graph, target_key)
        create_fact_edge(
            graph,
            from_entity_id=current["entity_id"],
            to_entity_id=target["entity_id"],
            relation=relation,
            predicate=predicate,
            fact_text=fact_summary,
            timestamp=timestamp,
            origin="falkor",
        )
    return build_graph_item_detail_payload(graph, tool=tool, workspace=workspace, stable_key=current_stable_key)


def delete_graph_item_payload(
    graph,
    *,
    stable_key: str,
) -> None:
    graph.query(
        """
        MATCH (node:MemoryNode {stable_key: $stable_key})
        OPTIONAL MATCH (node)-[edge]-()
        DELETE edge, node
        """,
        params={"stable_key": stable_key},
    )
    invalidate_graph_caches(graph)


def build_graph_stats_payload(graph) -> dict[str, Any]:
    def count(query: str) -> int:
        value = scalar_query(graph, query)
        return int(value or 0)
    return {
        "workspaceCount": count("MATCH (:Workspace) RETURN count(*)"),
        "repositoryCount": count("MATCH (:Repository) RETURN count(*)"),
        "branchCount": count("MATCH (:Branch) RETURN count(*)"),
        "worktreeCount": count("MATCH (:Worktree) RETURN count(*)"),
        "threadCount": count("MATCH (:Thread) RETURN count(*)"),
        "episodeCount": count("MATCH (:Episode) RETURN count(*)"),
        "entityCount": count("MATCH (:MemoryNode) RETURN count(*)"),
        "edgeCount": count("MATCH ()-[edge]->() RETURN count(edge)"),
        "itemCount": count("MATCH (:SemanticItem) RETURN count(*)"),
    }


def build_recent_entries_payload(graph, *, limit: int = 12) -> list[dict[str, Any]]:
    result = graph.query(
        """
        MATCH (node:SemanticItem)
        RETURN
          node.entity_id AS entity_id,
          node.kind AS kind,
          node.label AS label,
          coalesce(node.summary, '') AS summary,
          coalesce(node.source_kind, '') AS source_kind,
          coalesce(node.confidence, 1.0) AS confidence,
          coalesce(node.created_at, node.updated_at) AS created_at
        ORDER BY coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(limit, 1)},
    )
    items: list[dict[str, Any]] = []
    for row in result_rows(result):
        items.append(
            {
                "id": int(row[0]),
                "category": str(row[1] or ""),
                "title": str(row[2] or ""),
                "preview": str(row[3] or ""),
                "tags": "",
                "source": str(row[4] or ""),
                "confidence": float(row[5] or 1.0),
                "createdAt": str(row[6] or ""),
            }
        )
    return items


def build_recent_entities_payload(graph, *, limit: int = 12) -> list[dict[str, Any]]:
    result = graph.query(
        """
        MATCH (node:MemoryNode)
        RETURN
          node.entity_id AS entity_id,
          node.kind AS kind,
          node.label AS label,
          coalesce(node.summary, '') AS summary,
          coalesce(node.updated_at, node.created_at) AS updated_at
        ORDER BY coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(limit, 1)},
    )
    return [
        {
            "id": int(row[0]),
            "kind": str(row[1] or ""),
            "label": str(row[2] or ""),
            "summary": str(row[3] or "") or None,
            "updatedAt": str(row[4] or ""),
        }
        for row in result_rows(result)
    ]


def build_recent_edges_payload(graph, *, limit: int = 12) -> list[dict[str, Any]]:
    result = graph.query(
        """
        MATCH (src:MemoryNode)-[fact:FACT_EDGE]->(dst:MemoryNode)
        RETURN
          fact.edge_id AS edge_id,
          fact.relation AS relation,
          coalesce(fact.predicate, fact.relation) AS predicate,
          src.label AS from_label,
          src.kind AS from_kind,
          dst.label AS to_label,
          dst.kind AS to_kind,
          coalesce(fact.fact_text, '') AS fact_text,
          coalesce(fact.updated_at, fact.created_at) AS updated_at
        ORDER BY coalesce(fact.updated_at, fact.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(limit, 1)},
    )
    return [
        {
            "id": int(row[0]),
            "relation": str(row[1] or ""),
            "predicate": str(row[2] or row[1] or ""),
            "fromLabel": str(row[3] or ""),
            "fromKind": str(row[4] or ""),
            "toLabel": str(row[5] or ""),
            "toKind": str(row[6] or ""),
            "factText": str(row[7] or "") or None,
            "updatedAt": str(row[8] or ""),
        }
        for row in result_rows(result)
    ]


def build_workspace_memory_snapshot_payload(graph, *, tool, workspace: dict[str, Any]) -> dict[str, Any]:
    return {
        "recentEntries": build_recent_entries_payload(graph),
        "graphSnapshot": {
            "databasePath": None,
            "stats": build_graph_stats_payload(graph),
            "recentEpisodes": fetch_recent_episodes(graph, limit=8),
            "recentEntities": build_recent_entities_payload(graph, limit=12),
            "recentEdges": build_recent_edges_payload(graph, limit=12),
        },
    }


def build_workspace_memory_entry_payload(graph, *, entry_id: int) -> dict[str, Any]:
    result = graph.query(
        """
        MATCH (node:MemoryNode {entity_id: $entity_id})
        RETURN
          node.entity_id AS entity_id,
          node.kind AS kind,
          node.label AS label,
          coalesce(node.detail_content, '') AS detail_content,
          '' AS tags,
          coalesce(node.source_kind, '') AS source_kind,
          coalesce(node.confidence, 1.0) AS confidence,
          coalesce(node.created_at, node.updated_at) AS created_at,
          coalesce(node.updated_at, node.created_at) AS updated_at
        LIMIT 1
        """,
        params={"entity_id": entry_id},
    )
    rows = result_rows(result)
    if not rows:
        fail(f"Graph memory entry not found: {entry_id}", 2)
    row = rows[0]
    return {
        "entry": {
            "id": int(row[0]),
            "category": str(row[1] or ""),
            "title": str(row[2] or ""),
            "content": str(row[3] or ""),
            "tags": str(row[4] or ""),
            "source": str(row[5] or ""),
            "confidence": float(row[6] or 1.0),
            "createdAt": str(row[7] or ""),
            "updatedAt": str(row[8] or ""),
        }
    }


def build_graph_search_payload(
    graph,
    *,
    tool,
    conn,
    workspace: dict[str, Any],
    config: dict[str, Any],
    query: str,
    limit: int,
) -> dict[str, Any]:
    route = classify_query(query)
    if route == "status":
        route = "lexical"
    consult = build_consult_payload(
        graph,
        tool=tool,
        conn=conn,
        workspace=workspace,
        config=config,
        query=query,
        limit=limit,
        route=route,
    )
    nodes = []
    for hit in consult.get("hits", []):
        nodes.append(
            {
                "id": 0,
                "kind": str(hit.get("kind") or ""),
                "label": str(hit.get("title") or ""),
                "summary": str(hit.get("preview") or "") or None,
                "stateFlags": [],
                "isFocus": False,
                "sourceKind": None,
                "sourceRef": str(hit.get("stable_key") or "") or None,
            }
        )
    stable_keys = [str(hit.get("stable_key") or "") for hit in consult.get("hits", []) if hit.get("stable_key")]
    if stable_keys:
        result = graph.query(
            """
            MATCH (node:MemoryNode)
            WHERE node.stable_key IN $stable_keys
            RETURN node.entity_id, node.stable_key, coalesce(node.source_kind, '')
            """,
            params={"stable_keys": stable_keys},
        )
        details_by_key = {
            str(row[1]): {
                "id": int(row[0]),
                "source_kind": str(row[2] or "") or None,
            }
            for row in result_rows(result)
        }
        for node in nodes:
            source_ref = node.get("sourceRef")
            if source_ref:
                details = details_by_key.get(str(source_ref))
                if details:
                    node["id"] = details["id"]
                    node["sourceKind"] = details["source_kind"]
    return {"workspace": tool.workspace_payload(workspace), "results": nodes}


def build_workspace_explorer_payload(graph, *, tool, workspace: dict[str, Any], limit: int = 24) -> dict[str, Any]:
    row_items = fetch_semantic_nodes_for_workspace(graph, limit=limit)
    nodes = build_graph_nodes(row_items)
    node_ids = [node["id"] for node in nodes]
    workspace_payload = tool.workspace_payload(workspace)
    connection_limit = max(limit * 2, 48)
    return {
        "scopeTitle": str(workspace_payload.get("title") or workspace_payload.get("slug") or "Workspace Graph"),
        "focusNodeID": node_ids[0] if node_ids else None,
        "nodes": nodes,
        "connections": fetch_connections(graph, node_ids, limit=connection_limit),
        # Global episode scans are too expensive for the workspace graph path.
        # Keep the graph responsive and let thread-scoped explorer views carry recent episode context.
        "recentEpisodes": [],
        "conflictSuggestions": [],
    }


def build_thread_explorer_payload(graph, *, tool, workspace: dict[str, Any], thread_id: str, limit: int = 90) -> dict[str, Any]:
    scope_title, row_items = fetch_semantic_nodes_for_thread(graph, thread_id, limit=limit)
    focus_stable_key = row_items[0]["stableKey"] if row_items else None
    nodes = build_graph_nodes(row_items, focus_stable_key=focus_stable_key)
    node_ids = [node["id"] for node in nodes]
    focus_node_id = next((node["id"] for node in nodes if node.get("isFocus")), None)
    return {
        "scopeTitle": scope_title,
        "focusNodeID": focus_node_id,
        "nodes": nodes,
        "connections": fetch_connections(graph, node_ids, limit=max(limit * 3, 72)),
        "recentEpisodes": fetch_recent_episodes(graph, limit=12, thread_id=thread_id),
        "conflictSuggestions": [],
    }


def merge_candidates(lexical_items: list[dict[str, Any]], vector_items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(lexical_items):
        normalized = dict(item)
        normalized["hybrid_score"] = max(limit * 3 - index, 1)
        merged[normalized["stable_key"]] = normalized
    for index, item in enumerate(vector_items):
        stable_key = str(item["stable_key"])
        contribution = float(item.get("embedding_score", 0.0)) * 10.0 + max(limit - index, 1)
        current = merged.get(stable_key)
        if current is None:
            normalized = dict(item)
            normalized["hybrid_score"] = contribution
            merged[stable_key] = normalized
            continue
        current["hybrid_score"] = float(current.get("hybrid_score", 0.0)) + contribution
        current["embedding_score"] = max(float(current.get("embedding_score", 0.0)), float(item.get("embedding_score", 0.0)))
        reasons = set(current.get("retrieval_reasons", []))
        reasons.update(item.get("retrieval_reasons", []))
        current["retrieval_reasons"] = sorted(reasons)
    return sort_candidates(list(merged.values()))


def short_hits(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    result = []
    for item in items[:limit]:
        result.append(
            {
                "stable_key": str(item.get("stable_key") or ""),
                "kind": str(item.get("kind") or ""),
                "title": str(item.get("title") or ""),
                "preview": str(item.get("preview") or ""),
                "retrieval_reasons": list(item.get("retrieval_reasons") or []),
                "lexical_score": item.get("lexical_score"),
                "embedding_score": item.get("embedding_score"),
                "hybrid_score": item.get("hybrid_score"),
                "reranker_score": item.get("reranker_score"),
            }
        )
    return result


def resolved_lite_path(args: argparse.Namespace) -> str | None:
    lite_path = str(getattr(args, "lite_path", "") or "").strip()
    env_host = str(os.environ.get("AUTOPSY_FALKORDB_HOST") or "").strip()
    env_port = str(os.environ.get("AUTOPSY_FALKORDB_PORT") or "").strip()
    if lite_path and env_host == "" and env_port == "" and str(getattr(args, "host", "127.0.0.1")) == "127.0.0.1" and int(getattr(args, "port", 6381)) == 6381:
        return lite_path
    return None


def load_workspace_and_config(args: argparse.Namespace):
    workspace = resolve_workspace_reference(getattr(args, "workspace", None), str(Path.cwd()))
    config = load_embeddings_config(Path(workspace["root_path"]))
    return FalkorToolShim, workspace, config


def ensure_runtime_indexes(graph) -> None:
    statements = [
        "CREATE INDEX ON :MemoryNode(entity_id)",
        "CREATE INDEX ON :MemoryNode(stable_key)",
        "CREATE INDEX ON :MemoryNode(kind)",
        "CREATE FULLTEXT INDEX ON :SemanticItem(label, summary, detail_content, search_text)",
        "CREATE FULLTEXT INDEX ON :FACT_EDGE(fact_text, relation, predicate)",
    ]
    for statement in statements:
        try:
            graph.query(statement)
        except Exception:
            pass


def check_runtime_index_probe(graph) -> bool:
    try:
        graph.query("CALL db.idx.fulltext.queryNodes('SemanticItem', 'probe') YIELD node RETURN count(node) LIMIT 1")
        return True
    except Exception:
        return False


def build_sync_payload(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    workspace_sync = sync_workspace_payload(graph, workspace=workspace)
    ensure_runtime_indexes(graph)
    invalidate_graph_caches(graph)
    stats = build_graph_stats_payload(graph)
    vector_count = int(scalar_query(graph, "MATCH (node:SemanticItem) WHERE node.embedding IS NOT NULL RETURN count(node)") or 0)
    return {
        "workspace": tool.workspace_payload(workspace),
        "graph_name": graph.name,
        "backend": "falkor",
        "mode": "native",
        "counts": {
            "entities": int(stats.get("entityCount") or 0),
            "items": int(stats.get("itemCount") or 0),
            "edges": int(stats.get("edgeCount") or 0),
            "vectors": vector_count,
        },
        "stats": stats,
        "sync": workspace_sync,
        "indexes_ready": check_runtime_index_probe(graph),
        "timings": {"sync_s": round(time.perf_counter() - started, 3)},
    }


def ensure_workspace_graph(
    *,
    tool=None,
    conn=None,
    workspace: dict[str, Any],
    config: dict[str, Any] | None = None,
    host: str,
    port: int,
    graph_name_base: str,
    lite_path: str | None = None,
) -> tuple[Any, str]:
    graph_name = workspace_graph_name(graph_name_base, workspace)
    graph = ensure_graph(host, port, graph_name, lite_path=lite_path)
    return graph, graph_name


def build_consult_payload(
    graph,
    *,
    tool,
    conn,
    workspace: dict[str, Any],
    config: dict[str, Any],
    query: str,
    limit: int,
    inspect_limit: int = 3,
    route: str = "auto",
) -> dict[str, Any]:
    selected_route = route if route != "auto" else classify_query(query)
    if selected_route == "status":
        return build_status_payload(
            graph,
            tool=tool,
            workspace=workspace,
            thread_id=None,
            limit=max(1, limit),
            section_limit=min(4, max(1, limit)),
            recent_days=tool.STATUS_WINDOW_DAYS_DEFAULT,
        )

    item_count = semantic_item_count(graph)
    exact_items, exact_elapsed = fetch_exact_text_candidates(graph, query, limit=limit)
    lexical_items, lexical_elapsed = fetch_node_lexical(graph, query, limit=limit)
    relationship_hits, relationship_elapsed = fetch_relationship_lexical(graph, query, limit=limit)
    token_overlap_items: list[dict[str, Any]] = []
    token_overlap_elapsed = 0.0
    token_overlap_skipped_reason: str | None = None
    if should_use_token_overlap_scan(item_count, config):
        token_overlap_items, token_overlap_elapsed = fetch_token_overlap_candidates(graph, query, limit=limit)
    else:
        token_overlap_skipped_reason = f"semantic item count {item_count} exceeds token-overlap scan limit {token_overlap_scan_max_items(config)}"

    deduped: dict[str, dict[str, Any]] = {}
    for source_items in (exact_items, lexical_items, token_overlap_items):
        for item in source_items:
            current = deduped.get(item["stable_key"])
            if current is None:
                deduped[item["stable_key"]] = dict(item)
                continue
            reasons = set(current.get("retrieval_reasons", []))
            reasons.update(item.get("retrieval_reasons", []))
            current["retrieval_reasons"] = sorted(reasons)
            current["lexical_score"] = max(float(current.get("lexical_score", 0.0)), float(item.get("lexical_score", 0.0)))
            current["exact_match_boost"] = max(float(current.get("exact_match_boost", 0.0)), float(item.get("exact_match_boost", 0.0)))
            current["rank"] = min(int(current.get("rank", 1_000_000)), int(item.get("rank", 1_000_000)))
            current["updated_at"] = current.get("updated_at") or item.get("updated_at", "")
            current["activity_at"] = current.get("activity_at") or item.get("activity_at", "")
    lexical_items = filter_weak_lexical_hits(query, rerank_lexical_hits(query, list(deduped.values())))
    if not lexical_items and query_has_unlikely_identifier(query):
        relationship_hits = []

    vector_items: list[dict[str, Any]] = []
    vector_elapsed = 0.0
    merged_items = lexical_items
    reranked_elapsed = 0.0
    hybrid_skipped_reason: str | None = None

    if selected_route == "hybrid":
        if lexical_results_are_strong(lexical_items, limit=limit, config=config):
            hybrid_skipped_reason = "lexical_fast_path"
        elif not lexical_items and query_has_unlikely_identifier(query):
            hybrid_skipped_reason = "no_lexical_anchor_for_identifier_query"
        else:
            vector_items, vector_elapsed = fetch_vector_candidates(graph, tool, query, config, limit=limit)
            vector_items = apply_query_sensitive_scoring(query, vector_items)
            merged_items = merge_candidates(lexical_items, vector_items, limit=limit)
            rerank_min_candidates = max(1, int(config.get("rerank_min_candidates", EMBEDDINGS_CONFIG_DEFAULT["rerank_min_candidates"])))
            if not reranker_enabled_for_current_process(config):
                hybrid_skipped_reason = "reranker_disabled_for_cli"
                merged_items = apply_query_sensitive_scoring(query, merged_items)
            elif len(merged_items) >= rerank_min_candidates:
                started = time.perf_counter()
                merged_items = tool.rerank_candidates(query, merged_items, config)
                merged_items = tool.filter_low_relevance_candidates(query, merged_items, config)
                reranked_elapsed = time.perf_counter() - started
            else:
                hybrid_skipped_reason = "too_few_candidates_for_rerank"
                merged_items = apply_query_sensitive_scoring(query, merged_items)

    hits = short_hits(merged_items, limit=limit)
    inspected_items = []
    seen_inspected: set[str] = set()
    for hit in hits[:max(0, inspect_limit)]:
        stable_key = str(hit.get("stable_key") or "")
        if not stable_key or stable_key in seen_inspected:
            continue
        seen_inspected.add(stable_key)
        try:
            inspected_items.append(fetch_item(graph, stable_key))
        except Exception:
            continue

    return {
        "route": selected_route,
        "query": query,
        "workspace": tool.workspace_payload(workspace),
        "graph_name": graph.name,
        "timings": {
            "exact_s": round(exact_elapsed, 3),
            "lexical_s": round(lexical_elapsed, 3),
            "relationship_s": round(relationship_elapsed, 3),
            "token_overlap_s": round(token_overlap_elapsed, 3),
            "vector_s": round(vector_elapsed, 3),
            "rerank_s": round(reranked_elapsed, 3),
        },
        "routing": {
            "semantic_item_count": item_count,
            "token_overlap_skipped_reason": token_overlap_skipped_reason,
            "hybrid_skipped_reason": hybrid_skipped_reason,
        },
        "hits": hits,
        "items": inspected_items,
        "relationship_hits": relationship_hits[:limit],
        "lexical_only_hits": short_hits(lexical_items, limit=limit),
        "vector_only_hits": short_hits(vector_items, limit=limit),
    }


def build_item_payload(graph, *, tool, workspace: dict[str, Any], stable_key: str) -> dict[str, Any]:
    return {
        "workspace": tool.workspace_payload(workspace),
        "item": fetch_item(graph, stable_key),
    }


def build_neighbors_payload(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    stable_key: str | None,
    entity_id: int | None,
    thread_id: str | None,
    limit: int,
    all_kinds: bool,
) -> dict[str, Any]:
    seed = resolve_seed(graph, stable_key=stable_key, entity_id=entity_id, thread_id=thread_id)
    return {
        "workspace": tool.workspace_payload(workspace),
        "seed_entity_id": seed["entity_id"],
        "neighbors": fetch_neighbors(graph, seed, limit=limit, semantic_only=not all_kinds),
    }


def build_timeline_payload(graph, *, tool, workspace: dict[str, Any], stable_key: str) -> dict[str, Any]:
    return {
        "workspace": tool.workspace_payload(workspace),
        "timeline": fetch_timeline(graph, stable_key),
    }


def build_snapshot_payload(graph, *, tool, workspace: dict[str, Any], stable_key: str, limit: int) -> dict[str, Any]:
    return {
        "workspace": tool.workspace_payload(workspace),
        "snapshot": fetch_snapshot(graph, stable_key, limit=limit),
    }


def timed_call(callback) -> tuple[Any, float, str | None]:
    started = time.perf_counter()
    try:
        value = callback()
        return value, time.perf_counter() - started, None
    except Exception as exc:
        return None, time.perf_counter() - started, str(exc)


def payload_item_stable_key(payload: dict[str, Any] | None) -> str:
    item = (payload or {}).get("item") if isinstance(payload, dict) else None
    if not isinstance(item, dict):
        return ""
    return str(item.get("stable_key") or item.get("stableKey") or "")


def benchmark_attribute(name: str, checks: list[dict[str, Any]], *, seconds: float | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    total = max(len(checks), 1)
    passed = sum(1 for check in checks if bool(check.get("passed")))
    score = round((passed / total) * 10.0, 1)
    payload: dict[str, Any] = {
        "name": name,
        "score": score,
        "passed": passed,
        "total": total,
        "checks": checks,
    }
    if seconds is not None:
        payload["seconds"] = round(seconds, 3)
    if details:
        payload["details"] = details
    if score >= 9.5:
        payload["grade"] = "excellent"
    elif score >= 8.0:
        payload["grade"] = "good"
    elif score >= 6.0:
        payload["grade"] = "partial"
    else:
        payload["grade"] = "weak"
    return payload


def sample_semantic_items(graph, limit: int) -> list[dict[str, Any]]:
    result = graph.query(
        """
        MATCH (node:SemanticItem)
        WHERE coalesce(node.source_kind, '') <> 'graph_episode'
          AND NOT coalesce(node.stable_key, '') STARTS WITH 'turn-outcome:'
        RETURN node.stable_key, node.kind, node.label, coalesce(node.summary, ''), coalesce(node.updated_at, node.created_at)
        ORDER BY coalesce(node.updated_at, node.created_at) DESC
        LIMIT $limit
        """,
        params={"limit": max(1, limit)},
    )
    items = []
    for row in result_rows(result):
        stable_key = str(row[0] or "")
        title = str(row[2] or "")
        if stable_key and title:
            items.append(
                {
                    "stable_key": stable_key,
                    "kind": str(row[1] or ""),
                    "title": title,
                    "summary": str(row[3] or ""),
                    "updated_at": str(row[4] or ""),
                }
            )
    return items


def benchmark_recall(graph, *, tool, workspace: dict[str, Any], config: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    elapsed_total = 0.0
    for sample in samples:
        query = str(sample.get("title") or "")
        payload, elapsed, error = timed_call(
            lambda query=query: build_consult_payload(
                graph,
                tool=tool,
                conn=None,
                workspace=workspace,
                config=config,
                query=query,
                limit=5,
                inspect_limit=1,
                route="lexical",
            )
        )
        elapsed_total += elapsed
        top_key = ""
        if isinstance(payload, dict):
            hits = list(payload.get("hits") or [])
            if hits:
                top_key = str(hits[0].get("stable_key") or "")
        checks.append(
            {
                "sample": sample.get("stable_key"),
                "query": query,
                "top_key": top_key,
                "passed": top_key == sample.get("stable_key"),
                "error": error,
                "seconds": round(elapsed, 3),
            }
        )
    if not checks:
        checks.append({"sample": None, "passed": False, "error": "no semantic items available"})
    return benchmark_attribute("recall_top1", checks, seconds=elapsed_total)


def benchmark_inspection(graph, *, tool, workspace: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    elapsed_total = 0.0
    for sample in samples[:3]:
        payload, elapsed, error = timed_call(
            lambda stable_key=sample["stable_key"]: build_item_payload(
                graph,
                tool=tool,
                workspace=workspace,
                stable_key=stable_key,
            )
        )
        elapsed_total += elapsed
        item = payload.get("item") if isinstance(payload, dict) else {}
        links = list(item.get("links") or []) if isinstance(item, dict) else []
        checks.append(
            {
                "stable_key": sample.get("stable_key"),
                "passed": isinstance(item, dict)
                and item.get("stable_key") == sample.get("stable_key")
                and bool(item.get("title"))
                and isinstance(links, list),
                "error": error,
                "seconds": round(elapsed, 3),
            }
        )
    if not checks:
        checks.append({"stable_key": None, "passed": False, "error": "no items to inspect"})
    return benchmark_attribute("inspection_accuracy", checks, seconds=elapsed_total)


def benchmark_precision_abstention(graph, *, tool, workspace: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    marker = f"nohit-{uuid.uuid4().hex}-glass-cactus-riverboat-lunar-biscuit"
    checks: list[dict[str, Any]] = []
    elapsed_total = 0.0
    for label, route in (("consult", "lexical"), ("search", "lexical")):
        if label == "consult":
            payload, elapsed, error = timed_call(
                lambda: build_consult_payload(
                    graph,
                    tool=tool,
                    conn=None,
                    workspace=workspace,
                    config=config,
                    query=marker,
                    limit=5,
                    inspect_limit=0,
                    route=route,
                )
            )
            count = len(payload.get("hits") or []) if isinstance(payload, dict) else -1
        else:
            payload, elapsed, error = timed_call(
                lambda: build_graph_search_payload(
                    graph,
                    tool=tool,
                    conn=None,
                    workspace=workspace,
                    config=config,
                    query=marker,
                    limit=5,
                )
            )
            count = len(payload.get("results") or []) if isinstance(payload, dict) else -1
        elapsed_total += elapsed
        checks.append(
            {
                "query": marker,
                "path": label,
                "result_count": count,
                "passed": count == 0,
                "error": error,
                "seconds": round(elapsed, 3),
            }
        )
    return benchmark_attribute("precision_abstention", checks, seconds=elapsed_total)


def benchmark_performance(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    config: dict[str, Any],
    sample: dict[str, Any] | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    status_payload, status_elapsed, status_error = timed_call(
        lambda: build_status_payload(
            graph,
            tool=tool,
            workspace=workspace,
            thread_id=None,
            limit=6,
            section_limit=3,
            recent_days=tool.STATUS_WINDOW_DAYS_DEFAULT,
        )
    )
    checks.append(
        {
            "path": "status",
            "seconds": round(status_elapsed, 3),
            "passed": status_error is None and isinstance(status_payload, dict) and status_elapsed <= 1.25,
            "error": status_error,
        }
    )
    if sample:
        consult_payload, consult_elapsed, consult_error = timed_call(
            lambda: build_consult_payload(
                graph,
                tool=tool,
                conn=None,
                workspace=workspace,
                config=config,
                query=str(sample.get("title") or ""),
                limit=5,
                inspect_limit=1,
                route="lexical",
            )
        )
        checks.append(
            {
                "path": "lexical_consult",
                "seconds": round(consult_elapsed, 3),
                "passed": consult_error is None and isinstance(consult_payload, dict) and consult_elapsed <= 1.0,
                "error": consult_error,
            }
        )
    negative = f"perf-nohit-{uuid.uuid4().hex}"
    negative_payload, negative_elapsed, negative_error = timed_call(
        lambda: build_consult_payload(
            graph,
            tool=tool,
            conn=None,
            workspace=workspace,
            config=config,
            query=negative,
            limit=5,
            inspect_limit=0,
            route="lexical",
        )
    )
    checks.append(
        {
            "path": "negative_consult",
            "seconds": round(negative_elapsed, 3),
            "passed": negative_error is None and isinstance(negative_payload, dict) and negative_elapsed <= 1.0,
            "error": negative_error,
        }
    )
    return benchmark_attribute("performance", checks, seconds=status_elapsed + negative_elapsed)


def benchmark_scale_readiness(graph, *, tool, workspace: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    threshold = token_overlap_scan_max_items(config)
    checks.append(
        {
            "name": "token_overlap_scan_guard",
            "threshold": threshold,
            "passed": threshold > 0 and should_use_token_overlap_scan(threshold + 1, config) is False,
        }
    )
    checks.append(
        {
            "name": "expanded_vector_candidate_pool",
            "candidate_limit": int(config.get("vector_candidate_limit") or config.get("candidate_limit") or 0),
            "passed": int(config.get("vector_candidate_limit") or config.get("candidate_limit") or 0) >= 48,
        }
    )
    payload, elapsed, error = timed_call(
        lambda: build_consult_payload(
            graph,
            tool=tool,
            conn=None,
            workspace=workspace,
            config=config,
            query="Autopsy memory Falkor benchmark retrieval",
            limit=5,
            inspect_limit=0,
            route="hybrid",
        )
    )
    routing = payload.get("routing") if isinstance(payload, dict) else {}
    timings = payload.get("timings") if isinstance(payload, dict) else {}
    checks.append(
        {
            "name": "lexical_fast_path_avoids_heavy_hybrid",
            "passed": error is None
            and isinstance(payload, dict)
            and routing.get("hybrid_skipped_reason") == "lexical_fast_path"
            and float(timings.get("rerank_s") or 0.0) == 0.0,
            "seconds": round(elapsed, 3),
            "error": error,
            "routing": routing,
        }
    )
    return benchmark_attribute("scale_readiness", checks, seconds=elapsed)


def benchmark_writes_and_relations(graph, *, tool, workspace: dict[str, Any]) -> dict[str, Any]:
    title = f"Autopsy benchmark probe {uuid.uuid4().hex[:8]}"
    content = "Temporary Falkor-native write probe. This item should be removed by the benchmark."
    checks: list[dict[str, Any]] = []
    elapsed_total = 0.0
    stable_key = ""
    episode_key = ""
    try:
        created, elapsed, error = timed_call(
            lambda: create_graph_note_payload(
                graph,
                tool=tool,
                workspace=workspace,
                kind="attempt",
                title=title,
                content=content,
                repository_root_path=None,
                thread_id=None,
            )
        )
        elapsed_total += elapsed
        stable_key = payload_item_stable_key(created)
        checks.append({"path": "create", "stable_key": stable_key, "passed": bool(stable_key), "error": error, "seconds": round(elapsed, 3)})

        fetched, elapsed, error = timed_call(lambda: fetch_item(graph, stable_key))
        elapsed_total += elapsed
        links = list(fetched.get("links") or []) if isinstance(fetched, dict) else []
        captured_links = [link for link in links if str(link.get("relation") or "") == "captured_in"]
        if captured_links:
            episode_key = str(captured_links[0].get("entity_stable_key") or "")
        checks.append(
            {
                "path": "relation",
                "stable_key": stable_key,
                "relation": "captured_in",
                "passed": bool(captured_links),
                "error": error,
                "seconds": round(elapsed, 3),
            }
        )

        _, elapsed, error = timed_call(lambda: delete_graph_item_payload(graph, stable_key=stable_key))
        elapsed_total += elapsed
        if episode_key:
            delete_graph_item_payload(graph, stable_key=episode_key)
        missing_after_delete = lookup_node_by_stable_key(graph, stable_key) is None
        checks.append({"path": "delete", "stable_key": stable_key, "passed": missing_after_delete, "error": error, "seconds": round(elapsed, 3)})
    except Exception as exc:
        checks.append({"path": "write_probe", "passed": False, "error": str(exc)})
    finally:
        if stable_key and lookup_node_by_stable_key(graph, stable_key) is not None:
            delete_graph_item_payload(graph, stable_key=stable_key)
        if episode_key and lookup_node_by_stable_key(graph, episode_key) is not None:
            delete_graph_item_payload(graph, stable_key=episode_key)
    return benchmark_attribute("writes_and_relations", checks, seconds=elapsed_total)


def benchmark_falkor_native(graph, *, include_sync: bool, sync_payload: dict[str, Any] | None) -> dict[str, Any]:
    checks = [
        {
            "name": "graph_reachable",
            "passed": scalar_query(graph, "MATCH (node) RETURN count(node) LIMIT 1") is not None,
        },
        {
            "name": "runtime_backend",
            "passed": True,
            "backend": "falkor",
        },
        {
            "name": "indexes_queryable",
            "passed": check_runtime_index_probe(graph),
        },
    ]
    if include_sync:
        checks.append(
            {
                "name": "native_sync",
                "passed": isinstance(sync_payload, dict) and bool((sync_payload.get("sync") or {}).get("synced")),
            }
        )
    return benchmark_attribute("falkor_native", checks)


def build_benchmark_payload(
    graph,
    *,
    tool,
    workspace: dict[str, Any],
    config: dict[str, Any],
    sample_size: int,
    include_sync: bool,
    skip_write_probe: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    ensure_runtime_indexes(graph)
    sync_payload = build_sync_payload(graph, tool=tool, workspace=workspace, config=config) if include_sync else None
    stats = build_graph_stats_payload(graph)
    samples = sample_semantic_items(graph, max(1, sample_size))
    embedding_available, embedding_error = embedding_provider_available(config)
    reranker_available, reranker_error = reranker_provider_available(config)
    operational_checks = [
        {
            "name": "graph_reachable",
            "passed": scalar_query(graph, "MATCH (node) RETURN count(node) LIMIT 1") is not None,
        },
        {
            "name": "workspace_resolved",
            "passed": bool(workspace.get("root_path")),
            "workspace": tool.workspace_payload(workspace),
        },
        {
            "name": "semantic_items_present",
            "passed": int(stats.get("itemCount") or 0) > 0,
            "item_count": int(stats.get("itemCount") or 0),
        },
        {
            "name": "fulltext_queryable",
            "passed": check_runtime_index_probe(graph),
        },
        {
            "name": "embedding_provider_configured",
            "passed": embedding_available,
            "provider": str(config.get("provider") or ""),
            "error": embedding_error,
        },
        {
            "name": "reranker_provider_configured",
            "passed": reranker_available,
            "provider": str(reranker_config(config).get("provider") or ""),
            "error": reranker_error,
        },
    ]
    attributes = [
        benchmark_attribute("operational_health", operational_checks, details={"stats": stats}),
        benchmark_recall(graph, tool=tool, workspace=workspace, config=config, samples=samples),
        benchmark_inspection(graph, tool=tool, workspace=workspace, samples=samples),
        benchmark_precision_abstention(graph, tool=tool, workspace=workspace, config=config),
        benchmark_performance(graph, tool=tool, workspace=workspace, config=config, sample=samples[0] if samples else None),
        benchmark_scale_readiness(graph, tool=tool, workspace=workspace, config=config),
    ]
    if not skip_write_probe:
        attributes.append(benchmark_writes_and_relations(graph, tool=tool, workspace=workspace))
    attributes.append(benchmark_falkor_native(graph, include_sync=include_sync, sync_payload=sync_payload))
    overall = round(sum(float(attribute.get("score") or 0.0) for attribute in attributes) / max(len(attributes), 1), 1)
    return {
        "benchmark": "autopsy-memory-falkor",
        "overall_score": overall,
        "passed": overall >= 8.0 and all(float(attribute.get("score") or 0.0) >= 6.0 for attribute in attributes),
        "workspace": tool.workspace_payload(workspace),
        "graph_name": graph.name,
        "sample_size": len(samples),
        "stats": stats,
        "attributes": attributes,
        "sync": sync_payload,
        "workflow": {
            "complete": overall >= 8.0,
            "next_steps": [] if overall >= 8.0 else ["Inspect failed attribute checks and rerun after fixing graph/index/query health."],
        },
        "timings": {"total_s": round(time.perf_counter() - started, 3)},
    }


def open_workspace_graph(args: argparse.Namespace):
    tool, workspace, config = load_workspace_and_config(args)
    graph, _ = ensure_workspace_graph(
        tool=tool,
        conn=None,
        workspace=workspace,
        config=config,
        host=args.host,
        port=args.port,
        graph_name_base=args.graph_name,
        lite_path=resolved_lite_path(args),
    )
    return tool, workspace, config, graph


def cmd_sync(args: argparse.Namespace) -> None:
    tool, workspace, config, graph = open_workspace_graph(args)
    payload = build_sync_payload(graph, tool=tool, workspace=workspace, config=config)
    print(json.dumps(payload, indent=2))


def cmd_consult(args: argparse.Namespace) -> None:
    tool, workspace, config, graph = open_workspace_graph(args)
    query = str(getattr(args, "query", None) or getattr(args, "query_text", None) or "").strip()
    if not query:
        fail("expected --query or positional query", 2)
    payload = build_consult_payload(
        graph,
        tool=tool,
        conn=None,
        workspace=workspace,
        config=config,
        query=query,
        limit=args.limit,
        inspect_limit=getattr(args, "inspect_limit", 3),
        route=args.route,
    )
    reliable_hits = list(payload.get("hits") or []) or list(payload.get("items") or [])
    weak_signal_hits = (
        list(payload.get("relationship_hits") or [])
        + list(payload.get("lexical_only_hits") or [])
        + list(payload.get("vector_only_hits") or [])
    )
    if reliable_hits:
        payload["workflow"] = tool.build_read_workflow(
            workspace["root_path"],
            command="consult",
            query=query,
            hits=reliable_hits,
            inspected_items=list(payload.get("items") or []),
            current_only=bool(getattr(args, "current_only", False)),
        )
    elif weak_signal_hits:
        payload["workflow"] = {
            "status": "weak_signals_only",
            "coverage": "weak",
            "complete": False,
            "next_step": "refine_query",
            "message": "No reliable memory hits were found. Weak side-channel candidates are shown for debugging only.",
            "suggested_next_steps": [
                workflow_step(
                    "refine-query",
                    "Use a more specific query or inspect exact items before relying on weak relationship/vector side channels.",
                )
            ],
        }
    else:
        payload["workflow"] = tool.build_read_workflow(
            workspace["root_path"],
            command="consult",
            query=query,
            hits=[],
            inspected_items=[],
            current_only=bool(getattr(args, "current_only", False)),
        )
    print(json.dumps(payload, indent=2))


def cmd_item(args: argparse.Namespace) -> None:
    tool, workspace, _config, graph = open_workspace_graph(args)
    payload = build_item_payload(graph, tool=tool, workspace=workspace, stable_key=args.stable_key)
    print(json.dumps(payload, indent=2))


def cmd_neighbors(args: argparse.Namespace) -> None:
    tool, workspace, _config, graph = open_workspace_graph(args)
    payload = build_neighbors_payload(
        graph,
        tool=tool,
        workspace=workspace,
        stable_key=getattr(args, "stable_key", None),
        entity_id=getattr(args, "entity_id", None),
        thread_id=getattr(args, "thread_id", None),
        limit=args.limit,
        all_kinds=args.all_kinds,
    )
    print(json.dumps(payload, indent=2))


def cmd_timeline(args: argparse.Namespace) -> None:
    tool, workspace, _config, graph = open_workspace_graph(args)
    payload = build_timeline_payload(graph, tool=tool, workspace=workspace, stable_key=args.stable_key)
    print(json.dumps(payload, indent=2))


def cmd_snapshot(args: argparse.Namespace) -> None:
    tool, workspace, _config, graph = open_workspace_graph(args)
    payload = build_snapshot_payload(graph, tool=tool, workspace=workspace, stable_key=args.stable_key, limit=args.limit)
    print(json.dumps(payload, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    tool, workspace, _config, graph = open_workspace_graph(args)
    payload = build_status_payload(
        graph,
        tool=tool,
        workspace=workspace,
        thread_id=getattr(args, "thread_id", None),
        limit=args.limit,
        section_limit=args.section_limit,
        recent_days=args.recent_days,
    )
    print(json.dumps(payload, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    tool, workspace, config, graph = open_workspace_graph(args)
    query = str(getattr(args, "query", None) or getattr(args, "query_text", None) or "").strip()
    if not query:
        fail("expected --query or positional query", 2)
    payload = build_graph_search_payload(
        graph,
        tool=tool,
        conn=None,
        workspace=workspace,
        config=config,
        query=query,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2))


def cmd_benchmark(args: argparse.Namespace) -> None:
    tool, workspace, config, graph = open_workspace_graph(args)
    payload = build_benchmark_payload(
        graph,
        tool=tool,
        workspace=workspace,
        config=config,
        sample_size=args.sample_size,
        include_sync=args.include_sync,
        skip_write_probe=args.skip_write_probe,
    )
    print(json.dumps(payload, indent=2))


NOTE_KIND_ALIASES = {
    "decision": "decision",
    "attempt": "attempt",
    "question": "open_question",
    "open-question": "open_question",
    "open_question": "open_question",
    "preference": "preference",
    "plan": "plan",
    "resolved-question": "decision",
    "resolved_question": "decision",
    "reverted-attempt": "attempt",
    "reverted_attempt": "attempt",
    "capture-outcome": "attempt",
    "capture": "memory_note",
    "create": "memory_note",
}


def normalize_note_kind(value: str | None, *, fallback: str = "memory_note") -> str:
    raw = str(value or fallback).strip().lower().replace(" ", "-")
    return NOTE_KIND_ALIASES.get(raw, raw.replace("-", "_"))


def note_text_from_args(args: argparse.Namespace) -> tuple[str, str]:
    positional = " ".join(str(part) for part in getattr(args, "text", []) if str(part).strip()).strip()
    content = str(getattr(args, "content", None) or positional or "").strip()
    if not content and not sys.stdin.isatty():
        content = sys.stdin.read().strip()
    title = str(getattr(args, "title", None) or "").strip()
    if not title:
        title = summary_snippet(content, limit=88) or "Memory note"
    if not content:
        content = title
    return title, content


def repository_path_from_args(args: argparse.Namespace) -> str | None:
    value = str(getattr(args, "repository_root_path", None) or getattr(args, "repo", None) or "").strip()
    return value or None


def memory_write_quality_warnings(graph, *, kind: str, title: str, content: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    trimmed_title = " ".join(str(title or "").split())
    trimmed_content = " ".join(str(content or "").split())
    signal_tokens = query_signal_tokens(f"{trimmed_title} {trimmed_content}")
    if len(trimmed_content) < 80:
        warnings.append({
            "code": "content_too_short",
            "severity": "medium",
            "message": "Memory content is short; durable memories work better with outcome, rationale, and concrete verification.",
        })
    if trimmed_title and trimmed_title == trimmed_content:
        warnings.append({
            "code": "title_duplicates_content",
            "severity": "medium",
            "message": "Title and content are identical; add details that will help future retrieval and inspection.",
        })
    if len(set(signal_tokens)) < 6:
        warnings.append({
            "code": "low_signal_terms",
            "severity": "low",
            "message": "Memory has few distinctive terms; include repo names, commands, files, commits, or exact decisions when possible.",
        })
    duplicates: list[dict[str, Any]] = []
    try:
        rows = result_rows(graph.query(
            """
            MATCH (node:SemanticItem)
            WHERE node.kind = $kind
              AND (
                toLower(coalesce(node.label, '')) = $title
                OR toLower(coalesce(node.detail_content, '')) = $content
              )
            RETURN node.stable_key, node.kind, node.label, coalesce(node.updated_at, node.created_at)
            LIMIT 5
            """,
            params={
                "kind": kind,
                "title": trimmed_title.lower(),
                "content": trimmed_content.lower(),
            },
        ))
        for row in rows:
            duplicates.append({
                "stable_key": str(row[0] or ""),
                "kind": str(row[1] or ""),
                "title": str(row[2] or ""),
                "updated_at": str(row[3] or ""),
            })
    except Exception:
        duplicates = []
    if duplicates:
        warnings.append({
            "code": "possible_duplicate",
            "severity": "medium",
            "message": "A memory with the same title or content already exists; consider updating or relating the existing item.",
            "candidates": duplicates,
        })
    return warnings


def create_requested_fact_relations(graph, *, source_stable_key: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    source = fetch_item(graph, source_stable_key)
    created = []
    timestamp = utc_now_iso()
    for relation in ("informed-by", "answers", "supersedes", "reverts", "depends-on", "implements", "constrains", "refines"):
        values = list(getattr(args, relation.replace("-", "_"), []) or [])
        for target_key in values:
            target_stable_key = str(target_key or "").strip()
            if not target_stable_key:
                continue
            target = fetch_item(graph, target_stable_key)
            canonical_relation = relation.replace("-", "_")
            create_fact_edge(
                graph,
                from_entity_id=int(source["entity_id"]),
                to_entity_id=int(target["entity_id"]),
                relation=canonical_relation,
                predicate=canonical_relation.upper(),
                fact_text=f"{source_stable_key} {canonical_relation} {target_stable_key}",
                timestamp=timestamp,
                origin="falkor",
            )
            created.append({"relation": canonical_relation, "target": target_stable_key})
    return created


def cmd_create_note(args: argparse.Namespace) -> None:
    tool, workspace, _config, graph = open_workspace_graph(args)
    command_kind = normalize_note_kind(getattr(args, "command", None))
    requested_kind = str(getattr(args, "kind", "") or "").strip()
    outcome = str(getattr(args, "outcome", "") or "").strip()
    kind = normalize_note_kind(requested_kind or outcome or command_kind)
    title, content = note_text_from_args(args)
    quality_warnings = memory_write_quality_warnings(graph, kind=kind, title=title, content=content)
    payload = create_graph_note_payload(
        graph,
        tool=tool,
        workspace=workspace,
        kind=kind,
        title=title,
        content=content,
        repository_root_path=repository_path_from_args(args),
        thread_id=str(getattr(args, "thread_id", "") or "").strip() or None,
    )
    stable_key = payload_item_stable_key(payload)
    if stable_key:
        relations = create_requested_fact_relations(graph, source_stable_key=stable_key, args=args)
        if relations:
            payload = build_graph_item_detail_payload(graph, tool=tool, workspace=workspace, stable_key=stable_key)
            payload["created_relations"] = relations
    payload["write_quality"] = {
        "warnings": quality_warnings,
        "complete": not bool(quality_warnings),
    }
    print(json.dumps(payload, indent=2))


def cmd_update_item(args: argparse.Namespace) -> None:
    tool, workspace, _config, graph = open_workspace_graph(args)
    title, content = note_text_from_args(args)
    kind = normalize_note_kind(getattr(args, "kind", None), fallback="memory_note")
    payload = update_graph_item_payload(
        graph,
        tool=tool,
        workspace=workspace,
        stable_key=args.stable_key,
        kind=kind,
        title=title,
        content=content,
    )
    print(json.dumps(payload, indent=2))


def cmd_delete_item(args: argparse.Namespace) -> None:
    _tool, _workspace, _config, graph = open_workspace_graph(args)
    delete_graph_item_payload(graph, stable_key=args.stable_key)
    print(json.dumps({"deleted": True, "stable_key": args.stable_key}, indent=2))


def export_memory_payload(
    graph,
    *,
    workspace: dict[str, Any],
    include_operational: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    max_items = max(0, int(limit or 0))
    item_query = """
        MATCH (node:MemoryNode)
        WHERE $include_operational OR node.kind IN $semantic_kinds
        RETURN
          node.entity_id,
          node.stable_key,
          node.kind,
          node.label,
          node.summary,
          node.detail_content,
          node.source_kind,
          coalesce(node.confidence, 1.0),
          node.created_at,
          node.updated_at
        ORDER BY node.updated_at DESC, node.entity_id DESC
    """
    params = {
        "include_operational": bool(include_operational),
        "semantic_kinds": sorted(SEARCHABLE_KINDS),
    }
    if max_items > 0:
        item_query += "\n        LIMIT $limit"
        params["limit"] = max_items
    rows = result_rows(graph.query(item_query, params=params))
    items = [
        {
            "entity_id": int(row[0]),
            "stable_key": str(row[1] or ""),
            "kind": str(row[2] or ""),
            "title": str(row[3] or ""),
            "summary": str(row[4] or ""),
            "content": str(row[5] or ""),
            "source_kind": str(row[6] or ""),
            "confidence": 1.0 if row[7] is None else float(row[7]),
            "created_at": str(row[8] or ""),
            "updated_at": str(row[9] or ""),
        }
        for row in rows
    ]
    stable_keys = [item["stable_key"] for item in items if item.get("stable_key")]
    fact_edges: list[dict[str, Any]] = []
    structural_edges: list[dict[str, Any]] = []
    if stable_keys:
        fact_rows = result_rows(graph.query(
            """
            MATCH (source:MemoryNode)-[fact:FACT_EDGE]->(target:MemoryNode)
            WHERE source.stable_key IN $stable_keys AND target.stable_key IN $stable_keys
            RETURN
              source.stable_key,
              target.stable_key,
              fact.relation,
              fact.predicate,
              fact.fact_text,
              fact.valid_at,
              fact.invalid_at,
              fact.expired_at,
              fact.updated_at
            ORDER BY fact.updated_at DESC
            """,
            params={"stable_keys": stable_keys},
        ))
        fact_edges = [
            {
                "from": str(row[0] or ""),
                "to": str(row[1] or ""),
                "relation": str(row[2] or ""),
                "predicate": str(row[3] or ""),
                "fact_text": str(row[4] or ""),
                "valid_at": str(row[5] or ""),
                "invalid_at": str(row[6] or ""),
                "expired_at": str(row[7] or ""),
                "updated_at": str(row[8] or ""),
            }
            for row in fact_rows
        ]
        structural_rows = result_rows(graph.query(
            """
            MATCH (source:MemoryNode)-[edge]->(target:MemoryNode)
            WHERE type(edge) IN $edge_types
              AND source.stable_key IN $stable_keys
              AND target.stable_key IN $stable_keys
            RETURN source.stable_key, target.stable_key, coalesce(edge.relation, toLower(type(edge))), edge.updated_at
            ORDER BY edge.updated_at DESC
            """,
            params={"stable_keys": stable_keys, "edge_types": list(STRUCTURAL_EDGE_TYPES)},
        ))
        structural_edges = [
            {
                "from": str(row[0] or ""),
                "to": str(row[1] or ""),
                "relation": str(row[2] or ""),
                "updated_at": str(row[3] or ""),
            }
            for row in structural_rows
        ]
    return {
        "schema_version": 1,
        "exported_at": utc_now_iso(),
        "autopsy_version": package_version(),
        "workspace": workspace_payload(workspace),
        "graph_name": str(getattr(graph, "name", "") or ""),
        "include_operational": bool(include_operational),
        "items": items,
        "relations": fact_edges,
        "structural_edges": structural_edges,
        "counts": {
            "items": len(items),
            "relations": len(fact_edges),
            "structural_edges": len(structural_edges),
        },
    }


def write_payload(payload: dict[str, Any], output: str | None = None) -> None:
    serialized = json.dumps(payload, indent=2)
    if output:
        output_path = Path(output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
        print(json.dumps({"written": str(output_path), "bytes": output_path.stat().st_size}, indent=2))
        return
    print(serialized)


def cmd_export(args: argparse.Namespace) -> None:
    _tool, workspace, _config, graph = open_workspace_graph(args)
    payload = export_memory_payload(
        graph,
        workspace=workspace,
        include_operational=bool(getattr(args, "include_operational", False)),
        limit=int(getattr(args, "limit", 0) or 0),
    )
    write_payload(payload, getattr(args, "output", None))


def cmd_backup(args: argparse.Namespace) -> None:
    output = str(getattr(args, "output", "") or "").strip()
    if not output:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = str(APP_SUPPORT_DIR_DEFAULT / "Backups" / f"autopsy-memory-{timestamp}.json")
    args.output = output
    cmd_export(args)


def chunked_values(values: list[str], size: int = 500) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), max(1, size))]


def load_restore_json(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.exists():
        fail(f"restore input does not exist: {path}", 2)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"restore input is not valid JSON: {exc}", 2)
    if not isinstance(payload, dict):
        fail("restore input must be a JSON object", 2)
    return payload


def restore_confidence(raw_item: dict[str, Any]) -> float:
    raw_value = raw_item.get("confidence")
    if raw_value is None:
        return 1.0
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return 1.0


def restore_item_from_raw(raw_item: dict[str, Any], *, fallback_timestamp: str) -> dict[str, Any]:
    stable_key = str(raw_item.get("stable_key") or raw_item.get("stableKey") or "").strip()
    content = str(raw_item.get("content") or raw_item.get("detail_content") or raw_item.get("detailContent") or "").strip()
    summary = str(raw_item.get("summary") or summary_snippet(content)).strip()
    title = str(raw_item.get("title") or raw_item.get("label") or summary or stable_key).strip()
    timestamp = str(raw_item.get("updated_at") or raw_item.get("updatedAt") or raw_item.get("created_at") or raw_item.get("createdAt") or fallback_timestamp).strip()
    return {
        "stable_key": stable_key,
        "kind": str(raw_item.get("kind") or "memory_note").strip() or "memory_note",
        "title": title,
        "summary": summary,
        "content": content,
        "source_kind": str(raw_item.get("source_kind") or raw_item.get("sourceKind") or "restore").strip() or "restore",
        "confidence": restore_confidence(raw_item),
        "timestamp": timestamp or fallback_timestamp,
    }


def normalized_restore_items(payload: dict[str, Any], *, include_operational: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        fail("restore input must contain an items array", 2)
    timestamp = utc_now_iso()
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            skipped.append({"index": index, "reason": "not_object"})
            continue
        item = restore_item_from_raw(raw_item, fallback_timestamp=timestamp)
        stable_key = item["stable_key"]
        if not stable_key:
            skipped.append({"index": index, "reason": "missing_stable_key"})
            continue
        if stable_key in seen:
            skipped.append({"index": index, "stable_key": stable_key, "reason": "duplicate_in_input"})
            continue
        if item["kind"] in OPERATIONAL_KINDS and not include_operational:
            skipped.append({"index": index, "stable_key": stable_key, "kind": item["kind"], "reason": "operational_excluded"})
            continue
        seen.add(stable_key)
        items.append(item)
    return items, skipped


def normalized_restore_fact_edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_edges = payload.get("relations") or []
    if not isinstance(raw_edges, list):
        fail("restore input relations must be an array when present", 2)
    edges: list[dict[str, Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        from_key = str(raw_edge.get("from") or raw_edge.get("from_stable_key") or raw_edge.get("fromStableKey") or "").strip()
        to_key = str(raw_edge.get("to") or raw_edge.get("to_stable_key") or raw_edge.get("toStableKey") or "").strip()
        relation = str(raw_edge.get("relation") or "").strip()
        if not from_key or not to_key or not relation:
            continue
        predicate = str(raw_edge.get("predicate") or relation.upper()).strip() or relation.upper()
        edges.append({
            "from": from_key,
            "to": to_key,
            "relation": relation,
            "predicate": predicate,
            "fact_text": str(raw_edge.get("fact_text") or raw_edge.get("factText") or f"{from_key} {relation} {to_key}").strip(),
            "timestamp": str(raw_edge.get("updated_at") or raw_edge.get("updatedAt") or utc_now_iso()).strip(),
        })
    return edges


def normalized_restore_structural_edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_edges = payload.get("structural_edges") or payload.get("structuralEdges") or []
    if not isinstance(raw_edges, list):
        fail("restore input structural_edges must be an array when present", 2)
    edges: list[dict[str, Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        from_key = str(raw_edge.get("from") or raw_edge.get("from_stable_key") or raw_edge.get("fromStableKey") or "").strip()
        to_key = str(raw_edge.get("to") or raw_edge.get("to_stable_key") or raw_edge.get("toStableKey") or "").strip()
        relation = str(raw_edge.get("relation") or "").strip()
        if from_key and to_key and relation:
            edges.append({
                "from": from_key,
                "to": to_key,
                "relation": relation,
                "timestamp": str(raw_edge.get("updated_at") or raw_edge.get("updatedAt") or utc_now_iso()).strip(),
            })
    return edges


def existing_restore_keys(graph, stable_keys: list[str]) -> set[str]:
    existing: set[str] = set()
    for chunk in chunked_values(stable_keys):
        rows = result_rows(graph.query(
            """
            MATCH (node:MemoryNode)
            WHERE node.stable_key IN $stable_keys
            RETURN node.stable_key
            """,
            params={"stable_keys": chunk},
        ))
        existing.update(str(row[0] or "") for row in rows if row and row[0])
    return existing


def restore_memory_payload(
    graph,
    *,
    workspace: dict[str, Any],
    input_path: str,
    payload: dict[str, Any],
    dry_run: bool,
    replace: bool,
    include_operational: bool,
) -> dict[str, Any]:
    schema_version = payload.get("schema_version")
    if schema_version != 1:
        fail(f"unsupported restore schema_version: {schema_version!r}", 2)
    items, skipped_items = normalized_restore_items(payload, include_operational=include_operational)
    fact_edges = normalized_restore_fact_edges(payload)
    structural_edges = normalized_restore_structural_edges(payload)
    item_keys = [item["stable_key"] for item in items]
    item_key_set = set(item_keys)
    existing_keys = existing_restore_keys(graph, item_keys) if item_keys else set()
    available_keys = existing_keys | item_key_set
    missing_fact_edges = [
        edge for edge in fact_edges
        if edge["from"] not in available_keys or edge["to"] not in available_keys
    ]
    missing_structural_edges = [
        edge for edge in structural_edges
        if edge["from"] not in available_keys or edge["to"] not in available_keys
    ]
    report: dict[str, Any] = {
        "restored": not dry_run,
        "dry_run": dry_run,
        "mode": "replace" if replace else "merge",
        "replace_scope": "restored_keys" if replace else None,
        "input": str(Path(input_path).expanduser()),
        "schema_version": schema_version,
        "workspace": workspace_payload(workspace),
        "source": {
            "exported_at": payload.get("exported_at"),
            "autopsy_version": payload.get("autopsy_version"),
            "graph_name": payload.get("graph_name"),
        },
        "counts": {
            "input_items": len(payload.get("items") or []),
            "restorable_items": len(items),
            "skipped_items": len(skipped_items),
            "existing_items": len(existing_keys),
            "new_items": len(item_key_set - existing_keys),
            "input_relations": len(fact_edges),
            "input_structural_edges": len(structural_edges),
            "skipped_relations_missing_endpoint": len(missing_fact_edges),
            "skipped_structural_edges_missing_endpoint": len(missing_structural_edges),
        },
        "skipped_items": skipped_items[:50],
        "warnings": [],
    }
    if replace:
        report["warnings"].append("replace deletes only keys present in the restore file before re-importing them; unrelated graph data is not wiped.")
    if dry_run:
        report["counts"].update({
            "would_create_items": len(item_key_set - existing_keys) + (len(existing_keys) if replace else 0),
            "would_update_items": 0 if replace else len(existing_keys),
            "would_upsert_relations": len(fact_edges) - len(missing_fact_edges),
            "would_upsert_structural_edges": len(structural_edges) - len(missing_structural_edges),
        })
        report["workflow"] = {
            "status": "dry_run",
            "complete": True,
            "next_step": "rerun_without_dry_run",
            "message": "Restore input validated without writing to Falkor.",
        }
        return report

    if replace and existing_keys:
        for key in sorted(existing_keys):
            delete_graph_item_payload(graph, stable_key=key)

    created_items = 0
    updated_items = 0
    for item in items:
        existed = item["stable_key"] in existing_keys
        upsert_memory_node(
            graph,
            kind=item["kind"],
            stable_key=item["stable_key"],
            label=item["title"],
            summary=item["summary"],
            detail_content=item["content"],
            confidence=item["confidence"],
            source_kind=item["source_kind"],
            timestamp=item["timestamp"],
            origin="restore",
        )
        if replace or not existed:
            created_items += 1
        else:
            updated_items += 1

    fact_created = 0
    fact_updated = 0
    fact_skipped = 0
    for edge in fact_edges:
        if edge["from"] not in available_keys or edge["to"] not in available_keys:
            fact_skipped += 1
            continue
        result = upsert_fact_edge(
            graph,
            from_stable_key=edge["from"],
            to_stable_key=edge["to"],
            relation=edge["relation"],
            predicate=edge["predicate"],
            fact_text=edge["fact_text"],
            timestamp=edge["timestamp"],
            origin="restore",
        )
        if result == "created":
            fact_created += 1
        elif result == "updated":
            fact_updated += 1
        else:
            fact_skipped += 1

    structural_upserted = 0
    structural_skipped = 0
    for edge in structural_edges:
        if edge["from"] not in available_keys or edge["to"] not in available_keys:
            structural_skipped += 1
            continue
        upsert_structural_edge(
            graph,
            from_stable_key=edge["from"],
            to_stable_key=edge["to"],
            relation=edge["relation"],
            timestamp=edge["timestamp"],
            origin="restore",
        )
        structural_upserted += 1

    invalidate_graph_caches(graph)
    report["counts"].update({
        "created_items": created_items,
        "updated_items": updated_items,
        "replaced_items": len(existing_keys) if replace else 0,
        "created_relations": fact_created,
        "updated_relations": fact_updated,
        "skipped_relations": fact_skipped,
        "upserted_structural_edges": structural_upserted,
        "skipped_structural_edges": structural_skipped,
    })
    report["workflow"] = {
        "status": "ok",
        "complete": True,
        "next_step": "verify_restore",
        "message": "Restore completed. Run consult/item checks for restored facts before relying on them.",
    }
    return report


def cmd_restore(args: argparse.Namespace) -> None:
    if bool(getattr(args, "replace", False)) and not bool(getattr(args, "dry_run", False)) and not bool(getattr(args, "yes", False)):
        fail("restore --replace is destructive for matching keys and requires --yes unless --dry-run is used", 2)
    _tool, workspace, _config, graph = open_workspace_graph(args)
    ensure_runtime_indexes(graph)
    input_path = str(getattr(args, "input", "") or "").strip()
    payload = load_restore_json(input_path)
    report = restore_memory_payload(
        graph,
        workspace=workspace,
        input_path=input_path,
        payload=payload,
        dry_run=bool(getattr(args, "dry_run", False)),
        replace=bool(getattr(args, "replace", False)),
        include_operational=bool(getattr(args, "include_operational", False)),
    )
    print(json.dumps(report, indent=2))


def latest_backup_status() -> dict[str, Any]:
    backup_dir = APP_SUPPORT_DIR_DEFAULT / "Backups"
    if not backup_dir.exists():
        return {"directory": str(backup_dir), "latest": None, "count": 0}
    backups = sorted(backup_dir.glob("autopsy-memory-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not backups:
        return {"directory": str(backup_dir), "latest": None, "count": 0}
    latest = backups[0]
    age_seconds = max(0, int(time.time() - latest.stat().st_mtime))
    return {
        "directory": str(backup_dir),
        "latest": str(latest),
        "count": len(backups),
        "age_seconds": age_seconds,
        "age_hours": round(age_seconds / 3600.0, 2),
        "bytes": latest.stat().st_size,
    }


def build_health_payload(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    tool, workspace, config, graph = open_workspace_graph(args)
    ensure_runtime_indexes(graph)
    stats = build_graph_stats_payload(graph)
    vector_count = int(scalar_query(graph, "MATCH (node:SemanticItem) WHERE node.embedding IS NOT NULL RETURN count(node)") or 0)
    index_ok = check_runtime_index_probe(graph)
    checks = [
        python_version_check(),
        installed_autopsy_command_check(),
        import_check("falkordb", required=True),
        import_check("redis", required=True),
        import_check("redislite.falkordb_client", required=True),
        import_check("sentence_transformers", required=False),
    ]
    required_ok = all(check["ok"] for check in checks if check["required"])
    repo_hint = repository_path_from_args(args) or str(Path.cwd().resolve())
    targets = instruction_targets(
        home=Path.home(),
        repo_path=Path(repo_hint).expanduser().resolve(),
        install_global=True,
        agent="all",
    )
    init_targets = [target_status(target) for target in targets]
    managed_targets = sum(1 for target in init_targets if target.get("state") == "managed")
    backup = latest_backup_status()
    latest_backup_age = backup.get("age_seconds")
    backup_fresh = latest_backup_age is not None and int(latest_backup_age) <= 7 * 24 * 60 * 60
    graph_ok = scalar_query(graph, "MATCH (node) RETURN count(node) LIMIT 1") is not None and index_ok
    ok = required_ok and graph_ok
    return {
        "ok": ok,
        "workspace": tool.workspace_payload(workspace),
        "graph_name": graph.name,
        "backend": "falkor",
        "mode": "native",
        "counts": {
            "entities": int(stats.get("entityCount") or 0),
            "items": int(stats.get("itemCount") or 0),
            "edges": int(stats.get("edgeCount") or 0),
            "vectors": vector_count,
        },
        "stats": stats,
        "checks": {
            "runtime": checks,
            "required_runtime_ok": required_ok,
            "indexes_ready": index_ok,
            "graph_ready": graph_ok,
            "embeddings_configured": bool(config.get("enabled", True)),
            "reranker_configured": bool(reranker_config(config).get("enabled", False)),
            "init_managed_targets": managed_targets,
            "init_target_count": len(init_targets),
            "backup_fresh": backup_fresh,
        },
        "init_targets": init_targets,
        "backup": backup,
        "paths": {
            "app_support_dir": str(APP_SUPPORT_DIR_DEFAULT),
            "falkordb_lite_path": str(resolved_lite_path(args) or ""),
            "memory_settings": str(GLOBAL_MEMORY_SETTINGS_DEFAULT),
            "unified_memory_root": str(unified_memory_root_path()),
        },
        "workflow": {
            "status": "ok" if ok else "needs_attention",
            "complete": ok,
            "next_step": "done" if ok else "inspect_failed_checks",
            "message": "Autopsy memory health checks passed." if ok else "Autopsy memory health found required checks that need attention.",
        },
        "timings": {"health_s": round(time.perf_counter() - started, 3)},
    }


def cmd_health(args: argparse.Namespace) -> None:
    try:
        payload = build_health_payload(args)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "backend": "falkor",
            "mode": "native",
            "error": str(exc),
            "workflow": {
                "status": "error",
                "complete": False,
                "next_step": "fix_falkor_runtime",
                "message": "Falkor health check failed before graph inspection completed.",
            },
        }, indent=2))
        raise SystemExit(1)
    print(json.dumps(payload, indent=2))
    if not payload.get("ok"):
        raise SystemExit(1)


def cmd_doctor(args: argparse.Namespace) -> None:
    checks = [
        python_version_check(),
        installed_autopsy_command_check(),
        import_check("falkordb", required=True),
        import_check("redis", required=True),
        import_check("redislite.falkordb_client", required=True),
        import_check("sentence_transformers", required=False),
    ]
    required_ok = all(check["ok"] for check in checks if check["required"])
    payload = {
        "ok": required_ok,
        "checks": checks,
        "paths": {
            "app_support_dir": str(APP_SUPPORT_DIR_DEFAULT),
            "falkordb_lite_path": str(resolved_lite_path(args) or ""),
            "memory_settings": str(GLOBAL_MEMORY_SETTINGS_DEFAULT),
            "unified_memory_root": str(unified_memory_root_path()),
        },
        "environment": {
            "AUTOPSY_APP_SUPPORT_DIR": os.environ.get("AUTOPSY_APP_SUPPORT_DIR"),
            "AUTOPSY_FALKORDB_HOST": os.environ.get("AUTOPSY_FALKORDB_HOST"),
            "AUTOPSY_FALKORDB_PORT": os.environ.get("AUTOPSY_FALKORDB_PORT"),
            "AUTOPSY_FALKORDB_LITE_PATH": os.environ.get("AUTOPSY_FALKORDB_LITE_PATH"),
            "AUTOPSY_UNIFIED_MEMORY": os.environ.get("AUTOPSY_UNIFIED_MEMORY"),
            "AUTOPSY_UNIFIED_MEMORY_ROOT": os.environ.get("AUTOPSY_UNIFIED_MEMORY_ROOT"),
        },
    }
    print(json.dumps(payload, indent=2))
    if not required_ok:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    return build_cli_parser(
        CommandHandlers(
            version=cmd_version,
            instructions=cmd_instructions,
            init=cmd_init,
            doctor=cmd_doctor,
            sync=cmd_sync,
            status=cmd_status,
            consult=cmd_consult,
            search=cmd_search,
            benchmark=cmd_benchmark,
            export=cmd_export,
            backup=cmd_backup,
            restore=cmd_restore,
            health=cmd_health,
            create_note=cmd_create_note,
            update_item=cmd_update_item,
            delete_item=cmd_delete_item,
            item=cmd_item,
            neighbors=cmd_neighbors,
            timeline=cmd_timeline,
            snapshot=cmd_snapshot,
        ),
        falkordb_lite_path_default=FALKORDB_LITE_PATH_DEFAULT,
        status_window_days_default=STATUS_WINDOW_DAYS_DEFAULT,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args(normalized_cli_args(sys.argv[1:]))
    args.func(args)


if __name__ == "__main__":
    main()
