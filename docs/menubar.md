# Autopsy Menu Bar

Autopsy Menu Bar is the native macOS companion for the local-first Autopsy memory layer.

The app is intentionally not a memory browser. The installed `autopsy` CLI and Falkor graph remain canonical. The menu bar app polls the CLI for a small activity feed, then stays quiet unless memory needs attention.

## Stack

- SwiftPM executable target at `apps/menubar`.
- SwiftUI `MenuBarExtra` with accessory activation.
- `autopsy menubar` stages a minimal `.app` bundle before launch so macOS services such as notifications have a bundle identity.
- `autopsy activity` for recent writes, recent consults, status, and attention items.
- Manual `autopsy health` and `autopsy backup` controls.
- Login startup is managed through the popover's **Open at Login** row or the `autopsy menubar --install-launch-agent` command.

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

Normal `autopsy menubar` launches the staged app bundle without forcing a rebuild when the bundle is current. Homebrew-style installs default to the release app bundle, and the global installer prestages that bundle on macOS so first launch does not need a debug build. The app caches the last successful activity payload and LaunchAgent status locally, so the popover can show recent writes, recent consults, attention, and startup state immediately after restart while a refresh runs in the background. The popover is a compact menu stack rather than a sectioned app-style list: short status rows, clipped recent activity, divider-separated action rows, and plain hover buttons. `--install-launch-agent` writes a user LaunchAgent at `~/Library/LaunchAgents/com.naveenshaji.autopsy.menubar.plist` so the utility opens at login. Homebrew-style installs write that LaunchAgent through the stable `<prefix>/opt/autopsy-memory/menubar` path when available, so login startup follows package updates instead of pinning to one Cellar version. The same startup state is visible and editable from the popover's **Open at Login** row.

For low-level SwiftPM debugging, run directly from the repo:

```bash
cd apps/menubar
swift run AutopsyMenuBar
```

Direct `swift run` launches an unbundled executable, so notification APIs are disabled in that mode.

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
- Optional login startup through the user LaunchAgent.
