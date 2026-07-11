#!/usr/bin/env python3
import argparse
import contextlib
import copy
import hashlib
import importlib
import importlib.util
import io
import json
import os
import re
import shlex
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_EMBEDDING_MODEL_CACHE = {}
_RERANKER_MODEL_CACHE = {}
_TOOL_MODULE_CACHE = {}
_TOOL_MODULE_LOCK = threading.Lock()
_EMBEDDINGS_CONFIG_CACHE = {}
_EMBEDDINGS_STATUS_CACHE = {}
_FALKOR_CONTEXT_CACHE = {}
_FALKOR_FAILURE_CACHE = {}
_FALKOR_CONTEXT_LOCK = threading.Lock()
_FALKOR_VALIDATION_TTL_SECONDS = 10.0
_FALKOR_FAILURE_TTL_SECONDS = 30.0
_WORKER_DEFAULT_IDLE_TIMEOUT_SECONDS = 3600.0
_WORKER_DEFAULT_OWNERSHIP_CHECK_SECONDS = 5.0
DIRECT_RETRIEVAL_REASONS = {'lexical', 'exact', 'token_overlap', 'entity_overlap', 'graph_relation'}

APP_SUPPORT_DIR_DEFAULT = Path(os.environ.get('AUTOPSY_APP_SUPPORT_DIR') or Path.home() / 'Library' / 'Application Support' / 'Autopsy')
FALKORDB_LITE_PATH_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'FalkorDB' / 'autopsy-memory.db'
GLOBAL_MEMORY_SETTINGS_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'Config' / 'memory-settings.json'
UNIFIED_MEMORY_ROOT_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'MemoryRoot'
STATUS_WINDOW_DAYS_DEFAULT = 21
EMBEDDINGS_CONFIG_DEFAULT = {
    'enabled': True,
    'provider': 'sentence_transformers',
    'model': 'BAAI/bge-base-en-v1.5',
    'model_revision': 'a5beb1e3e68b9ab74eb54cfd186867f64f240e1a',
    'device': 'cpu',
    'dimension': 768,
    'similarity_function': 'cosine',
    'on_write': True,
    'write_failure_policy': 'defer',
    'text_template_version': 'autopsy-passage-v1',
    'batch_size': 16,
    'candidate_limit': 48,
    'fulltext_candidate_limit': 1000,
    'reranker': {
        'enabled': True,
        'provider': 'sentence_transformers',
        'model': 'BAAI/bge-reranker-base',
        'model_revision': '2cfc18c9415c912f9d8155881c133215df768a70',
        'device': 'cpu',
        'batch_size': 8,
            'candidate_limit': 24,
            'min_score': 0.05,
            'embedding_min_score': 0.62,
            'semantic_only_min_score': 0.12,
        },
    }


def workflow_step(name: str, reason: str, command: str | None = None) -> dict:
    payload = {'name': name, 'reason': reason}
    if command:
        payload['command'] = command
    return payload


def cli_quote(value) -> str:
    return shlex.quote(str(value))


def normalize_workspace_slug(value: str | None) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')


def unified_memory_enabled() -> bool:
    raw_value = os.environ.get('AUTOPSY_UNIFIED_MEMORY')
    if raw_value is None or str(raw_value).strip() == '':
        return True
    value = str(raw_value).strip().lower()
    return value not in {'', '0', 'false', 'no', 'off'}


def unified_memory_root_path() -> str:
    raw = str(os.environ.get('AUTOPSY_UNIFIED_MEMORY_ROOT') or '').strip()
    if not raw:
        raw = str(UNIFIED_MEMORY_ROOT_DEFAULT)
    return os.path.realpath(os.path.expanduser(raw))


def resolve_workspace_reference(selector: str | None, cwd: str) -> dict:
    if unified_memory_enabled():
        root_path = unified_memory_root_path()
        title = Path(root_path).name or 'Autopsy Memory'
        slug = normalize_workspace_slug(title) or 'autopsy-memory'
        return {
            'id': root_path,
            'workspace_key': root_path,
            'slug': slug,
            'title': title,
            'root_path': root_path,
        }

    root_path = os.path.realpath(os.path.expanduser(selector or cwd))
    title = Path(root_path).name or 'workspace'
    slug = normalize_workspace_slug(title) or 'workspace'
    return {
        'id': root_path,
        'workspace_key': root_path,
        'slug': slug,
        'title': title,
        'root_path': root_path,
    }


def workspace_payload(workspace: dict) -> dict:
    return {
        'id': workspace.get('id'),
        'workspace_key': workspace.get('workspace_key'),
        'slug': workspace.get('slug'),
        'title': workspace.get('title'),
        'root_path': workspace.get('root_path'),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')



def build_read_workflow(
    workspace_root: str,
    *,
    command: str,
    query: str | None = None,
    thread_id: str | None = None,
    hits: list[dict] | None = None,
    inspected_items: list[dict] | None = None,
    current_only: bool = False,
    as_of: str | None = None,
) -> dict:
    hits = hits or []
    inspected_items = inspected_items or []
    first_hit_key = next((item.get('stable_key') for item in inspected_items if item.get('stable_key')), None)
    current_clause = ' --current-only' if current_only else ''
    as_of_clause = f' --as-of {as_of}' if as_of else ''
    if not hits:
        suggested = []
        if query and command != 'consult':
            suggested.append(workflow_step(
                'fallback-search',
                'No strong memory hits were found. Fall back to keyword search before assuming no prior context exists.',
                f'autopsy search {cli_quote(query)}{current_clause}{as_of_clause}',
            ))
        if thread_id:
            suggested.append(workflow_step(
                'inspect-thread-neighbors',
                'Check thread-scoped semantic memory before concluding there is no relevant prior context.',
                f'autopsy neighbors --thread-id {cli_quote(thread_id)}{current_clause}{as_of_clause}',
            ))
        return {
            'status': 'empty',
            'coverage': 'none',
            'complete': False,
            'next_step': 'fallback' if suggested else 'conclude',
            'message': 'No graph memory hits were found for this read.' if command != 'consult' else 'No graph memory hits were found after relaxed retrieval.',
            'suggested_next_steps': suggested,
        }

    if inspected_items:
        suggested = []
        if first_hit_key:
            suggested.append(workflow_step(
                'inspect-lineage',
                'If the retrieved memory may have changed over time, inspect its timeline before relying on it.',
                f'autopsy timeline {cli_quote(first_hit_key)}',
            ))
            suggested.append(workflow_step(
                'inspect-neighbors',
                'Use neighbors when the answer depends on nearby related facts or state transitions.',
                f'autopsy neighbors --stable-key {cli_quote(first_hit_key)}',
            ))
        return {
            'status': 'ok',
            'coverage': 'strong',
            'complete': True,
            'next_step': 'done',
            'message': 'High-signal memory was retrieved and inspected.',
            'suggested_next_steps': suggested,
        }

    suggested = []
    if first_hit_key:
        suggested.append(workflow_step(
            'inspect-item',
            'Hits were found, but no item details were inspected yet.',
            f'autopsy item {cli_quote(first_hit_key)}',
        ))
    return {
        'status': 'weak',
        'coverage': 'partial',
        'complete': False,
        'next_step': 'inspect',
        'message': 'Memory hits were found, but they should be inspected before they are relied on.',
        'suggested_next_steps': suggested,
    }


def load_global_memory_settings() -> dict:
    if GLOBAL_MEMORY_SETTINGS_DEFAULT.exists() is False:
        return {}
    try:
        raw = json.loads(GLOBAL_MEMORY_SETTINGS_DEFAULT.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def load_embeddings_config(root_dir: Path) -> dict:
    config_path = root_dir / 'memory' / 'config' / 'autopsy_embeddings.json'
    config = copy.deepcopy(EMBEDDINGS_CONFIG_DEFAULT)
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding='utf-8'))
        if isinstance(raw, dict):
            reranker_raw = raw.get('reranker')
            if isinstance(reranker_raw, dict):
                config['reranker'].update(reranker_raw)
            for key, value in raw.items():
                if key == 'reranker':
                    continue
                config[key] = value
    settings = load_global_memory_settings()
    memory = settings.get('memory') if isinstance(settings, dict) else None
    reranker = memory.get('reranker') if isinstance(memory, dict) else None
    if isinstance(reranker, dict) and 'enabled' in reranker:
        config.setdefault('reranker', {})
        config['reranker']['enabled'] = bool(reranker.get('enabled'))
    return config


