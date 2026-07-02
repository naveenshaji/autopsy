# Autopsy Menu Bar

Autopsy Menu Bar is the native macOS companion for the local-first Autopsy memory layer.

The app is intentionally not a memory browser. The installed `autopsy` CLI and Falkor graph remain canonical. The CLI and worker write a small local activity snapshot, and the menu bar app watches that file so it stays instant and quiet.

## Stack

- SwiftPM executable target at `apps/menubar`.
- SwiftUI `MenuBarExtra` with accessory activation.
- `autopsy menubar` stages a minimal `.app` bundle before launch so the menu bar utility has a stable bundle identity.
- Local activity snapshot for recent writes, recent consults, and attention items.
- Global agent instruction status from `autopsy init --check --global --agent all`.
- Setup health is checked internally and used by onboarding/repair actions without showing a diagnostic setup row to end users.
- Login startup is managed through `autopsy install` or the lower-level `autopsy menubar --install-launch-agent`.
- The installed LaunchAgent supervises the app process directly, so the menu bar item stays visible and restarts if the app exits.
- The running menu bar app silently keeps the resident Autopsy worker warm for local memory operations.

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

Normal `autopsy menubar` stages the app bundle without forcing a rebuild when the bundle is current, then installs and kickstarts the user LaunchAgent when a GUI launchd session is available. Homebrew-style installs default to the release app bundle, and the global installer prestages that bundle on macOS so first launch does not need a debug build. The app caches the last successful activity payload locally and watches `~/Library/Application Support/Autopsy/Activity/activity.json`, so the popover can show recent writes, recent consults, and attention items immediately after restart without polling the CLI for activity. The popover is a compact fixed-height menu stack: Writes and Consults are tabs sharing one large scroll area, hover detail flyouts persist while moving between adjacent activity rows or into the full-height detail pane, global agent instruction status sits below activity, and action rows remain fixed at the bottom. Setup diagnostics stay out of the main menu surface. The menu bar icon does not switch shape during refresh. The app also runs a silent worker keepalive through the installed CLI, which keeps memory worker routes available while the LaunchAgent is active. `autopsy install` writes a user LaunchAgent at `~/Library/LaunchAgents/com.naveenshaji.autopsy.menubar.plist` so the utility opens at login. Homebrew-style installs write that LaunchAgent through the stable `<prefix>/opt/autopsy-memory/menubar` path when available, so login startup follows package updates instead of pinning to one Cellar version. The LaunchAgent runs the app executable directly with `KeepAlive`, rather than launching once through `open`, so launchd can keep the status item present. Quit unloads the LaunchAgent first so the utility actually exits.

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
- Setup diagnostics stay internal unless the onboarding flow needs an explicit install action.

## Current Surface

- Tabbed recent memory writes and consult telemetry.
- Full-height hover details for memory writes and consults that stay open during adjacent-row/detail-pane movement and close after leaving that area.
- Show More controls for long memory text in the flyout.
- Codex, Claude Code, Gemini CLI, OpenCode, Cursor, GitHub Copilot, and Windsurf instruction status with install actions.
- First-run setup prompt when no memory or agent instructions exist.
- Homebrew update check/update action.
- Shared memory Settings controls for server health, graph-owner invites,
  repo grants, invite-token hygiene counts, expiring invite/token issuance,
  invite-token inventory copy, token cleanup, audit copy, shared memory archive/restore, and
  shared memory history copy/version restore, shared context copy with optional
  relation evidence threshold, shared
  relation create/list/unlink with evidence rating, and private
  personal-to-shared link create/list/unlink with link evidence rating and linked-context evidence
  threshold. Audit copies
  include privacy-preserving context-read events with hashed queries and counts
  when the server records them.
- Attention items when available.
- Quit action.
