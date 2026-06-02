# Autopsy Menu Bar

Autopsy Menu Bar is the native macOS companion for the local-first Autopsy memory layer.

The app is intentionally not a memory browser. The installed `autopsy` CLI and Falkor graph remain canonical. The menu bar app polls the CLI for a small activity feed, then stays quiet unless memory needs attention.

## Stack

- SwiftPM executable target at `apps/menubar`.
- SwiftUI `MenuBarExtra` with accessory activation.
- `autopsy menubar` stages a minimal `.app` bundle before launch so the menu bar utility has a stable bundle identity.
- `autopsy activity` for recent writes, recent consults, and attention items.
- Manual `autopsy health` and `autopsy backup` controls.
- Global agent instruction status from `autopsy init --check --global --agent all`.
- Login startup is managed through `autopsy install` or the lower-level `autopsy menubar --install-launch-agent`.
- The installed LaunchAgent supervises the app process directly, so the menu bar item stays visible and restarts if the app exits.

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
autopsy menubar --rebuild
autopsy menubar --release
autopsy menubar --install-launch-agent
autopsy menubar --launch-agent-status
autopsy menubar --uninstall-launch-agent
```

Normal `autopsy menubar` launches the staged app bundle without forcing a rebuild when the bundle is current. Homebrew-style installs default to the release app bundle, and the global installer prestages that bundle on macOS so first launch does not need a debug build. The app caches the last successful activity payload locally, so the popover can show recent writes, recent consults, and attention items immediately after restart while a refresh runs silently in the background. The popover is a compact fixed-height menu stack: Writes and Consults are tabs sharing one large scroll area, hover detail flyouts persist while moving between adjacent activity rows or into the full-height detail pane, global agent instruction status sits below activity, and action rows remain fixed at the bottom. The menu bar icon does not switch shape during refresh. `autopsy install` writes a user LaunchAgent at `~/Library/LaunchAgents/com.naveenshaji.autopsy.menubar.plist` so the utility opens at login. Homebrew-style installs write that LaunchAgent through the stable `<prefix>/opt/autopsy-memory/menubar` path when available, so login startup follows package updates instead of pinning to one Cellar version. The LaunchAgent runs the app executable directly with `KeepAlive`, rather than launching once through `open`, so launchd can keep the status item present. Restart terminates the process and lets launchd bring it back; Quit unloads the LaunchAgent first so the utility actually exits.

For low-level SwiftPM debugging, run directly from the repo:

```bash
cd apps/menubar
swift run AutopsyMenuBar
```

Direct `swift run` launches an unbundled executable and is intended only for low-level debugging.

Run checks:

```bash
./scripts/menubar-check.sh
```

## Product Boundaries

- Quiet by default.
- No graph browser.
- No direct Falkor writes from the app.
- No duplicate observability database.
- Health failures and unavailable CLI/Falkor state are surfaced inline.

## Current Surface

- Tabbed recent memory writes and consult telemetry.
- Full-height hover details for memory writes and consults that stay open during adjacent-row/detail-pane movement and close after leaving that area.
- Show More controls for long memory text in the flyout.
- Codex, Claude Code, Gemini CLI, and OpenCode global instruction status with install actions.
- First-run setup prompt when no memory or agent instructions exist.
- Attention items when available.
- Manual health, backup, restart, and quit actions.
