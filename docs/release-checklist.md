# Release Checklist

Use this checklist before tagging or publishing Autopsy Memory.

## Required

- `python -m compileall -q src tests` passes.
- `python -m unittest discover -s tests` passes.
- `python -m pip install -e ".[dev]"` works in a fresh virtual environment.
- `python -m build --wheel` works in a fresh virtual environment.
- The release interpreter is Python 3.12 or newer.
- `./scripts/install-global.sh` installs the standalone CLI in the target environment.
- `which autopsy` points at the standalone memory CLI wrapper or package entrypoint.
- `autopsy version --json` prints package metadata.
- `autopsy doctor` passes in the target release environment.
- `autopsy health` passes in an isolated release-check graph.
- `autopsy init --check` reports target instruction state without writing.
- `autopsy instructions` prints copy-pasteable agent instructions.
- `autopsy export --limit 1` returns valid JSON.
- `autopsy restore <export.json> --dry-run` validates without writing.
- `autopsy benchmark --sample-size 5 --include-sync` passes before any health claim.
- `autopsy activity --limit 3` returns valid JSON for lightweight UI clients.
- `autopsy menubar --print-path` resolves the installed menu bar app source.
- `autopsy menubar --launch-agent-status` reports LaunchAgent state without writing.
- `./scripts/menubar-check.sh` passes when shipping the macOS menu bar app.

## Packaging

- Version in `pyproject.toml` matches `src/autopsy_memory/__init__.py`.
- README install commands work from a clean checkout.
- CLI entrypoints exist: `autopsy`, `autopsy-memory-worker`, and `autopsy-memory-mcp`.
- The license file is intentional for the release channel.

## Product Safety

- Falkor failure is loud.
- No alternate persistence backend is introduced.
- No secrets are checked in.
- Backup/export behavior is documented.
- Restore defaults to merge, supports dry-run, and requires explicit confirmation for replace.
- Public claims distinguish internal benchmark gates from public leaderboards.
- Menu Bar stays CLI/Falkor-backed and does not introduce a separate memory store or graph browser.

## Optional Public Release

- Select a real open-source license before making the repo public.
- Add GitHub release notes.
- Add signed artifacts or package provenance if distributing binaries.
- Add a public benchmark harness before making comparative claims.
