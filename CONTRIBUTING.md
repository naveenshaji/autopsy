# Contributing To Autopsy

Thanks for taking the time to look at Autopsy.

This repository is public, but it is not yet under an open-source license. Until
`LICENSE.md` is replaced with an explicit open-source license, treat the code as
all-rights-reserved. Issues, bug reports, design feedback, and small coordinated
patches are welcome; please discuss larger code contributions before investing
significant time.

## Good First Contributions

- Report install or setup failures with `autopsy doctor` output.
- Improve end-user docs, troubleshooting notes, and examples.
- File menu bar UX issues with clear reproduction steps.
- Add focused CLI contract tests for behavior that should not regress.
- Tighten Homebrew packaging, release, or setup documentation.

## Project Shape

- `src/autopsy_memory`: Python CLI, worker, graph logic, MCP bridge.
- `apps/menubar`: native Swift menu bar app.
- `docs`: detailed user, operator, and release docs.
- `tests`: Python contract tests.
- `Formula`: Homebrew formula generated from public release tags.
- `scripts`: install, release, menu bar, and formula helper scripts.

## Local Setup

Use Python 3.12 or newer:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

For optional local embedding and reranker support:

```bash
python -m pip install -e ".[ml,dev]"
```

On macOS, the menu bar app requires SwiftPM:

```bash
cd apps/menubar
swift build
```

## Test Before Sending A Patch

For Python-only changes:

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -q
```

For menu bar changes:

```bash
cd apps/menubar
swift build
cd ../..
./scripts/menubar-check.sh
```

For packaging or release-adjacent changes:

```bash
./scripts/release-check.sh
brew style naveenshaji/autopsy/autopsy-memory
brew audit --formula --strict naveenshaji/autopsy/autopsy-memory
brew fetch --formula --deps naveenshaji/autopsy/autopsy-memory
```

For memory-system changes, also run:

```bash
autopsy health
autopsy benchmark --sample-size 5 --include-sync
```

Do not claim memory health unless the benchmark passes or you explicitly report
the failure.

## Development Guidelines

- Keep the root README end-user focused. Put detailed command references in
  `docs/`.
- Preserve local-first behavior. Autopsy should fail loudly when the graph
  runtime is unavailable.
- Avoid storing secrets in tests, docs, fixtures, or memory examples.
- Keep menu bar behavior quiet, fast, and scoped to useful activity/setup state.
- Prefer explicit semantic relations for durable memory writes in examples and
  tests when a relation applies.
- Add narrowly scoped tests for CLI behavior, packaging behavior, and regression
  fixes.

## Homebrew Formula Updates

The formula is generated after a public release tag exists:

```bash
/opt/homebrew/opt/python@3.12/libexec/bin/python scripts/update-homebrew-formula.py \
  --version <version> \
  --python /opt/homebrew/opt/python@3.12/libexec/bin/python
```

Then copy or generate the same formula into the public tap repository
`naveenshaji/homebrew-autopsy`, validate it, commit it, and push it.

## Reporting Issues

Include:

- macOS version and architecture.
- Install method and `autopsy version --json`.
- `autopsy doctor` output.
- The command that failed.
- For menu bar issues, `autopsy menubar --launch-agent-status` output.
- Any relevant log path shown by doctor or launchd diagnostics.

Do not include secrets, private keys, tokens, or sensitive project data in issue
reports.

