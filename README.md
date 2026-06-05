# Autopsy Memory

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![macOS](https://img.shields.io/badge/platform-macOS-black.svg)
![Homebrew](https://img.shields.io/badge/install-Homebrew-fbb040.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-3776ab.svg)
![Status](https://img.shields.io/badge/status-Alpha-orange.svg)

Local graph memory for coding agents.

Autopsy gives Codex, Claude Code, Gemini CLI, OpenCode, Cursor, GitHub Copilot,
and Windsurf a shared memory layer that survives across sessions and repos.

It is built for agent work with history:

- what was decided,
- what failed,
- what superseded what,
- which procedure is current,
- what context should be recalled before touching this repo again.

Everything runs locally by default: graph storage, activity snapshots, settings,
embeddings, reranking, and the menu bar companion. No hosted memory account. No
required API keys.

The macOS menu bar app stays quiet. It shows recent writes, recent consults,
agent instruction status, and updates.

## Quickstart

Requirements:

- macOS 14 Sonoma or newer on Apple Silicon.
- Homebrew.

Install:

```bash
brew tap naveenshaji/autopsy
brew install autopsy-memory
autopsy install
```

`autopsy install` is the normal setup command. It:

- verifies the `autopsy` command on your PATH,
- installs global agent instructions,
- starts the macOS menu bar app,
- warms up the local retrieval models.

Check that everything is ready:

```bash
autopsy version --json
autopsy doctor
autopsy status --current-only
```

Run a deeper confidence check when setting up a new machine:

```bash
autopsy install --smoke-test
```

That runs doctor, a current-state read, an abstention consult, and a temporary
write/delete check.

After setup, use your coding agent normally. The installed agent instructions
tell supported agents when to consult Autopsy before substantial work and when
to write durable outcomes after material work.

## Why Autopsy

Markdown files are good instructions. They are bad operational memory.

Autopsy stores memory as typed graph records instead of a growing note file.
That gives agents:

- **Lineage:** what refined, implemented, superseded, or depended on what.
- **Temporal recall:** what was true then versus what is current now.
- **Local semantic retrieval:** embeddings and reranking without external APIs.
- **Bounded context:** compact answers with evidence instead of whole-file dumps.
- **Inspectability:** exact reads through `item`, `timeline`, `history`, and
  `neighbors`.

Use it when you want agents to stop rediscovering the same repo facts and start
carrying forward the state of the work.

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
memory writes, recent consults, agent instruction setup, and update checks. It
does not own storage and it does not browse the graph.

**Local-first operation**

Autopsy does not require hosted sync or API keys for its default retrieval
stack. The default data directory is:

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
- Autopsy includes the local ML runtime used for semantic retrieval and
  reranking. `autopsy install` starts a background model warmup so the
  sentence-transformer weights are cached before normal retrieval work.

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
  then open a new terminal and run `autopsy install`.
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

## License

Autopsy is licensed under the Apache License, Version 2.0. See
[LICENSE](LICENSE).

## For Contributors

Autopsy is alpha software. Please coordinate before spending significant time on
larger external code contributions.

Start here: [CONTRIBUTING.md](CONTRIBUTING.md).
