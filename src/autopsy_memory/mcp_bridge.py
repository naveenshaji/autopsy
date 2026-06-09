#!/usr/bin/env python3
import argparse
import fcntl
import importlib.metadata
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


SERVER_NAME = "autopsy_falkor_memory"
SERVER_VERSION = "0.1.0"
DEFAULT_GRAPH_NAME = "autopsy_memory"
RELATION_FIELDS = ("informed_by", "answers", "supersedes", "reverts", "depends_on", "implements", "constrains", "refines")
AUTOPSY_CELLAR_VERSION_RE = re.compile(r"/Cellar/autopsy-memory/([^/\s]+)/")


class BridgeError(RuntimeError):
    pass


def app_support_dir() -> Path:
    override = os.environ.get("AUTOPSY_APP_SUPPORT_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "Autopsy"


DEFAULT_WORKSPACE_ROOT = str(app_support_dir() / "MemoryRoot")


def script_paths() -> dict[str, Path]:
    script = Path(__file__).resolve()
    package_dir = script.parent
    return {
        "script": script,
        "package_dir": package_dir,
        "worker": Path(os.environ.get("AUTOPSY_WORKER_SCRIPT") or package_dir / "worker.py").expanduser(),
        "tool": Path(os.environ.get("AUTOPSY_MEMORY_TOOL") or package_dir / "cli.py").expanduser(),
    }


def info_file() -> Path:
    return app_support_dir() / "CLI" / "ml-worker.json"


def lock_file() -> Path:
    return app_support_dir() / "CLI" / "ml-worker.lock"


def settings_file() -> Path:
    db_path = Path(
        os.environ.get("AUTOPSY_FALKORDB_LITE_PATH")
        or app_support_dir() / "FalkorDB" / "autopsy-memory.db"
    ).expanduser()
    return Path(str(db_path) + ".settings")


def worker_log_file() -> Path:
    return app_support_dir() / "CLI" / "mcp-worker.stderr.log"


def default_worker_environment() -> dict[str, str]:
    env = hardened_python_environment(os.environ)
    env["AUTOPSY_UNIFIED_MEMORY"] = env.get("AUTOPSY_UNIFIED_MEMORY") or "1"
    env["AUTOPSY_UNIFIED_MEMORY_ROOT"] = env.get("AUTOPSY_UNIFIED_MEMORY_ROOT") or DEFAULT_WORKSPACE_ROOT
    env["AUTOPSY_MEMORY_BACKEND"] = "falkordb"
    env["AUTOPSY_FALKORDB_ENABLED"] = "1"
    env["AUTOPSY_FALKORDB_GRAPH_NAME"] = env.get("AUTOPSY_FALKORDB_GRAPH_NAME") or DEFAULT_GRAPH_NAME
    if not env.get("AUTOPSY_FALKORDB_HOST") and not env.get("AUTOPSY_FALKORDB_PORT"):
        env["AUTOPSY_FALKORDB_LITE_PATH"] = env.get("AUTOPSY_FALKORDB_LITE_PATH") or str(
            app_support_dir() / "FalkorDB" / "autopsy-memory.db"
        )
    return env


def hardened_python_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    env.pop("PYTHONHOME", None)
    if str(env.get("AUTOPSY_ALLOW_PYTHONPATH") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return env


def can_import_modules(python: Path, modules: list[str]) -> bool:
    if not python.exists() or not os.access(python, os.X_OK):
        return False
    code = "; ".join(f"import {module}" for module in modules)
    result = subprocess.run(
        [str(python), "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=hardened_python_environment(),
        timeout=20,
        check=False,
    )
    return result.returncode == 0


def python_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit_python = os.environ.get("AUTOPSY_PYTHON")
    if explicit_python:
        candidates.append(Path(explicit_python).expanduser())
    for value in (
        sys.executable,
        str(app_support_dir() / "Python" / "runtime" / "bin" / "python"),
    ):
        if value:
            candidates.append(Path(value).expanduser())
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory:
            candidates.append(Path(directory) / "python3")
    candidates.extend(
        [
            Path("/opt/homebrew/bin/python3"),
            Path("/usr/local/bin/python3"),
            Path("/usr/bin/python3"),
        ]
    )
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_worker_python() -> Path:
    required = ["redislite.falkordb_client", "falkordb", "redis"]
    for candidate in python_candidates():
        try:
            if can_import_modules(candidate, required):
                return candidate
        except Exception:
            continue
    raise BridgeError(
        "No Python runtime can import Autopsy memory dependencies "
        "(redislite.falkordb_client, falkordb, redis). "
        "Install the package with the local extra or run `autopsy doctor` for details."
    )


def read_worker_info() -> dict[str, Any] | None:
    path = info_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def source_fingerprint() -> str:
    parts: list[str] = []
    paths = script_paths()
    for name in ("script", "worker", "tool"):
        path = paths[name]
        try:
            stat = path.stat()
        except FileNotFoundError:
            parts.append(f"{name}:{path}:missing")
            continue
        parts.append(f"{name}:{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def worker_info_matches_current_sources(info: dict[str, Any]) -> bool:
    return str(info.get("source_fingerprint") or "") == source_fingerprint()


def health_check(info: dict[str, Any], timeout: float = 2.0) -> bool:
    base_url = str(info.get("base_url") or "")
    token = str(info.get("token") or "")
    if not base_url or not token:
        return False
    request = urllib.request.Request(
        base_url.rstrip("/") + "/health",
        headers={"x-autopsy-token": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status < 200 or response.status >= 300:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("ok"))
    except Exception:
        return False


def terminate_pid(pid: Any) -> None:
    try:
        value = int(pid)
    except Exception:
        return
    if value <= 0 or value == os.getpid():
        return
    try:
        os.kill(value, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(value, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.kill(value, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(value, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)


def clear_worker_info() -> None:
    try:
        info_file().unlink()
    except FileNotFoundError:
        pass


def clear_stale_falkor_settings() -> str | None:
    path = settings_file()
    if not path.exists():
        return None
    backup = path.with_name(path.name + ".stale-" + time.strftime("%Y%m%d%H%M%S"))
    path.replace(backup)
    return str(backup)


def read_falkor_settings() -> dict[str, Any] | None:
    path = settings_file()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def terminate_falkor_runtime_from_settings() -> dict[str, Any]:
    settings = read_falkor_settings() or {}
    pidfile = str(settings.get("pidfile") or "").strip()
    payload: dict[str, Any] = {
        "pidfile": pidfile or None,
        "pid": None,
        "terminated": False,
        "settings_backup": None,
    }
    if pidfile:
        try:
            pid_text = Path(pidfile).read_text(encoding="utf-8").strip()
            payload["pid"] = int(pid_text)
        except Exception as exc:
            payload["pid_error"] = str(exc)
        if payload.get("pid"):
            terminate_pid(payload["pid"])
            payload["terminated"] = True
    payload["settings_backup"] = clear_stale_falkor_settings()
    return payload


def process_table_rows() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        rows.append({"pid": pid, "command": command.strip()})
    return rows


def worker_process_records(*, info_path: Path | None = None) -> list[dict[str, Any]]:
    info_text = str(info_path.expanduser()) if info_path else ""
    records: list[dict[str, Any]] = []
    for row in process_table_rows():
        command = str(row.get("command") or "")
        if "autopsy_memory/worker.py" not in command and "autopsy_memory.worker" not in command:
            continue
        if info_text and info_text not in command:
            continue
        records.append({"pid": int(row["pid"]), "command": command})
    return records


def redislite_process_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in process_table_rows():
        command = str(row.get("command") or "")
        if "redislite/bin/redis-server" not in command:
            continue
        if "autopsy" not in command.lower():
            continue
        records.append({"pid": int(row["pid"]), "command": command})
    return records


def autopsy_distribution_version() -> str | None:
    try:
        return importlib.metadata.version("autopsy-memory")
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def redislite_package_version(command: str) -> str | None:
    match = AUTOPSY_CELLAR_VERSION_RE.search(command)
    return match.group(1) if match else None


def annotate_redislite_process_records(records: list[dict[str, Any]], *, current_version: str | None) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    current_prefix = str(Path(sys.prefix).resolve())
    for record in records:
        command = str(record.get("command") or "")
        package_version = redislite_package_version(command)
        enriched = dict(record)
        enriched["package_version"] = package_version
        enriched["current_package_version"] = current_version
        enriched["stale_package_version"] = bool(package_version and current_version and package_version != current_version)
        enriched["matches_current_prefix"] = bool(current_prefix and current_prefix in command)
        annotated.append(enriched)
    return annotated


def redislite_keep_score(record: dict[str, Any], *, current_version: str | None) -> tuple[int, int]:
    score = 0
    if current_version and record.get("package_version") == current_version:
        score += 100
    if record.get("matches_current_prefix"):
        score += 50
    try:
        pid = int(record.get("pid"))
    except Exception:
        pid = 0
    return score, -pid


def reap_stale_redislite_processes(*, expected_max: int = 2, cleanup_current_excess: bool = False) -> dict[str, Any]:
    current_version = autopsy_distribution_version()
    before = annotate_redislite_process_records(redislite_process_records(), current_version=current_version)
    expected = max(0, int(expected_max))
    terminate_records = [record for record in before if record.get("stale_package_version")]

    if cleanup_current_excess:
        remaining = [record for record in before if not record.get("stale_package_version")]
        kept = sorted(
            remaining,
            key=lambda record: redislite_keep_score(record, current_version=current_version),
            reverse=True,
        )[:expected]
        kept_pids = {int(record["pid"]) for record in kept}
        terminate_records.extend(record for record in remaining if int(record["pid"]) not in kept_pids)

    terminated: list[int] = []
    seen: set[int] = set()
    for record in terminate_records:
        pid = int(record["pid"])
        if pid in seen:
            continue
        seen.add(pid)
        terminate_pid(pid)
        terminated.append(pid)

    after = annotate_redislite_process_records(redislite_process_records(), current_version=current_version)
    return {
        "terminated": terminated,
        "before_count": len(before),
        "after_count": len(after),
        "expected_max": expected,
        "cleanup_current_excess": cleanup_current_excess,
        "current_package_version": current_version,
        "records_before": before[:20],
        "records_after": after[:20],
    }


def redislite_lifecycle_payload(*, expected_max: int = 2, cleanup: bool = False) -> dict[str, Any]:
    cleanup_payload = None
    if cleanup:
        cleanup_payload = reap_stale_redislite_processes(expected_max=expected_max, cleanup_current_excess=True)
    current_version = autopsy_distribution_version()
    records = annotate_redislite_process_records(redislite_process_records(), current_version=current_version)
    expected = max(0, int(expected_max))
    excess_count = max(0, len(records) - expected)
    return {
        "name": "redislite_processes",
        "required": False,
        "ok": excess_count == 0,
        "count": len(records),
        "expected_max": expected,
        "excess_count": excess_count,
        "current_package_version": current_version,
        "cleanup": cleanup_payload,
        "records": records[:20],
    }


def reap_stale_worker_processes(*, keep_pid: int | None = None, info_path: Path | None = None) -> dict[str, Any]:
    records = worker_process_records(info_path=info_path)
    terminated: list[int] = []
    for record in records:
        pid = int(record["pid"])
        if pid == os.getpid() or (keep_pid is not None and pid == keep_pid):
            continue
        terminate_pid(pid)
        terminated.append(pid)
    return {
        "terminated": terminated,
        "records": records,
        "keep_pid": keep_pid,
        "info_file": str(info_path.expanduser()) if info_path else None,
    }


def worker_lifecycle_payload(*, cleanup: bool = False) -> dict[str, Any]:
    info = read_worker_info()
    current_pid = None
    if isinstance(info, dict):
        try:
            current_pid = int(info.get("pid"))
        except Exception:
            current_pid = None
    current_matches = bool(info and worker_info_matches_current_sources(info))
    current_healthy = bool(info and current_matches and health_check(info))
    same_info_records = worker_process_records(info_path=info_file())
    all_records = worker_process_records()
    stale_same_info = [
        record for record in same_info_records
        if current_pid is None or int(record["pid"]) != current_pid
    ]
    stale_all = [
        record for record in all_records
        if current_pid is None or int(record["pid"]) != current_pid
    ]
    cleanup_payload = None
    if cleanup:
        cleanup_payload = reap_stale_worker_processes(keep_pid=current_pid if current_healthy else None, info_path=info_file())
    lifecycle_ok = (not info or (current_matches and current_healthy)) and not stale_same_info
    return {
        "name": "resident_worker",
        "required": False,
        "ok": lifecycle_ok,
        "current": {
            "present": bool(info),
            "pid": current_pid,
            "matches_current_sources": current_matches,
            "healthy": current_healthy,
            "info_file": str(info_file()),
        },
        "stale_same_info_count": len(stale_same_info),
        "stale_worker_count": len(stale_all),
        "stale_same_info": stale_same_info,
        "stale_workers": stale_all[:20],
        "cleanup": cleanup_payload,
    }


def start_worker_locked() -> dict[str, Any]:
    existing = read_worker_info()
    if existing and worker_info_matches_current_sources(existing) and health_check(existing):
        try:
            reap_stale_worker_processes(keep_pid=int(existing.get("pid")), info_path=info_file())
            reap_stale_redislite_processes(expected_max=1, cleanup_current_excess=False)
        except Exception:
            pass
        return existing

    if existing:
        terminate_pid(existing.get("pid"))
        clear_worker_info()
        terminate_falkor_runtime_from_settings()
    reap_stale_worker_processes(info_path=info_file())
    reap_stale_redislite_processes(expected_max=0, cleanup_current_excess=True)

    paths = script_paths()
    if not paths["worker"].exists():
        raise BridgeError(f"Autopsy worker script not found: {paths['worker']}")
    if not paths["tool"].exists():
        raise BridgeError(f"Autopsy memory tool not found: {paths['tool']}")

    info_file().parent.mkdir(parents=True, exist_ok=True)
    worker_log_file().parent.mkdir(parents=True, exist_ok=True)
    python = resolve_worker_python()
    token = uuid.uuid4().hex.upper()
    env = default_worker_environment()
    stderr = worker_log_file().open("ab")
    stdout = subprocess.DEVNULL
    subprocess.Popen(
        [
            str(python),
            str(paths["worker"]),
            "--token",
            token,
            "--info-file",
            str(info_file()),
            "--source-fingerprint",
            source_fingerprint(),
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )

    deadline = time.monotonic() + 12
    last_info: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_info = read_worker_info()
        if last_info and last_info.get("token") == token and health_check(last_info):
            return last_info
        time.sleep(0.1)

    if last_info:
        terminate_pid(last_info.get("pid"))
    clear_worker_info()
    raise BridgeError(f"Autopsy worker did not become healthy. See {worker_log_file()}")


def ensure_worker() -> dict[str, Any]:
    info = read_worker_info()
    if info and worker_info_matches_current_sources(info) and health_check(info):
        return info

    lock_file().parent.mkdir(parents=True, exist_ok=True)
    with lock_file().open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return start_worker_locked()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def worker_request(path: str, payload: dict[str, Any], retry_on_stale_socket: bool = True) -> dict[str, Any]:
    info = ensure_worker()
    base_url = str(info["base_url"]).rstrip("/")
    token = str(info["token"])
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers={
            "content-type": "application/json",
            "x-autopsy-token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            message = str(payload.get("error") or body)
        except Exception:
            message = body
        if retry_on_stale_socket and is_stale_falkor_socket_error(message):
            recover_stale_falkor_socket(info)
            return worker_request(path, payload_for_retry(path, request), retry_on_stale_socket=False)
        if retry_on_stale_socket and is_stale_worker_route_error(message):
            terminate_pid(info.get("pid"))
            clear_worker_info()
            return worker_request(path, payload_for_retry(path, request), retry_on_stale_socket=False)
        raise BridgeError(message)
    except urllib.error.URLError as error:
        if retry_on_stale_socket:
            terminate_pid(info.get("pid"))
            clear_worker_info()
            return worker_request(path, payload, retry_on_stale_socket=False)
        raise BridgeError(str(error))


def payload_for_retry(_path: str, request: urllib.request.Request) -> dict[str, Any]:
    data = request.data or b"{}"
    return json.loads(data.decode("utf-8"))


def is_stale_falkor_socket_error(message: str) -> bool:
    lowered = message.lower()
    return "redis.socket" in lowered and (
        "connection refused" in lowered
        or "no such file" in lowered
        or "error 2 connecting" in lowered
        or "stale" in lowered
    )


def is_stale_worker_route_error(message: str) -> bool:
    lowered = message.strip().lower()
    return (
        lowered == "not found"
        or "404" in lowered
        or "attempted relative import with no known parent package" in lowered
    )


def recover_stale_falkor_socket(info: dict[str, Any]) -> None:
    runtime_cleanup = terminate_falkor_runtime_from_settings()
    terminate_pid(info.get("pid"))
    clear_worker_info()
    backup = runtime_cleanup.get("settings_backup")
    if backup:
        log_diagnostic(f"Backed up stale Falkor settings to {backup}")


def log_diagnostic(message: str) -> None:
    print(f"{SERVER_NAME}: {message}", file=sys.stderr, flush=True)


def workspace_root(arguments: dict[str, Any]) -> str:
    value = arguments.get("workspace") or os.environ.get("AUTOPSY_UNIFIED_MEMORY_ROOT") or DEFAULT_WORKSPACE_ROOT
    return str(Path(str(value)).expanduser())


def cwd_for(arguments: dict[str, Any], workspace: str) -> str:
    value = arguments.get("cwd") or workspace
    return str(Path(str(value)).expanduser())


def int_argument(arguments: dict[str, Any], name: str, default: int) -> int:
    value = arguments.get(name)
    if value is None or value == "":
        return default
    return int(value)


def list_argument(arguments: dict[str, Any], name: str) -> list[Any]:
    value = arguments.get(name)
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def metadata_argument(arguments: dict[str, Any]) -> Any:
    if "metadata" not in arguments:
        return []
    value = arguments.get("metadata")
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def filter_json_argument(arguments: dict[str, Any]) -> Any:
    if "filter_json" in arguments:
        value = arguments.get("filter_json")
    elif "filter" in arguments:
        value = arguments.get("filter")
    else:
        return None
    if value is None or value == "":
        return None
    return value


def entity_scope_arguments(arguments: dict[str, Any]) -> list[Any]:
    scopes: list[Any] = []
    for field in ("entity_scopes", "entity_scope"):
        if arguments.get(field):
            scopes.extend(list_argument(arguments, field))
    for argument_name, scope_type in (
        ("user_id", "user"),
        ("agent_id", "agent"),
        ("app_id", "app"),
        ("run_id", "run"),
        ("group_id", "group"),
    ):
        if arguments.get(argument_name):
            scopes.extend(f"{scope_type}:{value}" for value in list_argument(arguments, argument_name))
    return scopes


def base_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    workspace = workspace_root(arguments)
    return {
        "tool_path": str(script_paths()["tool"]),
        "workspace": workspace,
        "cwd": cwd_for(arguments, workspace),
    }


def request_payload(arguments: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    payload = base_payload(arguments)
    payload["request"] = request
    return payload


def context_graph_thread_id(arguments: dict[str, Any]) -> str:
    for name in ("thread_id", "threadId", "session_id", "sessionId"):
        value = arguments.get(name)
        if value:
            return str(value).strip()
    for name in ("AUTOPSY_CONTEXT_GRAPH_THREAD_ID", "AUTOPSY_THREAD_ID", "CODEX_THREAD_ID", "CLAUDE_THREAD_ID"):
        value = os.environ.get(name)
        if value:
            return str(value).strip()
    return ""


def build_context_graph_event_request(
    arguments: dict[str, Any],
    *,
    event_type: str,
    title: str,
    content: str = "",
    status: str = "complete",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thread_id = context_graph_thread_id(arguments)
    if not thread_id:
        raise BridgeError("thread_id is required")
    request = {
        "thread_id": thread_id,
        "event_type": event_type,
        "title": title,
        "content": content,
        "status": status,
        "agent": str(arguments.get("agent") or arguments.get("agent_id") or ""),
        "app": str(arguments.get("app") or arguments.get("app_id") or ""),
        "run_id": str(arguments.get("run_id") or ""),
        "metadata": metadata or {},
    }
    if arguments.get("timestamp"):
        request["timestamp"] = str(arguments["timestamp"])
    return request


def record_context_graph_event_if_thread(
    arguments: dict[str, Any],
    *,
    event_type: str,
    title: str,
    content: str = "",
    status: str = "complete",
    metadata: dict[str, Any] | None = None,
) -> None:
    if not context_graph_thread_id(arguments):
        return
    try:
        from .context_graph_settings import context_graph_capture_state
        from .cli import context_event_command_title, should_capture_context_command

        if not context_graph_capture_state("mcp-context-event").get("record"):
            return
        normalized_event_type = str(event_type or "").strip().lower()
        if normalized_event_type not in {"command", "shell_command"}:
            return
        raw_metadata = metadata if isinstance(metadata, dict) else {}
        command = str(raw_metadata.get("command") or content or title or "").strip()
        if not should_capture_context_command(command):
            return
        request = build_context_graph_event_request(
            arguments,
            event_type="command",
            title=context_event_command_title(command),
            content=command,
            status=status,
            metadata={"command": command, "capture": "command_only"},
        )
        worker_request("/context-graph/events", {"request": request}, retry_on_stale_socket=False)
    except Exception as exc:
        log_diagnostic(f"context graph event recording failed: {exc}")


def compact_response(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def tool_status(arguments: dict[str, Any]) -> dict[str, Any]:
    request = {
        "limit": int(arguments.get("limit") or 8),
        "section_limit": int(arguments.get("section_limit") or 4),
        "recent_days": int(arguments.get("recent_days") or 14),
    }
    if arguments.get("thread_id"):
        request["thread_id"] = str(arguments["thread_id"])
    if arguments.get("as_of"):
        request["as_of"] = str(arguments["as_of"])
    return worker_request("/memory/status", request_payload(arguments, request))


def tool_consult(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise BridgeError("query is required")
    route = str(arguments.get("route") or "auto").strip().lower()
    if route not in {"auto", "status", "lexical", "hybrid"}:
        route = "auto"
    request = {
        "query": query,
        "current_only": bool(arguments.get("current_only", True)),
        "limit": int_argument(arguments, "limit", 8),
        "inspect_limit": int_argument(arguments, "inspect_limit", 3),
        "route": route,
        "scope": str(arguments.get("scope") or "system"),
    }
    if arguments.get("repo"):
        request["repo"] = str(arguments["repo"])
    if arguments.get("repository_root_path"):
        request["repository_root_path"] = str(arguments["repository_root_path"])
    if arguments.get("kinds"):
        request["kinds"] = list(arguments.get("kinds") or [])
    elif arguments.get("kind"):
        request["kinds"] = list(arguments.get("kind") if isinstance(arguments.get("kind"), list) else [arguments.get("kind")])
    if arguments.get("memory_types"):
        request["memory_types"] = list_argument(arguments, "memory_types")
    elif arguments.get("memory_type"):
        request["memory_types"] = list_argument(arguments, "memory_type")
    if arguments.get("tags"):
        request["tags"] = list_argument(arguments, "tags")
    elif arguments.get("tag"):
        request["tags"] = list_argument(arguments, "tag")
    if arguments.get("namespaces"):
        request["namespaces"] = list_argument(arguments, "namespaces")
    elif arguments.get("namespace"):
        request["namespaces"] = list_argument(arguments, "namespace")
    entity_scopes = entity_scope_arguments(arguments)
    if entity_scopes:
        request["entity_scopes"] = entity_scopes
    if "metadata" in arguments:
        request["metadata"] = metadata_argument(arguments)
    if "filter_json" in arguments or "filter" in arguments:
        request["filter_json"] = filter_json_argument(arguments)
    if "min_fact_rating" in arguments:
        request["min_fact_rating"] = arguments.get("min_fact_rating")
    if arguments.get("thread_id"):
        request["thread_id"] = str(arguments["thread_id"])
    if arguments.get("as_of"):
        request["as_of"] = str(arguments["as_of"])
    payload = worker_request("/memory/consult", request_payload(arguments, request))
    return payload


def tool_item(arguments: dict[str, Any]) -> dict[str, Any]:
    stable_key = str(arguments.get("stable_key") or "").strip()
    if not stable_key:
        raise BridgeError("stable_key is required")
    return worker_request("/memory/graph/item", request_payload(arguments, {"stable_key": stable_key}))


def tool_timeline(arguments: dict[str, Any]) -> dict[str, Any]:
    stable_key = str(arguments.get("stable_key") or "").strip()
    if not stable_key:
        raise BridgeError("stable_key is required")
    request = {"stable_key": stable_key}
    if arguments.get("as_of"):
        request["as_of"] = str(arguments["as_of"])
    return worker_request("/memory/timeline", request_payload(arguments, request))


def tool_history(arguments: dict[str, Any]) -> dict[str, Any]:
    stable_key = str(arguments.get("stable_key") or "").strip()
    if not stable_key:
        raise BridgeError("stable_key is required")
    request = {
        "stable_key": stable_key,
        "limit": int(arguments.get("limit") or 50),
    }
    return worker_request("/memory/history", request_payload(arguments, request))


def tool_neighbors(arguments: dict[str, Any]) -> dict[str, Any]:
    stable_key = str(arguments.get("stable_key") or "").strip()
    if not stable_key:
        raise BridgeError("stable_key is required")
    request = {
        "stable_key": stable_key,
        "relation_limit": int(arguments.get("relation_limit") or 12),
    }
    if "min_fact_rating" in arguments:
        request["min_fact_rating"] = arguments.get("min_fact_rating")
    return worker_request("/memory/neighbors", request_payload(arguments, request))


def tool_observe(arguments: dict[str, Any]) -> dict[str, Any]:
    stable_key = str(arguments.get("stable_key") or "").strip()
    if not stable_key:
        raise BridgeError("stable_key is required")
    request = {
        "stable_key": stable_key,
        "limit": int(arguments.get("limit") or 5),
        "write": bool(arguments.get("write")),
        "write_if_stale": bool(arguments.get("write_if_stale")),
    }
    if "min_fact_rating" in arguments:
        request["min_fact_rating"] = arguments.get("min_fact_rating")
    if arguments.get("title"):
        request["title"] = str(arguments["title"])
    return worker_request("/memory/observe", request_payload(arguments, request))


def tool_graph_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise BridgeError("query is required")
    request = {
        "query": query,
        "limit": int(arguments.get("limit") or 24),
    }
    if arguments.get("kinds"):
        request["kinds"] = list_argument(arguments, "kinds")
    elif arguments.get("kind"):
        request["kinds"] = list_argument(arguments, "kind")
    if arguments.get("memory_types"):
        request["memory_types"] = list_argument(arguments, "memory_types")
    elif arguments.get("memory_type"):
        request["memory_types"] = list_argument(arguments, "memory_type")
    if arguments.get("tags"):
        request["tags"] = list_argument(arguments, "tags")
    elif arguments.get("tag"):
        request["tags"] = list_argument(arguments, "tag")
    if arguments.get("namespaces"):
        request["namespaces"] = list_argument(arguments, "namespaces")
    elif arguments.get("namespace"):
        request["namespaces"] = list_argument(arguments, "namespace")
    entity_scopes = entity_scope_arguments(arguments)
    if entity_scopes:
        request["entity_scopes"] = entity_scopes
    if "metadata" in arguments:
        request["metadata"] = metadata_argument(arguments)
    if "filter_json" in arguments or "filter" in arguments:
        request["filter_json"] = filter_json_argument(arguments)
    if "min_fact_rating" in arguments:
        request["min_fact_rating"] = arguments.get("min_fact_rating")
    if arguments.get("as_of"):
        request["as_of"] = str(arguments["as_of"])
    return worker_request("/memory/graph/search", request_payload(arguments, request))


def tool_create_note(arguments: dict[str, Any]) -> dict[str, Any]:
    kind = str(arguments.get("kind") or "memory_note").strip()
    title = str(arguments.get("title") or "").strip()
    content = str(arguments.get("content") or "").strip()
    if not title:
        raise BridgeError("title is required")
    if not content:
        raise BridgeError("content is required")
    request = {
        "kind": kind,
        "title": title,
        "content": content,
    }
    if arguments.get("scope"):
        request["scope"] = str(arguments["scope"])
    if arguments.get("repo"):
        request["repo"] = str(arguments["repo"])
    if arguments.get("repository_root_path"):
        request["repository_root_path"] = str(arguments["repository_root_path"])
    if arguments.get("thread_id"):
        request["thread_id"] = str(arguments["thread_id"])
    if arguments.get("tags"):
        request["tags"] = list_argument(arguments, "tags")
    elif arguments.get("tag"):
        request["tags"] = list_argument(arguments, "tag")
    if arguments.get("namespaces"):
        request["namespaces"] = list_argument(arguments, "namespaces")
    elif arguments.get("namespace"):
        request["namespaces"] = list_argument(arguments, "namespace")
    entity_scopes = entity_scope_arguments(arguments)
    if entity_scopes:
        request["entity_scopes"] = entity_scopes
    if "metadata" in arguments:
        request["metadata"] = metadata_argument(arguments)
    for field in RELATION_FIELDS:
        values = arguments.get(field)
        if values:
            request[field] = values
    for field in ("relation_valid_at", "relation_invalid_at", "relation_expires_at"):
        if arguments.get(field):
            request[field] = str(arguments[field])
    if "fact_rating" in arguments:
        request["fact_rating"] = arguments.get("fact_rating")
    if arguments.get("no_relations_ok"):
        request["no_relations_ok"] = True
    if arguments.get("allow_unsafe_memory"):
        request["allow_unsafe_memory"] = True
    payload = worker_request("/memory/graph/note", request_payload(arguments, request))
    return payload


def tool_update_item(arguments: dict[str, Any]) -> dict[str, Any]:
    stable_key = str(arguments.get("stable_key") or "").strip()
    kind = str(arguments.get("kind") or "memory_note").strip()
    title = str(arguments.get("title") or "").strip()
    content = str(arguments.get("content") or "").strip()
    if not stable_key:
        raise BridgeError("stable_key is required")
    if not title:
        raise BridgeError("title is required")
    if not content:
        raise BridgeError("content is required")
    request = {
        "stable_key": stable_key,
        "kind": kind,
        "title": title,
        "content": content,
    }
    if arguments.get("tags"):
        request["tags"] = list_argument(arguments, "tags")
    elif arguments.get("tag"):
        request["tags"] = list_argument(arguments, "tag")
    if arguments.get("namespaces"):
        request["namespaces"] = list_argument(arguments, "namespaces")
    elif arguments.get("namespace"):
        request["namespaces"] = list_argument(arguments, "namespace")
    entity_scopes = entity_scope_arguments(arguments)
    if entity_scopes:
        request["entity_scopes"] = entity_scopes
    if "metadata" in arguments:
        request["metadata"] = metadata_argument(arguments)
    if arguments.get("allow_unsafe_memory"):
        request["allow_unsafe_memory"] = True
    return worker_request("/memory/graph/item/update", request_payload(arguments, request))


def tool_delete_item(arguments: dict[str, Any]) -> dict[str, Any]:
    stable_key = str(arguments.get("stable_key") or "").strip()
    if not stable_key:
        raise BridgeError("stable_key is required")
    return worker_request("/memory/graph/item/delete", request_payload(arguments, {"stable_key": stable_key}))


def tool_context_graph_event(arguments: dict[str, Any]) -> dict[str, Any]:
    from .context_graph_settings import context_graph_capture_state, context_graph_skip_payload
    from .cli import context_event_command_title, should_capture_context_command

    command = str(arguments.get("command") or arguments.get("context_command") or "").strip()
    if not command:
        raise BridgeError("command is required")
    capture_state = context_graph_capture_state("mcp-context-event")
    if not capture_state.get("record"):
        return context_graph_skip_payload("mcp-context-event", command=command, settings=capture_state)
    if not should_capture_context_command(command):
        return {"ok": True, "skipped": True, "reason": "command_not_allowlisted", "command": command}
    metadata = {"command": command, "capture": "command_only"}
    request = build_context_graph_event_request(
        arguments,
        event_type="command",
        title=context_event_command_title(command),
        content=command,
        status=str(arguments.get("status") or "complete"),
        metadata=metadata,
    )
    return worker_request("/context-graph/events", {"request": request})


def tool_context_graph_url(arguments: dict[str, Any]) -> dict[str, Any]:
    from .context_graph_settings import load_context_graph_settings

    thread_id = context_graph_thread_id(arguments)
    if not thread_id:
        raise BridgeError("thread_id is required")
    settings = load_context_graph_settings()
    if not bool(settings.get("enabled")):
        return {
            "ok": True,
            "skipped": True,
            "reason": "context_graph_disabled",
            "message": "Context graph is disabled in Autopsy settings. No graph URL was opened.",
            "context_graph": {
                "enabled": False,
                "mode": str(settings.get("mode") or "cli"),
            },
            "thread_id": thread_id,
        }
    info = ensure_worker()
    base_url = str(info.get("base_url") or "").rstrip("/")
    token = str(info.get("token") or "")
    url = (
        f"{base_url}/context-graph/threads/"
        f"{urllib.parse.quote(thread_id, safe='')}?token={urllib.parse.quote(token, safe='')}"
    )
    return {
        "thread_id": thread_id,
        "url": url,
        "worker": {
            "base_url": base_url,
            "pid": info.get("pid"),
        },
    }


def tool_worker_info(_arguments: dict[str, Any]) -> dict[str, Any]:
    info = ensure_worker()
    paths = script_paths()
    return {
        "ok": health_check(info),
        "worker": {
            "base_url": info.get("base_url"),
            "pid": info.get("pid"),
            "info_file": str(info_file()),
        },
        "paths": {
            "bridge": str(paths["script"]),
            "worker": str(paths["worker"]),
            "memory_tool": str(paths["tool"]),
            "settings": str(settings_file()),
            "log": str(worker_log_file()),
        },
        "graph": {
            "workspace_root": os.environ.get("AUTOPSY_UNIFIED_MEMORY_ROOT") or DEFAULT_WORKSPACE_ROOT,
            "lite_path": os.environ.get("AUTOPSY_FALKORDB_LITE_PATH")
            or str(app_support_dir() / "FalkorDB" / "autopsy-memory.db"),
            "graph_name": os.environ.get("AUTOPSY_FALKORDB_GRAPH_NAME") or DEFAULT_GRAPH_NAME,
        },
    }


KIND_ENUM = ["memory_note", "decision", "open_question", "preference", "attempt", "plan", "procedure", "observation", "summary"]


def relation_tool_properties() -> dict[str, Any]:
    return {
        field: {
            "type": "array",
            "items": {"type": "string"},
            "description": f"Stable keys this memory {field.replace('_', ' ')}.",
        }
        for field in RELATION_FIELDS
    }


def optional_workspace_properties() -> dict[str, Any]:
    return {
        "workspace": {
            "type": "string",
            "description": "Workspace root path. Defaults to AUTOPSY_UNIFIED_MEMORY_ROOT or the Autopsy app-support MemoryRoot.",
        },
        "cwd": {
            "type": "string",
            "description": "Execution cwd for workspace resolution. Defaults to workspace.",
        },
    }


def entity_scope_tool_properties() -> dict[str, Any]:
    return {
        "entity_scope": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Entity scopes as TYPE:ID values such as user:alice, agent:planner, app:web, run:ticket-42, or group:team-a.",
        },
        "entity_scopes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Entity scopes as TYPE:ID values such as user:alice, agent:planner, app:web, run:ticket-42, or group:team-a.",
        },
        "user_id": {"type": "array", "items": {"type": "string"}, "description": "User-scoped memory partition."},
        "agent_id": {"type": "array", "items": {"type": "string"}, "description": "Agent-scoped memory partition."},
        "app_id": {"type": "array", "items": {"type": "string"}, "description": "Application-scoped memory partition."},
        "run_id": {"type": "array", "items": {"type": "string"}, "description": "Run/session-scoped memory partition."},
        "group_id": {"type": "array", "items": {"type": "string"}, "description": "Group/tenant-scoped memory partition."},
    }


TOOLS: dict[str, dict[str, Any]] = {
    "autopsy_memory_status": {
        "description": "Summarize current Autopsy memory state: active items, open loops, recent decisions, activity, and threads.",
        "handler": tool_status,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "thread_id": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
                "section_limit": {"type": "integer", "default": 4},
                "recent_days": {"type": "integer", "default": 14},
                "as_of": {"type": "string"},
            },
        },
    },
    "autopsy_memory_consult": {
        "description": "Recall relevant high-signal Autopsy graph memory with workflow completeness, relations, embeddings, and reranker metadata.",
        "handler": tool_consult,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "query": {"type": "string"},
                "thread_id": {"type": "string"},
                "current_only": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 8},
                "inspect_limit": {"type": "integer", "default": 3},
                "route": {"type": "string", "enum": ["auto", "status", "lexical", "hybrid"], "default": "auto"},
                "scope": {"type": "string", "enum": ["system", "repo"], "default": "system"},
                "repo": {"type": "string"},
                "repository_root_path": {"type": "string"},
                "kind": {"type": "array", "items": {"type": "string"}},
                "kinds": {"type": "array", "items": {"type": "string"}},
                "memory_type": {"type": "array", "items": {"type": "string"}, "description": "Cognitive memory types: semantic, episodic, procedural, or observation."},
                "memory_types": {"type": "array", "items": {"type": "string"}, "description": "Cognitive memory types: semantic, episodic, procedural, or observation."},
                "tag": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "namespace": {"type": "array", "items": {"type": "string"}},
                "namespaces": {"type": "array", "items": {"type": "string"}},
                **entity_scope_tool_properties(),
                "metadata": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "Metadata filters such as key=value, key!=value, key~=text, or score>=8.",
                },
                "filter_json": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "JSON boolean filter over kind, tag, namespace, entity scope, metadata, and item fields.",
                },
                "filter": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "Alias for filter_json.",
                },
                "min_fact_rating": {"type": "number", "minimum": 0, "maximum": 1, "description": "Filter relation/fact side-channel retrieval to facts rated at or above this threshold."},
                "as_of": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "autopsy_memory_item": {
        "description": "Fetch one Autopsy memory item by stable key.",
        "handler": tool_item,
        "schema": {
            "type": "object",
            "properties": {**optional_workspace_properties(), "stable_key": {"type": "string"}},
            "required": ["stable_key"],
        },
    },
    "autopsy_memory_timeline": {
        "description": "Fetch the temporal relation timeline for one Autopsy memory item.",
        "handler": tool_timeline,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "stable_key": {"type": "string"},
                "as_of": {"type": "string"},
            },
            "required": ["stable_key"],
        },
    },
    "autopsy_memory_history": {
        "description": "Fetch recorded old/new change history for one Autopsy memory item, including updates, expiration, pinning, and deletion events.",
        "handler": tool_history,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "stable_key": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["stable_key"],
        },
    },
    "autopsy_memory_neighbors": {
        "description": "Fetch graph neighbors and explicit relations around one Autopsy memory item.",
        "handler": tool_neighbors,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "stable_key": {"type": "string"},
                "relation_limit": {"type": "integer", "default": 12},
                "min_fact_rating": {"type": "number", "minimum": 0, "maximum": 1, "description": "Filter semantic neighbors to relation facts rated at or above this threshold."},
            },
            "required": ["stable_key"],
        },
    },
    "autopsy_memory_observe": {
        "description": "Draft or materialize an evidence-backed observation from one seed memory and its semantic graph neighborhood.",
        "handler": tool_observe,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "stable_key": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
                "min_fact_rating": {"type": "number", "minimum": 0, "maximum": 1, "description": "Only use relation facts rated at or above this threshold as observation evidence."},
                "title": {"type": "string", "description": "Optional title override for the derived observation."},
                "write": {"type": "boolean", "default": False, "description": "When true, upsert the observation and link it back to evidence memories."},
                "write_if_stale": {"type": "boolean", "default": False, "description": "When true, upsert only if the existing observation is missing or its stored evidence fingerprint differs from current graph evidence."},
            },
            "required": ["stable_key"],
        },
    },
    "autopsy_memory_search": {
        "description": "Search Autopsy memory nodes directly.",
        "handler": tool_graph_search,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 24},
                "kind": {"type": "array", "items": {"type": "string"}},
                "kinds": {"type": "array", "items": {"type": "string"}},
                "memory_type": {"type": "array", "items": {"type": "string"}, "description": "Cognitive memory types: semantic, episodic, procedural, or observation."},
                "memory_types": {"type": "array", "items": {"type": "string"}, "description": "Cognitive memory types: semantic, episodic, procedural, or observation."},
                "tag": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "namespace": {"type": "array", "items": {"type": "string"}},
                "namespaces": {"type": "array", "items": {"type": "string"}},
                **entity_scope_tool_properties(),
                "metadata": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "Metadata filters such as key=value, key!=value, key~=text, or score>=8.",
                },
                "filter_json": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "JSON boolean filter over kind, tag, namespace, entity scope, metadata, and item fields.",
                },
                "filter": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "Alias for filter_json.",
                },
                "min_fact_rating": {"type": "number", "minimum": 0, "maximum": 1, "description": "Filter relation/fact side-channel retrieval to facts rated at or above this threshold."},
                "as_of": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "autopsy_memory_create_note": {
        "description": "Create a typed Autopsy graph memory item in the shared Falkor graph.",
        "handler": tool_create_note,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "kind": {"type": "string", "enum": KIND_ENUM, "default": "memory_note"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "scope": {"type": "string", "enum": ["system", "repo"], "default": "system"},
                "repo": {"type": "string"},
                "repository_root_path": {"type": "string"},
                "thread_id": {"type": "string"},
                "tag": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "namespace": {"type": "array", "items": {"type": "string"}},
                "namespaces": {"type": "array", "items": {"type": "string"}},
                **entity_scope_tool_properties(),
                "metadata": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "Structured memory metadata to persist with the item.",
                },
                "relation_valid_at": {"type": "string", "description": "ISO-8601 timestamp for when newly created semantic relation facts became true."},
                "relation_invalid_at": {"type": "string", "description": "ISO-8601 timestamp for when newly created semantic relation facts stopped being true."},
                "relation_expires_at": {"type": "string", "description": "ISO-8601 timestamp for when newly created semantic relation facts should leave current reads."},
                "fact_rating": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional quality rating to attach to newly created semantic relation facts."},
                **relation_tool_properties(),
                "no_relations_ok": {
                    "type": "boolean",
                    "default": False,
                    "description": "Only set true when the memory is intentionally standalone and no semantic relation applies.",
                },
                "allow_unsafe_memory": {
                    "type": "boolean",
                    "default": False,
                    "description": "Bypass the write-time safety guard for deliberate incident evidence; unsafe findings remain in write_quality.",
                },
            },
            "required": ["title", "content"],
        },
    },
    "autopsy_memory_update_item": {
        "description": "Update a typed Autopsy graph memory item in the shared Falkor graph.",
        "handler": tool_update_item,
        "schema": {
            "type": "object",
            "properties": {
                **optional_workspace_properties(),
                "stable_key": {"type": "string"},
                "kind": {"type": "string", "enum": KIND_ENUM, "default": "memory_note"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tag": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "namespace": {"type": "array", "items": {"type": "string"}},
                "namespaces": {"type": "array", "items": {"type": "string"}},
                **entity_scope_tool_properties(),
                "metadata": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "object", "additionalProperties": True},
                    ],
                    "description": "Structured memory metadata to replace or persist with the item.",
                },
                "allow_unsafe_memory": {
                    "type": "boolean",
                    "default": False,
                    "description": "Bypass the write-time safety guard for deliberate incident evidence; unsafe findings remain in write_quality.",
                },
            },
            "required": ["stable_key", "title", "content"],
        },
    },
    "autopsy_memory_delete_item": {
        "description": "Delete one Autopsy graph memory item by stable key.",
        "handler": tool_delete_item,
        "schema": {
            "type": "object",
            "properties": {**optional_workspace_properties(), "stable_key": {"type": "string"}},
            "required": ["stable_key"],
        },
    },
    "autopsy_context_graph_event": {
        "description": "Record one allowlisted shell command for the live per-thread Autopsy context graph. Only command text is persisted; command output and generic graph events are ignored.",
        "handler": tool_context_graph_event,
        "schema": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "command": {"type": "string", "description": "Shell command text that fetched useful context. Non-allowlisted commands are skipped."},
                "status": {"type": "string", "description": "Optional state flag such as in_progress, complete, blocked, or error."},
                "timestamp": {"type": "string"},
                "agent": {"type": "string"},
                "app": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["thread_id", "command"],
        },
    },
    "autopsy_context_graph_url": {
        "description": "Return the local browser URL for a live per-thread Autopsy context graph.",
        "handler": tool_context_graph_url,
        "schema": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
            },
            "required": ["thread_id"],
        },
    },
    "autopsy_memory_worker_info": {
        "description": "Check the shared Autopsy memory worker, bridge paths, and Falkor graph configuration.",
        "handler": tool_worker_info,
        "schema": {"type": "object", "properties": {}},
    },
}


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": spec["description"],
            "inputSchema": spec["schema"],
        }
        for name, spec in TOOLS.items()
    ]


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            return None
        line = line.decode("utf-8").strip()
        if line == "":
            break
        key, _, value = line.partition(":")
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(message: dict[str, Any]) -> None:
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def success(request_id: Any, result: dict[str, Any]) -> None:
    write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def error(request_id: Any, code: int, message: str) -> None:
    write_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def handle_request(message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if request_id is None and method != "ping":
        return

    try:
        if method == "initialize":
            success(
                request_id,
                {
                    "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        elif method == "ping":
            if request_id is not None:
                success(request_id, {})
        elif method == "tools/list":
            success(request_id, {"tools": tool_definitions()})
        elif method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if name not in TOOLS:
                raise BridgeError(f"Unknown tool: {name}")
            handler = TOOLS[name]["handler"]
            payload = handler(arguments)
            success(
                request_id,
                {
                    "content": [{"type": "text", "text": compact_response(payload)}],
                    "isError": False,
                },
            )
        else:
            error(request_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        if method == "tools/call":
            success(
                request_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        else:
            error(request_id, -32000, str(exc))


def serve() -> None:
    while True:
        message = read_message()
        if message is None:
            return
        handle_request(message)


def print_config() -> None:
    print(json.dumps(tool_worker_info({}), indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Autopsy worker-backed MCP memory bridge.")
    parser.add_argument("--print-config", action="store_true", help="Start/check the worker and print bridge configuration.")
    args = parser.parse_args()
    if args.print_config:
        print_config()
        return
    serve()


if __name__ == "__main__":
    main()
