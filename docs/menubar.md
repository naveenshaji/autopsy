# Autopsy Menu Bar

Autopsy Menu Bar is the native macOS companion for the local-first Autopsy memory layer.

The app is intentionally not a memory browser. The installed `autopsy` CLI and Falkor graph remain canonical. The menu bar app polls the CLI for a small activity feed, then stays quiet unless memory needs attention.

## Stack

- SwiftPM executable target at `apps/menubar`.
- SwiftUI `MenuBarExtra` with accessory activation.
- `autopsy activity` for recent writes, recent consults, status, and attention items.
- Manual `autopsy health` and `autopsy backup` controls.

## Local Development

Requirements:

- macOS 13 or newer.
- Swift toolchain with SwiftPM.
- The standalone `autopsy` CLI is installed and available on `PATH`, or configured in app settings.
- FalkorDBLite is healthy enough for `autopsy activity`.

Run through the installed CLI:

```bash
autopsy menubar
```

Useful launcher modes:

```bash
autopsy menubar --print-path
autopsy menubar --build
autopsy menubar --release
```

Run directly from the repo:

```bash
cd apps/menubar
swift run AutopsyMenuBar
```

Run checks:

```bash
./scripts/menubar-check.sh
```

## Product Boundaries

- Quiet by default.
- No graph browser.
- No direct Falkor writes from the app.
- No duplicate observability database.
- Successful write notifications are opt-in.
- Health failures and unavailable CLI/Falkor state are surfaced inline.

## Current Surface

- Recent memory writes.
- Recent consult telemetry.
- Current workspace/status summary.
- Attention items when available.
- Manual refresh, health, backup, settings, and quit actions.
