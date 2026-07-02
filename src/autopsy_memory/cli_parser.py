"""Argument parser wiring for the Autopsy memory CLI."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .init import SUPPORTED_AGENTS


CommandHandler = Callable[[argparse.Namespace], None]


@dataclass(frozen=True)
class CommandHandlers:
    version: CommandHandler
    instructions: CommandHandler
    init: CommandHandler
    install: CommandHandler
    doctor: CommandHandler
    sync: CommandHandler
    status: CommandHandler
    context: CommandHandler
    consult: CommandHandler
    search: CommandHandler
    benchmark: CommandHandler
    audit: CommandHandler
    export: CommandHandler
    backup: CommandHandler
    restore: CommandHandler
    compare_backups: CommandHandler
    health: CommandHandler
    diagnostics: CommandHandler
    repair_embedded_snapshot: CommandHandler
    activity: CommandHandler
    shared_server: CommandHandler
    menubar: CommandHandler
    model_warmup: CommandHandler
    create_note: CommandHandler
    update_item: CommandHandler
    delete_item: CommandHandler
    expire_item: CommandHandler
    pin_item: CommandHandler
    feedback: CommandHandler
    import_session: CommandHandler
    consolidate_session: CommandHandler
    observe: CommandHandler
    item: CommandHandler
    neighbors: CommandHandler
    timeline: CommandHandler
    history: CommandHandler
    snapshot: CommandHandler


def add_common_arguments(parser: argparse.ArgumentParser, *, falkordb_lite_path_default: Path) -> None:
    parser.add_argument("--workspace", default=str(Path.cwd()), help="Workspace root path.")
    parser.add_argument("--scope", choices=("system", "repo"), help="Read scope. Use repo to constrain retrieval to one repository.")
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
        parser.add_argument("--kind", help="Memory kind, for example decision, attempt, observation, procedure, question, preference, plan, or memory_note.")
    if include_outcome:
        parser.add_argument("--outcome", choices=("decision", "attempt", "observation", "procedure", "question", "preference", "plan", "resolved-question", "reverted-attempt"), default="attempt")
    parser.add_argument("--title")
    parser.add_argument("--content")
    parser.add_argument("--thread-id")
    parser.add_argument("--tag", action="append", help="Attach one or more normalized memory tags. Repeat or comma-separate values.")
    parser.add_argument("--namespace", action="append", help="Attach one or more normalized memory namespaces. Repeat or comma-separate values.")
    add_entity_scope_arguments(parser, verb="Attach")
    parser.add_argument("--metadata", action="append", help="Attach structured memory metadata as KEY=VALUE. Repeat for multiple fields.")
    for relation_flag in ("informed-by", "answers", "supersedes", "reverts", "depends-on", "implements", "constrains", "refines"):
        parser.add_argument(f"--{relation_flag}", action="append", default=[])
    parser.add_argument("--relation-valid-at", help="ISO-8601 timestamp for when newly created semantic relation facts became true.")
    parser.add_argument("--relation-invalid-at", help="ISO-8601 timestamp for when newly created semantic relation facts stopped being true.")
    parser.add_argument("--relation-expires-at", help="ISO-8601 timestamp for when newly created semantic relation facts should leave current reads.")
    parser.add_argument("--fact-rating", type=float, help="Optional 0.0-1.0 quality rating to attach to newly created semantic relation facts.")
    parser.add_argument(
        "--no-relations-ok",
        action="store_true",
        help="Mark this write as intentionally standalone when no semantic relation applies.",
    )
    parser.add_argument(
        "--allow-unsafe-memory",
        action="store_true",
        help="Bypass the write-time safety guard for deliberate incident evidence; unsafe findings remain in write_quality.",
    )
    parser.add_argument("text", nargs="*")


def add_entity_scope_arguments(parser: argparse.ArgumentParser, *, verb: str = "Restrict") -> None:
    parser.add_argument("--entity-scope", action="append", help=f"{verb} one or more entity scopes as TYPE:ID, for example user:alice, agent:planner, app:web, run:ticket-42, or group:team-a. Repeat or comma-separate values.")
    parser.add_argument("--user-id", action="append", help=f"{verb} a user-scoped memory partition. Repeat or comma-separate values.")
    parser.add_argument("--agent-id", action="append", help=f"{verb} an agent-scoped memory partition. Repeat or comma-separate values.")
    parser.add_argument("--app-id", action="append", help=f"{verb} an application-scoped memory partition. Repeat or comma-separate values.")
    parser.add_argument("--run-id", action="append", help=f"{verb} a run/session-scoped memory partition. Repeat or comma-separate values.")
    parser.add_argument("--group-id", action="append", help=f"{verb} a group/tenant-scoped memory partition. Repeat or comma-separate values.")


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
    instructions_parser.add_argument("--agent", choices=("generic", *SUPPORTED_AGENTS), default="generic", help="Render instructions for a specific agent.")
    instructions_parser.add_argument("--json", action="store_true", help="Print instructions as JSON.")
    instructions_parser.set_defaults(func=handlers.instructions)

    init_parser = subparsers.add_parser("init", help="Install CLI-first persistent instructions for coding agents.")
    init_parser.add_argument("--global", dest="global_scope", action="store_true", help="Install global instructions for selected agents.")
    init_parser.add_argument("--repo", dest="repo_path", nargs="?", const="", help="Install repo-local instructions. Defaults to the current directory when no path is provided.")
    init_parser.add_argument("--agent", choices=("all", *SUPPORTED_AGENTS), default="all", help="Instruction target agent.")
    init_parser.add_argument("--print", dest="print_instructions", action="store_true", help="Print the managed instruction block without writing files.")
    init_parser.add_argument("--check", action="store_true", help="Inspect target files without writing changes.")
    init_parser.add_argument("--dry-run", action="store_true", help="Preview file changes without writing them.")
    init_parser.add_argument("--yes", action="store_true", help="Apply changes without prompting.")
    init_parser.add_argument("--smoke-test", action="store_true", help="Run doctor, read, abstention, and temporary write/delete smoke checks.")
    init_parser.add_argument("--skip-write-smoke", action="store_true", help="Skip temporary write/delete smoke check.")
    init_parser.add_argument("--mcp", action="store_true", help="Print optional MCP configuration. MCP is not installed by default.")
    init_parser.set_defaults(func=handlers.init)

    install_parser = subparsers.add_parser("install", help="Install Autopsy for normal local use.")
    install_parser.add_argument("--agent", choices=("all", *SUPPORTED_AGENTS), default="all", help="Instruction target agent.")
    install_parser.add_argument("--repo", dest="repo_path", nargs="?", const="", help="Also install repo-local instructions. Defaults to the current directory when no path is provided.")
    install_parser.add_argument("--dry-run", action="store_true", help="Preview setup without writing files or installing launchd state.")
    install_parser.add_argument("--skip-path-repair", action="store_true", help="Do not repair the autopsy command on PATH.")
    install_parser.add_argument("--skip-instructions", action="store_true", help="Do not install agent instructions.")
    install_parser.add_argument("--skip-menubar", action="store_true", help="Do not install the macOS menu bar LaunchAgent.")
    install_parser.add_argument("--skip-doctor", action="store_true", help="Do not run doctor after setup.")
    install_parser.add_argument("--skip-model-warmup", action="store_true", help="Do not start the background local ML model warmup.")
    install_parser.add_argument("--menubar-dir", help="Path to the Swift menu bar app package.")
    install_parser.add_argument("--rebuild", action="store_true", help="Force rebuilding the Swift menu bar app before installing startup.")
    install_parser.add_argument("--release", action="store_true", help="Use a release SwiftPM build for the menu bar app.")
    install_parser.add_argument("--smoke-test", action="store_true", help="Run doctor, read, abstention, and temporary write/delete smoke checks after installing instructions.")
    install_parser.add_argument("--skip-write-smoke", action="store_true", help="Skip temporary write/delete smoke check.")
    install_parser.set_defaults(func=handlers.install)

    doctor_parser = subparsers.add_parser("doctor", parents=[common], help="Check local runtime dependencies and Autopsy memory paths.")
    doctor_parser.add_argument("--cleanup-workers", action="store_true", help="Terminate stale resident memory workers that share the current worker info file.")
    doctor_parser.set_defaults(func=handlers.doctor)

    sync_parser = subparsers.add_parser("sync", parents=[common], help="Ensure the Falkor memory graph is initialized for the workspace.")
    sync_parser.set_defaults(func=handlers.sync)

    status_parser = subparsers.add_parser("status", parents=[common], help="Show current Falkor memory status.")
    status_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor status is current by default.")
    status_parser.add_argument("--as-of", help="Read memory as of an ISO-8601 timestamp, excluding records updated after that time.")
    status_parser.add_argument("--thread-id")
    status_parser.add_argument("--limit", type=int, default=8)
    status_parser.add_argument("--section-limit", type=int, default=4)
    status_parser.add_argument("--recent-days", type=int, default=status_window_days_default)
    status_parser.set_defaults(func=handlers.status)

    context_parser = subparsers.add_parser("context", parents=[common], help="Build a compact agent context pack from status plus consult.")
    context_parser.add_argument("query_text", nargs="?", help="Natural-language task or context query.")
    context_parser.add_argument("--query", help="Natural-language task or context query.")
    context_parser.add_argument("--limit", type=int, default=5, help="Top-k retrieval result count.")
    context_parser.add_argument("--inspect-limit", type=int, default=3, help="Number of top retrieval hits to inspect.")
    context_parser.add_argument("--kind", action="append", help="Restrict retrieval to one or more memory kinds. Repeat or comma-separate values.")
    context_parser.add_argument("--memory-type", action="append", help="Restrict retrieval to semantic, episodic, procedural, or observation memory. Repeat or comma-separate values.")
    context_parser.add_argument("--tag", action="append", help="Restrict retrieval to memories containing all requested tags. Repeat or comma-separate values.")
    context_parser.add_argument("--namespace", action="append", help="Restrict retrieval to one or more memory namespaces. Repeat or comma-separate values.")
    add_entity_scope_arguments(context_parser)
    context_parser.add_argument("--metadata", action="append", help="Restrict retrieval with metadata filters such as key=value, key!=value, key~=text, or score>=8.")
    context_parser.add_argument("--filter-json", action="append", help="Restrict retrieval with a JSON boolean filter over kind, tag, namespace, entity scope, metadata, and item fields.")
    context_parser.add_argument("--min-fact-rating", type=float, help="Only include relation facts rated at or above this 0.0-1.0 threshold in relation retrieval.")
    context_parser.add_argument("--status-limit", type=int, default=6, help="Maximum current-state items to include.")
    context_parser.add_argument("--section-limit", type=int, default=3, help="Maximum items per current-state section.")
    context_parser.add_argument("--recent-days", type=int, default=status_window_days_default)
    context_parser.add_argument("--max-chars", type=int, default=6000, help="Approximate character budget for agent_context entries.")
    context_parser.add_argument("--include-shared", action="store_true", help="Also fetch source-attributed context from the configured shared memory server.")
    context_parser.add_argument("--shared-query", help="Query text for shared memory context. Defaults to the local context query.")
    context_parser.add_argument("--shared-repo-scope", help="Exact shared-server repo scope for --include-shared. Defaults to --repo or the current repository.")
    context_parser.add_argument("--shared-graph-slug", help="Shared graph slug for --include-shared. Defaults to the configured graph.")
    context_parser.add_argument("--shared-server-config", dest="shared_server_config", help="Path to the local shared-server config JSON for --include-shared.")
    context_parser.add_argument("--shared-limit", type=int, default=8, help="Maximum shared memories to retrieve with --include-shared.")
    context_parser.add_argument("--shared-include-archived", action="store_true", help="With --include-shared, include archived shared memories.")
    context_parser.add_argument("--shared-no-relations", action="store_true", help="With --include-shared, omit adjacent shared graph relations.")
    context_parser.add_argument("--shared-min-fact-rating", type=float, help="With --include-shared, omit adjacent shared relations below this 0.0-1.0 rating. Defaults to --min-fact-rating when omitted.")
    context_parser.add_argument("--include-linked-shared", action="store_true", help="Also follow private personal-to-shared links from local context stable keys.")
    context_parser.add_argument("--linked-shared-personal-key", action="append", help="Specific personal stable key to resolve through private shared links. Repeat or comma-separate.")
    context_parser.add_argument("--linked-shared-repo-scope", help="Exact shared-server repo scope for --include-linked-shared. Defaults to --shared-repo-scope, --repo, or the current repository.")
    context_parser.add_argument("--linked-shared-limit", type=int, default=8, help="Maximum linked shared memories to retrieve.")
    context_parser.add_argument("--linked-shared-include-archived", action="store_true", help="With --include-linked-shared, include archived shared targets.")
    context_parser.add_argument("--linked-shared-no-relations", action="store_true", help="With --include-linked-shared, omit adjacent shared graph relations.")
    context_parser.add_argument("--linked-shared-min-fact-rating", type=float, help="With --include-linked-shared, omit adjacent shared relations below this 0.0-1.0 rating. Defaults to --shared-min-fact-rating or --min-fact-rating.")
    context_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output structured JSON or a deterministic text context block.",
    )
    context_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    context_parser.add_argument("--as-of", help="Read memory as of an ISO-8601 timestamp, excluding records updated after that time.")
    context_parser.add_argument("--no-worker", action="store_true", help="Run consult in this CLI process instead of the resident worker.")
    context_parser.add_argument(
        "--route",
        choices=("auto", "status", "lexical", "hybrid"),
        default="auto",
        help="Force or auto-select the retrieval route for the consult portion.",
    )
    context_parser.set_defaults(func=handlers.context)

    consult_parser = subparsers.add_parser("consult", parents=[common], help="Query the retrieval stack.")
    consult_parser.add_argument("query_text", nargs="?", help="Natural-language query.")
    consult_parser.add_argument("--query", help="Natural-language query.")
    consult_parser.add_argument("--limit", type=int, default=5, help="Top-k result count.")
    consult_parser.add_argument("--inspect-limit", type=int, default=3, help="Number of top hits to inspect.")
    consult_parser.add_argument("--kind", action="append", help="Restrict retrieval to one or more memory kinds. Repeat or comma-separate values.")
    consult_parser.add_argument("--memory-type", action="append", help="Restrict retrieval to semantic, episodic, procedural, or observation memory. Repeat or comma-separate values.")
    consult_parser.add_argument("--tag", action="append", help="Restrict retrieval to memories containing all requested tags. Repeat or comma-separate values.")
    consult_parser.add_argument("--namespace", action="append", help="Restrict retrieval to one or more memory namespaces. Repeat or comma-separate values.")
    add_entity_scope_arguments(consult_parser)
    consult_parser.add_argument("--metadata", action="append", help="Restrict retrieval with metadata filters such as key=value, key!=value, key~=text, or score>=8.")
    consult_parser.add_argument("--filter-json", action="append", help="Restrict retrieval with a JSON boolean filter over kind, tag, namespace, entity scope, metadata, and item fields.")
    consult_parser.add_argument("--min-fact-rating", type=float, help="Only include relation facts rated at or above this 0.0-1.0 threshold in relation retrieval.")
    consult_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    consult_parser.add_argument("--as-of", help="Read memory as of an ISO-8601 timestamp, excluding records updated after that time.")
    consult_parser.add_argument("--no-worker", action="store_true", help="Run consult in this CLI process instead of the resident worker.")
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
    search_parser.add_argument("--kind", action="append", help="Restrict search to one or more memory kinds. Repeat or comma-separate values.")
    search_parser.add_argument("--memory-type", action="append", help="Restrict search to semantic, episodic, procedural, or observation memory. Repeat or comma-separate values.")
    search_parser.add_argument("--tag", action="append", help="Restrict search to memories containing all requested tags. Repeat or comma-separate values.")
    search_parser.add_argument("--namespace", action="append", help="Restrict search to one or more memory namespaces. Repeat or comma-separate values.")
    add_entity_scope_arguments(search_parser)
    search_parser.add_argument("--metadata", action="append", help="Restrict search with metadata filters such as key=value, key!=value, key~=text, or score>=8.")
    search_parser.add_argument("--filter-json", action="append", help="Restrict search with a JSON boolean filter over kind, tag, namespace, entity scope, metadata, and item fields.")
    search_parser.add_argument("--min-fact-rating", type=float, help="Only include relation facts rated at or above this 0.0-1.0 threshold in relation retrieval.")
    search_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    search_parser.add_argument("--as-of", help="Read memory as of an ISO-8601 timestamp, excluding records updated after that time.")
    search_parser.set_defaults(func=handlers.search)

    recall_parser = subparsers.add_parser("recall", parents=[common], help="Recall relevant Falkor memory items.")
    recall_parser.add_argument("query_text", nargs="?", help="Natural-language query.")
    recall_parser.add_argument("--query", help="Natural-language query.")
    recall_parser.add_argument("--limit", type=int, default=5)
    recall_parser.add_argument("--inspect-limit", type=int, default=3)
    recall_parser.add_argument("--kind", action="append", help="Restrict retrieval to one or more memory kinds. Repeat or comma-separate values.")
    recall_parser.add_argument("--memory-type", action="append", help="Restrict retrieval to semantic, episodic, procedural, or observation memory. Repeat or comma-separate values.")
    recall_parser.add_argument("--tag", action="append", help="Restrict retrieval to memories containing all requested tags. Repeat or comma-separate values.")
    recall_parser.add_argument("--namespace", action="append", help="Restrict retrieval to one or more memory namespaces. Repeat or comma-separate values.")
    add_entity_scope_arguments(recall_parser)
    recall_parser.add_argument("--metadata", action="append", help="Restrict retrieval with metadata filters such as key=value, key!=value, key~=text, or score>=8.")
    recall_parser.add_argument("--filter-json", action="append", help="Restrict retrieval with a JSON boolean filter over kind, tag, namespace, entity scope, metadata, and item fields.")
    recall_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    recall_parser.add_argument("--as-of", help="Read memory as of an ISO-8601 timestamp, excluding records updated after that time.")
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

    audit_parser = subparsers.add_parser("audit", parents=[common], help="Audit memory quality, lineage, duplicate, and governance issues.")
    audit_parser.add_argument("--limit", type=int, default=100, help="Maximum recent semantic memories to audit.")
    audit_parser.add_argument("--kind", action="append", help="Restrict audit to one or more memory kinds. Repeat or comma-separate values.")
    audit_parser.add_argument("--memory-type", action="append", help="Restrict audit to semantic, episodic, procedural, or observation memory. Repeat or comma-separate values.")
    audit_parser.add_argument("--tag", action="append", help="Restrict audit to memories containing all requested tags. Repeat or comma-separate values.")
    audit_parser.add_argument("--namespace", action="append", help="Restrict audit to one or more memory namespaces. Repeat or comma-separate values.")
    add_entity_scope_arguments(audit_parser)
    audit_parser.add_argument("--metadata", action="append", help="Restrict audit with metadata filters such as key=value, key!=value, key~=text, or score>=8.")
    audit_parser.add_argument("--filter-json", action="append", help="Restrict audit with a JSON boolean filter over kind, tag, namespace, entity scope, metadata, and item fields.")
    audit_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output structured JSON or an agent-readable repair plan.",
    )
    audit_parser.add_argument(
        "--min-severity",
        choices=("low", "medium", "high"),
        default="low",
        help="Minimum issue severity to include in text output.",
    )
    audit_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; audit reads the current graph by default.")
    audit_parser.set_defaults(func=handlers.audit)

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

    for restore_command in ("restore", "import"):
        restore_parser = subparsers.add_parser(restore_command, parents=[common], help="Restore or import a JSON memory export.")
        restore_parser.add_argument("input", help="Path to an Autopsy memory export or backup JSON file.")
        mode_group = restore_parser.add_mutually_exclusive_group()
        mode_group.add_argument("--merge", dest="replace", action="store_false", help="Merge export items into the current graph. This is the default.")
        mode_group.add_argument("--replace", action="store_true", help="Delete restored keys before importing them. Requires --yes.")
        restore_parser.set_defaults(replace=False)
        restore_parser.add_argument("--dry-run", action="store_true", help="Validate and report the restore plan without writing to Falkor.")
        restore_parser.add_argument("--offline", action="store_true", help="With --dry-run, validate the backup file without opening the memory runtime.")
        restore_parser.add_argument("--yes", action="store_true", help="Confirm destructive replace mode.")
        restore_parser.add_argument("--include-operational", action="store_true", help="Restore workspace/repository/thread/worktree/branch nodes.")
        restore_parser.set_defaults(func=handlers.restore)

    compare_backups_parser = subparsers.add_parser(
        "compare-backups",
        aliases=["compare-exports"],
        parents=[common],
        help="Compare two Autopsy backup/export/salvage JSON files without opening FalkorDB.",
    )
    compare_backups_parser.add_argument("base", help="Base Autopsy JSON backup/export/salvage file.")
    compare_backups_parser.add_argument("candidate", help="Candidate Autopsy JSON backup/export/salvage file to compare against the base.")
    compare_backups_parser.add_argument("--include-operational", action="store_true", help="Include workspace/repository/thread/worktree/branch nodes in the comparison.")
    compare_backups_parser.add_argument("--sample-limit", type=int, default=20, help="Maximum keys or relation signatures to include in each difference sample.")
    compare_backups_parser.set_defaults(func=handlers.compare_backups)

    health_parser = subparsers.add_parser("health", parents=[common], help="Run a product health summary for the local memory layer.")
    health_parser.set_defaults(func=handlers.health)

    diagnostics_parser = subparsers.add_parser("diagnostics", parents=[common], help="Show sanitized local diagnostic log summaries and recent events.")
    diagnostics_parser.add_argument("--log", choices=["all", "memory-guard", "memory-relations"], default="all", help="Diagnostic log to inspect.")
    diagnostics_parser.add_argument("--limit", type=int, default=10, help="Maximum recent sanitized events per selected log.")
    diagnostics_parser.set_defaults(func=handlers.diagnostics)

    repair_embedded_parser = subparsers.add_parser("repair-embedded-snapshot", parents=[common], help="Plan or repair an embedded FalkorDBLite snapshot rollback by quarantining stale files.")
    repair_embedded_parser.add_argument("--dry-run", action="store_true", help="Report the repair plan without moving files. This is the default unless --yes and --accept-data-loss are both supplied.")
    repair_embedded_parser.add_argument("--yes", action="store_true", help="Confirm moving stale embedded database files into a repair bundle.")
    repair_embedded_parser.add_argument("--accept-data-loss", action="store_true", help="Acknowledge that quarantining a stale snapshot may lose writes newer than the selected backup.")
    repair_embedded_parser.add_argument("--restore-backup", help="Optional Autopsy JSON backup to restore after quarantining the stale embedded files.")
    repair_embedded_parser.add_argument("--restore-latest-backup", action="store_true", help="Restore the newest valid default Autopsy JSON backup after quarantining stale embedded files.")
    repair_embedded_parser.add_argument("--backup-limit", type=int, default=5, help="Number of recent default backups to validate and show in the repair plan.")
    repair_embedded_parser.add_argument("--salvage-output", help="Optional path for a read-only JSON export of the stale embedded snapshot before any quarantine.")
    repair_embedded_parser.add_argument("--salvage-limit", type=int, default=0, help="Maximum number of items to include in --salvage-output. Default exports all matching items.")
    repair_embedded_parser.add_argument("--skip-salvage", action="store_true", help="Skip the automatic stale-snapshot salvage export during confirmed repair.")
    repair_embedded_parser.add_argument("--include-operational", action="store_true", help="When --restore-backup is used, restore workspace/repository/thread/worktree/branch nodes too.")
    repair_embedded_parser.add_argument("--skip-cleanup-workers", action="store_true", help="Do not stop stale resident workers or excess RedisLite processes before moving files.")
    repair_embedded_parser.set_defaults(func=handlers.repair_embedded_snapshot)

    activity_parser = subparsers.add_parser("activity", parents=[common], help="Show recent memory activity for lightweight UI clients.")
    activity_parser.add_argument("--limit", type=int, default=8, help="Default number of writes and consult events to return.")
    activity_parser.add_argument("--writes-limit", type=int, help="Number of recent memory writes to return.")
    activity_parser.add_argument("--consults-limit", type=int, help="Number of recent consult events to return.")
    activity_parser.add_argument("--section-limit", type=int, default=3, help="Maximum current-state items per status section.")
    activity_parser.add_argument("--recent-days", type=int, default=status_window_days_default)
    activity_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; activity reads the current graph by default.")
    activity_parser.set_defaults(func=handlers.activity)

    shared_server_parser = subparsers.add_parser("shared-server", parents=[common], help="Configure and use the Autopsy shared memory server.")
    shared_server_parser.add_argument(
        "shared_server_action",
        nargs="?",
        choices=(
            "status",
            "configure",
            "health",
            "team-status",
            "users",
            "create-user",
            "disable-user",
            "enable-user",
            "tokens",
            "scoped-tokens",
            "create-token",
            "grants",
            "grant",
            "access-check",
            "audit",
            "audit-integrity",
            "invite",
            "revoke-token",
            "revoke-grant",
            "handoff-owner",
            "publish",
            "list",
            "memory-history",
            "archive",
            "restore",
            "restore-version",
            "relate",
            "context",
            "shared-relations",
            "unrelate",
            "link",
            "personal-links",
            "personal-context",
            "unlink",
        ),
        default="status",
        help="Configure, check, administer shared access, publish local memory, list shared memory, inspect shared history, or manage shared and personal relations.",
    )
    shared_server_parser.add_argument("stable_key", nargs="?", help="Primary id: stable key for publish/link/relate/memory-history, user id for disable-user/enable-user, token id for revoke-token, or relation id for unlink/unrelate.")
    shared_server_parser.add_argument("target_key", nargs="?", help="Target shared memory stable key for link or relate.")
    shared_server_parser.add_argument("--config", dest="shared_server_config", help="Path to the local shared-server config JSON.")
    shared_server_parser.add_argument("--base-url", help="Shared server base URL, for example https://autopsy-server.fly.dev.")
    shared_server_parser.add_argument("--graph-slug", help="Shared graph slug. Defaults to autopsy when configuring.")
    shared_server_parser.add_argument("--user-id", help="Server user id for config, token, user lifecycle, or grant operations.")
    shared_server_parser.add_argument("--from-user-id", help="Source owner user id for shared-server handoff-owner.")
    shared_server_parser.add_argument("--to-user-id", help="Target owner user id for shared-server handoff-owner.")
    shared_server_parser.add_argument("--email", help="Email for shared-server create-user or invite.")
    shared_server_parser.add_argument("--name", default="", help="Display name for shared-server create-user or invite.")
    shared_server_parser.add_argument("--label", default="default", help="Token label for shared-server create-token or invite.")
    shared_server_parser.add_argument("--expires-at", help="ISO-8601 expiration timestamp for shared-server create-token or invite.")
    shared_server_parser.add_argument("--role", choices=("reader", "writer", "owner"), help="Grant role for shared-server grant or invite.")
    shared_server_parser.add_argument("--source-role-after", choices=("reader", "writer", "none"), default="writer", help="Role to leave the source owner with after shared-server handoff-owner.")
    shared_server_parser.add_argument("--mode", choices=("read", "write", "admin"), default="read", help="Access mode for shared-server access-check.")
    shared_server_parser.add_argument("--repo-scope", help="Exact shared-server repo scope. Overrides --repo path resolution for shared-server operations.")
    shared_server_parser.add_argument("--token", help="Bearer token for shared memory server access. Stored in a 0600 local config file.")
    shared_server_parser.add_argument("--relation", help="Relation name for shared-server link.")
    shared_server_parser.add_argument("--fact", default="", help="Optional relation fact text for shared-server link or relate.")
    shared_server_parser.add_argument("--fact-rating", type=float, help="Optional 0.0-1.0 quality rating for shared-server relate or link.")
    shared_server_parser.add_argument("--personal-key", help="Personal stable-key filter for shared-server personal-links or personal-context, or personal key for link.")
    shared_server_parser.add_argument("--shared-key", help="Shared stable-key filter for shared-server personal-links, or shared key for link.")
    shared_server_parser.add_argument("--source-key", help="Source stable-key filter for shared-server shared-relations, or source key for relate.")
    shared_server_parser.add_argument("--target-shared-key", help="Target stable-key filter for shared-server shared-relations, or target key for relate.")
    shared_server_parser.add_argument("--reason", default="", help="Reason for shared-server archive or restore lifecycle actions.")
    shared_server_parser.add_argument("--version-id", help="Shared memory version id for shared-server restore-version.")
    shared_server_parser.add_argument("--version-ns", type=int, help="Shared memory version_ns for shared-server restore-version.")
    shared_server_parser.add_argument("--query", default="", help="Query text for shared-server context retrieval.")
    shared_server_parser.add_argument("--limit", type=int, default=50, help="Maximum shared records to list or retrieve.")
    shared_server_parser.add_argument("--action", action="append", help="With shared-server audit or audit-integrity, restrict to one or more audit event actions. Repeat or comma-separate values.")
    shared_server_parser.add_argument("--global-audit", action="store_true", help="With shared-server audit or audit-integrity, read the global audit stream instead of one shared graph/repo window.")
    shared_server_parser.add_argument("--expected-version-ns", type=int, help="With shared-server publish or restore-version, reject the write unless the current shared memory version_ns matches this value.")
    shared_server_parser.add_argument("--include-archived", action="store_true", help="With shared-server list, context, or personal-context, include archived shared memories.")
    shared_server_parser.add_argument("--no-relations", action="store_true", help="With shared-server context or personal-context, omit adjacent shared graph relations.")
    shared_server_parser.add_argument("--min-fact-rating", type=float, help="With shared-server context or personal-context, omit adjacent shared relations below this 0.0-1.0 evidence rating.")
    shared_server_parser.add_argument(
        "--from-owner-config",
        nargs="?",
        const="",
        help="Configure from the local autopsy-server owner config. Defaults to ~/.config/autopsy-server/owner.json.",
    )
    shared_server_parser.add_argument("--check", action="store_true", help="With status, also call remote /health and /v1/me.")
    shared_server_parser.set_defaults(func=handlers.shared_server)

    menubar_parser = subparsers.add_parser("menubar", help="Run the native macOS Autopsy menu bar app.")
    menubar_parser.add_argument("--dir", dest="menubar_dir", help="Path to the Swift menu bar app package.")
    menubar_parser.add_argument("--build", action="store_true", help="Build the Swift menu bar app without running it.")
    menubar_parser.add_argument("--rebuild", action="store_true", help="Force rebuilding the Swift menu bar app before launching or staging it.")
    menubar_parser.add_argument("--release", action="store_true", help="Use a release SwiftPM build.")
    menubar_parser.add_argument("--print-path", action="store_true", help="Print resolved menu bar app paths as JSON.")
    menubar_parser.add_argument("--install-launch-agent", action="store_true", help="Install and start a user LaunchAgent so the menu bar app opens at login.")
    menubar_parser.add_argument("--uninstall-launch-agent", action="store_true", help="Remove the Autopsy menu bar LaunchAgent.")
    menubar_parser.add_argument("--launch-agent-status", action="store_true", help="Print LaunchAgent installation and loaded status as JSON.")
    menubar_parser.add_argument("--keep-worker-alive", action="store_true", help=argparse.SUPPRESS)
    menubar_parser.set_defaults(func=handlers.menubar)

    model_warmup_parser = subparsers.add_parser("model-warmup", help="Download and warm the local Autopsy ML models.")
    model_warmup_parser.add_argument("--root", help="Memory root whose embedding configuration should be used. Defaults to the unified memory root.")
    model_warmup_parser.set_defaults(func=handlers.model_warmup)

    create_parser = subparsers.add_parser("create", parents=[common], help="Create a typed Falkor memory note.")
    add_note_write_arguments(create_parser, include_kind=True)
    create_parser.set_defaults(func=handlers.create_note)

    capture_parser = subparsers.add_parser("capture", parents=[common], help="Create a general Falkor memory note.")
    add_note_write_arguments(capture_parser, include_kind=True)
    capture_parser.set_defaults(func=handlers.create_note)

    capture_outcome_parser = subparsers.add_parser("capture-outcome", parents=[common], help="Capture a durable outcome in Falkor memory.")
    add_note_write_arguments(capture_outcome_parser, include_outcome=True)
    capture_outcome_parser.set_defaults(func=handlers.create_note)

    for note_command in ("decision", "attempt", "observation", "procedure", "question", "preference", "plan", "resolved-question", "reverted-attempt"):
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

    expire_parser = subparsers.add_parser("expire", parents=[common], help="Soft-expire a memory item so current reads omit it while history remains inspectable.")
    expire_parser.add_argument("stable_key")
    expire_parser.add_argument("--expires-at", help="ISO-8601 expiration timestamp. Defaults to now.")
    expire_parser.add_argument("--reason", default="", help="Short reason for the lifecycle change.")
    expire_parser.add_argument("--clear", action="store_true", help="Clear an existing expiration and restore the item to current reads.")
    expire_parser.set_defaults(func=handlers.expire_item)

    pin_parser = subparsers.add_parser("pin", parents=[common], help="Pin a memory into the core context pack so it is visible without retrieval.")
    pin_parser.add_argument("stable_key")
    pin_parser.add_argument("--label", default="", help="Optional short core-memory label or memory-block label.")
    pin_parser.add_argument("--reason", default="", help="Short reason for pinning this memory.")
    pin_parser.add_argument("--description", default="", help="Memory-block description that tells agents how this core memory should be used.")
    pin_parser.add_argument("--limit", type=int, dest="block_limit", help="Maximum characters from this block value to expose in context.")
    pin_parser.add_argument(
        "--read-only",
        dest="read_only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Mark the memory block read-only for ordinary update operations. Use --no-read-only to clear.",
    )
    pin_parser.add_argument(
        "--shared",
        dest="shared",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Mark the memory block as shared across agents or scopes. Use --no-shared to clear.",
    )
    pin_parser.add_argument("--clear", action="store_true", help="Unpin the memory from core context packs.")
    pin_parser.set_defaults(func=handlers.pin_item)

    feedback_parser = subparsers.add_parser("feedback", parents=[common], help="Record useful/not-useful feedback for a memory item.")
    feedback_parser.add_argument("stable_key")
    feedback_parser.add_argument("--rating", choices=("useful", "not-useful", "neutral"), required=True)
    feedback_parser.add_argument("--note", default="", help="Optional short note explaining the feedback.")
    feedback_parser.add_argument("--source", default="cli", help="Feedback source label.")
    feedback_parser.set_defaults(func=handlers.feedback)

    import_session_parser = subparsers.add_parser("import-session", parents=[common], help="Import an agent JSONL transcript as episodic timeline memory.")
    import_session_parser.add_argument("path", help="Path to a JSONL transcript file.")
    import_session_parser.add_argument("--title", default="", help="Optional title for the imported session timeline.")
    import_session_parser.add_argument("--source", default="agent-jsonl", help="Source label such as claude-jsonl, codex-jsonl, or cursor-jsonl.")
    import_session_parser.add_argument("--max-events", type=int, default=200, help="Maximum parsed events to import.")
    import_session_parser.add_argument("--dry-run", action="store_true", help="Validate and summarize without writing to Falkor.")
    import_session_parser.set_defaults(func=handlers.import_session)

    consolidate_session_parser = subparsers.add_parser("consolidate-session", parents=[common], help="Draft or write semantic memory from an imported session timeline.")
    consolidate_session_parser.add_argument("stable_key", help="Imported session stable key, for example session-import:<sha>.")
    consolidate_session_parser.add_argument("--title", default="", help="Optional title for the consolidated memory.")
    consolidate_session_parser.add_argument("--kind", choices=("memory_note", "attempt", "decision", "observation", "procedure", "plan", "summary"), default="memory_note")
    consolidate_session_parser.add_argument("--max-events", type=int, default=80, help="Maximum timeline events to include.")
    consolidate_session_parser.add_argument("--write", action="store_true", help="Write the consolidation memory instead of returning a draft only.")
    consolidate_session_parser.set_defaults(func=handlers.consolidate_session)

    observe_parser = subparsers.add_parser("observe", parents=[common], help="Draft or materialize a graph-derived observation from one seed memory.")
    observe_parser.add_argument("--stable-key", required=True, help="Seed memory stable key.")
    observe_parser.add_argument("--limit", type=int, default=5, help="Maximum related memories to use as evidence.")
    observe_parser.add_argument("--min-fact-rating", type=float, help="Only use relation facts rated at or above this 0.0-1.0 threshold.")
    observe_parser.add_argument("--title", default="", help="Optional title override for the derived observation.")
    observe_parser.add_argument("--write", action="store_true", help="Materialize or update the observation memory; default is draft-only.")
    observe_parser.add_argument("--write-if-stale", action="store_true", help="Materialize only when the existing observation is missing or its evidence fingerprint differs from current graph evidence.")
    observe_parser.set_defaults(func=handlers.observe)

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
    neighbors_parser.add_argument("--min-fact-rating", type=float, help="Only include semantic neighbors connected by relation facts rated at or above this 0.0-1.0 threshold.")
    neighbors_parser.add_argument("--all-kinds", action="store_true")
    neighbors_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    neighbors_parser.set_defaults(func=handlers.neighbors)

    timeline_parser = subparsers.add_parser("timeline", parents=[common], help="Fetch a relation timeline from Falkor memory.")
    timeline_parser.add_argument("stable_key")
    timeline_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    timeline_parser.set_defaults(func=handlers.timeline)

    history_parser = subparsers.add_parser("history", parents=[common], help="Fetch recorded old/new change history for one memory item.")
    history_parser.add_argument("stable_key")
    history_parser.add_argument("--limit", type=int, default=50)
    history_parser.add_argument("--current-only", action="store_true", help="Accepted for compatibility; Falkor reads the current graph by default.")
    history_parser.set_defaults(func=handlers.history)

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
