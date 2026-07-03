#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from typing import MutableMapping


PRODUCTION_APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Autopsy"
DEFAULT_DEV_APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "AutopsyDev"
ALLOW_PRODUCTION_ENV = "AUTOPSY_DEV_ALLOW_PRODUCTION_MEMORY"
ALLOW_REMOTE_FALKOR_ENV = "AUTOPSY_DEV_ALLOW_REMOTE_FALKORDB"
ALLOW_CUSTOM_PATHS_ENV = "AUTOPSY_DEV_ALLOW_CUSTOM_PATHS"
REMOTE_FALKOR_ENV_KEYS = ("AUTOPSY_FALKORDB_HOST", "AUTOPSY_FALKORDB_PORT")
DEV_PATH_ENV_KEYS = (
    "AUTOPSY_UNIFIED_MEMORY_ROOT",
    "AUTOPSY_FALKORDB_LITE_PATH",
    "AUTOPSY_SHARED_SERVER_CONFIG",
    "AUTOPSY_ACTIVITY_SNAPSHOT_PATH",
    "AUTOPSY_MEMORY_GUARD_LOG_PATH",
    "AUTOPSY_MEMORY_RELATION_LOG_PATH",
)


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_production_path(path: str | Path, production_root: Path = PRODUCTION_APP_SUPPORT_DIR) -> bool:
    resolved = _resolved(path)
    production = _resolved(production_root)
    return resolved == production or production in resolved.parents


def _is_within_path(path: str | Path, root: str | Path) -> bool:
    resolved = _resolved(path)
    resolved_root = _resolved(root)
    return resolved == resolved_root or resolved_root in resolved.parents


