#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from typing import MutableMapping


PRODUCTION_APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Autopsy"
DEFAULT_DEV_APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "AutopsyDev"
ALLOW_PRODUCTION_ENV = "AUTOPSY_DEV_ALLOW_PRODUCTION_MEMORY"


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_production_path(path: str | Path, production_root: Path = PRODUCTION_APP_SUPPORT_DIR) -> bool:
    resolved = _resolved(path)
    production = _resolved(production_root)
    return resolved == production or production in resolved.parents


def configure_dev_environment(environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    env = environ if environ is not None else os.environ
    allow_production = str(env.get(ALLOW_PRODUCTION_ENV) or "").strip() == "1"
    app_support = env.get("AUTOPSY_APP_SUPPORT_DIR") or env.get("AUTOPSY_DEV_APP_SUPPORT_DIR") or str(DEFAULT_DEV_APP_SUPPORT_DIR)

    guarded_values = {
        "AUTOPSY_APP_SUPPORT_DIR": app_support,
        "AUTOPSY_FALKORDB_LITE_PATH": env.get("AUTOPSY_FALKORDB_LITE_PATH") or "",
        "AUTOPSY_UNIFIED_MEMORY_ROOT": env.get("AUTOPSY_UNIFIED_MEMORY_ROOT") or "",
    }
    if not allow_production:
        for key, value in guarded_values.items():
            if value and _is_production_path(value):
                raise SystemExit(
                    f"autopsy-dev refused to use production memory via {key}={value}. "
                    f"Use autopsy for release memory, or set {ALLOW_PRODUCTION_ENV}=1 intentionally."
                )

    env["AUTOPSY_DEV_MODE"] = "1"
    env["AUTOPSY_APP_SUPPORT_DIR"] = app_support
    app_support_path = Path(app_support).expanduser()
    env.setdefault("AUTOPSY_UNIFIED_MEMORY_ROOT", str(app_support_path / "MemoryRoot"))
    env.setdefault("AUTOPSY_FALKORDB_LITE_PATH", str(app_support_path / "FalkorDB" / "autopsy-memory.db"))
    return {
        "AUTOPSY_DEV_MODE": env["AUTOPSY_DEV_MODE"],
        "AUTOPSY_APP_SUPPORT_DIR": env["AUTOPSY_APP_SUPPORT_DIR"],
        "AUTOPSY_UNIFIED_MEMORY_ROOT": env["AUTOPSY_UNIFIED_MEMORY_ROOT"],
        "AUTOPSY_FALKORDB_LITE_PATH": env["AUTOPSY_FALKORDB_LITE_PATH"],
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
