"""Doctor checks for Autopsy memory runtime and installation state."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any


def import_check(module_name: str, *, required: bool) -> dict[str, Any]:
    try:
        __import__(module_name)
        return {"name": module_name, "required": required, "ok": True}
    except Exception as exc:
        return {"name": module_name, "required": required, "ok": False, "error": str(exc)}


def python_version_check() -> dict[str, Any]:
    ok = sys.version_info >= (3, 12)
    payload = {
        "name": "python_version",
        "required": True,
        "ok": ok,
        "version": sys.version.split()[0],
        "minimum": "3.12",
    }
    if not ok:
        payload["error"] = "Autopsy requires Python 3.12 or newer."
    return payload


def installed_autopsy_command_check() -> dict[str, Any]:
    path = shutil.which("autopsy")
    payload: dict[str, Any] = {
        "name": "installed_autopsy_command",
        "required": True,
        "ok": True,
        "path": path,
    }
    if not path:
        payload["ok"] = False
        payload["error"] = "No autopsy command was found on PATH."
        return payload
    try:
        script = Path(path).read_text(encoding="utf-8", errors="ignore")[:12000]
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = f"Could not inspect installed autopsy command: {exc}"
        return payload
    legacy_wrapper = "AUTOPSY_BUNDLED_MEMORY_TOOL" in script or "Autopsy_AutopsyCore.bundle" in script
    standalone_wrapper = "AUTOPSY_STANDALONE_MEMORY_WRAPPER" in script
    package_entrypoint = "autopsy_memory.cli" in script
    payload.update({
        "legacy_wrapper": legacy_wrapper,
        "standalone_wrapper": standalone_wrapper,
        "package_entrypoint": package_entrypoint,
    })
    if legacy_wrapper:
        payload["ok"] = False
        payload["error"] = "The autopsy command on PATH is the legacy app wrapper, not the standalone memory CLI."
    elif not (standalone_wrapper or package_entrypoint):
        payload["ok"] = False
        payload["error"] = "The autopsy command on PATH does not appear to launch autopsy_memory.cli."
    return payload
