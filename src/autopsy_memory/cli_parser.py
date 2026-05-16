"""Argument parser wiring for the Autopsy memory CLI."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CommandHandler = Callable[[argparse.Namespace], None]


@dataclass(frozen=True)
class CommandHandlers:
    version: CommandHandler
    instructions: CommandHandler
    init: CommandHandler
    doctor: CommandHandler
    sync: CommandHandler
    status: CommandHandler
    consult: CommandHandler
    search: CommandHandler
    benchmark: CommandHandler
    export: CommandHandler
    backup: CommandHandler
    create_note: CommandHandler
    update_item: CommandHandler
    delete_item: CommandHandler
    item: CommandHandler
    neighbors: CommandHandler
    timeline: CommandHandler
    snapshot: CommandHandler


def add_common_arguments(parser: argparse.ArgumentParser, *, falkordb_lite_path_default: Path) -> None:
    parser.add_argument("--workspace", default=str(Path.cwd()), help="Workspace root path.")
    parser.add_argument("--scope", choices=("system", "repo"), help="Accepted for compatibility; Falkor memory is stored in the unified graph.")
    parser.add_argument("--repo", help="Repository root hint for repo-scoped reads and writes.")
    parser.add_argument("--repository-root-path", help="Repository root hint for repo-scoped reads and writes.")
    parser.add_argument("--host", default=str(os.environ.get("AUTOPSY_FALKORDB_HOST") or "127.0.0.1"), help="FalkorDB host.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AUTOPSY_FALKORDB_PORT") or "6381"), help="FalkorDB port.")
    parser.add_argument(
        "--lite-path",
        default=str(os.environ.get("AUTOPSY_FALKORDB_LITE_PATH") or falkordb_lite_path_default),
        help="Path to the embedded FalkorDBLite database. Used when no explicit host or port override is provided.",
    )
    parser.add_argument("--graph-name", default=str(os.environ.get("AUTOPSY_FALKORDB_GRAPH_NAME") or "autopsy_memory"), help="FalkorDB graph name.")


def add_note_write_arguments(parser: argparse.ArgumentParser, *, include_kind: bool = False, include_outcome: bool = False) -> None:
    if include_kind:
        parser.add_argument("--kind", help="Memory kind, for example decision, attempt, question, preference, plan, or memory_note.")
    if include_outcome:
        parser.add_argument("--outcome", choices=("decision", "attempt", "question", "preference", "plan", "resolved-question", "reverted-attempt"), default="attempt")
    parser.add_argument("--title")
    parser.add_argument("--content")
    parser.add_argument("--thread-id")
    for relation_flag in ("informed-by", "answers", "supersedes", "reverts", "depends-on", "implements", "constrains", "refines"):
        parser.add_argument(f"--{relation_flag}", action="append", default=[])
    parser.add_argument("text", nargs="*")


def build_parser(
    handlers: CommandHandlers,
    *,
    falkordb_lite_path_default: Path,
    status_window_days_default: int,
) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    add_common_arguments(common, falkordb_lite_path_default=falkordb_lite_path_default)
    parser = argparse.ArgumentParser(
        description="Falkor-backed memory retrieval for Autopsy.",
        parents=[common],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser("version", help="Print the Autopsy memory package version.")
    version_parser.add_argument("--json", action="store_true", help="Print version metadata as JSON.")
    version_parser.set_defaults(func=handlers.version)

    instructions_parser = subparsers.add_parser("instructions", help="Print copy-pasteable agent instructions for Autopsy memory.")
    instructions_parser.add_argument("--json", action="store_true", help="Print instructions as JSON.")
    instructions_parser.set_defaults(func=handlers.instructions)

    init_parser = subparsers.add_parser("init", help="Install CLI-first persistent instructions for coding agents.")
    init_parser.add_argument("--global", dest="global_scope", action="store_true", help="Install global instructions for selected agents.")
    init_parser.add_argument("--repo", dest="repo_path", nargs="?", const="", help="Install repo-local instructions. Defaults to the current directory when no path is provided.")
    init_parser.add_argument("--agent", choices=("all", "codex", "claude"), default="all", help="Instruction target agent.")
    init_parser.add_argument("--print", dest="print_instructions", action="store_true", help="Print the managed instruction block without writing files.")
    init_parser.add_argument("--check", action="store_true", help="Inspect target files without writing changes.")
    init_parser.add_argument("--dry-run", action="store_true", help="Preview file changes without writing them.")
    init_parser.add_argument("--yes", action="store_true", help="Apply changes without prompting.")
    init_parser.add_argument("--smoke-test", action="store_true", help="Run doctor, read, abstention, and temporary write/delete smoke checks.")
    init_parser.add_argument("--skip-write-smoke", action="store_true", help="Skip temporary write/delete smoke check.")
    init_parser.add_argument("--mcp", action="store_true", help="Print optional MCP configuration. MCP is not installed by default.")
    init_parser.set_defaults(func=handlers.init)

    doctor_parser = subparsers.add_parser("doctor", parents=[common], help="Check local runtime dependencies and Autopsy memory paths.")
    doctor_parser.set_defaults(func=handlers.doctor)

    sync_parser = subparsers.add_parser("sync", parents=[common], help="Ensure the Falkor memory graph is initialized for the workspace.")
    sync_parser.set_defaults(func=handlers.sync)

    status_parser = subparsers.add_parser("status", parents=[common], help="Show current Falkor memory status.")
    status_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor status is current by default.")
    status_parser.add_argument("--thread-id")
    status_parser.add_argument("--limit", type=int, default=8)
    status_parser.add_argument("--section-limit", type=int, default=4)
    status_parser.add_argument("--recent-days", type=int, default=status_window_days_default)
    status_parser.set_defaults(func=handlers.status)

    consult_parser = subparsers.add_parser("consult", parents=[common], help="Query the retrieval stack.")
    consult_parser.add_argument("query_text", nargs="?", help="Natural-language query.")
    consult_parser.add_argument("--query", help="Natural-language query.")
    consult_parser.add_argument("--limit", type=int, default=5, help="Top-k result count.")
    consult_parser.add_argument("--inspect-limit", type=int, default=3, help="Number of top hits to inspect.")
    consult_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    consult_parser.add_argument(
        "--route",
        choices=("auto", "status", "lexical", "hybrid"),
        default="auto",
        help="Force or auto-select the retrieval route.",
    )
    consult_parser.set_defaults(func=handlers.consult)

    search_parser = subparsers.add_parser("search", parents=[common], help="Search Falkor memory.")
    search_parser.add_argument("query_text", nargs="?", help="Search query.")
    search_parser.add_argument("--query", help="Search query.")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    search_parser.set_defaults(func=handlers.search)

    recall_parser = subparsers.add_parser("recall", parents=[common], help="Recall relevant Falkor memory items.")
    recall_parser.add_argument("query_text", nargs="?", help="Natural-language query.")
    recall_parser.add_argument("--query", help="Natural-language query.")
    recall_parser.add_argument("--limit", type=int, default=5)
    recall_parser.add_argument("--inspect-limit", type=int, default=3)
    recall_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    recall_parser.add_argument(
        "--route",
        choices=("auto", "status", "lexical", "hybrid"),
        default="auto",
        help="Force or auto-select the retrieval route.",
    )
    recall_parser.set_defaults(func=handlers.consult)

    benchmark_parser = subparsers.add_parser("benchmark", parents=[common], help="Run the Falkor memory benchmark gate.")
    benchmark_parser.add_argument("--sample-size", type=int, default=5)
    benchmark_parser.add_argument("--include-sync", action="store_true")
    benchmark_parser.add_argument("--skip-write-probe", action="store_true")
    benchmark_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; benchmark reads the current graph by default.")
    benchmark_parser.set_defaults(func=handlers.benchmark)

    export_parser = subparsers.add_parser("export", parents=[common], help="Export memory items and in-graph relations as JSON.")
    export_parser.add_argument("--output", "-o", help="Write JSON to this path instead of stdout.")
    export_parser.add_argument("--limit", type=int, default=0, help="Maximum number of items to export. Default exports all matching items.")
    export_parser.add_argument("--include-operational", action="store_true", help="Include workspace/repository/thread/worktree/branch nodes.")
    export_parser.set_defaults(func=handlers.export)

    backup_parser = subparsers.add_parser("backup", parents=[common], help="Write a timestamped JSON memory backup.")
    backup_parser.add_argument("--output", "-o", help="Write backup JSON to this path instead of the default backups directory.")
    backup_parser.add_argument("--limit", type=int, default=0, help="Maximum number of items to export. Default exports all matching items.")
    backup_parser.add_argument("--include-operational", action="store_true", help="Include workspace/repository/thread/worktree/branch nodes.")
    backup_parser.set_defaults(func=handlers.backup)

    create_parser = subparsers.add_parser("create", parents=[common], help="Create a typed Falkor memory note.")
    add_note_write_arguments(create_parser, include_kind=True)
    create_parser.set_defaults(func=handlers.create_note)

    capture_parser = subparsers.add_parser("capture", parents=[common], help="Create a general Falkor memory note.")
    add_note_write_arguments(capture_parser, include_kind=True)
    capture_parser.set_defaults(func=handlers.create_note)

    capture_outcome_parser = subparsers.add_parser("capture-outcome", parents=[common], help="Capture a durable outcome in Falkor memory.")
    add_note_write_arguments(capture_outcome_parser, include_outcome=True)
    capture_outcome_parser.set_defaults(func=handlers.create_note)

    for note_command in ("decision", "attempt", "question", "preference", "plan", "resolved-question", "reverted-attempt"):
        note_parser = subparsers.add_parser(note_command, parents=[common], help=f"Create a {note_command} memory note.")
        add_note_write_arguments(note_parser)
        note_parser.set_defaults(func=handlers.create_note)

    update_parser = subparsers.add_parser("update", parents=[common], help="Update a Falkor memory item.")
    update_parser.add_argument("stable_key")
    add_note_write_arguments(update_parser, include_kind=True)
    update_parser.set_defaults(func=handlers.update_item)

    delete_parser = subparsers.add_parser("delete", parents=[common], help="Delete a Falkor memory item.")
    delete_parser.add_argument("stable_key")
    delete_parser.set_defaults(func=handlers.delete_item)

    item_parser = subparsers.add_parser("item", parents=[common], help="Fetch one graph item from Falkor memory.")
    item_parser.add_argument("stable_key")
    item_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    item_parser.set_defaults(func=handlers.item)

    neighbors_parser = subparsers.add_parser("neighbors", parents=[common], help="Fetch graph neighbors from Falkor memory.")
    group = neighbors_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stable-key")
    group.add_argument("--entity-id", type=int)
    group.add_argument("--thread-id")
    neighbors_parser.add_argument("--limit", type=int, default=12)
    neighbors_parser.add_argument("--all-kinds", action="store_true")
    neighbors_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    neighbors_parser.set_defaults(func=handlers.neighbors)

    timeline_parser = subparsers.add_parser("timeline", parents=[common], help="Fetch a relation timeline from Falkor memory.")
    timeline_parser.add_argument("stable_key")
    timeline_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    timeline_parser.set_defaults(func=handlers.timeline)

    snapshot_parser = subparsers.add_parser("snapshot", parents=[common], help="Fetch a graph snapshot around one item from Falkor memory.")
    snapshot_parser.add_argument("stable_key")
    snapshot_parser.add_argument("--limit", type=int, default=20)
    snapshot_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    snapshot_parser.set_defaults(func=handlers.snapshot)

    return parser


def normalized_cli_args(raw_args: list[str]) -> list[str]:
    if raw_args[:1] == ["memory"]:
        return raw_args[1:]
    return raw_args
