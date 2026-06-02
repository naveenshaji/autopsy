# Changelog

## Unreleased

## 0.1.19 - 2026-06-02

Fixes the Homebrew menu bar activity reader and small-screen detail behavior.

- Packages the menu bar app with the stable Homebrew wrapper path instead of the raw virtualenv entrypoint, so activity fetches use the same runtime environment as terminal `autopsy` commands.
- Makes the Swift menu bar app normalize stale cached direct Cellar `libexec/bin/autopsy` paths to the stable Homebrew `opt` wrapper after upgrades.
- Adds a defensive Swift process environment fallback for direct Cellar paths by setting unified memory mode and inferring the native FalkorDB module path.
- Prevents hover detail flyouts from resizing the popover window on normal screens, avoiding left/right placement flicker.
- Uses an in-place detail panel on narrow screens instead of opening a side flyout where there is no room.

## 0.1.18 - 2026-06-02

Fixes the Homebrew test/default-path edge cases from v0.1.17.

- Moves embedded Redis log files out of `~/Library/Application Support/...` to a stable temp log directory so Redis config parsing is not broken by spaces in the default macOS path.
- Keeps runtime diagnostics pointing at the new Redis log location.
- Excludes the native FalkorDB `.so` resource from Homebrew's Python virtualenv installer while still staging it into `libexec/share/autopsy/falkordb.so`.

## 0.1.17 - 2026-06-02

Fixes the self-contained Homebrew runtime on Apple Silicon.

- Vendors the native Darwin arm64 FalkorDB module in the Homebrew formula and sets `AUTOPSY_FALKORDB_MODULE_PATH` in all installed Autopsy wrappers.
- Adds an embedded FalkorDB runtime probe to `autopsy doctor` so package installs fail fast before normal memory commands.
- Makes backend startup failures return structured JSON with Redis log tail diagnostics instead of raw Python tracebacks.
- Teaches `doctor` to recognize Homebrew env wrappers that exec the real `autopsy_memory.cli` entrypoint.
- Documents Homebrew as the preferred self-contained macOS install path while PyPI `falkordblite` lacks a native Darwin module.

## 0.1.16 - 2026-06-02

Removes a personal development path from shipped defaults.

- Changes the default unified memory root from `~/github/codex` to `~/Library/Application Support/Autopsy/MemoryRoot`.
- Updates the CLI, worker, and MCP bridge to agree on the neutral default.
- Keeps `AUTOPSY_UNIFIED_MEMORY_ROOT` as the explicit override for users who want a custom root.

## 0.1.15 - 2026-06-02

Simplifies first-run setup after Homebrew installs.

- Adds `autopsy install` to install global agent instructions and, on macOS, install/start the menu bar LaunchAgent.
- Keeps repo-local instruction installation opt-in through `autopsy install --repo`.
- Updates Homebrew caveats so users do not need to know the lower-level `menubar --install-launch-agent` command.

## 0.1.14 - 2026-06-02

Fixes the first public Homebrew install path for the native menu bar app.

- Disables SwiftPM's nested sandbox when the CLI builds the staged menu bar app bundle.
- Redirects SwiftPM cache, configuration, and security state into the package-local `.build` directory.
- Keeps `brew install autopsy-memory` from failing before Homebrew can link the `autopsy` command.

## 0.1.13 - 2026-06-02

Publishes the public Homebrew-ready menu bar utility.

- Adds Homebrew tap packaging with pinned Python resources and a source-built Swift menu bar app.
- Adds a formula regeneration script for public release tags.
- Adds Homebrew distribution documentation and release checklist coverage.
- Switches the menu bar activity area to Writes and Consults tabs with a single larger scroll list.
- Adds full-height hover detail flyouts with expandable memory text.
- Removes broken write notifications and noisy refresh indicators.
- Adds broader agent instruction status/install support and a Quit action.
- Keeps the installed menu bar app supervised through the stable Homebrew `opt` path.

## 0.1.12 - 2026-06-02

Finishes moving the native utility to a menu-bar-only surface.

