# Autopsy Init

`autopsy init` is the first-run setup command for coding agents.

The default integration is persistent instructions plus the `autopsy` CLI. MCP is optional.

## Default

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

## Policy

- CLI-first is the default integration path.
- MCP setup is not installed by default.
- Existing files are not overwritten wholesale.
- Managed blocks are idempotent.
- `--check` and `--dry-run` do not write files.
