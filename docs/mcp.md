# Autopsy Memory MCP Bridge

## Goal

Agents should use the same durable local memory graph through product-level memory semantics instead of raw Falkor queries.

The managed Codex MCP server is:
- `autopsy_falkor_memory`

Despite the compatibility name, this is not the raw official Falkor MCP server. It is a small stdio MCP bridge over the Autopsy memory worker. That worker owns the product-level memory semantics and talks to the same Falkor-backed graph as the CLI.

## Why This Shape

Raw Falkor access is useful for low-level graph debugging, but it is not the right default interface for agents.

Autopsy memory semantics include:
- `status`
- `consult`
- `item`
- `neighbors`
- `timeline`
- graph search
- typed note capture
- item update/delete
- worker health and recovery

Those are higher-level product operations. The bridge keeps Codex on those operations instead of forcing every memory task through raw Cypher.

## Runtime Flow

1. Codex starts the `autopsy_falkor_memory` MCP server.
2. The MCP bridge reads `~/Library/Application Support/Autopsy/CLI/ml-worker.json`.
3. If a healthy Autopsy memory worker is already running, the bridge reuses it.
4. If no worker is healthy, the bridge starts the packaged `autopsy_memory.worker`.
5. The worker uses the shared Falkor DB at `~/Library/Application Support/Autopsy/FalkorDB/autopsy-memory.db`.
6. CLI, MCP clients, and optional UI clients read/write through the same graph.

The bridge writes only protocol messages to stdout. Worker logs go to:

`~/Library/Application Support/Autopsy/CLI/mcp-worker.stderr.log`

## Shared Ownership

The standalone memory layer owns graph semantics.

Clients should use the bridge or CLI to:
- recall memory through `consult`
- write typed notes
- fetch items, timelines, and neighbors

Both clients use the same graph name and DB path by default:
- graph base name: `autopsy_memory`
- unified workspace root: `~/Library/Application Support/Autopsy/MemoryRoot`
- DB path: `~/Library/Application Support/Autopsy/FalkorDB/autopsy-memory.db`

## Recovery Behavior

The bridge checks worker health before each request. If the worker info file is stale, it starts a fresh worker.

If FalkorDB Lite leaves a dead Unix socket in `autopsy-memory.db.settings`, the bridge backs up the settings file with a `.stale-<timestamp>` suffix, restarts the worker, and retries once. It does not delete or rewrite the memory DB.

## Codex Configuration

Configure Codex with:

```toml
[mcp_servers.autopsy_falkor_memory]
command = "autopsy-memory-mcp"
```

Useful environment overrides:
- `AUTOPSY_MEMORY_BACKEND=falkordb`
- `AUTOPSY_FALKORDB_ENABLED=1`
- `AUTOPSY_FALKORDB_GRAPH_NAME=autopsy_memory`
- `AUTOPSY_FALKORDB_LITE_PATH=~/Library/Application Support/Autopsy/FalkorDB/autopsy-memory.db`
- `AUTOPSY_UNIFIED_MEMORY_ROOT=~/Library/Application Support/Autopsy/MemoryRoot`
- `AUTOPSY_MEMORY_TOOL=/path/to/autopsy_memory/cli.py`
- `AUTOPSY_WORKER_SCRIPT=/path/to/autopsy_memory/worker.py`

## Tool Surface

The bridge exposes these MCP tools:
- `autopsy_memory_status`
- `autopsy_memory_consult`
- `autopsy_memory_item`
- `autopsy_memory_timeline`
- `autopsy_memory_neighbors`
- `autopsy_memory_search`
- `autopsy_memory_create_note`
- `autopsy_memory_update_item`
- `autopsy_memory_delete_item`
- `autopsy_memory_worker_info`

## When To Use Raw Falkor MCP

Use raw Falkor tooling only for low-level graph implementation debugging:
- schema inspection
- index debugging
- Cypher query development
- investigating Falkor engine behavior

Do not use raw Falkor MCP as the default memory interface for agents. It bypasses Autopsy's workflow completeness, ranking, typed note APIs, and recovery behavior.

## Migration Rule

New Codex-facing memory capabilities should prefer:
1. the Autopsy memory MCP bridge for product memory semantics
2. Autopsy CLI or worker endpoints for local integrations
3. raw Falkor MCP only for low-level graph debugging