- Removes the separate SwiftUI Settings scene and app command menu.
- Moves login startup control into the compact popover as an **Open at Login** menu toggle row.
- Keeps CLI recovery available through a conditional **Use Detected Command** row when the stored command differs from the bundled default.
- Removes app-window style settings and quit shortcuts from the menu bar utility.

## 0.1.11 - 2026-06-02

Moves the menu bar popover to a compact menu-stack structure.

- Replaces the app-like sectioned `List` popover with divider-separated menu rows modeled after `codex-account-switcher`.
- Uses plain row buttons with hover affordances for actions and toggles.
- Narrows the popover and limits visible recent activity to the most useful writes and consults.
- Keeps long row labels clipped with full text available through tooltips.

## 0.1.10 - 2026-06-01

Makes the menu bar app useful immediately after launch.

- Caches the last successful activity payload so the popover can show recent writes, consults, status, and attention before the first refresh completes.
- Caches LaunchAgent status so Settings and the startup row do not begin from an unknown state after restart.
- Keeps the last successful update time unchanged when a refresh fails, making stale data clearer.
- Allows write notifications after an initial empty activity feed instead of requiring a prior write to seed notification state.

## 0.1.9 - 2026-06-01

Keeps the menu bar login item stable across Homebrew-style updates.

- Writes the user LaunchAgent with the stable `<prefix>/opt/autopsy-memory/menubar` path when the app is installed from a Homebrew-style Cellar.
- Uses release builds by default for Homebrew-style menu bar launches and prestages the release app bundle during the global installer on macOS.
- Keeps explicit custom menu bar directories unchanged for source and development launches.

## 0.1.8 - 2026-06-01

Restores native action feedback in the menu bar status row.

- Shows successful utility actions, such as health, backup, and login-startup changes, in the status footnote.
- Clears stale action text when a new utility action starts so old success messages do not survive failures or new work.

## 0.1.7 - 2026-06-01

Adds standard macOS command affordances to the menu bar utility.

- Adds a native Commands menu for refresh, health, backup, settings, and quit.
- Adds standard keyboard shortcuts for refresh (`Command-R`), settings (`Command-,`), and quit (`Command-Q`) from the menu bar popover.
- Keeps health and backup as explicit controls without assigning nonstandard shortcuts.

## 0.1.6 - 2026-06-01

Moves the menu bar popover closer to default macOS patterns.

- Replaces custom capsule activity counters with a native sectioned `List`.
- Replaces custom material attention cards with plain list rows.
- Uses default macOS button, toggle, label, and section styling for the popover controls.
- Keeps the menu bar surface tightly scoped to status, recent writes, recent consults, attention, startup, notifications, health, backup, settings, and quit.

## 0.1.5 - 2026-06-01

Improves the native menu bar utility's everyday install and startup behavior.

- Skips unnecessary Swift rebuilds when the staged menu bar app bundle is current.
- Opens the menu bar app without forcing duplicate instances.
- Adds `autopsy menubar --rebuild` and LaunchAgent install/status/uninstall commands.
- Adds an in-app **Open Autopsy at Login** setting backed by the LaunchAgent.
- Adds CLI timeouts so slow memory reads show an error instead of spinning indefinitely.
- Shows compact write/consult/attention counts and login-startup status in the popover.

## 0.1.4 - 2026-06-01

Fixes native menu bar launch stability.

- Stages `AutopsyMenuBar.app` before launching so macOS services see a real bundle identity.
- Prevents unbundled SwiftPM debug launches from touching UserNotifications APIs.
- Adds the staged app bundle path to `autopsy menubar --print-path`.

## 0.1.3 - 2026-06-01

Replaces Observatory with a native menu bar companion.

- Removes the Tauri/Svelte Observatory graph browser product surface.
- Adds a native Swift macOS menu bar utility focused on recent writes, recent consults, health, backup, and quiet attention states.
- Adds `autopsy activity` as the lightweight JSON feed for UI clients.
- Adds `autopsy menubar` so the installed CLI can launch, build, or locate the menu bar app.

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
