# Changelog

## Unreleased

- Adds the Tauri v2 Autopsy Observatory app with a Rust CLI bridge, Svelte/Bits UI frontend, Sigma.js/Graphology neighborhood graph, and tray/menu bar health and backup actions.
- Keeps the installed `autopsy` CLI and Falkor graph as the canonical engine; Observatory performs read-only inspection and serializes CLI calls to avoid embedded Falkor startup races.

## 0.1.2 - 2026-05-16

Adds restore, health, and trust guardrails.

- Adds `autopsy restore` and `autopsy import` for schema-versioned backup restores with dry-run validation, safe merge defaults, operational-node opt-in, and explicit `--replace --yes` confirmation.
- Adds `autopsy health` for runtime, Falkor graph, index, vector, backup, and init-instruction status.
- Tightens `consult` workflow metadata so weak relationship/vector side channels no longer look like reliable partial answers.
- Adds write-quality warnings for short, low-signal, duplicate, or title-equals-content memory writes.
- Updates agent instructions, release checks, and docs for backup/restore and health.

## 0.1.1 - 2026-05-16

Adds CLI-first first-run setup.

- Adds `autopsy init` for managed persistent instruction installation.
- Supports Codex global `~/.codex/AGENTS.md`, Claude Code global `~/.claude/CLAUDE.md`, repo `AGENTS.md`, and repo `CLAUDE.md`.
- Adds `--check`, `--dry-run`, `--print`, `--mcp`, `--agent`, `--global`, `--repo`, and `--smoke-test` modes.
- Keeps MCP optional and positions persistent instructions plus CLI commands as the default agent integration.
- Adds init tests, release checks, and documentation.

## 0.1.0 - 2026-05-16

Initial private release of the standalone Autopsy memory layer.

- Ships the `autopsy` CLI, `autopsy-memory-worker`, and `autopsy-memory-mcp`.
- Stores local-first memory in FalkorDBLite with no alternate persistence fallback.
- Supports status, consult, search, item, timeline, neighbors, snapshot, typed writes, explicit relations, export, backup, doctor, instructions, and benchmark commands.
- Adds a Homebrew-style global installer that places a versioned package under `<prefix>/Cellar/autopsy-memory/<version>` and installs `autopsy` into `<prefix>/bin`.
- Adds release checks, CI, CLI contract tests, and stale legacy-wrapper detection in `autopsy doctor`.
