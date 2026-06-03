#!/usr/bin/env python3
import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shlex
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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
DIRECT_RETRIEVAL_REASONS = {'lexical', 'exact', 'token_overlap', 'entity_overlap', 'graph_relation'}

APP_SUPPORT_DIR_DEFAULT = Path.home() / 'Library' / 'Application Support' / 'Autopsy'
GLOBAL_MEMORY_SETTINGS_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'Config' / 'memory-settings.json'
UNIFIED_MEMORY_ROOT_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'MemoryRoot'
STATUS_WINDOW_DAYS_DEFAULT = 21
EMBEDDINGS_CONFIG_DEFAULT = {
    'enabled': True,
    'provider': 'sentence_transformers',
    'model': 'BAAI/bge-base-en-v1.5',
    'device': 'cpu',
    'batch_size': 16,
    'candidate_limit': 48,
    'reranker': {
        'enabled': True,
        'provider': 'sentence_transformers',
        'model': 'BAAI/bge-reranker-base',
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


def embedding_provider_available(config: dict) -> tuple[bool, str | None]:
    provider = str(config.get('provider') or '').strip().lower()
    if not config.get('enabled', True):
        return (False, 'disabled')
    if provider != 'sentence_transformers':
        return (False, f'unsupported provider: {provider}')
    try:
        __import__('sentence_transformers')
    except Exception as exc:
        return (False, f'sentence-transformers unavailable: {exc}')
    return (True, None)


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
    try:
        __import__('sentence_transformers')
    except Exception as exc:
        return (False, f'sentence-transformers unavailable: {exc}')
    return (True, None)


def embed_texts_with_provider(texts: list[str], config: dict) -> list[list[float]]:
    provider = str(config.get('provider') or '').strip().lower()
    model_name = str(config.get('model') or '').strip()
    if provider != 'sentence_transformers':
        raise RuntimeError(f'Unsupported embeddings provider: {provider}')
    if not model_name:
        raise RuntimeError('Embeddings config missing model')
    model = load_sentence_transformer(model_name, str(config.get('device') or 'cpu'))
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
    model = load_cross_encoder(model_name, str(reranker.get('device') or 'cpu'))
    scores = model.predict(
        [[query, text] for text in shortlist_texts],
        batch_size=max(1, int(reranker.get('batch_size', 8))),
        show_progress_bar=False,
    )
    normalized_shortlist = []
    for item, score in zip(shortlist, scores):
        normalized = dict(item)
        normalized['reranker_score'] = float(score)
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
    score += float(item.get('query_penalty') or 0.0)
    return score


def sort_candidates(items: list[dict]) -> list[dict]:
    return sorted(
        items,
        key=lambda item: (
            -candidate_final_score(item),
            item.get('rank', 1_000_000),
            item.get('stable_key') or '',
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

def falkor_backend_settings() -> dict | None:
    backend = str(os.environ.get('AUTOPSY_MEMORY_BACKEND') or '').strip().lower()
    enabled_flag = str(os.environ.get('AUTOPSY_FALKORDB_ENABLED') or '').strip().lower()
    enabled = backend in {'', 'falkordb'} or enabled_flag in {'1', 'true', 'yes', 'on'}
    if not enabled:
        raise RuntimeError('FalkorDB memory backend is required')
    lite_path = str(os.environ.get('AUTOPSY_FALKORDB_LITE_PATH') or '').strip()
    settings = {
        'host': str(os.environ.get('AUTOPSY_FALKORDB_HOST') or '127.0.0.1'),
        'port': int(os.environ.get('AUTOPSY_FALKORDB_PORT') or '6381'),
        'graph_name': str(os.environ.get('AUTOPSY_FALKORDB_GRAPH_NAME') or 'autopsy_memory'),
    }
    if lite_path and not os.environ.get('AUTOPSY_FALKORDB_HOST') and not os.environ.get('AUTOPSY_FALKORDB_PORT'):
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
    _EMBEDDINGS_STATUS_CACHE[key] = copy.deepcopy(status)
    return status


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
        graph, resolved_graph_name = module.ensure_workspace_graph(
            workspace=workspace,
            host=settings['host'],
            port=settings['port'],
            graph_name_base=settings['graph_name'],
            lite_path=settings.get('lite_path'),
        )
        module.sync_workspace_payload(graph, workspace=workspace)
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


def run_falkor_operation(falkor: dict, operation):
    graph = falkor['module'].ensure_graph(
        falkor['host'],
        falkor['port'],
        falkor['graph_name'],
        lite_path=falkor.get('lite_path'),
    )
    try:
        return operation(graph)
    except Exception:
        reset_lite_client = getattr(falkor['module'], 'reset_falkordb_lite_client', None)
        if callable(reset_lite_client):
            reset_lite_client(falkor.get('lite_path'))
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
    read_guard = response.get('read_guard') if isinstance(response.get('read_guard'), dict) else {}
    if not workflow_hits and int(read_guard.get('blocked_count') or 0) > 0:
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
        module.ensure_runtime_indexes(graph)
        stats = module.build_graph_stats_payload(graph)
        vector_count = int(module.scalar_query(graph, "MATCH (node:SemanticItem) WHERE node.embedding IS NOT NULL RETURN count(node)") or 0)
        index_ok = module.check_runtime_index_probe(graph)
        graph_ok = module.scalar_query(graph, "MATCH (node) RETURN count(node) LIMIT 1") is not None and index_ok
        return stats, vector_count, index_ok, graph_ok

    stats, vector_count, index_ok, graph_ok = run_falkor_operation(falkor, inspect_graph)
    checks = [
        module.python_version_check(),
        module.installed_autopsy_command_check(),
        module.import_check("falkordb", required=True),
        module.import_check("redis", required=True),
        module.import_check("redislite.falkordb_client", required=True),
        module.import_check("sentence_transformers", required=False),
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
    latest_backup_age = backup.get("age_seconds")
    backup_fresh = latest_backup_age is not None and int(latest_backup_age) <= 7 * 24 * 60 * 60
    ok = required_ok and graph_ok
    return {
        "ok": ok,
        "workspace": tool.workspace_payload(workspace),
        "graph_name": falkor['graph_name'],
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
            "embeddings_configured": bool(embeddings_config.get("enabled", True)),
            "reranker_configured": bool(module.reranker_config(embeddings_config).get("enabled", False)),
            "init_managed_targets": managed_targets,
            "init_target_count": len(init_targets),
            "backup_fresh": backup_fresh,
        },
        "init_targets": init_targets,
        "backup": backup,
        "paths": {
            "app_support_dir": str(module.APP_SUPPORT_DIR_DEFAULT),
            "falkordb_lite_path": str(falkor.get('lite_path') or ""),
            "memory_settings": str(module.GLOBAL_MEMORY_SETTINGS_DEFAULT),
            "unified_memory_root": str(module.unified_memory_root_path()),
        },
        "workflow": {
            "status": "ok" if ok else "needs_attention",
            "complete": ok,
            "next_step": "done" if ok else "inspect_failed_checks",
            "message": "Autopsy memory health checks passed." if ok else "Autopsy memory health found required checks that need attention.",
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


def refresh_activity_snapshot_for_worker(module, falkor: dict, tool, workspace: dict) -> None:
    try:
        run_falkor_operation(
            falkor,
            lambda graph: module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace),
        )
    except Exception:
        pass


def handle_memory_consult(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, embeddings_config, embeddings_status, falkor = require_falkor_context(payload)
    response = consult_via_falkor(tool, workspace, embeddings_config, embeddings_status, falkor, request)
    refresh_activity_snapshot_for_worker(module, falkor, tool, workspace)
    return response


def handle_memory_health(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return health_via_falkor(tool, workspace, embeddings_config, falkor, request)


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
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_observe_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
            limit=max(1, int(request.get('limit') or 5)),
            min_fact_rating=request.get('min_fact_rating'),
            title=str(request.get('title') or ''),
            write=bool(request.get('write')),
            write_if_stale=bool(request.get('write_if_stale')),
        ),
    )


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
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_graph_item_detail_payload(
            graph,
            tool=tool,
            workspace=workspace,
            stable_key=str(request.get('stable_key') or ''),
        ),
    )


def handle_memory_graph_workspace(payload: dict) -> dict:
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_workspace_explorer_payload(
            graph,
            tool=tool,
            workspace=workspace,
        ),
    )


def handle_memory_graph_thread(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload, include_embeddings_status=False)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].build_thread_explorer_payload(
            graph,
            tool=tool,
            workspace=workspace,
            thread_id=str(request.get('thread_id') or ''),
        ),
    )


def handle_memory_graph_note_create(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    module = falkor['module']

    def create_note(graph):
        kind = str(request.get('kind') or 'memory_note')
        title = str(request.get('title') or '')
        content = str(request.get('content') or '')
        relation_specs = module.relation_specs_from_mapping(request)
        targets = module.relation_target_records(graph, relation_specs)
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
        response = module.create_graph_note_payload(
            graph,
            tool=tool,
            workspace=workspace,
            kind=kind,
            title=title,
            content=content,
            repository_root_path=str(request.get('repository_root_path') or '') or None,
            thread_id=str(request.get('thread_id') or '') or None,
            tags=list_request_argument(request, 'tags'),
            namespaces=list_request_argument(request, 'namespaces'),
            entity_scopes=list_request_argument(request, 'entity_scopes'),
            metadata=metadata_request_argument(request),
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
        return response

    return run_falkor_operation(
        falkor,
        create_note,
    )


def handle_memory_graph_item_update(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    module = falkor['module']

    def update_item(graph):
        kind = str(request.get('kind') or 'memory_note')
        title = str(request.get('title') or '')
        content = str(request.get('content') or '')
        write_quality = module.build_write_quality_payload(
            graph,
            kind=kind,
            title=title,
            content=content,
            relation_count=0,
            no_relations_ok=bool(request.get('no_relations_ok')),
            allow_unsafe_memory=bool(request.get('allow_unsafe_memory')),
        )
        stable_key = str(request.get('stable_key') or '')
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
        )
        response['write_quality'] = write_quality
        module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace)
        return response

    return run_falkor_operation(
        falkor,
        update_item,
    )


def handle_memory_graph_conflict_resolve(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    response = run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].resolve_graph_conflict_payload(
            graph,
            tool=tool,
            workspace=workspace,
            current_stable_key=str(request.get('current_stable_key') or ''),
            superseded_stable_keys=[str(value) for value in (request.get('superseded_stable_keys') or [])],
            relation=str(request.get('relation') or ''),
            summary=str(request.get('summary') or '') or None,
        ),
    )
    refresh_activity_snapshot_for_worker(falkor['module'], falkor, tool, workspace)
    return response


def handle_memory_graph_item_delete(payload: dict) -> dict:
    request = payload.get('request') or {}
    tool, module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    run_falkor_operation(
        falkor,
        lambda graph: (
            module.delete_graph_item_payload(
                graph,
                stable_key=str(request.get('stable_key') or ''),
            ),
            module.refresh_activity_snapshot(graph, tool=tool, workspace=workspace),
        ),
    )
    return {"deleted": True}


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


def handle_memory_sync_thread_summary(payload: dict) -> dict:
    request = payload.get('request') or {}
    _tool, _module, workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].sync_thread_summary_payload(
            graph,
            workspace=request.get('workspace') or workspace,
            summary=request.get('summary') or {},
        ),
    )


