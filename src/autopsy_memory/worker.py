#!/usr/bin/env python3
import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
import mimetypes
import os
import re
import shlex
import sys
import threading
import time
from datetime import datetime, timezone
from importlib import resources
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

_EMBEDDING_MODEL_CACHE = {}
_RERANKER_MODEL_CACHE = {}
_TOOL_MODULE_CACHE = {}
_TOOL_MODULE_LOCK = threading.Lock()
_EMBEDDINGS_CONFIG_CACHE = {}
_EMBEDDINGS_STATUS_CACHE = {}
_FALKOR_CONTEXT_CACHE = {}
_FALKOR_FAILURE_CACHE = {}
_CONTEXT_GRAPH_MEMORY_ENRICH_CACHE = {}
_FALKOR_CONTEXT_LOCK = threading.Lock()
_CONTEXT_GRAPH_LOCK = threading.Lock()
_FALKOR_VALIDATION_TTL_SECONDS = 10.0
_FALKOR_FAILURE_TTL_SECONDS = 30.0
_WORKER_DEFAULT_IDLE_TIMEOUT_SECONDS = 3600.0
_WORKER_DEFAULT_OWNERSHIP_CHECK_SECONDS = 5.0
DIRECT_RETRIEVAL_REASONS = {'lexical', 'exact', 'token_overlap', 'entity_overlap', 'graph_relation'}

APP_SUPPORT_DIR_DEFAULT = Path.home() / 'Library' / 'Application Support' / 'Autopsy'
FALKORDB_LITE_PATH_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'FalkorDB' / 'autopsy-memory.db'
GLOBAL_MEMORY_SETTINGS_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'Config' / 'memory-settings.json'
UNIFIED_MEMORY_ROOT_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'MemoryRoot'
CONTEXT_GRAPH_DIR_DEFAULT = APP_SUPPORT_DIR_DEFAULT / 'ContextGraph'
STATUS_WINDOW_DAYS_DEFAULT = 21
CONTEXT_GRAPH_ALLOWED_EVENT_TYPES = {'command', 'shell_command'}
CONTEXT_GRAPH_COMMAND_DENY_CONTAINS = (
    'autopsy codex-hook',
    'autopsy context-event',
    'autopsy context-graph-url',
)
CONTEXT_GRAPH_COMMAND_ALLOW_PREFIXES = (
    'autopsy status',
    'autopsy context',
    'autopsy consult',
    'autopsy search',
    'autopsy item',
    'autopsy timeline',
    'autopsy history',
    'autopsy neighbors',
    'git status',
    'git diff',
    'git show',
    'git log',
    'rg',
    'nl',
    'sed',
)
CONTEXT_GRAPH_COMMAND_ALLOW_CONTAINS: tuple[str, ...] = ()
CONTEXT_GRAPH_COMMAND_SETUP_PREFIXES = (
    'cd',
)
CONTEXT_GRAPH_MAX_RENDERED_COMMAND_EVENTS = 24
CONTEXT_GRAPH_METADATA_DENY_KEYS = {
    'content',
    'output',
    'outputs',
    'stdout',
    'stderr',
    'result',
    'response',
    'tool_response',
    'tool_output',
    'text',
}
CONTEXT_GRAPH_METADATA_ALLOW_KEYS = {
    'capture': 'capture',
    'command': 'command',
}
CONTEXT_GRAPH_MEMORY_ENRICH_TTL_SECONDS = 30.0
CONTEXT_GRAPH_MEMORY_RELATION_LIMIT = 4


