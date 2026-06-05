"""Doctor checks for Autopsy memory runtime and installation state."""

from __future__ import annotations

import shutil
import sys
import re
import os
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


def autopsy_command_candidates() -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory).expanduser() / "autopsy"
        try:
            resolved = str(candidate.resolve())
        except OSError:
            resolved = str(candidate)
        if resolved in seen or not candidate.exists() or not os.access(candidate, os.X_OK):
            continue
        seen.add(resolved)
        candidates.append(str(candidate))
    return candidates


def script_launches_package_entrypoint(path: str | Path) -> bool:
    script = read_script_prefix(path)
    flags = script_entrypoint_flags(script)
    exec_target = exec_target_from_script(script)
    if flags["legacy_wrapper"]:
        return False
    if flags["standalone_wrapper"] or flags["package_entrypoint"]:
        return True
    if exec_target:
        target_flags = script_entrypoint_flags(read_script_prefix(exec_target))
        return not target_flags["legacy_wrapper"] and (target_flags["standalone_wrapper"] or target_flags["package_entrypoint"])
    return False


def installed_autopsy_command_check() -> dict[str, Any]:
    path = shutil.which("autopsy")
    candidates = autopsy_command_candidates()
    payload: dict[str, Any] = {
        "name": "installed_autopsy_command",
        "required": True,
        "ok": True,
        "path": path,
        "path_candidates": candidates,
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
    if not payload["ok"]:
        for candidate in candidates[1:]:
            try:
                if script_launches_package_entrypoint(candidate):
                    payload["shadowed_valid_command"] = candidate
                    payload["error"] = (
                        f"{payload['error']} A valid Autopsy command exists later on PATH at {candidate}; "
                        "move or remove the earlier command, or put Homebrew's bin directory first."
                    )
                    break
            except Exception:
                continue
    return payload