def _path_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except Exception:
        return 0


def load_embeddings_config_cached(root_dir: Path) -> dict:
    resolved_root = root_dir.expanduser().resolve()
    config_path = resolved_root / 'memory' / 'config' / 'autopsy_embeddings.json'
    key = (
        str(resolved_root),
        _path_mtime_ns(config_path),
        _path_mtime_ns(GLOBAL_MEMORY_SETTINGS_DEFAULT),
    )
    cached = _EMBEDDINGS_CONFIG_CACHE.get(key)
    if cached is not None:
        return copy.deepcopy(cached)
    config = load_embeddings_config(resolved_root)
    _EMBEDDINGS_CONFIG_CACHE.clear()
    _EMBEDDINGS_CONFIG_CACHE[key] = copy.deepcopy(config)
    return config


def sentence_transformers_available() -> tuple[bool, str | None]:
    try:
        importlib.invalidate_caches()
        __import__('sentence_transformers')
    except Exception as exc:
        return (False, f'sentence-transformers unavailable: {exc}')
    return (True, None)


def embedding_provider_available(config: dict) -> tuple[bool, str | None]:
    provider = str(config.get('provider') or '').strip().lower()
    if not config.get('enabled', True):
        return (False, 'disabled')
    if provider != 'sentence_transformers':
        return (False, f'unsupported provider: {provider}')
    return sentence_transformers_available()


def reranker_config(config: dict | None) -> dict:
    if not isinstance(config, dict):
        return {}
    payload = config.get('reranker')
    return payload if isinstance(payload, dict) else {}


def reranker_provider_available(config: dict | None) -> tuple[bool, str | None]:
    reranker = reranker_config(config)
    if not reranker.get('enabled', False):
        return (False, 'disabled')
    provider = str(reranker.get('provider') or '').strip().lower()
    if provider != 'sentence_transformers':
        return (False, f'unsupported provider: {provider}')
    return sentence_transformers_available()


def embed_texts_with_provider(texts: list[str], config: dict) -> list[list[float]]:
    provider = str(config.get('provider') or '').strip().lower()
    model_name = str(config.get('model') or '').strip()
    if provider != 'sentence_transformers':
        raise RuntimeError(f'Unsupported embeddings provider: {provider}')
    if not model_name:
        raise RuntimeError('Embeddings config missing model')
    model = load_sentence_transformer(
        model_name,
        str(config.get('device') or 'cpu'),
        str(config.get('model_revision') or ''),
    )
    batch_size = max(1, int(config.get('batch_size', 16)))
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return [vector.tolist() for vector in vectors]


def rerank_candidates(query: str, candidates: list[dict], config: dict | None) -> list[dict]:
    reranker = reranker_config(config)
    if not candidates:
        return []
    available, _ = reranker_provider_available(config)
    if not available:
        return candidates
    provider = str(reranker.get('provider') or '').strip().lower()
    model_name = str(reranker.get('model') or '').strip()
    if provider != 'sentence_transformers' or not model_name:
        return candidates
    candidate_limit = max(1, int(reranker.get('candidate_limit', 24)))
    shortlist = candidates[:candidate_limit]
    shortlist_texts = [
        '\n'.join(
            part.strip()
            for part in (
                str(item.get('title') or item.get('entity_label') or ''),
                str(item.get('preview') or item.get('entity_summary') or ''),
                str(item.get('fact_text') or ''),
            )
            if part and part.strip()
        )
        for item in shortlist
    ]
    model = load_cross_encoder(
        model_name,
        str(reranker.get('device') or 'cpu'),
        str(reranker.get('model_revision') or ''),
    )
    scores = model.predict(
        [[query, text] for text in shortlist_texts],
        batch_size=max(1, int(reranker.get('batch_size', 8))),
        show_progress_bar=False,
    )
    normalized_shortlist = []
    for item, score in zip(shortlist, scores):
        normalized = dict(item)
        normalized['reranker_score'] = round(float(score), 8)
        reasons = set(normalized.get('retrieval_reasons', []))
        reasons.add('reranker')
        normalized['retrieval_reasons'] = sorted(reasons)
        normalized_shortlist.append(normalized)
    ranked_shortlist = sort_candidates(normalized_shortlist)
    if len(candidates) <= candidate_limit:
        return ranked_shortlist
    return sort_candidates(ranked_shortlist + candidates[candidate_limit:])


def candidate_final_score(item: dict) -> float:
    score = 0.0
    if item.get('reranker_score') is not None:
        score += float(item.get('reranker_score') or 0.0) * 100.0
    score += float(item.get('lexical_rank_score') or 0.0)
    score += float(item.get('exact_match_boost') or 0.0)
    score += float(item.get('token_overlap_score') or 0.0) * 2.0
    score += float(item.get('entity_overlap_score') or 0.0) * 3.0
    score += float(item.get('relationship_score') or 0.0) * 1.5
    score += float(item.get('lexical_score') or 0.0)
    score += float(item.get('embedding_score') or 0.0) * 10.0
    score += float(item.get('usage_rank_score') or 0.0)
    score += float(item.get('query_penalty') or 0.0)
    return score


def sort_candidates(items: list[dict]) -> list[dict]:
    return sorted(
        items,
        key=lambda item: (
            -candidate_final_score(item),
            item.get('stable_key') or '',
            item.get('rank', 1_000_000),
        ),
    )


def filter_low_relevance_candidates(query: str, candidates: list[dict], config: dict | None) -> list[dict]:
    if not candidates:
        return []
    reranker = reranker_config(config)
    min_score = float(reranker.get('min_score', 0.05))
    embedding_min_score = float(reranker.get('embedding_min_score', 0.62))
    semantic_only_min_score = max(min_score, float(reranker.get('semantic_only_min_score', 0.12)))
    reranker_observed = any(
        'reranker_score' in item or 'reranker' in set(item.get('retrieval_reasons', []))
        for item in candidates
    )
    filtered = []
    for item in candidates:
        reasons = set(item.get('retrieval_reasons', []))
        if DIRECT_RETRIEVAL_REASONS & reasons:
            filtered.append(item)
            continue
        reranker_score = item.get('reranker_score')
        if reranker_score is not None:
            if float(reranker_score) >= semantic_only_min_score:
                filtered.append(item)
            continue
        if reranker_observed:
            continue
        embedding_score = item.get('embedding_score')
        if embedding_score is None or float(embedding_score) < embedding_min_score:
            continue
        filtered.append(item)
    return filtered


class FalkorToolShim:
    STATUS_WINDOW_DAYS_DEFAULT = STATUS_WINDOW_DAYS_DEFAULT
    workflow_step = staticmethod(workflow_step)
    workspace_payload = staticmethod(workspace_payload)
    build_read_workflow = staticmethod(build_read_workflow)
    embedding_provider_available = staticmethod(embedding_provider_available)
    embed_texts_with_provider = staticmethod(embed_texts_with_provider)
    rerank_candidates = staticmethod(rerank_candidates)
    filter_low_relevance_candidates = staticmethod(filter_low_relevance_candidates)