def context_graph_truthy_setting(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {'1', 'true', 'yes', 'on', 'enabled'}:
        return True
    if text in {'0', 'false', 'no', 'off', 'disabled'}:
        return False
    return default


def load_context_graph_runtime_settings() -> dict:
    try:
        from autopsy_memory.context_graph_settings import load_context_graph_settings
        return load_context_graph_settings()
    except Exception:
        configured = str(
            os.environ.get('AUTOPSY_CONTEXT_GRAPH_SETTINGS_PATH')
            or os.environ.get('AUTOPSY_CONTEXT_GRAPH_SETTINGS')
            or ''
        ).strip()
        path = Path(configured).expanduser() if configured else APP_SUPPORT_DIR_DEFAULT / 'Config' / 'context-graph-settings.json'
        raw = {}
        if path.exists():
            try:
                parsed = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(parsed, dict):
                    raw = parsed
            except Exception:
                raw = {}
        return {
            'enabled': context_graph_truthy_setting(raw.get('enabled'), True),
            'mode': str(raw.get('mode') or 'cli').strip().lower() or 'cli',
            'multi_turn': context_graph_truthy_setting(raw.get('multi_turn') or raw.get('multiTurn'), False),
        }


CONTEXT_GRAPH_COMMAND_OPTION_VALUE_FLAGS = {
    '--workspace',
    '--query',
    '-q',
    '--scope',
    '--repo',
    '--repository-root-path',
    '--kind',
    '--memory-type',
    '--tag',
    '--namespace',
    '--entity-scope',
    '--user-id',
    '--agent-id',
    '--app-id',
    '--run-id',
    '--group-id',
    '--metadata',
    '--filter-json',
    '--min-fact-rating',
    '--limit',
    '--inspect-limit',
    '--relation-limit',
    '--as-of',
    '--stable-key',
    '--thread-id',
}
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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def stable_graph_identifier(key: str) -> int:
    value = 1_469_598_103_934_665_603
    for byte in str(key).encode('utf-8'):
        value ^= byte
        value = (value * 1_099_511_628_211) & 0xffff_ffff_ffff_ffff
    return int(value & 0x7fff_ffff)


def trimmed_excerpt(text: str | None, max_length: int = 220) -> str:
    trimmed = str(text or '').strip()
    if len(trimmed) <= max_length:
        return trimmed
    return trimmed[:max_length].strip() + '...'


def empty_to_none(value: str | None) -> str | None:
    stripped = str(value or '').strip()
    return stripped or None


def context_graph_root_dir() -> Path:
    raw = str(os.environ.get('AUTOPSY_CONTEXT_GRAPH_DIR') or '').strip()
    if raw:
        return Path(raw).expanduser()
    return CONTEXT_GRAPH_DIR_DEFAULT


def context_graph_thread_file(thread_id: str) -> Path:
    digest = hashlib.sha256(str(thread_id).encode('utf-8')).hexdigest()[:32]
    return context_graph_root_dir() / 'threads' / f'{digest}.json'


def normalize_context_event_type(value: str | None) -> str:
    normalized = re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')
    return normalized or 'context_event'


def context_graph_command_title(command: str, max_length: int = 180) -> str:
    text = re.sub(r'\s+', ' ', str(command or '')).strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + '...'


def context_graph_command_matches_prefix(command: str, prefix: str) -> bool:
    return command == prefix or command.startswith(f'{prefix} ') or command.startswith(f'{prefix}\t')


def context_graph_command_has_unsafe_shell_syntax(command: str) -> bool:
    quote = ''
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == '\\':
            escaped = True
            index += 1
            continue
        if quote == "'":
            if char == "'":
                quote = ''
            index += 1
            continue
        if quote == '"':
            if char == '"':
                quote = ''
                index += 1
                continue
            if char == '`' or (char == '$' and index + 1 < len(command) and command[index + 1] == '('):
                return True
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in {'>', '<', '`'}:
            return True
        if char == '$' and index + 1 < len(command) and command[index + 1] == '(':
            return True
        index += 1
    return False


def context_graph_command_segments(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote = ''
    escaped = False
    index = 0

    def flush_segment() -> None:
        segment = ''.join(current).strip()
        current.clear()
        if segment:
            segments.append(segment)

    while index < len(command):
        char = command[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue
        if char == '\\':
            current.append(char)
            escaped = True
            index += 1
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ''
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue
        if char == ';':
            flush_segment()
            index += 1
            continue
        if char == '&' and index + 1 < len(command) and command[index + 1] == '&':
            flush_segment()
            index += 2
            continue
        if char == '&':
            flush_segment()
            segments.append('&')
            index += 1
            continue
        if char == '|':
            if index + 1 < len(command) and command[index + 1] == '|':
                flush_segment()
                index += 2
                continue
            flush_segment()
            index += 1
            continue
        current.append(char)
        index += 1
    flush_segment()
    return segments


def context_graph_command_is_allowed_segment(segment: str) -> bool:
    if context_graph_command_has_disallowed_write_flags(segment):
        return False
    return (
        any(context_graph_command_matches_prefix(segment, prefix) for prefix in CONTEXT_GRAPH_COMMAND_ALLOW_PREFIXES)
        or any(fragment in segment for fragment in CONTEXT_GRAPH_COMMAND_ALLOW_CONTAINS)
    )


def context_graph_command_has_disallowed_write_flags(segment: str) -> bool:
    try:
        parts = shlex.split(segment)
    except ValueError:
        return True
    if not parts:
        return False
    executable = parts[0]
    if executable == 'sed':
        return any(part == '-i' or part.startswith('-i') or part == '--in-place' or part.startswith('--in-place=') for part in parts[1:])
    if executable == 'git' and len(parts) > 1 and parts[1] in {'diff', 'show', 'log', 'status'}:
        return any(part == '--output' or part.startswith('--output=') for part in parts[2:])
    return False


def context_graph_command_is_setup_segment(segment: str) -> bool:
    return any(context_graph_command_matches_prefix(segment, prefix) for prefix in CONTEXT_GRAPH_COMMAND_SETUP_PREFIXES)


def should_capture_context_graph_command(command: str) -> bool:
    raw_text = str(command or '')
    if '\n' in raw_text or '\r' in raw_text:
        return False
    text = re.sub(r'\s+', ' ', raw_text).strip().lower()
    if not text:
        return False
    if context_graph_command_has_unsafe_shell_syntax(text):
        return False
    if any(fragment in text for fragment in CONTEXT_GRAPH_COMMAND_DENY_CONTAINS):
        return False
    saw_allowed_segment = False
    for segment in context_graph_command_segments(text):
        if context_graph_command_is_allowed_segment(segment):
            saw_allowed_segment = True
            continue
        if context_graph_command_is_setup_segment(segment):
            continue
        return False
    return saw_allowed_segment


def context_graph_shell_words(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return []


def context_graph_primary_command_segment(command: str) -> str:
    for segment in context_graph_command_segments(str(command or '')):
        if context_graph_command_is_setup_segment(segment):
            continue
        return segment.strip()
    return ''


def context_graph_option_value(parts: list[str], names: set[str] | tuple[str, ...]) -> str:
    names_set = set(names)
    for index, part in enumerate(parts):
        if part in names_set and index + 1 < len(parts):
            return str(parts[index + 1] or '').strip()
        for name in names_set:
            if part.startswith(f'{name}='):
                return part.split('=', 1)[1].strip()
    return ''


def context_graph_has_flag(parts: list[str], names: set[str] | tuple[str, ...]) -> bool:
    names_set = set(names)
    return any(part in names_set for part in parts)


def context_graph_positionals(parts: list[str], start_index: int) -> list[str]:
    values: list[str] = []
    skip_next = False
    for part in parts[start_index:]:
        if skip_next:
            skip_next = False
            continue
        if part in CONTEXT_GRAPH_COMMAND_OPTION_VALUE_FLAGS:
            skip_next = True
            continue
        if any(part.startswith(f'{flag}=') for flag in CONTEXT_GRAPH_COMMAND_OPTION_VALUE_FLAGS):
            continue
        if part.startswith('-'):
            continue
        values.append(part)
    return values


def context_graph_command_chip(text: str, max_length: int = 54) -> str:
    return trimmed_excerpt(re.sub(r'\s+', ' ', str(text or '')).strip(), max_length)


def context_graph_memory_scope_chips(parts: list[str]) -> list[str]:
    chips: list[str] = []
    if context_graph_has_flag(parts, {'--current-only'}):
        chips.append('current only')
    scope = context_graph_option_value(parts, {'--scope'})
    if scope:
        chips.append(f'scope: {context_graph_command_chip(scope, 28)}')
    repo = context_graph_option_value(parts, {'--repo', '--repository-root-path'})
    if repo:
        chips.append(f'repo: {context_graph_command_chip(Path(repo).name or repo, 28)}')
    kind = context_graph_option_value(parts, {'--kind'})
    if kind:
        chips.append(f'kind: {context_graph_command_chip(kind, 28)}')
    memory_type = context_graph_option_value(parts, {'--memory-type'})
    if memory_type:
        chips.append(f'type: {context_graph_command_chip(memory_type, 28)}')
    return chips


def context_graph_memory_stable_key(parts: list[str], subcommand: str) -> str:
    stable_key = context_graph_option_value(parts, {'--stable-key'})
    if stable_key:
        return stable_key
    if subcommand in {'item', 'timeline', 'history'}:
        positionals = context_graph_positionals(parts, 2)
        return positionals[0] if positionals else ''
    if subcommand == 'neighbors':
        positionals = context_graph_positionals(parts, 2)
        if positionals and not context_graph_option_value(parts, {'--thread-id'}):
            return positionals[0]
    return ''


def context_graph_memory_query(parts: list[str], subcommand: str) -> str:
    query = context_graph_option_value(parts, {'--query', '-q'})
    if query:
        return query
    if subcommand == 'search':
        return ' '.join(context_graph_positionals(parts, 2)).strip()
    return ''


def context_graph_file_search_chips(parts: list[str]) -> list[str]:
    positionals = context_graph_positionals(parts, 1)
    chips: list[str] = []
    if positionals:
        chips.append(f'pattern: {context_graph_command_chip(positionals[0])}')
    if len(positionals) > 1:
        chips.append(f'paths: {context_graph_command_chip(", ".join(positionals[1:3]))}')
    return chips


def context_graph_file_read_chips(parts: list[str]) -> list[str]:
    if not parts:
        return []
    executable = parts[0]
    positionals = context_graph_positionals(parts, 1)
    chips: list[str] = []
    if executable == 'sed':
        script = ''
        if '-n' in parts:
            index = parts.index('-n')
            if index + 1 < len(parts):
                script = parts[index + 1]
        if script:
            chips.append(f'range: {context_graph_command_chip(script, 28)}')
        if positionals:
            chips.append(f'file: {context_graph_command_chip(positionals[-1])}')
    elif positionals:
        chips.append(f'file: {context_graph_command_chip(positionals[-1])}')
    return chips


def context_graph_git_chips(parts: list[str]) -> list[str]:
    if len(parts) < 2:
        return []
    positionals = context_graph_positionals(parts, 2)
    chips: list[str] = []
    if positionals:
        chips.append(f'target: {context_graph_command_chip(", ".join(positionals[:2]))}')
    if context_graph_has_flag(parts, {'--stat'}):
        chips.append('stat')
    if context_graph_has_flag(parts, {'--short'}):
        chips.append('short')
    return chips


def context_graph_command_view(command: str) -> dict:
    segment = context_graph_primary_command_segment(command)
    parts = context_graph_shell_words(segment)
    if not parts:
        return {
            'family': 'command',
            'visual_kind': 'command_context',
            'label': 'Run command',
            'summary': '',
            'chips': [],
        }
    executable = parts[0].lower()
    subcommand = parts[1].lower() if len(parts) > 1 else ''

    if executable == 'autopsy':
        chips = context_graph_memory_scope_chips(parts)
        stable_key = context_graph_memory_stable_key(parts, subcommand)
        query = context_graph_memory_query(parts, subcommand)
        if query:
            chips.insert(0, f'query: {context_graph_command_chip(query)}')
        if stable_key:
            chips.insert(0, f'key: {context_graph_command_chip(stable_key)}')
        memory_views = {
            'status': ('memory_status_context', 'Check memory status'),
            'context': ('memory_query_context', 'Build memory context'),
            'consult': ('memory_query_context', 'Consult memory'),
            'search': ('memory_search_context', 'Search memory'),
            'item': ('memory_item_context', 'Inspect memory item'),
            'timeline': ('memory_timeline_context', 'Review memory timeline'),
            'history': ('memory_history_context', 'Review memory history'),
            'neighbors': ('memory_neighbors_context', 'Read memory relations'),
        }
        visual_kind, label = memory_views.get(subcommand, ('memory_query_context', 'Read memory'))
        return {
            'family': 'memory',
            'subcommand': subcommand,
            'visual_kind': visual_kind,
            'label': label,
            'summary': '\n'.join(chips),
            'chips': chips[:4],
            'stable_key': stable_key,
            'query': query,
            'min_fact_rating': context_graph_option_value(parts, {'--min-fact-rating'}),
        }

    if executable == 'rg':
        chips = context_graph_file_search_chips(parts)
        return {
            'family': 'file',
            'visual_kind': 'file_search_context',
            'label': 'Search files',
            'summary': '\n'.join(chips),
            'chips': chips[:3],
        }

    if executable in {'nl', 'sed'}:
        chips = context_graph_file_read_chips(parts)
        return {
            'family': 'file',
            'visual_kind': 'file_read_context',
            'label': 'Read file',
            'summary': '\n'.join(chips),
            'chips': chips[:3],
        }

    if executable == 'git':
        labels = {
            'status': 'Check git status',
            'diff': 'Review git diff',
            'show': 'Inspect git object',
            'log': 'Read git history',
        }
        chips = context_graph_git_chips(parts)
        return {
            'family': 'git',
            'visual_kind': f'git_{subcommand}_context' if subcommand in labels else 'git_context',
            'label': labels.get(subcommand, 'Inspect git'),
            'summary': '\n'.join(chips),
            'chips': chips[:3],
        }

    return {
        'family': 'command',
        'visual_kind': 'command_context',
        'label': 'Run command',
        'summary': context_graph_command_title(command, 88),
        'chips': [],
    }


def context_graph_command_text(event: dict) -> str:
    metadata = event.get('metadata') if isinstance(event.get('metadata'), dict) else {}
    for value in (metadata.get('command'), event.get('content'), event.get('title')):
        text = str(value or '').strip()
        if text:
            return text
    return ''


def sanitized_context_graph_metadata(metadata: dict) -> dict:
    sanitized: dict = {}
    for key, value in dict(metadata or {}).items():
        normalized_key = re.sub(r'[^a-z0-9]+', '_', str(key or '').strip().lower()).strip('_')
        if not normalized_key or normalized_key in CONTEXT_GRAPH_METADATA_DENY_KEYS:
            continue
        canonical_key = CONTEXT_GRAPH_METADATA_ALLOW_KEYS.get(normalized_key)
        if not canonical_key:
            continue
        sanitized[canonical_key] = value
    return sanitized


def context_graph_skip_result(raw: dict, reason: str, *, event_type: str = '', command: str = '') -> dict:
    thread_id = str(raw.get('thread_id') or raw.get('threadId') or '').strip()
    state = load_context_graph_thread_state(thread_id) if thread_id else {
        'thread_id': thread_id,
        'created_at': utc_now_iso(),
        'updated_at': utc_now_iso(),
        'revision': 0,
        'events': [],
    }
    state['_context_graph_settings'] = load_context_graph_runtime_settings()
    payload = {
        'ok': True,
        'skipped': True,
        'reason': reason,
        'event_type': event_type,
        'thread': context_graph_thread_summary(state),
        'snapshot': build_context_graph_snapshot_from_state(state),
    }
    if command:
        payload['command'] = command
    return payload


def normalize_allowed_context_graph_event(raw: dict) -> tuple[dict | None, dict | None]:
    event = normalize_context_event(raw)
    event_type = normalize_context_event_type(event.get('event_type'))
    if event_type not in CONTEXT_GRAPH_ALLOWED_EVENT_TYPES:
        return None, context_graph_skip_result(raw, 'generic_events_disabled', event_type=event_type)
    command = context_graph_command_text(event)
    if not command:
        return None, context_graph_skip_result(raw, 'command_required', event_type=event_type)
    if not should_capture_context_graph_command(command):
        return None, context_graph_skip_result(raw, 'command_not_allowlisted', event_type=event_type, command=command)
    metadata = sanitized_context_graph_metadata(event.get('metadata') if isinstance(event.get('metadata'), dict) else {})
    metadata['command'] = command
    metadata['capture'] = 'command_only'
    event['event_type'] = 'command'
    event['title'] = context_graph_command_title(command)
    event['content'] = command
    event['metadata'] = metadata
    return event, None


def normalize_context_event(raw: dict) -> dict:
    thread_id = str(raw.get('thread_id') or raw.get('threadId') or '').strip()
    if not thread_id:
        raise ValueError('thread_id is required')
    event_type = normalize_context_event_type(raw.get('event_type') or raw.get('type') or raw.get('kind'))
    timestamp = str(raw.get('timestamp') or '').strip() or utc_now_iso()
    metadata = raw.get('metadata') if isinstance(raw.get('metadata'), dict) else {}
    title = str(raw.get('title') or raw.get('label') or '').strip()
    content = str(raw.get('content') or raw.get('summary') or raw.get('text') or '').strip()
    if not title:
        title = {
            'user_message': 'User Message',
            'assistant_message': 'Assistant Response',
            'reasoning': 'Reasoning',
            'plan': 'Plan',
            'file_read': 'File Read',
            'file_search': 'File Search',
            'web_search': 'Web Search',
            'web_result': 'Web Result',
            'tool_call': 'Tool Call',
            'tool_result': 'Tool Result',
            'command': 'Command',
            'file_change': 'File Change',
            'memory_consult': 'Memory Consult',
            'memory_write': 'Memory Write',
            'instruction': 'Instruction',
        }.get(event_type, event_type.replace('_', ' ').title())
    seed = json.dumps({
        'thread_id': thread_id,
        'event_type': event_type,
        'timestamp': timestamp,
        'title': title,
        'content': content,
        'metadata': metadata,
    }, sort_keys=True)
    event_id = str(raw.get('id') or raw.get('event_id') or raw.get('eventId') or f'ctx-event:{hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]}')
    return {
        'id': event_id,
        'thread_id': thread_id,
        'event_type': event_type,
        'title': title,
        'content': content,
        'timestamp': timestamp,
        'status': str(raw.get('status') or '').strip(),
        'agent': str(raw.get('agent') or '').strip(),
        'app': str(raw.get('app') or '').strip(),
        'run_id': str(raw.get('run_id') or raw.get('runId') or '').strip(),
        'metadata': metadata,
    }


def load_context_graph_thread_state(thread_id: str) -> dict:
    path = context_graph_thread_file(thread_id)
    if not path.exists():
        now = utc_now_iso()
        return {
            'thread_id': thread_id,
            'created_at': now,
            'updated_at': now,
            'revision': 0,
            'events': [],
        }
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        now = utc_now_iso()
        return {
            'thread_id': thread_id,
            'created_at': now,
            'updated_at': now,
            'revision': 0,
            'events': [],
        }
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault('thread_id', thread_id)
    raw.setdefault('created_at', utc_now_iso())
    raw.setdefault('updated_at', raw.get('created_at') or utc_now_iso())
    raw.setdefault('revision', 0)
    events = raw.get('events')
    raw['events'] = events if isinstance(events, list) else []
    return raw


def save_context_graph_thread_state(state: dict) -> None:
    thread_id = str(state.get('thread_id') or '').strip()
    if not thread_id:
        raise ValueError('thread_id is required')
    path = context_graph_thread_file(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + '.tmp')
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding='utf-8')
    tmp_path.replace(path)


def record_context_graph_event(raw: dict) -> dict:
    event, skipped = normalize_allowed_context_graph_event(raw)
    if skipped is not None:
        return skipped
    if event is None:
        raise ValueError('context graph event could not be normalized')
    with _CONTEXT_GRAPH_LOCK:
        state = load_context_graph_thread_state(event['thread_id'])
        state['events'] = [
            existing for existing in list(state.get('events') or [])
            if (
                isinstance(existing, dict)
                and str(existing.get('id') or '') != event['id']
                and context_graph_is_renderable_event(existing)
            )
        ]
        state['events'].append(event)
        state['events'].sort(key=lambda item: str(item.get('timestamp') or ''))
        state['revision'] = int(state.get('revision') or 0) + 1
        state['updated_at'] = utc_now_iso()
        save_context_graph_thread_state(state)
    state['_context_graph_settings'] = load_context_graph_runtime_settings()
    return {
        'event': event,
        'thread': context_graph_thread_summary(state),
        'snapshot': build_context_graph_snapshot_from_state(state),
    }


def context_graph_thread_summary(state: dict) -> dict:
    events = context_graph_allowed_command_events(state.get('events') or [])
    thread_id = str(state.get('thread_id') or '')
    return {
        'thread_id': thread_id,
        'revision': int(state.get('revision') or 0),
        'event_count': len(events),
        'created_at': str(state.get('created_at') or ''),
        'updated_at': str(state.get('updated_at') or ''),
        'latest_event': events[-1] if events else None,
    }


def list_context_graph_threads(limit: int = 40) -> list[dict]:
    root = context_graph_root_dir() / 'threads'
    if not root.exists():
        return []
    summaries: list[dict] = []
    for path in root.glob('*.json'):
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(raw, dict):
            summaries.append(context_graph_thread_summary(raw))
    summaries.sort(key=lambda item: str(item.get('updated_at') or ''), reverse=True)
    return summaries[:max(1, limit)]


def context_graph_event_title(event: dict) -> str:
    return trimmed_excerpt(context_graph_command_text(event), 88)


def context_graph_event_run_id(event: dict) -> str:
    metadata = event.get('metadata') if isinstance(event.get('metadata'), dict) else {}
    return str(
        event.get('run_id')
        or event.get('runId')
        or metadata.get('turn_id')
        or metadata.get('turnId')
        or ''
    ).strip()


def context_graph_event_turn_key(event: dict, fallback_index: int) -> str:
    run_id = context_graph_event_run_id(event)
    if run_id:
        return run_id
    timestamp = str(event.get('timestamp') or event.get('created_at') or '').strip()
    if timestamp:
        return f'manual:{timestamp}'
    return f'manual:{fallback_index}'


def context_graph_turn_groups(events: list[dict]) -> list[dict]:
    groups_by_key: dict[str, dict] = {}
    ordered_keys: list[str] = []
    for index, event in enumerate(events):
        key = context_graph_event_turn_key(event, index)
        if key not in groups_by_key:
            groups_by_key[key] = {
                'key': key,
                'run_id': context_graph_event_run_id(event),
                'events': [],
                'first_timestamp': str(event.get('timestamp') or event.get('created_at') or '').strip(),
                'latest_timestamp': '',
            }
            ordered_keys.append(key)
        groups_by_key[key]['events'].append(event)
        timestamp = str(event.get('timestamp') or event.get('created_at') or '').strip()
        if timestamp:
            groups_by_key[key]['latest_timestamp'] = timestamp
    return [groups_by_key[key] for key in ordered_keys]


def context_graph_is_turn_scoping_event(event: dict) -> bool:
    event_type = normalize_context_event_type(event.get('event_type'))
    if event_type not in {'command', 'shell_command'}:
        return False
    return should_capture_context_graph_command(context_graph_command_text(event))


def context_graph_allowed_command_events(events: list[dict]) -> list[dict]:
    return [
        event for event in events
        if isinstance(event, dict) and context_graph_is_turn_scoping_event(event)
    ]


def context_graph_current_turn_events(events: list[dict]) -> list[dict]:
    candidate_events = [
        event for event in events
        if isinstance(event, dict) and context_graph_is_turn_scoping_event(event)
    ]
    latest_run_id = ''
    for event in reversed(candidate_events):
        if context_graph_is_turn_scoping_event(event):
            latest_run_id = context_graph_event_run_id(event)
            if latest_run_id:
                break
    if not latest_run_id:
        return candidate_events
    latest_run_start_index = 0
    for index, event in enumerate(candidate_events):
        if context_graph_is_turn_scoping_event(event) and context_graph_event_run_id(event) == latest_run_id:
            latest_run_start_index = index
            break
    return [
        event for event in candidate_events[latest_run_start_index:]
        if not context_graph_event_run_id(event) or context_graph_event_run_id(event) == latest_run_id
    ]


def context_graph_is_renderable_event(event: dict) -> bool:
    return context_graph_is_turn_scoping_event(event)


def context_graph_render_key(event: dict) -> str:
    metadata = event.get('metadata') if isinstance(event.get('metadata'), dict) else {}
    tool_use_id = str(metadata.get('tool_use_id') or metadata.get('toolUseId') or '').strip()
    if tool_use_id:
        run_id = context_graph_event_run_id(event)
        return f'tool:{run_id}:{tool_use_id}'
    event_id = str(event.get('id') or event.get('event_id') or event.get('eventId') or '').strip()
    if event_id:
        return f'event:{event_id}'
    return 'command:' + hashlib.sha256(context_graph_command_text(event).encode('utf-8')).hexdigest()[:24]


def deduplicated_context_graph_render_events(events: list[dict]) -> list[dict]:
    ordered_keys: list[str] = []
    events_by_key: dict[str, dict] = {}
    for event in events:
        key = context_graph_render_key(event)
        if key in events_by_key:
            ordered_keys = [existing for existing in ordered_keys if existing != key]
        ordered_keys.append(key)
        events_by_key[key] = event
    return [events_by_key[key] for key in ordered_keys]


def context_graph_memory_node_from_item(item: dict | None) -> dict | None:
    if not isinstance(item, dict):
        return None
    stable_key = str(item.get('stable_key') or item.get('stableKey') or item.get('entity_stable_key') or '').strip()
    if not stable_key:
        return None
    kind = str(item.get('kind') or item.get('entity_kind') or '').strip()
    label = str(item.get('title') or item.get('label') or item.get('entity_label') or stable_key).strip()
    return {
        'stable_key': stable_key,
        'kind': kind or 'memory',
        'label': label or stable_key,
        'summary': str(kind or item.get('memory_type') or 'memory').strip(),
        'updated_at': str(item.get('updated_at') or item.get('activity_at') or '').strip(),
    }


def context_graph_empty_memory_enrichment() -> dict:
    return {'items': [], 'relations': []}


def context_graph_memory_enrichment_from_item(item: dict, relations: list[dict]) -> dict:
    center = context_graph_memory_node_from_item(item)
    if center is None:
        return context_graph_empty_memory_enrichment()
    items: dict[str, dict] = {center['stable_key']: center}
    rendered_relations: list[dict] = []
    for relation in relations[:CONTEXT_GRAPH_MEMORY_RELATION_LIMIT]:
        if not isinstance(relation, dict):
            continue
        related = context_graph_memory_node_from_item(relation)
        if related is None:
            continue
        items[related['stable_key']] = related
        direction = str(relation.get('direction') or 'outgoing').strip().lower()
        if direction == 'incoming':
            from_key, to_key = related['stable_key'], center['stable_key']
        else:
            from_key, to_key = center['stable_key'], related['stable_key']
        rendered_relations.append({
            'from': from_key,
            'to': to_key,
            'relation': str(relation.get('relation') or '').strip() or 'related_to',
            'predicate': str(relation.get('predicate') or relation.get('relation') or '').strip() or 'related_to',
            'fact_text': str(relation.get('fact_text') or '').strip(),
            'fact_rating': relation.get('fact_rating'),
        })
    return {'items': list(items.values()), 'relations': rendered_relations}


def context_graph_memory_enrichment_from_relationship_hits(hits: list[dict], candidates: list[dict]) -> dict:
    items: dict[str, dict] = {}
    for candidate in candidates:
        node = context_graph_memory_node_from_item({
            'stable_key': candidate.get('stable_key'),
            'kind': candidate.get('kind'),
            'label': candidate.get('title') or candidate.get('label'),
            'summary': candidate.get('preview') or candidate.get('summary'),
            'updated_at': candidate.get('updated_at') or candidate.get('activity_at'),
        })
        if node is not None:
            items[node['stable_key']] = node
    relations: list[dict] = []
    for hit in hits[:CONTEXT_GRAPH_MEMORY_RELATION_LIMIT]:
        if not isinstance(hit, dict):
            continue
        source_key = str(hit.get('source_stable_key') or '').strip()
        target_key = str(hit.get('target_stable_key') or '').strip()
        if not source_key or not target_key:
            continue
        items.setdefault(source_key, {
            'stable_key': source_key,
            'kind': 'memory',
            'label': str(hit.get('source_label') or source_key).strip(),
            'summary': 'memory',
            'updated_at': str(hit.get('updated_at') or '').strip(),
        })
        items.setdefault(target_key, {
            'stable_key': target_key,
            'kind': 'memory',
            'label': str(hit.get('target_label') or target_key).strip(),
            'summary': 'memory',
            'updated_at': str(hit.get('updated_at') or '').strip(),
        })
        relations.append({
            'from': source_key,
            'to': target_key,
            'relation': str(hit.get('relation') or '').strip() or 'related_to',
            'predicate': str(hit.get('predicate') or hit.get('relation') or '').strip() or 'related_to',
            'fact_text': str(hit.get('fact_text') or '').strip(),
            'fact_rating': hit.get('fact_rating'),
        })
    return {'items': list(items.values()), 'relations': relations}


def context_graph_merge_memory_enrichments(enrichments: list[dict]) -> dict:
    items: dict[str, dict] = {}
    relations: dict[tuple[str, str, str, str], dict] = {}
    for enrichment in enrichments:
        if not isinstance(enrichment, dict):
            continue
        for item in enrichment.get('items') or []:
            if not isinstance(item, dict):
                continue
            stable_key = str(item.get('stable_key') or '').strip()
            if stable_key and stable_key not in items:
                items[stable_key] = item
        for relation in enrichment.get('relations') or []:
            if not isinstance(relation, dict):
                continue
            relation_key = (
                str(relation.get('from') or ''),
                str(relation.get('to') or ''),
                str(relation.get('relation') or ''),
                str(relation.get('fact_text') or ''),
            )
            if relation_key not in relations:
                relations[relation_key] = relation
    return {
        'items': list(items.values()),
        'relations': list(relations.values())[:CONTEXT_GRAPH_MEMORY_RELATION_LIMIT],
    }


def context_graph_default_memory_context():
    payload = {
        'tool_path': str(Path(__file__).resolve().with_name('cli.py')),
        'cwd': os.getcwd(),
    }
    return load_falkor_request_context(payload, include_embeddings_status=False)


def context_graph_fetch_memory_enrichment_uncached(view: dict) -> dict:
    if view.get('family') != 'memory':
        return context_graph_empty_memory_enrichment()
    stable_key = str(view.get('stable_key') or '').strip()
    query = str(view.get('query') or '').strip()
    if not stable_key and not query:
        return context_graph_empty_memory_enrichment()
    try:
        _tool, module, _workspace, _embeddings_config, _embeddings_status, falkor = context_graph_default_memory_context()
    except Exception:
        return context_graph_empty_memory_enrichment()

    subcommand = str(view.get('subcommand') or '').strip().lower()
    min_fact_rating_raw = str(view.get('min_fact_rating') or '').strip()
    min_fact_rating = None
    if min_fact_rating_raw:
        try:
            min_fact_rating = float(min_fact_rating_raw)
        except ValueError:
            min_fact_rating = None

    try:
        if stable_key:
            def fetch_direct(graph):
                if subcommand == 'timeline':
                    payload = module.fetch_timeline(graph, stable_key)
                    item = payload.get('item') if isinstance(payload, dict) else {}
                    relations = payload.get('events') if isinstance(payload, dict) else []
                    return context_graph_memory_enrichment_from_item(item or {}, relations or [])
                item = module.fetch_item(graph, stable_key)
                return context_graph_memory_enrichment_from_item(item, list(item.get('relations') or []))

            return run_falkor_operation(falkor, fetch_direct)

        if query and subcommand in {'context', 'consult', 'search'}:
            def fetch_query_relations(graph):
                enrichments: list[dict] = []
                candidates: list[dict] = []
                if hasattr(module, 'fetch_relationship_matches'):
                    hits, relationship_candidates, _elapsed = module.fetch_relationship_matches(
                        graph,
                        query,
                        limit=CONTEXT_GRAPH_MEMORY_RELATION_LIMIT,
                        min_fact_rating=min_fact_rating,
                    )
                    relationship_enrichment = context_graph_memory_enrichment_from_relationship_hits(hits, relationship_candidates)
                    if relationship_enrichment.get('relations'):
                        enrichments.append(relationship_enrichment)
                    candidates.extend(relationship_candidates)
                for fetch_name in ('fetch_exact_text_candidates', 'fetch_node_lexical', 'fetch_token_overlap_candidates'):
                    fetcher = getattr(module, fetch_name, None)
                    if not callable(fetcher):
                        continue
                    try:
                        fetched, _elapsed = fetcher(graph, query, limit=CONTEXT_GRAPH_MEMORY_RELATION_LIMIT)
                    except Exception:
                        continue
                    candidates.extend(fetched or [])
                ranked: dict[str, dict] = {}
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    stable_key = str(candidate.get('stable_key') or '').strip()
                    if not stable_key or stable_key in ranked:
                        continue
                    ranked[stable_key] = candidate
                sorter = getattr(module, 'sort_candidates', None)
                candidate_list = list(ranked.values())
                if callable(sorter):
                    try:
                        candidate_list = sorter(candidate_list)
                    except Exception:
                        candidate_list = sorted(candidate_list, key=lambda item: str(item.get('stable_key') or ''))
                for candidate in candidate_list[:2]:
                    stable_key = str(candidate.get('stable_key') or '').strip()
                    if not stable_key:
                        continue
                    try:
                        item = module.fetch_item(graph, stable_key)
                    except (Exception, SystemExit):
                        continue
                    enrichments.append(context_graph_memory_enrichment_from_item(item, list(item.get('relations') or [])))
                return context_graph_merge_memory_enrichments(enrichments)

            return run_falkor_operation(falkor, fetch_query_relations)
    except (Exception, SystemExit):
        return context_graph_empty_memory_enrichment()
    return context_graph_empty_memory_enrichment()


def context_graph_memory_enrichment_for_command(command: str, view: dict) -> dict:
    if view.get('family') != 'memory':
        return context_graph_empty_memory_enrichment()
    cache_key = hashlib.sha256(json.dumps({
        'command': str(command or ''),
        'view': {
            'subcommand': view.get('subcommand'),
            'stable_key': view.get('stable_key'),
            'query': view.get('query'),
            'min_fact_rating': view.get('min_fact_rating'),
        },
        'cwd': os.getcwd(),
    }, sort_keys=True).encode('utf-8')).hexdigest()
    now = time.monotonic()
    cached = _CONTEXT_GRAPH_MEMORY_ENRICH_CACHE.get(cache_key)
    if cached is not None and now - float(cached.get('cached_at') or 0.0) < CONTEXT_GRAPH_MEMORY_ENRICH_TTL_SECONDS:
        return copy.deepcopy(cached.get('payload') or context_graph_empty_memory_enrichment())
    payload = context_graph_fetch_memory_enrichment_uncached(view)
    _CONTEXT_GRAPH_MEMORY_ENRICH_CACHE.clear()
    _CONTEXT_GRAPH_MEMORY_ENRICH_CACHE[cache_key] = {
        'cached_at': now,
        'payload': copy.deepcopy(payload),
    }
    return payload


def build_context_graph_snapshot(thread_id: str) -> dict:
    with _CONTEXT_GRAPH_LOCK:
        state = load_context_graph_thread_state(thread_id)
    state['_context_graph_settings'] = load_context_graph_runtime_settings()
    return build_context_graph_snapshot_from_state(state)


def build_context_graph_snapshot_from_state(state: dict) -> dict:
    thread_id = str(state.get('thread_id') or '')
    settings = state.get('_context_graph_settings') if isinstance(state.get('_context_graph_settings'), dict) else {}
    multi_turn = bool(settings.get('multi_turn'))
    all_events = context_graph_allowed_command_events(state.get('events') or [])
    current_turn_events = all_events if multi_turn else context_graph_current_turn_events(all_events)
    renderable_events = deduplicated_context_graph_render_events([
        event for event in current_turn_events if context_graph_is_renderable_event(event)
    ])
    events = renderable_events[-CONTEXT_GRAPH_MAX_RENDERED_COMMAND_EVENTS:]
    turn_groups = context_graph_turn_groups(events) if multi_turn else []
    uses_turn_focus = bool(multi_turn and turn_groups)
    scope_key = 'multi-turn' if multi_turn else 'turn'
    scope_label = 'Multi-Turn Context' if multi_turn else 'Current Turn'
    public_scope_title = 'Multi-Turn Context' if multi_turn else 'Current Context'
    root_id = stable_graph_identifier(f'context-graph:{scope_key}:{thread_id}')
    # Completion/lifecycle records are intentionally not graph events; the graph is command-derived only.
    is_complete = False
    event_summary = f"{'Complete' if is_complete else 'In Progress'} - {len(events)} active event{'s' if len(events) != 1 else ''}"
    if multi_turn and turn_groups:
        event_summary += f" across {len(turn_groups)} turn{'s' if len(turn_groups) != 1 else ''}"
    nodes: list[dict] = [] if uses_turn_focus else [{
        'id': root_id,
        'kind': 'turn_context',
        'label': scope_label,
        'summary': event_summary,
        'stateFlags': ['complete'] if is_complete else ['current', 'in_progress'],
        'isFocus': True,
        'sourceKind': 'context_graph_thread',
        'sourceRef': thread_id,
        'turnScope': 'multi_turn' if multi_turn else 'current_turn',
    }]
    connections: list[dict] = []
    seen_nodes: dict[str, int] = {} if uses_turn_focus else {'root': root_id}
    seen_edges: set[str] = set()
    focus_node_id = root_id

    def add_node(
        *,
        key: str,
        kind: str,
        label: str,
        summary: str | None,
        state_flags: list[str],
        source_kind: str | None,
        source_ref: str | None,
        visual_kind: str | None = None,
        detail_chips: list[str] | None = None,
        updated_at: str | None = None,
        provenance: dict | None = None,
        is_focus: bool = False,
    ) -> int:
        if key in seen_nodes:
            node_id = seen_nodes[key]
            for index, node in enumerate(nodes):
                if node.get('id') == node_id:
                    merged_flags = sorted(set(list(node.get('stateFlags') or []) + state_flags))
                    merged_chips = list(node.get('detailChips') or [])
                    for chip in detail_chips or []:
                        if chip and chip not in merged_chips:
                            merged_chips.append(chip)
                    nodes[index] = {
                        **node,
                        'summary': node.get('summary') or summary,
                        'stateFlags': merged_flags,
                        'sourceKind': node.get('sourceKind') or source_kind,
                        'sourceRef': node.get('sourceRef') or source_ref,
                        'visualKind': node.get('visualKind') or visual_kind,
                        'detailChips': merged_chips,
                        'updatedAt': node.get('updatedAt') or updated_at,
                        'provenance': node.get('provenance') or provenance,
                        'isFocus': bool(node.get('isFocus')) or bool(is_focus),
                    }
                    break
            return node_id
        node_id = stable_graph_identifier(f'context-graph:node:{thread_id}:{key}')
        seen_nodes[key] = node_id
        node = {
            'id': node_id,
            'kind': kind,
            'label': trimmed_excerpt(label, 88) or kind.replace('_', ' ').title(),
            'summary': empty_to_none(summary),
            'stateFlags': sorted(set(state_flags)),
            'isFocus': bool(is_focus),
            'sourceKind': source_kind,
            'sourceRef': source_ref,
        }
        if visual_kind:
            node['visualKind'] = visual_kind
        if detail_chips:
            node['detailChips'] = [chip for chip in detail_chips if chip][:4]
        if updated_at:
            node['updatedAt'] = updated_at
        if provenance:
            node['provenance'] = provenance
        nodes.append(node)
        return node_id

    def add_edge(
        relation: str,
        from_node_id: int,
        to_node_id: int,
        explanation: str | None = None,
        *,
        predicate: str | None = None,
        subject_label: str | None = None,
        subject_kind: str | None = None,
        object_label: str | None = None,
        object_kind: str | None = None,
        fact_text: str | None = None,
        overlap_terms: list[str] | None = None,
        is_explicit: bool = True,
    ) -> None:
        edge_key = f'{relation}:{from_node_id}:{to_node_id}'
        if edge_key in seen_edges:
            return
        seen_edges.add(edge_key)
        connections.append({
            'id': stable_graph_identifier(f'context-graph:edge:{thread_id}:{edge_key}'),
            'relation': relation,
            'predicate': predicate or relation,
            'fromNodeID': from_node_id,
            'toNodeID': to_node_id,
            'subjectLabel': subject_label,
            'subjectKind': subject_kind,
            'objectLabel': object_label,
            'objectKind': object_kind,
            'factText': fact_text,
            'explanation': explanation or fact_text,
            'overlapTerms': overlap_terms or [],
            'isExplicit': is_explicit,
            'predicateDefinition': None,
        })

    def add_memory_enrichment(command_node_id: int, command: str, view: dict) -> None:
        enrichment = context_graph_memory_enrichment_for_command(command, view)
        memory_nodes = enrichment.get('items') if isinstance(enrichment, dict) else []
        memory_relations = enrichment.get('relations') if isinstance(enrichment, dict) else []
        if not isinstance(memory_nodes, list):
            memory_nodes = []
        if not isinstance(memory_relations, list):
            memory_relations = []
        memory_node_ids: dict[str, int] = {}
        memory_node_payloads: dict[str, dict] = {}
        for item in memory_nodes[:CONTEXT_GRAPH_MEMORY_RELATION_LIMIT * 2 + 1]:
            if not isinstance(item, dict):
                continue
            stable_key = str(item.get('stable_key') or '').strip()
            if not stable_key:
                continue
            memory_node_payloads[stable_key] = item
            memory_node_ids[stable_key] = add_node(
                key=f'memory:{stable_key}',
                kind='graph_memory',
                label=str(item.get('label') or stable_key),
                summary=str(item.get('summary') or item.get('kind') or 'memory'),
                state_flags=['consulted'],
                source_kind='autopsy_memory',
                source_ref=stable_key,
                visual_kind='graph_memory',
                detail_chips=[str(item.get('kind') or 'memory')],
                updated_at=str(item.get('updated_at') or ''),
            )
        stable_key = str(view.get('stable_key') or '').strip()
        if stable_key and stable_key in memory_node_ids:
            add_edge('read_memory', command_node_id, memory_node_ids[stable_key], 'Memory command target')
        for relation in memory_relations[:CONTEXT_GRAPH_MEMORY_RELATION_LIMIT]:
            if not isinstance(relation, dict):
                continue
            from_key = str(relation.get('from') or '').strip()
            to_key = str(relation.get('to') or '').strip()
            if from_key not in memory_node_ids or to_key not in memory_node_ids:
                continue
            relation_name = str(relation.get('relation') or 'related_to').strip() or 'related_to'
            predicate = str(relation.get('predicate') or relation_name).strip() or relation_name
            from_payload = memory_node_payloads.get(from_key) or {}
            to_payload = memory_node_payloads.get(to_key) or {}
            add_edge(
                relation_name,
                memory_node_ids[from_key],
                memory_node_ids[to_key],
                str(relation.get('fact_text') or '').strip() or None,
                predicate=predicate,
                subject_label=str(from_payload.get('label') or from_key),
                subject_kind=str(from_payload.get('kind') or 'memory'),
                object_label=str(to_payload.get('label') or to_key),
                object_kind=str(to_payload.get('kind') or 'memory'),
                fact_text=str(relation.get('fact_text') or '').strip() or None,
                overlap_terms=[predicate],
            )
        if not stable_key and memory_node_ids:
            for key, node_id in list(memory_node_ids.items())[:CONTEXT_GRAPH_MEMORY_RELATION_LIMIT]:
                add_edge('retrieved', command_node_id, node_id, 'Matched by memory relation text')

    command_events = [
        event for event in events
        if normalize_context_event_type(event.get('event_type')) in {'command', 'shell_command'}
    ]
    parent_node_by_event_key: dict[str, int] = {}
    latest_turn_key = turn_groups[-1].get('key') if turn_groups else ''
    if multi_turn and turn_groups:
        turn_node_ids: list[int] = []
        latest_turn_node_id: int | None = None
        for index, group in enumerate(turn_groups):
            group_key = str(group.get('key') or f'turn:{index}').strip()
            group_events = group.get('events') if isinstance(group.get('events'), list) else []
            run_id = str(group.get('run_id') or '').strip()
            is_latest_turn = group_key == latest_turn_key
            turn_label = 'Current Turn' if is_latest_turn else f'Turn {index + 1}'
            event_count = len(group_events)
            chips = [f'{event_count} event{"s" if event_count != 1 else ""}']
            if run_id:
                chips.append(f'run: {context_graph_command_chip(run_id, 28)}')
            turn_node_id = add_node(
                key=f'turn:{group_key}',
                kind='turn_context' if is_latest_turn else 'history_context',
                label=turn_label,
                summary=f"{event_count} captured command{'s' if event_count != 1 else ''}",
                state_flags=['current', 'in_progress'] if is_latest_turn else ['complete'],
                source_kind='context_graph_turn',
                source_ref=run_id or group_key,
                visual_kind=None if is_latest_turn else 'turn_group_context',
                detail_chips=chips,
                updated_at=str(group.get('latest_timestamp') or group.get('first_timestamp') or '').strip() or None,
                provenance={
                    'run_id': run_id,
                    'turn_index': index + 1,
                    'turn_count': len(turn_groups),
                    'current': is_latest_turn,
                },
                is_focus=is_latest_turn,
            )
            turn_node_ids.append(turn_node_id)
            if is_latest_turn:
                latest_turn_node_id = turn_node_id
                focus_node_id = turn_node_id
            for event in group_events:
                parent_node_by_event_key[context_graph_render_key(event)] = turn_node_id
        if latest_turn_node_id:
            for turn_node_id in turn_node_ids:
                if turn_node_id != latest_turn_node_id:
                    add_edge('previous_turn', turn_node_id, latest_turn_node_id, 'Previous turn retained for context')

    if not is_complete and events:
        reasoning_id = add_node(
            key='active:reasoning',
            kind='reasoning_context',
            label='Reasoning',
            summary='Turn in play',
            state_flags=['current', 'in_progress'],
            source_kind='context_graph_runtime',
            source_ref='active_turn',
        )
        add_edge('reasoned_with', reasoning_id, parent_node_by_event_key.get(context_graph_render_key(events[-1]), root_id))

    collapsed_file_reads_by_parent: dict[int, list[tuple[dict, str, dict, list[str], str]]] = {}

    def add_command_event_node(event: dict, command: str, command_view: dict, state_flags: list[str], event_id: str, parent_node_id: int) -> int:
        command_node_id = add_node(
            key=f'command:{context_graph_render_key(event)}',
            kind='command_context',
            label=str(command_view.get('label') or context_graph_event_title(event)),
            summary=str(command_view.get('summary') or '') or None,
            state_flags=state_flags,
            source_kind='context_graph_event',
            source_ref=str(command_view.get('stable_key') or event_id),
            visual_kind=str(command_view.get('visual_kind') or 'command_context'),
            detail_chips=list(command_view.get('chips') or []),
            provenance={'command': command, 'family': command_view.get('family')},
        )
        add_edge('consulted', command_node_id, parent_node_id)
        return command_node_id

    for event in command_events:
        event_id = str(event.get('id') or event.get('event_id') or event.get('eventId') or context_graph_render_key(event)).strip()
        state_flags = ['consulted']
        status = normalize_context_event_type(event.get('status'))
        if status in {'in_progress', 'running'}:
            state_flags.append('in_progress')
        elif status in {'blocked', 'error'}:
            state_flags.append(status)
        command = context_graph_command_text(event)
        command_view = context_graph_command_view(command)
        parent_node_id = parent_node_by_event_key.get(context_graph_render_key(event), root_id)
        if command_view.get('visual_kind') == 'file_read_context':
            collapsed_file_reads_by_parent.setdefault(parent_node_id, []).append((event, command, command_view, state_flags, event_id))
            continue
        command_node_id = add_command_event_node(event, command, command_view, state_flags, event_id, parent_node_id)
        if command_view.get('family') == 'memory':
            add_memory_enrichment(command_node_id, command, command_view)

    for parent_node_id, collapsed_file_reads in collapsed_file_reads_by_parent.items():
        merged_flags: list[str] = []
        merged_chips: list[str] = [f'{len(collapsed_file_reads)} read command{"s" if len(collapsed_file_reads) != 1 else ""}']
        commands: list[str] = []
        for _event, command, command_view, state_flags, _event_id in collapsed_file_reads:
            commands.append(command)
            for flag in state_flags:
                if flag not in merged_flags:
                    merged_flags.append(flag)
            for chip in list(command_view.get('chips') or []):
                if chip and chip not in merged_chips:
                    merged_chips.append(chip)
        summary_files = [chip for chip in merged_chips[1:] if chip.startswith('file: ')][:5]
        summary = f"{len(collapsed_file_reads)} read command{'s' if len(collapsed_file_reads) != 1 else ''}"
        if summary_files:
            summary += '\n' + '\n'.join(summary_files)
        file_read_node_id = add_node(
            key=f'command:file_read_context:collapsed:{parent_node_id}',
            kind='command_context',
            label='Read files' if len(collapsed_file_reads) != 1 else 'Read file',
            summary=summary,
            state_flags=merged_flags or ['consulted'],
            source_kind='context_graph_event',
            source_ref=f'file_read_context:{parent_node_id}',
            visual_kind='file_read_context',
            detail_chips=merged_chips,
            provenance={
                'family': 'file',
                'collapsed': True,
                'command_count': len(collapsed_file_reads),
                'commands': commands[:12],
            },
        )
        add_edge('consulted', file_read_node_id, parent_node_id)

    thread_summary = context_graph_thread_summary(state)
    thread_summary['event_count'] = len(events)
    thread_summary['latest_event'] = events[-1] if events else None
    thread_summary['turn_scope'] = 'multi_turn' if multi_turn else 'current_turn'

    return {
        'scopeTitle': public_scope_title,
        'focusNodeID': focus_node_id,
        'nodes': nodes,
        'connections': connections,
        'recentEpisodes': [],
        'conflictSuggestions': [],
        'thread': thread_summary,
        'events': events[-80:],
        'allEventCount': len(renderable_events),
        'turnScope': 'multi_turn' if multi_turn else 'current_turn',
    }


def context_graph_viewer_static_root() -> Path | None:
    override = str(os.environ.get('AUTOPSY_CONTEXT_GRAPH_STATIC_DIR') or '').strip()
    if override:
        path = Path(override).expanduser()
        return path if path.exists() else None
    try:
        root = Path(str(resources.files('autopsy_memory.context_graph_viewer').joinpath('static')))
        if root.exists():
            return root
    except Exception:
        pass
    direct_script_root = Path(__file__).resolve().parent / 'context_graph_viewer' / 'static'
    if direct_script_root.exists():
        return direct_script_root
    return None


def context_graph_thread_url(base_url: str, token: str, thread_id: str) -> str:
    encoded_thread = quote_path_segment(thread_id)
    return f'{base_url.rstrip("/")}/context-graph/threads/{encoded_thread}?token={token}'


def quote_path_segment(value: str) -> str:
    from urllib.parse import quote
    return quote(str(value), safe='')


def context_graph_index_html() -> bytes:
    root = context_graph_viewer_static_root()
    index_path = root / 'index.html' if root else None
    if index_path and index_path.exists():
        return index_path.read_bytes()
    return b"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Autopsy Context Graph</title>
    <style>
      body { margin: 0; font: 14px system-ui, sans-serif; background: #f4f1ea; color: #1d2228; }
      main { min-height: 100vh; display: grid; place-items: center; padding: 32px; box-sizing: border-box; }
      section { max-width: 720px; border: 1px solid rgba(29,34,40,.14); background: rgba(255,255,255,.72); border-radius: 16px; padding: 24px; }
      code { background: rgba(29,34,40,.08); padding: 2px 5px; border-radius: 5px; }
    </style>
  </head>
  <body>
    <main>
      <section>
        <h1>Autopsy Context Graph</h1>
        <p>The bundled graph viewer assets are not built yet. Run the context graph app build or install a package that includes <code>autopsy_memory/context_graph_viewer/static</code>.</p>
      </section>
    </main>
  </body>
</html>"""


def context_graph_static_asset(path: str) -> tuple[bytes, str] | None:
    root = context_graph_viewer_static_root()
    if root is None:
        return None
    relative = Path(unquote(path).lstrip('/'))
    if relative.is_absolute() or '..' in relative.parts:
        return None
    target = (root / relative).resolve()
    try:
        root_resolved = root.resolve()
    except Exception:
        return None
    if root_resolved not in target.parents and target != root_resolved:
        return None
    if not target.is_file():
        return None
    content_type = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
    return target.read_bytes(), content_type


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
        server.shutdown_reason = reason
        server.shutdown_requested = True
        print(f'autopsy worker exiting: {reason}', file=sys.stderr, flush=True)
        threading.Thread(target=force_exit_if_still_running, args=(server,), daemon=True).start()
        threading.Thread(target=server.shutdown, daemon=True).start()
        return


def force_exit_if_still_running(server, delay_seconds: float = 5.0) -> None:
    time.sleep(delay_seconds)
    if bool(getattr(server, 'shutdown_requested', False)):
        os._exit(0)


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
        if parsed.path.startswith('/context-graph/assets/'):
            asset = context_graph_static_asset(parsed.path.removeprefix('/context-graph/'))
            if asset is None:
                self._write_json(404, {'error': 'not found'})
                return
            body, content_type = asset
            self._write_bytes(200, body, content_type)
            return
        if parsed.path == '/context-graph' or parsed.path == '/context-graph/':
            if not self._require_token():
                return
            self._write_bytes(200, context_graph_index_html(), 'text/html; charset=utf-8')
            return
        if parsed.path.startswith('/context-graph/threads/'):
            if not self._require_token():
                return
            self._write_bytes(200, context_graph_index_html(), 'text/html; charset=utf-8')
            return
        if parsed.path.startswith('/context-graph/api/threads/') and parsed.path.endswith('/snapshot'):
            if not self._require_token():
                return
            thread_id = unquote(parsed.path.removeprefix('/context-graph/api/threads/').removesuffix('/snapshot').strip('/'))
            self._write_json(200, build_context_graph_snapshot(thread_id))
            return
        if parsed.path == '/context-graph/api/threads':
            if not self._require_token():
                return
            limit_values = parse_qs(parsed.query).get('limit', ['40'])
            try:
                limit = max(1, int(limit_values[0]))
            except Exception:
                limit = 40
            self._write_json(200, {'threads': list_context_graph_threads(limit=limit)})
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
            if parsed.path == '/context-graph/events':
                request = payload.get('request') if isinstance(payload.get('request'), dict) else payload
                result = record_context_graph_event(request)
                event = result.get('event') if isinstance(result.get('event'), dict) else {}
                thread = result.get('thread') if isinstance(result.get('thread'), dict) else {}
                thread_id = str(event.get('thread_id') or thread.get('thread_id') or request.get('thread_id') or request.get('threadId') or '').strip()
                result['url'] = context_graph_thread_url(
                    f'http://{self.server.server_address[0]}:{self.server.server_port}',
                    self.server.auth_token,
                    thread_id,
                )
                self._write_json(200, result)
                return
            if parsed.path == '/context-graph/thread':
                request = payload.get('request') if isinstance(payload.get('request'), dict) else payload
                thread_id = str(request.get('thread_id') or request.get('threadId') or '').strip()
                if not thread_id:
                    raise ValueError('thread_id is required')
                self._write_json(200, build_context_graph_snapshot(thread_id))
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
