# Autopsy Observatory

Autopsy Observatory is the visual companion app for the local-first Autopsy memory layer.

The app is intentionally not the memory authority. The installed `autopsy` CLI and Falkor graph remain canonical. Observatory calls CLI read commands through a Tauri v2 Rust backend, then renders read-only health, recall, timeline, and neighborhood views.

## Stack

- Tauri v2 desktop shell and Rust command backend.
- Svelte frontend with Bits UI primitives.
- Sigma.js and Graphology for focused graph-neighborhood rendering.
- Tauri tray/menu bar integration for quick health, backup, open, and quit actions.

## Local Development

Requirements:

- The standalone `autopsy` CLI is installed and available on `PATH`.
- FalkorDBLite is healthy enough for `autopsy health` and read commands.
- Node.js/npm and a Rust toolchain are installed.

```bash
cd apps/observatory
npm install --cache .npm-cache
npm run tauri:dev
```

Run checks:

```bash
./scripts/observatory-check.sh
```

## Product Boundaries

- Read-only by default.
- No direct writes to Falkor from the UI.
- No duplicate observability database.
- No raw memory content is persisted by Observatory.
- Rust serializes CLI calls to avoid embedded FalkorDBLite startup races.
- Falkor/CLI failures are surfaced to the UI instead of falling back to alternate storage.

## Current Views

- Overview: graph counts, health, backup freshness, active memories, recent activity.
- Recall Explain: query results, workflow status, and retrieval timings.
- Memory Map: Sigma.js local neighborhood around one selected memory.
- Timeline: relation lineage for the selected memory.

## Tray

The tray/menu bar component exposes:

- Open Observatory.
- Run Health.
- Run Backup.
- Quit.