def load_falkor_module(tool_path: str):
    raw_path = os.path.realpath(os.path.expanduser(tool_path))
    candidates = [raw_path]
    if os.path.isdir(raw_path):
        candidates = [
            os.path.join(raw_path, "cli.py"),
            os.path.join(raw_path, "falkordb_memory_prototype.py"),
        ]
    elif os.path.basename(raw_path) != "falkordb_memory_prototype.py":
        candidates.append(os.path.join(os.path.dirname(raw_path), "falkordb_memory_prototype.py"))
    resolved = next((candidate for candidate in candidates if os.path.exists(candidate)), candidates[0])
    with _TOOL_MODULE_LOCK:
        module = _TOOL_MODULE_CACHE.get(resolved)
        if module is not None:
            return module
        resolved_path = Path(resolved)
        if resolved_path.name == "cli.py" and resolved_path.parent.name == "autopsy_memory":
            package_root = str(resolved_path.parent.parent)
            if package_root not in sys.path:
                sys.path.insert(0, package_root)
            module = importlib.import_module("autopsy_memory.cli")
            _TOOL_MODULE_CACHE[resolved] = module
            return module
        spec = importlib.util.spec_from_file_location("autopsy_falkordb_memory_module", resolved)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load Falkor memory tool from {resolved}")
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("autopsy_falkordb_memory_module", module)
        spec.loader.exec_module(module)
        _TOOL_MODULE_CACHE[resolved] = module
        return module


def load_sentence_transformer(model_name: str, device: str, revision: str = ''):
    key = (model_name, revision, device)
    model = _EMBEDDING_MODEL_CACHE.get(key)
    if model is None:
        from sentence_transformers import SentenceTransformer
        kwargs = {'device': device}
        if revision:
            kwargs['revision'] = revision
        model = SentenceTransformer(model_name, **kwargs)
        _EMBEDDING_MODEL_CACHE[key] = model
    return model


def load_cross_encoder(model_name: str, device: str, revision: str = ''):
    key = (model_name, revision, device)
    model = _RERANKER_MODEL_CACHE.get(key)
    if model is None:
        from sentence_transformers import CrossEncoder
        kwargs = {'device': device}
        if revision:
            kwargs['revision'] = revision
        model = CrossEncoder(model_name, **kwargs)
        _RERANKER_MODEL_CACHE[key] = model
    return model


def env_float(name: str, default: float) -> float:
    raw_value = str(os.environ.get(name) or '').strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def worker_idle_timeout_seconds() -> float:
    return max(0.0, env_float('AUTOPSY_WORKER_IDLE_TIMEOUT_SECONDS', _WORKER_DEFAULT_IDLE_TIMEOUT_SECONDS))


def worker_ownership_check_seconds() -> float:
    return max(0.25, env_float('AUTOPSY_WORKER_OWNERSHIP_CHECK_SECONDS', _WORKER_DEFAULT_OWNERSHIP_CHECK_SECONDS))


def worker_info_owns_process(info: dict | None, *, token: str, source_fingerprint: str) -> bool:
    if not isinstance(info, dict):
        return False
    try:
        pid = int(info.get('pid'))
    except Exception:
        return False
    return (
        pid == os.getpid()
        and str(info.get('token') or '') == token
        and str(info.get('source_fingerprint') or '') == source_fingerprint
    )


def read_worker_info_file(path: str) -> dict | None:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def info_file_still_owned(path: str, *, token: str, source_fingerprint: str) -> bool:
    return worker_info_owns_process(read_worker_info_file(path), token=token, source_fingerprint=source_fingerprint)


def shutdown_falkor_contexts() -> None:
    with _FALKOR_CONTEXT_LOCK:
        contexts = list(_FALKOR_CONTEXT_CACHE.values())
        _FALKOR_CONTEXT_CACHE.clear()
    for falkor in contexts:
        reset_lite_client = getattr(falkor.get('module'), 'reset_falkordb_lite_client', None)
        if callable(reset_lite_client):
            try:
                reset_lite_client(falkor.get('lite_path'))
            except Exception:
                pass


def remove_owned_info_file(path: str, *, token: str, source_fingerprint: str) -> None:
    if not info_file_still_owned(path, token=token, source_fingerprint=source_fingerprint):
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def worker_should_exit(server, *, info_file: str, token: str, source_fingerprint: str) -> tuple[bool, str]:
    if not info_file_still_owned(info_file, token=token, source_fingerprint=source_fingerprint):
        return True, 'info_file_replaced'
    idle_timeout = float(getattr(server, 'idle_timeout_seconds', 0.0) or 0.0)
    if idle_timeout > 0:
        idle_for = time.monotonic() - float(getattr(server, 'last_request_at', 0.0) or 0.0)
        if idle_for >= idle_timeout:
            return True, 'idle_timeout'
    return False, ''


def worker_lifecycle_monitor(server, *, info_file: str, token: str, source_fingerprint: str) -> None:
    interval = float(getattr(server, 'ownership_check_seconds', _WORKER_DEFAULT_OWNERSHIP_CHECK_SECONDS) or _WORKER_DEFAULT_OWNERSHIP_CHECK_SECONDS)
    while not bool(getattr(server, 'shutdown_requested', False)):
        time.sleep(interval)
        should_exit, reason = worker_should_exit(server, info_file=info_file, token=token, source_fingerprint=source_fingerprint)
        if not should_exit:
            continue
        request_worker_shutdown(server, reason)
        return


def force_exit_if_still_running(server, delay_seconds: float = 5.0) -> None:
    time.sleep(delay_seconds)
    if bool(getattr(server, 'shutdown_requested', False)):
        os._exit(0)


def request_worker_shutdown(server, reason: str) -> None:
    if bool(getattr(server, 'shutdown_requested', False)):
        return
    server.shutdown_reason = reason
    server.shutdown_requested = True
    print(f'autopsy worker exiting: {reason}', file=sys.stderr, flush=True)
    threading.Thread(target=force_exit_if_still_running, args=(server,), daemon=True).start()
    threading.Thread(target=server.shutdown, daemon=True).start()


def install_worker_signal_handlers(server) -> None:
    def handle_signal(signum, _frame):
        request_worker_shutdown(server, f'signal_{signum}')

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(signum, handle_signal)
        except Exception:
            pass


def start_worker_lifecycle_monitor(server, *, info_file: str, token: str, source_fingerprint: str) -> threading.Thread:
    thread = threading.Thread(
        target=worker_lifecycle_monitor,
        kwargs={'server': server, 'info_file': info_file, 'token': token, 'source_fingerprint': source_fingerprint},
        daemon=True,
    )
    thread.start()
    return thread


def falkor_backend_settings() -> dict | None:
    backend = str(os.environ.get('AUTOPSY_MEMORY_BACKEND') or '').strip().lower()
    enabled_flag = str(os.environ.get('AUTOPSY_FALKORDB_ENABLED') or '').strip().lower()
    enabled = backend in {'', 'falkordb'} or enabled_flag in {'1', 'true', 'yes', 'on'}
    if not enabled:
        raise RuntimeError('FalkorDB memory backend is required')
    env_host = str(os.environ.get('AUTOPSY_FALKORDB_HOST') or '').strip()
    env_port = str(os.environ.get('AUTOPSY_FALKORDB_PORT') or '').strip()
    lite_path = str(os.environ.get('AUTOPSY_FALKORDB_LITE_PATH') or '').strip()
    if not lite_path and not env_host and not env_port:
        lite_path = str(FALKORDB_LITE_PATH_DEFAULT)
    settings = {
        'host': env_host or '127.0.0.1',
        'port': int(env_port or '6381'),
        'graph_name': str(os.environ.get('AUTOPSY_FALKORDB_GRAPH_NAME') or 'autopsy_memory'),
    }
    if lite_path and not env_host and not env_port:
        settings['lite_path'] = os.path.realpath(os.path.expanduser(lite_path))
    return settings


def falkor_embeddings_status(config: dict) -> dict:
    embeddings_available, embeddings_error = embedding_provider_available(config)
    reranker_available, reranker_error = reranker_provider_available(config)
    return {
        'enabled': bool(config.get('enabled', True)),
        'provider': config.get('provider'),
        'model': config.get('model'),
        'available': embeddings_available,
        'error': embeddings_error,
        'worker': {
            'available': True,
            'base_url': None,
            'pid': os.getpid(),
        },
        'reranker': {
            'enabled': bool(reranker_config(config).get('enabled', False)),
            'provider': reranker_config(config).get('provider'),
            'model': reranker_config(config).get('model'),
            'available': reranker_available,
            'error': reranker_error,
        },
    }