def _env_flag_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def configure_dev_environment(environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    env = environ if environ is not None else os.environ
    allow_production = _env_flag_enabled(env.get(ALLOW_PRODUCTION_ENV))
    allow_remote_falkor = _env_flag_enabled(env.get(ALLOW_REMOTE_FALKOR_ENV))
    allow_custom_paths = _env_flag_enabled(env.get(ALLOW_CUSTOM_PATHS_ENV))
    inherited_app_support = env.get("AUTOPSY_APP_SUPPORT_DIR") or ""
    explicit_dev_app_support = env.get("AUTOPSY_DEV_APP_SUPPORT_DIR") or ""
    app_support = (
        explicit_dev_app_support
        or (inherited_app_support if (allow_custom_paths or allow_production) else "")
        or str(DEFAULT_DEV_APP_SUPPORT_DIR)
    )
    app_support_path = Path(app_support).expanduser()

    path_defaults = {
        "AUTOPSY_UNIFIED_MEMORY_ROOT": str(app_support_path / "MemoryRoot"),
        "AUTOPSY_FALKORDB_LITE_PATH": str(app_support_path / "FalkorDB" / "autopsy-memory.db"),
        "AUTOPSY_SHARED_SERVER_CONFIG": str(app_support_path / "SharedServer" / "config.json"),
        "AUTOPSY_ACTIVITY_SNAPSHOT_PATH": str(app_support_path / "Activity" / "activity.json"),
        "AUTOPSY_MEMORY_GUARD_LOG_PATH": str(app_support_path / "Diagnostics" / "memory-guard.jsonl"),
        "AUTOPSY_MEMORY_RELATION_LOG_PATH": str(app_support_path / "Diagnostics" / "memory-relations.jsonl"),
    }

    guarded_values = {
        "AUTOPSY_APP_SUPPORT_DIR": inherited_app_support,
        "AUTOPSY_DEV_APP_SUPPORT_DIR": explicit_dev_app_support,
        "AUTOPSY_FALKORDB_LITE_PATH": env.get("AUTOPSY_FALKORDB_LITE_PATH") or "",
        "AUTOPSY_UNIFIED_MEMORY_ROOT": env.get("AUTOPSY_UNIFIED_MEMORY_ROOT") or "",
        "AUTOPSY_SHARED_SERVER_CONFIG": env.get("AUTOPSY_SHARED_SERVER_CONFIG") or "",
        "AUTOPSY_ACTIVITY_SNAPSHOT_PATH": env.get("AUTOPSY_ACTIVITY_SNAPSHOT_PATH") or "",
        "AUTOPSY_MEMORY_GUARD_LOG_PATH": env.get("AUTOPSY_MEMORY_GUARD_LOG_PATH") or "",
        "AUTOPSY_MEMORY_RELATION_LOG_PATH": env.get("AUTOPSY_MEMORY_RELATION_LOG_PATH") or "",
    }
    if not allow_production:
        for key, value in guarded_values.items():
            if value and _is_production_path(value):
                raise SystemExit(
                    f"autopsy-dev refused to use production memory via {key}={value}. "
                    f"Use autopsy for release memory, or set {ALLOW_PRODUCTION_ENV}=1 intentionally."
                )

    scrubbed_custom_path_keys: list[str] = []
    if not allow_custom_paths:
        if inherited_app_support and not _is_within_path(inherited_app_support, app_support_path):
            scrubbed_custom_path_keys.append("AUTOPSY_APP_SUPPORT_DIR")
            env.pop("AUTOPSY_APP_SUPPORT_DIR", None)
        for key in DEV_PATH_ENV_KEYS:
            value = str(env.get(key) or "").strip()
            if value and not _is_within_path(value, app_support_path):
                scrubbed_custom_path_keys.append(key)
                env.pop(key, None)

    scrubbed_remote_keys: list[str] = []
    if not allow_remote_falkor:
        for key in REMOTE_FALKOR_ENV_KEYS:
            if str(env.get(key) or "").strip():
                scrubbed_remote_keys.append(key)
                env.pop(key, None)

    env["AUTOPSY_DEV_MODE"] = "1"
    env["AUTOPSY_APP_SUPPORT_DIR"] = app_support
    env["AUTOPSY_MEMORY_BACKEND"] = "falkordb"
    env["AUTOPSY_FALKORDB_ENABLED"] = "1"
    for key in DEV_PATH_ENV_KEYS:
        env.setdefault(key, path_defaults[key])
    return {
        "AUTOPSY_DEV_MODE": env["AUTOPSY_DEV_MODE"],
        "AUTOPSY_APP_SUPPORT_DIR": env["AUTOPSY_APP_SUPPORT_DIR"],
        "AUTOPSY_UNIFIED_MEMORY_ROOT": env["AUTOPSY_UNIFIED_MEMORY_ROOT"],
        "AUTOPSY_FALKORDB_LITE_PATH": env["AUTOPSY_FALKORDB_LITE_PATH"],
        "AUTOPSY_SHARED_SERVER_CONFIG": env["AUTOPSY_SHARED_SERVER_CONFIG"],
        "AUTOPSY_ACTIVITY_SNAPSHOT_PATH": env["AUTOPSY_ACTIVITY_SNAPSHOT_PATH"],
        "AUTOPSY_MEMORY_GUARD_LOG_PATH": env["AUTOPSY_MEMORY_GUARD_LOG_PATH"],
        "AUTOPSY_MEMORY_RELATION_LOG_PATH": env["AUTOPSY_MEMORY_RELATION_LOG_PATH"],
        "AUTOPSY_MEMORY_BACKEND": env["AUTOPSY_MEMORY_BACKEND"],
        "AUTOPSY_FALKORDB_ENABLED": env["AUTOPSY_FALKORDB_ENABLED"],
        "scrubbed_remote_falkordb_env": ",".join(scrubbed_remote_keys),
        "scrubbed_custom_path_env": ",".join(scrubbed_custom_path_keys),
    }


def main(argv: list[str] | None = None) -> None:
    configure_dev_environment()
    from .cli import main as cli_main

    original_argv = sys.argv
    if argv is not None:
        sys.argv = [original_argv[0], *argv]
    try:
        cli_main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
