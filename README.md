# Autopsy Memory

Autopsy is local memory for coding agents.

It gives tools like Codex, Claude Code, Gemini CLI, OpenCode, Cursor, GitHub
Copilot, and Windsurf a durable place to remember decisions, fixes, preferences,
procedures, and open questions across sessions and repos. It runs on your Mac,
stores memory locally in a Falkor graph, and includes a quiet menu bar companion
that shows recent writes, recent consults, agent instruction status, and update
actions.

Autopsy is meant to feel like a background utility: always available, mostly
silent, and only visible when something needs judgment.

## Why Use It

Autopsy is for people who already try to give agents memory through markdown
files, copied summaries, project notes, or hosted memory tools and want something
more precise.

Markdown memory is useful for stable instructions, but it is a weak fit for
operational memory. A file can say "use this release process," but it cannot
easily answer which attempt superseded an older one, which decision a fix
implemented, whether a remembered fact expired, or what neighboring work should
be inspected before trusting a recall. As notes grow, agents either miss the
right paragraph or over-read stale context.

Hosted memory systems and API-backed vector stores solve some retrieval
problems, but they usually add another account, another set of API keys, another
sync boundary, and another place where durable repo context can leave your
machine. Autopsy is local-first: the graph, activity snapshots, settings, and
model cache live under `~/Library/Application Support/Autopsy`, and the default
retrieval stack runs without external API keys.

Compared with common agent-memory approaches:

| Approach | Good For | Where Autopsy Is Stronger |
| --- | --- | --- |
| Markdown files / `AGENTS.md` | Stable rules, repo setup notes, human-editable instructions. | Typed memories, explicit relations, temporal history, and targeted recall without forcing agents to reread a growing note file. |
| Copied summaries | Short handoff between two sessions. | Durable writes with provenance, update history, expiration, and later inspection commands. |
| Plain vector memory | Finding semantically similar snippets. | Combining semantic recall with graph neighbors, lineage, relation evidence, and stale/superseded filtering. |
| Hosted memory services | Cross-device sync and managed infrastructure. | Local-first storage, no required API keys, no external memory account, and repo context stays on your machine by default. |

Autopsy's main difference is that memory is a graph, not just text chunks:

- Memories are typed: `decision`, `attempt`, `observation`, `procedure`,
  `preference`, `plan`, `question`, and more.
- Relations are explicit: `refines`, `answers`, `supersedes`, `depends-on`,
  `implements`, `constrains`, and `informed-by`.
- Recall can walk nearby context instead of returning isolated snippets.
- Temporal history records creates, updates, expiration, pinning, and deletion,
  so agents can ask what was true then versus what is current now.
- Stale or superseded facts can be filtered, inspected through timeline/history,
  or kept as evidence without being treated as current guidance.

That means Autopsy can answer agent-sized questions like:

- "What did we already try, and why did it fail?"
- "Which release checklist is current for this repo?"
- "What decision does this implementation refine?"
- "What changed since the last time this memory was written?"
- "Is this memory current, expired, superseded, or only weakly related?"

Autopsy is not a graph browser, note-taking app, or hosted memory service. It is
a local graph memory layer for coding agents: quiet by default, technical enough
to preserve lineage, and private enough to use for real project context.

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