def falkor_embeddings_status_cached(config: dict) -> dict:
    key = json.dumps(config, sort_keys=True)
    cached = _EMBEDDINGS_STATUS_CACHE.get(key)
    if cached is not None:
        return copy.deepcopy(cached)
    status = falkor_embeddings_status(config)
    if not embeddings_status_has_transient_import_error(status):
        _EMBEDDINGS_STATUS_CACHE[key] = copy.deepcopy(status)
    return status


def embeddings_status_has_transient_import_error(status: dict) -> bool:
    error = str(status.get('error') or '')
    reranker = status.get('reranker') if isinstance(status.get('reranker'), dict) else {}
    reranker_error = str(reranker.get('error') or '')
    return (
        error.startswith('sentence-transformers unavailable:')
        or reranker_error.startswith('sentence-transformers unavailable:')
    )


def load_falkor_request_context(payload: dict, *, include_embeddings_status: bool = True):
    settings = falkor_backend_settings()
    if settings is None:
        return None
    tool_path = str(payload.get('tool_path') or '').strip()
    if not tool_path:
        raise ValueError('missing tool_path')
    workspace = resolve_workspace_reference(
        str(payload.get('workspace') or '').strip() or None,
        str(payload.get('cwd') or os.getcwd()),
    )
    embeddings_config = load_embeddings_config_cached(Path(str(workspace.get('root_path') or '')))
    embeddings_status = falkor_embeddings_status_cached(embeddings_config) if include_embeddings_status else None
    module = load_falkor_module(tool_path)
    falkor = maybe_load_falkor_context(payload, workspace, module, embeddings_config)
    if falkor is None:
        raise RuntimeError('FalkorDB backend is not enabled')
    return FalkorToolShim, module, workspace, embeddings_config, embeddings_status, falkor


def falkor_failure_cache_key(payload: dict):
    settings = falkor_backend_settings()
    tool_path = str(payload.get('tool_path') or '').strip()
    if not tool_path:
        return None
    workspace = resolve_workspace_reference(
        str(payload.get('workspace') or '').strip() or None,
        str(payload.get('cwd') or os.getcwd()),
    )
    return (
        os.path.realpath(tool_path),
        settings['host'],
        settings['port'],
        settings.get('lite_path') or '',
        settings['graph_name'],
        str(workspace.get('root_path') or ''),
    )


def try_load_falkor_context(payload: dict, *, include_embeddings_status: bool = True):
    cache_key = falkor_failure_cache_key(payload)
    if cache_key is not None:
        with _FALKOR_CONTEXT_LOCK:
            failure = _FALKOR_FAILURE_CACHE.get(cache_key)
            if failure is not None and time.monotonic() - float(failure.get('failed_at') or 0.0) < _FALKOR_FAILURE_TTL_SECONDS:
                return None
    try:
        context = load_falkor_request_context(payload, include_embeddings_status=include_embeddings_status)
        if cache_key is not None:
            with _FALKOR_CONTEXT_LOCK:
                _FALKOR_FAILURE_CACHE.pop(cache_key, None)
        return context
    except Exception as exc:
        if cache_key is not None:
            with _FALKOR_CONTEXT_LOCK:
                _FALKOR_FAILURE_CACHE[cache_key] = {
                    'failed_at': time.monotonic(),
                    'error': str(exc),
                }
        raise


def maybe_load_falkor_context(payload: dict, workspace: dict, module, embeddings_config: dict):
    settings = falkor_backend_settings()
    tool_path = str(payload.get('tool_path') or '').strip()
    if not tool_path:
        return None
    graph_name = module.workspace_graph_name(settings['graph_name'], workspace)
    cache_key = (
        os.path.realpath(tool_path),
        settings['host'],
        settings['port'],
        settings.get('lite_path') or '',
        graph_name,
    )
    with _FALKOR_CONTEXT_LOCK:
        cached = _FALKOR_CONTEXT_CACHE.get(cache_key)
        now = time.monotonic()
        if cached is not None:
            validated_at = float(cached.get('validated_at') or 0.0)
            if now - validated_at < _FALKOR_VALIDATION_TTL_SECONDS:
                return cached
        try:
            graph, resolved_graph_name = module.ensure_workspace_graph(
                workspace=workspace,
                host=settings['host'],
                port=settings['port'],
                graph_name_base=settings['graph_name'],
                lite_path=settings.get('lite_path'),
            )
            module.sync_workspace_payload(graph, workspace=workspace)
            module.ensure_runtime_indexes(graph, embeddings_config)
        except Exception as exc:
            if worker_memory_database_rollback_error(exc):
                reset_falkor_lite_client(module, settings.get('lite_path'))
            raise
        cached = {
            'module': module,
            'graph_name': resolved_graph_name,
            'host': settings['host'],
            'port': settings['port'],
            'lite_path': settings.get('lite_path'),
            'validated_at': now,
        }
        _FALKOR_CONTEXT_CACHE[cache_key] = cached
        return cached


def worker_memory_database_rollback_error(error: Exception | str) -> bool:
    return (
        error.__class__.__name__ == 'MemoryDatabaseRollbackError'
        or 'Autopsy memory database rollback detected' in str(error)
    )


def reset_falkor_lite_client(module, lite_path: str | None) -> None:
    if not lite_path:
        return
    reset_lite_client = getattr(module, 'reset_falkordb_lite_client', None)
    if callable(reset_lite_client):
        reset_lite_client(lite_path)


def run_falkor_operation(falkor: dict, operation):
    try:
        graph = falkor['module'].ensure_graph(
            falkor['host'],
            falkor['port'],
            falkor['graph_name'],
            lite_path=falkor.get('lite_path'),
        )
    except Exception as exc:
        if worker_memory_database_rollback_error(exc):
            reset_falkor_lite_client(falkor['module'], falkor.get('lite_path'))
        raise
    try:
        return operation(graph)
    except Exception as exc:
        reset_falkor_lite_client(falkor['module'], falkor.get('lite_path'))
        if worker_memory_database_rollback_error(exc):
            raise
        graph = falkor['module'].ensure_graph(
            falkor['host'],
            falkor['port'],
            falkor['graph_name'],
            lite_path=falkor.get('lite_path'),
        )
        return operation(graph)


def int_request_argument(request: dict, name: str, default: int) -> int:
    value = request.get(name)
    if value is None or value == '':
        return default
    return int(value)


def list_request_argument(request: dict, name: str) -> list:
    value = request.get(name)
    if value is None or value == '':
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def metadata_request_argument(request: dict):
    if 'metadata' not in request:
        return []
    value = request.get('metadata')
    if value is None or value == '':
        return []
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def filter_json_request_argument(request: dict):
    if 'filter_json' in request:
        value = request.get('filter_json')
    elif 'filter' in request:
        value = request.get('filter')
    else:
        return None
    if value is None or value == '':
        return None
    return value


