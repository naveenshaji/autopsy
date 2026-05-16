"""First-run instruction installer for Autopsy memory."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metadata import AGENT_INSTRUCTIONS


MANAGED_START = "<!-- AUTOPSY_MEMORY_START v1 -->"
MANAGED_END = "<!-- AUTOPSY_MEMORY_END -->"
LEGACY_HEADING = "## Autopsy Memory Usage"
SUPPORTED_AGENTS = ("codex", "claude")

MCP_SNIPPET = """[mcp_servers.autopsy_falkor_memory]
command = "autopsy-memory-mcp"
env = { AUTOPSY_UNIFIED_MEMORY = "1" }
"""


@dataclass(frozen=True)
class InstructionTarget:
    agent: str
    scope: str
    path: Path
    description: str


def managed_instruction_block() -> str:
    return f"{MANAGED_START}\n{AGENT_INSTRUCTIONS.rstrip()}\n{MANAGED_END}\n"


def strip_unmanaged_autopsy_sections(text: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    removed = False
    index = 0
    while index < len(lines):
        if lines[index].strip() != LEGACY_HEADING:
            output.append(lines[index])
            index += 1
            continue
        removed = True
        index += 1
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped == MANAGED_START:
                break
            if stripped.startswith("#"):
                break
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
    return "".join(output), removed


def patch_managed_block(existing: str, block: str) -> tuple[str, str]:
    start = existing.find(MANAGED_START)
    end = existing.find(MANAGED_END)
    if start >= 0 and end >= start:
        end += len(MANAGED_END)
        prefix, removed_prefix = strip_unmanaged_autopsy_sections(existing[:start])
        suffix, removed_suffix = strip_unmanaged_autopsy_sections(existing[end:])
        existing = prefix + existing[start:end] + suffix
        start = existing.find(MANAGED_START)
        end = existing.find(MANAGED_END)
        end += len(MANAGED_END)
        replacement = block.rstrip()
        new_text = existing[:start] + replacement + existing[end:]
        if not new_text.endswith("\n"):
            new_text += "\n"
        removed_legacy = removed_prefix or removed_suffix
        return new_text, "unchanged" if new_text == existing and not removed_legacy else "updated"

    existing, removed_legacy = strip_unmanaged_autopsy_sections(existing)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    extra_newline = "" if not existing.strip() else "\n"
    return f"{existing}{separator}{extra_newline}{block}", "updated" if removed_legacy else "added"


def selected_agents(value: str) -> list[str]:
    if value == "all":
        return list(SUPPORTED_AGENTS)
    return [value]


def resolve_repo_path(value: str | None) -> Path | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return Path.cwd()
    return Path(raw).expanduser().resolve()


def instruction_targets(
    *,
    home: Path,
    repo_path: Path | None,
    install_global: bool,
    agent: str,
) -> list[InstructionTarget]:
    agents = selected_agents(agent)
    targets: list[InstructionTarget] = []
    if install_global:
        if "codex" in agents:
            targets.append(InstructionTarget(
                agent="codex",
                scope="global",
                path=home / ".codex" / "AGENTS.md",
                description="Codex global instructions",
            ))
        if "claude" in agents:
            targets.append(InstructionTarget(
                agent="claude",
                scope="global",
                path=home / ".claude" / "CLAUDE.md",
                description="Claude Code global memory",
            ))
    if repo_path:
        if "codex" in agents:
            targets.append(InstructionTarget(
                agent="codex",
                scope="repo",
                path=repo_path / "AGENTS.md",
                description="repo Codex/agent instructions",
            ))
        if "claude" in agents:
            targets.append(InstructionTarget(
                agent="claude",
                scope="repo",
                path=repo_path / "CLAUDE.md",
                description="repo Claude Code memory",
            ))
    return targets


def target_status(target: InstructionTarget) -> dict[str, Any]:
    if not target.path.exists():
        state = "missing"
    else:
        text = target.path.read_text(encoding="utf-8", errors="ignore")
        state = "managed" if MANAGED_START in text and MANAGED_END in text else "unmanaged"
    return {
        "agent": target.agent,
        "scope": target.scope,
        "path": str(target.path),
        "description": target.description,
        "state": state,
    }


def write_target(target: InstructionTarget, *, dry_run: bool) -> dict[str, Any]:
    existing = target.path.read_text(encoding="utf-8") if target.path.exists() else ""
    new_text, action = patch_managed_block(existing, managed_instruction_block())
    changed = new_text != existing
    if changed and not dry_run:
        target.path.parent.mkdir(parents=True, exist_ok=True)
        target.path.write_text(new_text, encoding="utf-8")
    payload = target_status(target) if target.path.exists() else {
        "agent": target.agent,
        "scope": target.scope,
        "path": str(target.path),
        "description": target.description,
        "state": "missing",
    }
    payload.update({
        "action": action,
        "changed": changed,
        "dry_run": dry_run,
    })
    return payload


def run_command(command: list[str], *, timeout: int = 20) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return {
            "command": command,
            "ok": False,
            "error": str(exc),
        }
    return {
        "command": command,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[-4000:],
        "stderr": completed.stderr.strip()[-4000:],
    }


def smoke_tests(*, skip_write: bool) -> list[dict[str, Any]]:
    checks = [
        run_command(["autopsy", "doctor"], timeout=30),
        run_command(["autopsy", "status", "--current-only", "--limit", "1", "--section-limit", "1"], timeout=30),
        consult_abstention_check(),
    ]
    if not skip_write:
        title = "Autopsy init smoke test"
        content = "Temporary smoke-test memory created by autopsy init."
        write_result = run_command([
            "autopsy",
            "capture-outcome",
            "--outcome",
            "attempt",
            "--title",
            title,
            "--content",
            content,
        ], timeout=30)
        checks.append(write_result)
        if write_result.get("ok"):
            stable_key = extract_stable_key(write_result.get("stdout", ""))
            if stable_key:
                checks.append(run_command(["autopsy", "delete", stable_key], timeout=30))
    return checks


def consult_abstention_check() -> dict[str, Any]:
    result = run_command([
        "autopsy",
        "consult",
        "--current-only",
        "--query",
        "nohit-autopsy-init-smoke-glass-cactus-riverboat-lunar-biscuit",
    ], timeout=30)
    if not result.get("ok"):
        return result
    try:
        payload = json.loads(str(result.get("stdout") or ""))
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"consult output was not JSON: {exc}"
        return result
    hit_count = len(payload.get("hits") or [])
    result["hit_count"] = hit_count
    if hit_count:
        result["ok"] = False
        result["error"] = "no-hit consult smoke test returned memory hits"
    return result


def extract_stable_key(output: str) -> str | None:
    try:
        payload = json.loads(output)
    except Exception:
        return None
    item = payload.get("item") if isinstance(payload, dict) else None
    if isinstance(item, dict):
        value = item.get("stable_key") or item.get("stableKey")
        return str(value) if value else None
    items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(items, list) and items:
        value = items[0].get("stable_key") or items[0].get("stableKey")
        return str(value) if value else None
    return None


def build_init_payload(args: argparse.Namespace) -> dict[str, Any]:
    repo_arg = getattr(args, "repo_path", None)
    install_global = bool(getattr(args, "global_scope", False))
    repo_path = resolve_repo_path(repo_arg)
    if not install_global and repo_path is None and not getattr(args, "print_instructions", False) and not getattr(args, "mcp", False):
        install_global = True
        repo_path = Path.cwd().resolve()

    home = Path.home()
    targets = instruction_targets(
        home=home,
        repo_path=repo_path,
        install_global=install_global,
        agent=getattr(args, "agent", "all"),
    )
    dry_run = bool(getattr(args, "dry_run", False) or getattr(args, "check", False))
    apply_changes = not dry_run
    if getattr(args, "check", False):
        apply_changes = False
    if getattr(args, "dry_run", False):
        apply_changes = False

    payload: dict[str, Any] = {
        "mode": "init",
        "autopsy_command": shutil.which("autopsy"),
        "agent": getattr(args, "agent", "all"),
        "global": install_global,
        "repo": str(repo_path) if repo_path else None,
        "dry_run": dry_run,
        "targets": [],
        "mcp": None,
        "smoke_tests": [],
        "workflow": {
            "complete": True,
            "next_steps": [],
        },
    }

    if getattr(args, "print_instructions", False):
        payload["instructions"] = managed_instruction_block().rstrip()

    if getattr(args, "mcp", False):
        payload["mcp"] = {
            "optional": True,
            "note": "MCP is optional. The default Autopsy integration is persistent instructions plus CLI commands.",
            "codex_toml": MCP_SNIPPET.rstrip(),
        }

    for target in targets:
        if apply_changes:
            payload["targets"].append(write_target(target, dry_run=False))
        elif dry_run:
            payload["targets"].append(write_target(target, dry_run=True))
        else:
            payload["targets"].append(target_status(target))

    if getattr(args, "smoke_test", False):
        payload["smoke_tests"] = smoke_tests(skip_write=bool(getattr(args, "skip_write_smoke", False)))

    incomplete = []
    if not payload["autopsy_command"]:
        incomplete.append("Install the standalone Autopsy CLI before using agent instructions.")
    if not targets and not getattr(args, "print_instructions", False) and not getattr(args, "mcp", False):
        incomplete.append("Select at least one target with --global or --repo.")
    if incomplete:
        payload["workflow"] = {"complete": False, "next_steps": incomplete}
    return payload


def cmd_init(args: argparse.Namespace) -> None:
    print(json.dumps(build_init_payload(args), indent=2))
