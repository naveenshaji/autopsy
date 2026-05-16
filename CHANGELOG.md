# Changelog

## 0.1.0 - 2026-05-16

Initial private release of the standalone Autopsy memory layer.

- Ships the `autopsy` CLI, `autopsy-memory-worker`, and `autopsy-memory-mcp`.
- Stores local-first memory in FalkorDBLite with no alternate persistence fallback.
- Supports status, consult, search, item, timeline, neighbors, snapshot, typed writes, explicit relations, export, backup, doctor, instructions, and benchmark commands.
- Adds a Homebrew-style global installer that places a versioned package under `<prefix>/Cellar/autopsy-memory/<version>` and installs `autopsy` into `<prefix>/bin`.
- Adds release checks, CI, CLI contract tests, and stale legacy-wrapper detection in `autopsy doctor`.