def consult_via_falkor(tool, workspace, embeddings_config, embeddings_status, falkor, request: dict):
    module = falkor['module']
    scope = str(request.get('scope') or 'system')
    repository_root_path = str(request.get('repository_root_path') or request.get('repo') or '')
    if scope == 'repo' and not repository_root_path:
        repository_root_path = str(workspace.get('root_path') or os.getcwd())
    response = run_falkor_operation(
        falkor,
        lambda graph: module.build_consult_payload(
            graph,
            tool=tool,
            conn=None,
            workspace=workspace,
            config=embeddings_config,
            query=str(request.get('query') or ''),
            limit=int_request_argument(request, 'limit', 8),
            inspect_limit=int_request_argument(request, 'inspect_limit', 3),
            route=str(request.get('route') or 'auto'),
            scope=scope,
            repository_root_path=repository_root_path or None,
            kinds=list(request.get('kinds') or []),
            memory_types=list_request_argument(request, 'memory_types'),
            tags=list_request_argument(request, 'tags'),
            namespaces=list_request_argument(request, 'namespaces'),
            entity_scopes=list_request_argument(request, 'entity_scopes'),
            metadata=metadata_request_argument(request),
            filter_json=filter_json_request_argument(request),
            as_of=str(request.get('as_of') or '') or None,
            min_fact_rating=request.get('min_fact_rating'),
        ),
    )
    response.update({
        'thread_id': request.get('thread_id'),
        'current_only': bool(request.get('current_only', True)),
        'as_of': request.get('as_of'),
        'embeddings': embeddings_status,
        'backend': {
            'kind': 'falkordb',
            'graph_name': falkor['graph_name'],
        },
    })
    workflow_hits = response.get('hits', [])
    if not workflow_hits and response.get('items'):
        workflow_hits = response.get('items', [])
    response['workflow'] = tool.build_read_workflow(
        workspace['root_path'],
        command='consult',
        query=request.get('query'),
        thread_id=request.get('thread_id'),
        hits=workflow_hits,
        inspected_items=response.get('items', []),
        current_only=bool(request.get('current_only', True)),
        as_of=request.get('as_of'),
    )
    weak_signal_hits = (
        list(response.get('relationship_hits') or [])
        + list(response.get('relationship_candidate_hits') or [])
        + list(response.get('lexical_only_hits') or [])
        + list(response.get('entity_only_hits') or [])
        + list(response.get('vector_only_hits') or [])
    )
    read_guard = response.get('read_guard') if isinstance(response.get('read_guard'), dict) else {}
    if not workflow_hits and weak_signal_hits:
        response['workflow'] = {
            'status': 'weak_signals_only',
            'coverage': 'weak',
            'complete': False,
            'next_step': 'refine_query',
            'message': 'No reliable memory hits were found. Weak side-channel candidates are shown for debugging only.',
            'suggested_next_steps': [
                workflow_step(
                    'refine-query',
                    'Use a more specific query or inspect exact items before relying on weak side channels.',
                )
            ],
        }
    elif not workflow_hits and int(read_guard.get('blocked_count') or 0) > 0:
        response['workflow'] = {
            'status': 'unsafe_memory_quarantined',
            'coverage': 'blocked',
            'complete': False,
            'next_step': 'audit_quarantine',
            'message': 'Task-specific memory was found but withheld by the unsafe-memory read guard.',
            'suggested_next_steps': [
                workflow_step(
                    'audit-quarantine',
                    'Run audit or inspect the redacted read_guard metadata before deciding whether to delete, supersede, or quarantine unsafe memory.',
                )
            ],
        }
    return response


def health_via_falkor(tool, workspace, embeddings_config, falkor, request: dict):
    module = falkor['module']
    started = time.perf_counter()

    def inspect_graph(graph):
        module.ensure_runtime_indexes(graph, embeddings_config)
        stats = module.build_graph_stats_payload(graph)
        vector_count = int(module.scalar_query(graph, "MATCH (node:SemanticItem) WHERE node.embedding IS NOT NULL RETURN count(node)") or 0)
        index_ok = module.check_runtime_index_probe(graph)
        embedding_status = module.build_embedding_status_payload(graph, embeddings_config)
        graph_ok = module.scalar_query(graph, "MATCH (node) RETURN count(node) LIMIT 1") is not None and index_ok
        return stats, vector_count, index_ok, embedding_status, graph_ok

    stats, vector_count, index_ok, embedding_status, graph_ok = run_falkor_operation(falkor, inspect_graph)
    checks = [
        module.python_version_check(),
        module.installed_autopsy_command_check(),
        module.import_check("falkordb", required=True),
        module.import_check("redis", required=True),
        module.import_check("redislite.falkordb_client", required=True),
        module.import_check("sentence_transformers", required=True),
    ]
    required_ok = all(check["ok"] for check in checks if check["required"])
    repo_hint = str(request.get('repo') or workspace.get('root_path') or os.getcwd())
    targets = module.instruction_targets(
        home=Path.home(),
        repo_path=Path(repo_hint).expanduser().resolve(),
        install_global=True,
        agent="all",
    )
    init_targets = [module.target_status(target) for target in targets]
    managed_targets = sum(1 for target in init_targets if target.get("state") == "managed")
    backup = module.latest_backup_status()
    item_count = int(stats.get("itemCount") or 0)
    backup_health = module.backup_freshness_status(backup, item_count=item_count)
    embeddings_ready = (
        not bool(embeddings_config.get("enabled", True))
        or (
            bool(embedding_status.get("index_ready"))
            and int(embedding_status.get("current_items") or 0)
            == int(embedding_status.get("eligible_items") or 0)
        )
    )
    ok = required_ok and graph_ok and embeddings_ready and bool(backup_health.get("ok"))
    return {
        "ok": ok,
        "workspace": tool.workspace_payload(workspace),
        "graph_name": falkor['graph_name'],
        "backend": "falkor",
        "mode": "native",
        "counts": {
            "entities": int(stats.get("entityCount") or 0),
            "items": item_count,
            "edges": int(stats.get("edgeCount") or 0),
            "vectors": vector_count,
        },
        "stats": stats,
        "checks": {
            "runtime": checks,
            "required_runtime_ok": required_ok,
            "indexes_ready": index_ok,
            "graph_ready": graph_ok,
            "embeddings_configured": bool(embeddings_config.get("enabled", True)),
            "embeddings_ready": embeddings_ready,
            "embedding_index_ready": bool(embedding_status.get("index_ready")),
            "embedding_current_coverage": float(embedding_status.get("current_coverage") or 0.0),
            "reranker_configured": bool(module.reranker_config(embeddings_config).get("enabled", False)),
            "init_managed_targets": managed_targets,
            "init_target_count": len(init_targets),
            "backup_fresh": bool(backup_health.get("ok")),
            "backup_status": backup_health.get("status"),
            "backup_severity": backup_health.get("severity"),
        },
        "init_targets": init_targets,
        "backup": backup,
        "embeddings": embedding_status,
        "backup_health": backup_health,
        "paths": {
            "app_support_dir": str(module.APP_SUPPORT_DIR_DEFAULT),
            "falkordb_lite_path": str(falkor.get('lite_path') or ""),
            "memory_settings": str(module.GLOBAL_MEMORY_SETTINGS_DEFAULT),
            "unified_memory_root": str(module.unified_memory_root_path()),
        },
        "workflow": {
            "status": "ok" if ok else "needs_attention",
            "complete": ok,
            "next_step": "done" if ok else ("run_embeddings_backfill" if not embeddings_ready else "inspect_failed_checks_or_backup"),
            "message": "Autopsy memory health checks passed." if ok else "Autopsy memory health found required runtime, index, embedding-coverage, or backup checks that need attention.",
        },
        "timings": {"health_s": round(time.perf_counter() - started, 3)},
    }


def status_via_falkor(tool, workspace, embeddings_status, falkor, request: dict):
    response = run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_status_payload(
            graph,
            tool=tool,
            workspace=workspace,
            thread_id=str(request.get('thread_id') or '') or None,
            limit=max(1, int(request.get('limit') or 8)),
            section_limit=max(1, int(request.get('section_limit') or 4)),
            recent_days=max(0, int(request.get('recent_days') or tool.STATUS_WINDOW_DAYS_DEFAULT)),
            as_of=str(request.get('as_of') or '') or None,
        ),
    )
    if embeddings_status is not None:
        response['embeddings'] = embeddings_status
    return response


def timeline_via_falkor(tool, workspace, falkor, request: dict):
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_timeline_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
        ),
    )


def history_via_falkor(tool, workspace, falkor, request: dict):
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_history_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
            limit=max(1, int(request.get('limit') or 50)),
        ),
    )


def neighbors_via_falkor(tool, workspace, falkor, request: dict):
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_neighbors_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
            entity_id=None,
            thread_id=None,
            limit=max(1, int(request.get('relation_limit') or 12)),
            all_kinds=False,
            min_fact_rating=request.get('min_fact_rating'),
        ),
    )


def require_falkor_context(payload: dict, *, include_embeddings_status: bool = True):
    context = load_falkor_request_context(payload, include_embeddings_status=include_embeddings_status)
    if context is None:
        raise RuntimeError('FalkorDB memory backend is required and not enabled')
    return context


