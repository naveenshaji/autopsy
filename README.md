# Autopsy Memory

Autopsy is a local-first memory layer for coding agents. It provides a Falkor-backed graph, a CLI, an MCP bridge, typed writes, relation inspection, and a benchmark gate so agents can remember decisions, attempts, preferences, plans, and unresolved questions across repos.

This repository is the standalone memory product extraction. It intentionally does not contain the legacy macOS Codex client.

## What It Does

- Stores durable memory in a local Falkor graph.
- Retrieves context through `consult`, with workflow completeness metadata.
- Writes typed outcomes with explicit relations such as `refines`, `answers`, `supersedes`, and `depends-on`.
- Inspects exact facts through `item`, `timeline`, `neighbors`, and `snapshot`.
- Runs a benchmark gate for recall, abstention, latency, writes, relations, scale readiness, and Falkor health.
- Reports product health with runtime, graph, index, backup, vector, and init-instruction status.
- Restores exported backups with dry-run validation, safe merge defaults, and explicit replace confirmation.
- Exposes the same semantics through an MCP bridge for coding agents.

## Install

For the local machine, install the standalone CLI into a Homebrew-style prefix:

```bash
cd /Users/naveenshaji/github/codex/projects/autopsy
./scripts/install-global.sh
autopsy version --json
autopsy doctor
autopsy init
```

By default this uses `/opt/homebrew` when it is writable, otherwise `~/.local`. The layout is:

```text
<prefix>/Cellar/autopsy-memory/<version>/
<prefix>/opt/autopsy-memory -> <prefix>/Cellar/autopsy-memory/<version>
<prefix>/bin/autopsy
```

Use a repo-local virtual environment for development:

```bash
cd /Users/naveenshaji/github/codex/projects/autopsy
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[ml,dev]"
```

If you only need lexical/Falkor operations and want to avoid model downloads:

```bash
python -m pip install -e .
```

## Quickstart

```bash
autopsy version
autopsy doctor
autopsy init --check
autopsy health
autopsy status
autopsy consult --query "release decisions for this repo"
autopsy capture-outcome --outcome decision --title "Use Falkor only" --content "Falkor is the authoritative memory backend."
autopsy backup
autopsy restore ~/Library/Application\ Support/Autopsy/Backups/<backup>.json --dry-run
autopsy benchmark --sample-size 5 --include-sync
```

Compatibility aliases are preserved:

```bash
autopsy memory status
autopsy memory consult --query "prior decisions"
```

## Common Commands

```bash
autopsy status --current-only
autopsy consult --current-only --query "<task/context query>"
autopsy item <stable-key>
autopsy timeline <stable-key>
autopsy neighbors --stable-key <stable-key>
autopsy snapshot <stable-key>
autopsy capture-outcome --outcome decision --title "..." --content "..."
autopsy export --output ~/Desktop/autopsy-memory-export.json
autopsy backup
autopsy restore ~/Desktop/autopsy-memory-export.json --dry-run
autopsy init --global --repo . --agent all
autopsy instructions
autopsy health
autopsy benchmark --sample-size 5 --include-sync
```

Repo-scoped reads and writes:

```bash
autopsy consult --scope repo --repo /path/to/repo --query "release pattern"
autopsy capture-outcome --outcome attempt --repository-root-path /path/to/repo --title "..." --content "..."
```

## Data Location

By default, Autopsy uses:

```text
~/Library/Application Support/Autopsy/FalkorDB/autopsy-memory.db
~/Library/Application Support/Autopsy/Config/memory-settings.json
```

Override with:

```bash
export AUTOPSY_APP_SUPPORT_DIR="$HOME/Library/Application Support/Autopsy"
export AUTOPSY_FALKORDB_LITE_PATH="$AUTOPSY_APP_SUPPORT_DIR/FalkorDB/autopsy-memory.db"
export AUTOPSY_UNIFIED_MEMORY=1
export AUTOPSY_UNIFIED_MEMORY_ROOT="$HOME/github/codex"
```

Autopsy has no alternate local persistence fallback. If Falkor cannot initialize, commands fail loudly.

## MCP

Run the MCP bridge with:

```bash
autopsy-memory-mcp
```

For Codex-style MCP configuration:

```toml
[mcp_servers.autopsy_falkor_memory]
command = "autopsy-memory-mcp"
env = { AUTOPSY_UNIFIED_MEMORY = "1" }
```

The bridge exposes product-level memory tools such as `autopsy_memory_status`, `autopsy_memory_consult`, `autopsy_memory_item`, `autopsy_memory_timeline`, `autopsy_memory_neighbors`, `autopsy_memory_search`, and write/update/delete tools.

## Agent Instructions

Copy [docs/agent-instructions.md](docs/agent-instructions.md) into an agent or repo `AGENTS.md`. A ready-to-use example lives at [examples/AGENTS.md](examples/AGENTS.md).

## Benchmark Gate

For memory-system changes:

```bash
autopsy benchmark --sample-size 5 --include-sync
```

Do not claim memory health unless the benchmark passes or failures are explicitly reported.

The current internal benchmark is a product gate, not a public leaderboard. Public-style benchmarking requires seeded corpora, hidden queries, relevance judgments, large-graph latency measurements, and cost reporting. See [docs/benchmarks.md](docs/benchmarks.md).

## Release Checks

Before publishing a release:

```bash
./scripts/release-check.sh
```

The release checklist lives at [docs/release-checklist.md](docs/release-checklist.md).

## Repository Split

This repo is intended to be published as `naveenshaji/autopsy`.

The previous Swift macOS Codex client should live separately as `autopsy-client-legacy`. The client may integrate with this memory layer through the CLI, worker, or MCP bridge, but it should not own the canonical memory implementation.
