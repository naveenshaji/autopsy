# Autopsy Memory

Autopsy is local memory for coding agents.

It gives tools like Codex, Claude Code, Gemini CLI, OpenCode, Cursor, GitHub
Copilot, and Windsurf a durable place to remember decisions, fixes, preferences,
procedures, and open questions across sessions and repos. It runs on your Mac,
stores memory locally in a Falkor graph, and includes a quiet menu bar companion
that shows recent writes, recent consults, setup state, and update/repair
actions.

Autopsy is meant to feel like a background utility: always available, mostly
silent, and only visible when something needs judgment.

## Why Use It

Agents are powerful, but they forget. Autopsy helps them carry forward the parts
of prior work that actually matter:

- "We already tried that and it failed because..."
- "This repo ships through this release checklist."
- "The default memory root must stay neutral, not tied to one personal folder."
- "The menu bar app should run from the Homebrew `opt` path."
- "This instruction was superseded by a later fix."

Autopsy is not a graph browser, note-taking app, or hosted memory service. It is
a local memory layer for people who build with coding agents and want continuity
without handing durable project context to another cloud product.

## Quickstart

Requirements:

- macOS on Apple Silicon.
- Homebrew.
- Python is installed by the Homebrew formula.

Install Autopsy:

```bash
brew tap naveenshaji/autopsy
brew install autopsy-memory
autopsy install
```

`autopsy install` is the normal setup command. It:

- verifies and repairs the `autopsy` command on your PATH when possible,
- installs global agent instructions,
- starts the macOS menu bar app through a supervised LaunchAgent,
- runs `autopsy doctor` so setup problems fail loudly.

Check that everything is ready:

```bash
autopsy version --json
autopsy doctor
autopsy status --current-only
```

After setup, use your coding agent normally. The installed agent instructions
tell supported agents when to consult Autopsy before substantial work and when
to write durable outcomes after material work.

## What You Get

**A durable local memory graph**

Autopsy stores typed memories such as decisions, attempts, observations,
procedures, plans, preferences, and open questions. Memories can be linked with
semantic relations like `refines`, `answers`, `supersedes`, `depends-on`, and
`implements`.

**Context that agents can use**

`autopsy context` builds a compact task context pack with current state,
relevant memories, evidence, graph neighbors, lineage warnings, and follow-up
inspection commands.

**Consults that are honest about confidence**

`autopsy consult` returns relevant memories plus workflow metadata. If the
signal is weak or stale, the result says so instead of pretending recall is
complete.

**A quiet menu bar utility**

The native macOS menu bar app watches a local activity snapshot. It shows recent
memory writes, recent consults, agent instruction setup, update checks, and
setup repair only when needed. It does not own storage and it does not browse
the graph.

**Local-first operation**

Autopsy does not require hosted sync. The default data directory is:

```text
~/Library/Application Support/Autopsy
```

## Everyday Commands

Ask what Autopsy currently knows:

```bash
autopsy status --current-only
autopsy consult --current-only --query "release process for this repo"
autopsy context --current-only --format text --query "what should I know before changing the menu bar app?"
```

Write a one-off memory manually:

```bash
autopsy capture-outcome \
  --outcome decision \
  --title "Use Homebrew opt path for menu bar startup" \
  --content "LaunchAgents should point at /opt/homebrew/opt/autopsy-memory so package updates do not pin startup to one Cellar version." \
  --no-relations-ok
```

Install repo-local instructions from inside a project:

```bash
cd /path/to/project
autopsy install --repo
```

Back up and restore memory:

```bash
autopsy backup
autopsy restore ~/Library/Application\ Support/Autopsy/Backups/<backup>.json --dry-run
```

Update Autopsy:

```bash
brew update
brew upgrade autopsy-memory
autopsy install
```

Stop the menu bar app:

```bash
autopsy menubar --uninstall-launch-agent
```

## Supported Agent Surfaces

Autopsy can install managed instruction blocks for:

- Codex
- Claude Code
- Gemini CLI
- OpenCode
- Cursor
- GitHub Copilot
- Windsurf

The instructions tell agents to use Autopsy for nontrivial repo work,
debugging, releases, architecture questions, prior decisions, and durable
outcomes. You can inspect the generated instructions with:

```bash
autopsy instructions
```

## Privacy And Security

Autopsy is local-first, but durable memory is still durable memory.

- Do not store secrets, API keys, private keys, bearer tokens, or credentials.
- Treat Autopsy as project context, not a password manager.
- If Falkor cannot initialize, Autopsy fails loudly instead of silently falling
  back to another persistence backend.
- If the optional `ml` extra is installed, sentence-transformer models may be
  downloaded by the model provider. The Homebrew install is self-contained for
  normal local operation.

More detail: [docs/privacy-security.md](docs/privacy-security.md).

## Troubleshooting

Start with:

```bash
autopsy doctor
autopsy install
autopsy menubar --launch-agent-status
```

Common fixes:

- If `autopsy` is not found, run `brew update && brew upgrade autopsy-memory`,
  then open a new terminal.
- If the menu bar app is missing, run `autopsy install`.
- If the menu bar app starts but shows no recent activity, run
  `autopsy activity` once and then reopen the menu.
- If memory reads fail, run `autopsy doctor` and inspect the FalkorDB runtime
  diagnostics.

More detail: [docs/troubleshooting.md](docs/troubleshooting.md).

## Documentation

- [CLI reference](docs/cli.md)
- [Menu bar app](docs/menubar.md)
- [Homebrew distribution](docs/homebrew.md)
- [Agent instructions](docs/agent-instructions.md)
- [MCP bridge](docs/mcp.md)
- [Architecture](docs/architecture.md)
- [Benchmarks](docs/benchmarks.md)
- [Release checklist](docs/release-checklist.md)

## For Contributors

Autopsy is alpha software and the repository is public, but it is not yet under
an open-source license. See [LICENSE.md](LICENSE.md) and coordinate before
spending significant time on external code contributions.

Start here: [CONTRIBUTING.md](CONTRIBUTING.md).