def falkor_start_failure_payload_for_worker(payload: dict, error: Exception) -> dict:
    tool_path = str(payload.get('tool_path') or '').strip()
    try:
        settings = falkor_backend_settings() or {}
    except Exception:
        settings = {}

    def fallback_payload() -> dict:
        return {
            'ok': False,
            'backend': 'falkordb',
            'mode': 'embedded' if settings.get('lite_path') else 'external',
            'error': str(error),
            'workflow': {
                'status': 'runtime_unavailable',
                'complete': False,
                'next_step': 'fix_falkordb_runtime',
                'message': 'Autopsy could not start or reach the FalkorDB runtime.',
            },
        }

    if not tool_path:
        return fallback_payload()
    try:
        module = load_falkor_module(tool_path)
    except Exception:
        return fallback_payload()
    args = argparse.Namespace(
        workspace=str(payload.get('workspace') or '') or None,
        host=str(settings.get('host') or '127.0.0.1'),
        port=int(settings.get('port') or 6381),
        graph_name=str(settings.get('graph_name') or 'autopsy_memory'),
        lite_path=str(settings.get('lite_path') or ''),
    )
    return module.falkor_start_failure_payload(args, error)


def refresh_activity_snapshot_for_worker(module, falkor: dict, tool, workspace: dict) -> None:
    try:
        run_falkor_operation(
            falkor,
            lambda graph: module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace),
        )
    except Exception:
        pass


def attach_auto_backup_after_worker_write(
    module,
    response: dict,
    graph,
    workspace: dict,
    *,
    reason: str,
    operation: str = "",
    stable_key: str = "",
    expected_present: bool = True,
) -> dict:
    if not isinstance(response, dict) or response.get('blocked'):
        return response
    attach_ack = getattr(module, 'attach_write_ack_after_write', None)
    if callable(attach_ack):
        response = attach_ack(
            response,
            graph,
            stable_key=stable_key,
            operation=operation or reason,
            expected_present=expected_present,
        ) or response
    attach = getattr(module, 'attach_auto_backup_after_write', None)
    if not callable(attach):
        return response
    return attach(response, graph, workspace, reason=reason) or response