def handle_memory_sync_thread_context(payload: dict) -> dict:
    request = payload.get('request') or {}
    _tool, _module, _workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].sync_thread_context_payload(
            graph,
            summary=request.get('summary') or {},
            context=request.get('context') or {},
        ),
    )

def handle_memory_capture_thread_outcomes(payload: dict) -> dict:
    request = payload.get('request') or {}
    _tool, _module, _workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].capture_thread_outcomes_payload(
            graph,
            thread=request.get('thread') or {},
            context=request.get('context') or {},
        ),
    )


def handle_memory_record_thread_fork(payload: dict) -> dict:
    request = payload.get('request') or {}
    _tool, _module, _workspace, _embeddings_config, _embeddings_status, falkor = require_falkor_context(payload)
    return run_falkor_operation(
        falkor,
        lambda graph: falkor['module'].record_thread_fork_payload(
            graph,
            parent_thread_id=str(request.get('parent_thread_id') or ''),
            child_summary=request.get('child_summary') or {},
            child_context=request.get('child_context') or {},
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

    def _require_token(self) -> bool:
        token = self.headers.get('x-autopsy-token', '')
        if token != self.server.auth_token:
            self._write_json(403, {'error': 'forbidden'})
            return False
        return True

    def log_message(self, format, *args):
        return

    def do_GET(self):
        if not self._require_token():
            return
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            self._write_json(200, {'ok': True, 'pid': os.getpid()})
            return
        self._write_json(404, {'error': 'not found'})

    def do_POST(self):
        if not self._require_token():
            return
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
                device = str(payload.get('device') or 'cpu').strip() or 'cpu'
                batch_size = max(1, int(payload.get('batch_size', 16)))
                texts = payload.get('texts') or []
                if not isinstance(texts, list):
                    raise ValueError('texts must be a list')
                model = load_sentence_transformer(model_name, device)
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
                device = str(payload.get('device') or 'cpu').strip() or 'cpu'
                batch_size = max(1, int(payload.get('batch_size', 8)))
                query = str(payload.get('query') or '')
                texts = payload.get('texts') or []
                if not isinstance(texts, list):
                    raise ValueError('texts must be a list')
                model = load_cross_encoder(model_name, device)
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
            if parsed.path == '/memory/graph/search':
                self._write_json(200, handle_memory_graph_search(payload))
                return
            if parsed.path == '/memory/graph/item':
                self._write_json(200, handle_memory_graph_item(payload))
                return
            if parsed.path == '/memory/graph/workspace':
                self._write_json(200, handle_memory_graph_workspace(payload))
                return
            if parsed.path == '/memory/graph/thread':
                self._write_json(200, handle_memory_graph_thread(payload))
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
            if parsed.path == '/memory/sync/thread-summary':
                self._write_json(200, handle_memory_sync_thread_summary(payload))
                return
            if parsed.path == '/memory/sync/thread-context':
                self._write_json(200, handle_memory_sync_thread_context(payload))
                return
            if parsed.path == '/memory/threads/outcomes':
                self._write_json(200, handle_memory_capture_thread_outcomes(payload))
                return
            if parsed.path == '/memory/threads/fork':
                self._write_json(200, handle_memory_record_thread_fork(payload))
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

    info = {
        'base_url': f'http://{args.host}:{server.server_port}',
        'token': args.token,
        'pid': os.getpid(),
        'source_fingerprint': args.source_fingerprint,
    }
    os.makedirs(os.path.dirname(args.info_file), exist_ok=True)
    with open(args.info_file, 'w', encoding='utf-8') as handle:
        json.dump(info, handle)

    try:
        server.serve_forever()
    finally:
        try:
            os.remove(args.info_file)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
