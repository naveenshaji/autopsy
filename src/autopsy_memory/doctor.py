"""Doctor checks for Autopsy memory runtime and installation state."""

from __future__ import annotations

import shutil
import sys
import re
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


def read_script_prefix(path: str | Path, *, limit: int = 12000) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")[:limit]


def script_entrypoint_flags(script: str) -> dict[str, bool]:
    return {
        "legacy_wrapper": "AUTOPSY_BUNDLED_MEMORY_TOOL" in script or "Autopsy_AutopsyCore.bundle" in script,
        "standalone_wrapper": "AUTOPSY_STANDALONE_MEMORY_WRAPPER" in script,
        "package_entrypoint": "autopsy_memory.cli" in script,
    }


def exec_target_from_script(script: str) -> str | None:
    match = re.search(r'\bexec\s+(?:"([^"]+)"|\'([^\']+)\'|([^ \t\r\n]+))', script)
    if not match:
        return None
    return next((group for group in match.groups() if group), None)


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
        script = read_script_prefix(path)
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = f"Could not inspect installed autopsy command: {exc}"
        return payload

    flags = script_entrypoint_flags(script)
    exec_target = exec_target_from_script(script)
    target_flags = {"legacy_wrapper": False, "standalone_wrapper": False, "package_entrypoint": False}
    if exec_target:
        payload["wrapper_target"] = exec_target
        payload["homebrew_env_wrapper"] = "write_env_script" in script or "AUTOPSY_UNIFIED_MEMORY" in script
        try:
            target_flags = script_entrypoint_flags(read_script_prefix(exec_target))
            payload["target_package_entrypoint"] = target_flags["package_entrypoint"]
        except Exception as exc:
            payload["target_inspection_error"] = str(exc)

    legacy_wrapper = flags["legacy_wrapper"] or target_flags["legacy_wrapper"]
    standalone_wrapper = flags["standalone_wrapper"] or target_flags["standalone_wrapper"]
    package_entrypoint = flags["package_entrypoint"] or target_flags["package_entrypoint"]
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