def handle_memory_consult(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, embeddings_config, embeddings_status, falkor = require_falkor_context(payload)
    response = consult_via_falkor(tool, workspace, embeddings_config, embeddings_status, falkor, request)
    refresh_activity_snapshot_for_worker(module, falkor, tool, workspace)
    return response


def handle_memory_health(payload: dict) -> dict:
    request = payload.get('request') or {}
    try:
        tool, _module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    except Exception as exc:
        return falkor_start_failure_payload_for_worker(payload, exc)
    return health_via_falkor(tool, workspace, embeddings_config, falkor, request)


def handle_memory_diagnostics(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool_path = str(payload.get('tool_path') or '').strip()
    if not tool_path:
        raise ValueError('missing tool_path')
    module = load_falkor_module(tool_path)
    args = argparse.Namespace(
        log=str(request.get('log') or 'all'),
        limit=max(0, int(request.get('limit') or 10)),
    )
    return module.build_diagnostics_command_payload(args)


def repair_embedded_snapshot_plan_safety_payload() -> dict:
    return {
        'plan_only': True,
        'mutations_allowed': False,
        'forced_dry_run': True,
        'salvage_export_allowed': False,
        'worker_cleanup_allowed': False,
    }


def handle_memory_repair_embedded_snapshot_plan(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool_path = str(payload.get('tool_path') or '').strip()
    if not tool_path:
        raise ValueError('missing tool_path')
    module = load_falkor_module(tool_path)
    try:
        settings = falkor_backend_settings() or {}
    except Exception:
        settings = {}
    workspace = resolve_workspace_reference(
        str(payload.get('workspace') or '').strip() or None,
        str(payload.get('cwd') or os.getcwd()),
    )
    args = argparse.Namespace(
        workspace=str(workspace.get('root_path') or '') or None,
        host=str(settings.get('host') or '127.0.0.1'),
        port=int(settings.get('port') or 6381),
        graph_name=str(settings.get('graph_name') or 'autopsy_memory'),
        lite_path=str(request.get('lite_path') or settings.get('lite_path') or ''),
        dry_run=True,
        yes=False,
        accept_data_loss=False,
        restore_backup=str(request.get('restore_backup') or ''),
        restore_latest_backup=bool(request.get('restore_latest_backup')),
        backup_limit=max(0, int_request_argument(request, 'backup_limit', 5)),
        salvage_output='',
        salvage_limit=0,
        skip_salvage=True,
        include_operational=bool(request.get('include_operational')),
        skip_cleanup_workers=True,
    )
    safety = repair_embedded_snapshot_plan_safety_payload()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            repair_payload = module.build_embedded_snapshot_repair_payload(args)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
        message = stderr.getvalue().strip() or str(exc) or 'Repair preview failed before plan generation.'
        return {
            'ok': False,
            'command': 'repair-embedded-snapshot',
            'dry_run': True,
            'requires_confirmation': True,
            'exit_code': exit_code,
            'error': message,
            'mcp_safety': safety,
            'workflow': {
                'status': 'repair_plan_unavailable',
                'complete': False,
                'next_step': 'adjust_repair_preview_request',
                'message': message,
            },
        }
    repair_payload['dry_run'] = True
    repair_payload['requires_confirmation'] = True
    repair_payload['mcp_safety'] = safety
    return repair_payload


def handle_memory_status(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return status_via_falkor(tool, workspace, embeddings_status, falkor, request)


def handle_memory_timeline(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return timeline_via_falkor(tool, workspace, falkor, request)


def handle_memory_history(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return history_via_falkor(tool, workspace, falkor, request)


def handle_memory_neighbors(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return neighbors_via_falkor(tool, workspace, falkor, request)


def handle_memory_observe(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)

    def observe(graph):
        response = module.build_observe_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
            limit=max(1, int(request.get('limit') or 5)),
            min_fact_rating=request.get('min_fact_rating'),
            title=str(request.get('title') or ''),
            write=bool(request.get('write')),
            write_if_stale=bool(request.get('write_if_stale')),
            embedding_config=embeddings_config,
        )
        if bool(response.get('written')):
            attach_auto_backup_after_worker_write(module, response, graph, workspace, reason='worker_observe', operation='observe')
        return response

    return run_falkor_operation(falkor, observe)


def handle_memory_consolidate_session(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)

    def consolidate_session(graph):
        response = module.build_consolidate_session_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
            kind=str(request.get('kind') or 'memory_note'),
            title=str(request.get('title') or ''),
            max_events=max(1, int(request.get('max_events') or 80)),
            write=bool(request.get('write')),
            embedding_config=embeddings_config,
        )
        if bool(request.get('write')) and str((response.get('workflow') or {}).get('status') or '') == 'ok':
            module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
            attach_auto_backup_after_worker_write(module, response, graph, workspace, reason='worker_consolidate_session', operation='consolidate_session')
        return response

    return run_falkor_operation(falkor, consolidate_session)


def handle_memory_import_session(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)

    def import_session(graph):
        response = module.build_import_session_payload(
            graph,
            tool=tool,
            workspace=workspace,
            path=str(request.get('path') or ''),
            title=str(request.get('title') or ''),
            source=str(request.get('source') or 'agent-jsonl'),
            max_events=max(1, int(request.get('max_events') or 200)),
            dry_run=bool(request.get('dry_run')),
            repository_root_path=str(request.get('repository_root_path') or request.get('repo') or '') or None,
            embedding_config=embeddings_config,
        )
        if not bool(request.get('dry_run')) and str((response.get('workflow') or {}).get('status') or '') == 'ok':
            module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
            attach_auto_backup_after_worker_write(module, response, graph, workspace, reason='worker_import_session', operation='import_session')
        return response

    return run_falkor_operation(falkor, import_session)


def handle_memory_feedback(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)

    def record_feedback(graph):
        stable_key = str(request.get('stable_key') or '')
        if not module.lookup_node_by_stable_key(graph, stable_key):
            return module.blocked_missing_memory_item_payload_for_graph(graph, stable_key=stable_key, operation='feedback')
        rating = str(request.get('rating') or 'neutral').strip().lower()
        if rating not in {'useful', 'not-useful', 'neutral'}:
            raise ValueError('rating must be useful, not-useful, or neutral')
        usage = module.record_memory_feedback(
            graph,
            stable_key,
            rating=rating,
            note=str(request.get('note') or ''),
            source=str(request.get('source') or 'mcp'),
        )
        return {
            'workspace': tool.workspace_payload(workspace),
            'stable_key': stable_key,
            'feedback': usage,
            'workflow': {
                'status': 'ok',
                'complete': True,
                'next_step': 'done',
                'message': 'Memory feedback recorded.',
            },
        }

    return run_falkor_operation(falkor, record_feedback)


def handle_memory_snapshot(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return run_falkor_operation(
        falkor,
        lambda graph: module.build_snapshot_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
            limit=max(1, int(request.get('limit') or 20)),
        ),
    )


def handle_memory_expire(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)

    def expire_item(graph):
        stable_key = str(request.get('stable_key') or '')
        if not module.lookup_node_by_stable_key(graph, stable_key):
            return module.blocked_missing_memory_item_payload_for_graph(graph, stable_key=stable_key, operation='expire')
        response = module.expire_graph_item_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=stable_key,
            expires_at=str(request.get('expires_at') or ''),
            reason=str(request.get('reason') or ''),
            clear=bool(request.get('clear')),
        )
        module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
        attach_auto_backup_after_worker_write(module, response, graph, workspace, reason='worker_expire_item', operation='expire', stable_key=stable_key)
        return response

    return run_falkor_operation(falkor, expire_item)


def handle_memory_pin(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)

    def pin_item(graph):
        stable_key = str(request.get('stable_key') or '')
        if not module.lookup_node_by_stable_key(graph, stable_key):
            return module.blocked_missing_memory_item_payload_for_graph(graph, stable_key=stable_key, operation='pin')
        block_limit = request.get('block_limit') if request.get('block_limit') is not None else None
        response = module.pin_graph_item_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=stable_key,
            label=str(request.get('label') or ''),
            reason=str(request.get('reason') or ''),
            description=str(request.get('description') or ''),
            block_limit=int(block_limit) if block_limit is not None else None,
            read_only=bool(request.get('read_only')) if request.get('read_only') is not None else None,
            shared=bool(request.get('shared')) if request.get('shared') is not None else None,
            clear=bool(request.get('clear')),
        )
        module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
        attach_auto_backup_after_worker_write(module, response, graph, workspace, reason='worker_pin_item', operation='pin', stable_key=stable_key)
        return response

    return run_falkor_operation(falkor, pin_item)


def handle_memory_graph_search(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_graph_search_payload(
            graph,
            tool=tool,
            conn=None,
            workspace=workspace,
            config=embeddings_config,
            query=str(request.get('query') or ''),
            limit=max(1, int(request.get('limit') or 24)),
            as_of=str(request.get('as_of') or '') or None,
            kinds=list_request_argument(request, 'kinds'),
            memory_types=list_request_argument(request, 'memory_types'),
            tags=list_request_argument(request, 'tags'),
            namespaces=list_request_argument(request, 'namespaces'),
            entity_scopes=list_request_argument(request, 'entity_scopes'),
            metadata=metadata_request_argument(request),
            filter_json=filter_json_request_argument(request),
            min_fact_rating=request.get('min_fact_rating'),
        ),
    )


def handle_memory_graph_item(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)

    def item_detail(graph):
        stable_key = str(request.get('stable_key') or '')
        if not module.lookup_node_by_stable_key(graph, stable_key):
            return module.blocked_missing_memory_item_payload_for_graph(graph, stable_key=stable_key, operation='item')
        return module.build_graph_item_detail_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=stable_key,
        )

    return run_falkor_operation(
        falkor,
        item_detail,
    )


def handle_memory_graph_note_create(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    module = falkor['module']

    def create_note(graph):
        kind = str(request.get('kind') or 'memory_note')
        title = str(request.get('title') or '')
        content = str(request.get('content') or '')
        relation_specs = module.relation_specs_from_mapping(request)
        try:
            targets = module.relation_target_records(graph, relation_specs)
        except module.MissingRelationTargetsError as exc:
            return module.blocked_relation_write_payload(error=exc, operation='create')
        write_quality = module.build_write_quality_payload(
            graph,
            kind=kind,
            title=title,
            content=content,
            relation_count=len(relation_specs),
            no_relations_ok=bool(request.get('no_relations_ok')),
            allow_unsafe_memory=bool(request.get('allow_unsafe_memory')),
        )
        if module.write_quality_blocks_write(write_quality):
            return module.blocked_memory_write_payload(write_quality=write_quality, operation='create')
        scope = str(request.get('scope') or 'system')
        repository_root_path = str(request.get('repository_root_path') or request.get('repo') or '')
        if scope == 'repo' and not repository_root_path:
            repository_root_path = str(workspace.get('root_path') or os.getcwd())
        response = module.create_graph_note_payload(
            graph,
            tool=tool,
            workspace=workspace,
            kind=kind,
            title=title,
            content=content,
            repository_root_path=repository_root_path or None,
            thread_id=module.current_write_thread_id(str(request.get('thread_id') or '')),
            tags=list_request_argument(request, 'tags'),
            namespaces=list_request_argument(request, 'namespaces'),
            entity_scopes=list_request_argument(request, 'entity_scopes'),
            metadata=metadata_request_argument(request),
            embedding_config=embeddings_config,
        )
        stable_key = module.payload_item_stable_key(response)
        if stable_key:
            relations = module.create_requested_fact_relations_from_specs(
                graph,
                source_stable_key=stable_key,
                specs=relation_specs,
                targets=targets,
            )
            if relations:
                response = module.build_graph_item_detail_payload(graph, tool=tool, workspace=workspace, stable_key=stable_key)
                response['created_relations'] = relations
        response['write_quality'] = write_quality
        module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
        attach_auto_backup_after_worker_write(module, response, graph, workspace, reason='worker_create_note', operation='create', stable_key=stable_key)
        return response

    return run_falkor_operation(
        falkor,
        create_note,
    )


def handle_memory_graph_item_update(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    module = falkor['module']

    def update_item(graph):
        kind = str(request.get('kind') or 'memory_note')
        title = str(request.get('title') or '')
        content = str(request.get('content') or '')
        stable_key = str(request.get('stable_key') or '')
        if not module.lookup_node_by_stable_key(graph, stable_key):
            return module.blocked_missing_memory_item_payload_for_graph(graph, stable_key=stable_key, operation='update')
        write_quality = module.build_write_quality_payload(
            graph,
            kind=kind,
            title=title,
            content=content,
            relation_count=0,
            no_relations_ok=bool(request.get('no_relations_ok')),
            allow_unsafe_memory=bool(request.get('allow_unsafe_memory')),
        )
        if module.write_quality_blocks_write(write_quality):
            return module.blocked_memory_write_payload(write_quality=write_quality, stable_key=stable_key, operation='update')
        response = module.update_graph_item_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=stable_key,
            kind=kind,
            title=title,
            content=content,
            tags=list_request_argument(request, 'tags') if request.get('tags') is not None else None,
            namespaces=list_request_argument(request, 'namespaces'),
            entity_scopes=list_request_argument(request, 'entity_scopes') if request.get('entity_scopes') is not None else None,
            metadata=metadata_request_argument(request) if request.get('metadata') is not None else None,
            thread_id=module.current_write_thread_id(str(request.get('thread_id') or '')),
            embedding_config=embeddings_config,
        )
        response['write_quality'] = write_quality
        module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
        attach_auto_backup_after_worker_write(module, response, graph, workspace, reason='worker_update_item', operation='update', stable_key=stable_key)
        return response

    return run_falkor_operation(
        falkor,
        update_item,
    )


def handle_memory_graph_conflict_resolve(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    module = falkor['module']

    def resolve_conflict(graph):
        response = module.resolve_graph_conflict_payload(
            graph,
            tool=tool,
            workspace=workspace,
            current_stable_key=str(request.get('current_stable_key') or ''),
            superseded_stable_keys=[str(value) for value in (request.get('superseded_stable_keys') or [])],
            relation=str(request.get('relation') or ''),
            summary=str(request.get('summary') or '') or None,
        )
        module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
        attach_auto_backup_after_worker_write(
            module,
            response,
            graph,
            workspace,
            reason='worker_conflict_resolve',
            operation='resolve_conflict',
            stable_key=str(request.get('current_stable_key') or ''),
        )
        return response

    return run_falkor_operation(falkor, resolve_conflict)


def handle_memory_graph_item_delete(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)

    def delete_item(graph):
        stable_key = str(request.get('stable_key') or '')
        if not module.lookup_node_by_stable_key(graph, stable_key):
            return module.blocked_missing_memory_item_payload_for_graph(graph, stable_key=stable_key, operation='delete')
        module.delete_graph_item_payload(
            graph,
            stable_key=stable_key,
        )
        module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
        response = {"deleted": True, "stable_key": stable_key}
        attach_auto_backup_after_worker_write(
            module,
            response,
            graph,
            workspace,
            reason='worker_delete_item',
            operation='delete',
            stable_key=stable_key,
            expected_present=False,
        )
        return response

    return run_falkor_operation(falkor, delete_item)


def handle_memory_sync_workspace(payload: dict) -> dict:
    request = payload.get('request') or {}
    _tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].sync_workspace_payload(
            graph,
            workspace=request.get('workspace') or workspace,
        ),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = 'AutopsyMLWorker/0.1'

    def _write_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_token(self) -> bool:
        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get('token', [''])[0]
        token = self.headers.get('x-autopsy-token', '') or query_token
        if token != self.server.auth_token:
            self._write_json(403, {'error': 'forbidden'})
            return False
        return True

    def _touch_request(self) -> None:
        self.server.last_request_at = time.monotonic()

    def log_message(self, format, *args):
        return

    def do_GET(self):
        self._touch_request()
        parsed = urlparse(self.path)
        if parsed.path == '/favicon.ico':
            self._write_bytes(204, b'', 'image/x-icon')
            return
        if not self._require_token():
            return
        if parsed.path == '/health':
            self._write_json(200, {
                'ok': True,
                'pid': os.getpid(),
                'idle_timeout_seconds': getattr(self.server, 'idle_timeout_seconds', 0.0),
                'shutdown_reason': getattr(self.server, 'shutdown_reason', ''),
            })
            return
        self._write_json(404, {'error': 'not found'})

    def do_POST(self):
        if not self._require_token():
            return
        self._touch_request()
        length = int(self.headers.get('content-length', '0') or '0')
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception as exc:
            self._write_json(400, {'error': f'invalid json: {exc}'})
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == '/embed':
                provider = str(payload.get('provider') or '').strip().lower()
                if provider != 'sentence_transformers':
                    raise ValueError(f'unsupported provider: {provider}')
                model_name = str(payload.get('model') or '').strip()
                model_revision = str(payload.get('model_revision') or '').strip()
                device = str(payload.get('device') or 'cpu').strip() or 'cpu'
                batch_size = max(1, int(payload.get('batch_size', 16)))
                texts = payload.get('texts') or []
                if not isinstance(texts, list):
                    raise ValueError('texts must be a list')
                model = load_sentence_transformer(model_name, device, model_revision)
                vectors = model.encode(
                    texts,
                    batch_size=batch_size,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                )
                self._write_json(200, {'vectors': [vector.tolist() for vector in vectors]})
                return
            if parsed.path == '/rerank':
                provider = str(payload.get('provider') or '').strip().lower()
                if provider != 'sentence_transformers':
                    raise ValueError(f'unsupported provider: {provider}')
                model_name = str(payload.get('model') or '').strip()
                model_revision = str(payload.get('model_revision') or '').strip()
                device = str(payload.get('device') or 'cpu').strip() or 'cpu'
                batch_size = max(1, int(payload.get('batch_size', 8)))
                query = str(payload.get('query') or '')
                texts = payload.get('texts') or []
                if not isinstance(texts, list):
                    raise ValueError('texts must be a list')
                model = load_cross_encoder(model_name, device, model_revision)
                pairs = [[query, str(text or '')] for text in texts]
                scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=False)
                self._write_json(200, {'scores': [float(score) for score in scores]})
                return
            if parsed.path == '/memory/consult':
                self._write_json(200, handle_memory_consult(payload))
                return
            if parsed.path == '/memory/health':
                self._write_json(200, handle_memory_health(payload))
                return
            if parsed.path == '/memory/diagnostics':
                self._write_json(200, handle_memory_diagnostics(payload))
                return
            if parsed.path == '/memory/repair-embedded-snapshot/plan':
                self._write_json(200, handle_memory_repair_embedded_snapshot_plan(payload))
                return
            if parsed.path == '/memory/status':
                self._write_json(200, handle_memory_status(payload))
                return
            if parsed.path == '/memory/timeline':
                self._write_json(200, handle_memory_timeline(payload))
                return
            if parsed.path == '/memory/history':
                self._write_json(200, handle_memory_history(payload))
                return
            if parsed.path == '/memory/neighbors':
                self._write_json(200, handle_memory_neighbors(payload))
                return
            if parsed.path == '/memory/observe':
                self._write_json(200, handle_memory_observe(payload))
                return
            if parsed.path == '/memory/consolidate-session':
                self._write_json(200, handle_memory_consolidate_session(payload))
                return
            if parsed.path == '/memory/import-session':
                self._write_json(200, handle_memory_import_session(payload))
                return
            if parsed.path == '/memory/feedback':
                self._write_json(200, handle_memory_feedback(payload))
                return
            if parsed.path == '/memory/snapshot':
                self._write_json(200, handle_memory_snapshot(payload))
                return
            if parsed.path == '/memory/expire':
                self._write_json(200, handle_memory_expire(payload))
                return
            if parsed.path == '/memory/pin':
                self._write_json(200, handle_memory_pin(payload))
                return
            if parsed.path == '/memory/graph/search':
                self._write_json(200, handle_memory_graph_search(payload))
                return
            if parsed.path == '/memory/graph/item':
                self._write_json(200, handle_memory_graph_item(payload))
                return
            if parsed.path == '/memory/graph/note':
                self._write_json(200, handle_memory_graph_note_create(payload))
                return
            if parsed.path == '/memory/graph/item/update':
                self._write_json(200, handle_memory_graph_item_update(payload))
                return
            if parsed.path == '/memory/graph/conflicts/resolve':
                self._write_json(200, handle_memory_graph_conflict_resolve(payload))
                return
            if parsed.path == '/memory/graph/item/delete':
                self._write_json(200, handle_memory_graph_item_delete(payload))
                return
            if parsed.path == '/memory/sync/workspace':
                self._write_json(200, handle_memory_sync_workspace(payload))
                return
            self._write_json(404, {'error': 'not found'})
        except Exception as exc:
            self._write_json(500, {'error': str(exc)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--token', required=True)
    parser.add_argument('--info-file', required=True)
    parser.add_argument('--source-fingerprint', default='')
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.auth_token = args.token
    server.daemon_threads = True
    server.last_request_at = time.monotonic()
    server.idle_timeout_seconds = worker_idle_timeout_seconds()
    server.ownership_check_seconds = worker_ownership_check_seconds()
    server.shutdown_requested = False
    server.shutdown_reason = ''

    info = {
        'base_url': f'http://{args.host}:{server.server_port}',
        'token': args.token,
        'pid': os.getpid(),
        'python_executable': sys.executable,
        'python_version': sys.version.split()[0],
        'source_fingerprint': args.source_fingerprint,
    }
    os.makedirs(os.path.dirname(args.info_file), exist_ok=True)
    with open(args.info_file, 'w', encoding='utf-8') as handle:
        json.dump(info, handle)
    start_worker_lifecycle_monitor(
        server,
        info_file=args.info_file,
        token=args.token,
        source_fingerprint=args.source_fingerprint,
    )
    install_worker_signal_handlers(server)

    try:
        server.serve_forever()
    finally:
        server.shutdown_requested = True
        shutdown_falkor_contexts()
        remove_owned_info_file(
            args.info_file,
            token=args.token,
            source_fingerprint=args.source_fingerprint,
        )


if __name__ == '__main__':
    main()
