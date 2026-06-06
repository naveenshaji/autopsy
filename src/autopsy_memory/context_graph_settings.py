"""Persisted context graph capture settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CONTEXT_GRAPH_MODE_CLI = "cli"
CONTEXT_GRAPH_MODE_HOOKS = "hooks"
CONTEXT_GRAPH_MODES = (CONTEXT_GRAPH_MODE_CLI, CONTEXT_GRAPH_MODE_HOOKS)

DEFAULT_CONTEXT_GRAPH_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "mode": CONTEXT_GRAPH_MODE_CLI,
    "multi_turn": False,
}


def _truthy(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def normalize_context_graph_mode(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if text in {"hook", "hooks", "codex-hook", "codex-hooks", "codex"}:
        return CONTEXT_GRAPH_MODE_HOOKS
    if text in {"cli", "manual", "command", "context-event"}:
        return CONTEXT_GRAPH_MODE_CLI
    return CONTEXT_GRAPH_MODE_CLI


def normalize_context_graph_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "enabled": _truthy(source.get("enabled"), default=True),
        "mode": normalize_context_graph_mode(source.get("mode") or source.get("capture_mode")),
        "multi_turn": _truthy(source.get("multi_turn") or source.get("multiTurn"), default=False),
    }


def context_graph_settings_path() -> Path:
    configured = (
        os.environ.get("AUTOPSY_CONTEXT_GRAPH_SETTINGS_PATH")
        or os.environ.get("AUTOPSY_CONTEXT_GRAPH_SETTINGS")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser()
    app_support = Path(
        os.environ.get("AUTOPSY_APP_SUPPORT_DIR")
        or Path.home() / "Library" / "Application Support" / "Autopsy"
    )
    return app_support / "Config" / "context-graph-settings.json"


def load_context_graph_settings() -> dict[str, Any]:
    path = context_graph_settings_path()
    if not path.exists():
        return dict(DEFAULT_CONTEXT_GRAPH_SETTINGS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_CONTEXT_GRAPH_SETTINGS)
    return normalize_context_graph_settings(raw if isinstance(raw, dict) else {})


def save_context_graph_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_context_graph_settings(settings)
    path = context_graph_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def context_graph_settings_payload(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_context_graph_settings(settings or load_context_graph_settings())
    enabled = bool(normalized["enabled"])
    mode = str(normalized["mode"])
    if not enabled:
        status = "disabled"
        message = "Context graph capture is disabled in Autopsy settings."
    elif mode == CONTEXT_GRAPH_MODE_HOOKS:
        status = "hooks"
        message = "Context graph capture is using Codex hooks."
    else:
        status = "cli"
        message = "Context graph capture is using CLI context-event commands."
    return {
        **normalized,
        "status": status,
        "message": message,
        "path": str(context_graph_settings_path()),
    }


def context_graph_capture_state(caller: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_context_graph_settings(settings or load_context_graph_settings())
    enabled = bool(normalized["enabled"])
    mode = str(normalized["mode"])
    caller_key = str(caller or "").strip().lower()
    if not enabled:
        return {
            **normalized,
            "record": False,
            "reason": "context_graph_disabled",
            "message": "Context graph is disabled in Autopsy settings. No graph event was recorded.",
        }
    if caller_key in {"context-event", "mcp-context-event"} and mode == CONTEXT_GRAPH_MODE_HOOKS:
        return {
            **normalized,
            "record": False,
            "reason": "context_graph_hook_mode",
            "message": "Context graph is in hooks mode. Agents do not need to call autopsy context-event.",
        }
    if caller_key in {"codex-hook", "hook"} and mode != CONTEXT_GRAPH_MODE_HOOKS:
        return {
            **normalized,
            "record": False,
            "reason": "context_graph_cli_mode",
            "message": "Context graph is in CLI mode. Codex hook capture is inactive.",
        }
    return {
        **normalized,
        "record": True,
        "reason": "",
        "message": "",
    }


def context_graph_skip_payload(
    caller: str,
    *,
    command: str = "",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = context_graph_capture_state(caller, settings=settings)
    payload: dict[str, Any] = {
        "ok": True,
        "skipped": True,
        "reason": state["reason"],
        "message": state["message"],
        "context_graph": {
            "enabled": state["enabled"],
            "mode": state["mode"],
            "multi_turn": state["multi_turn"],
        },
    }
    if command:
        payload["command"] = command
    return payload
