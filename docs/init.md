# Autopsy Init

`autopsy install` is the normal first-run setup command for end users.

`autopsy init` is the lower-level instruction installer used when you only want
to inspect, print, or write agent instruction blocks.

The default integration is persistent instructions plus the `autopsy` CLI. MCP is optional.

## Normal Setup

```bash
autopsy install
autopsy install --smoke-test
```

`install` writes global agent instructions, starts the macOS menu bar app when
available, runs runtime checks, and starts background model warmup.

## Instruction-Only Setup

```bash
autopsy init
```

When no target is specified, this installs managed Autopsy memory instruction blocks into:

- `~/.codex/AGENTS.md`
- `~/.claude/CLAUDE.md`
- `~/.gemini/GEMINI.md`
- `~/.config/opencode/AGENTS.md`
- `./AGENTS.md`
- `./CLAUDE.md`
- `./GEMINI.md`
- `./.github/copilot-instructions.md`
- `./.windsurf/rules/autopsy.md`

Repo `./AGENTS.md` is shared by AGENTS.md-aware harnesses such as Codex, OpenCode, and Cursor.

The command uses managed markers and only replaces content between those markers:

```text
<!-- AUTOPSY_MEMORY_START v1 -->
...
<!-- AUTOPSY_MEMORY_END -->
```

## Common Modes

```bash
autopsy init --check
autopsy init --dry-run
autopsy init --global --agent codex
autopsy init --repo . --agent claude
autopsy init --global --agent gemini
autopsy init --repo . --agent copilot
autopsy init --print
autopsy init --mcp
autopsy init --smoke-test
```

`autopsy init --smoke-test` runs the same instruction-era smoke checks without
installing the menu bar LaunchAgent.

## Policy

- CLI-first is the default integration path.
- MCP setup is not installed by default.
- Existing files are not overwritten wholesale.
- Managed blocks are idempotent.
- `--check` and `--dry-run` do not write files.
