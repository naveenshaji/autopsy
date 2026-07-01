# Troubleshooting

## Check Dependencies

```bash
autopsy doctor
autopsy version --json
autopsy health
```

Required modules:

- `falkordb`
- `redis`
- `redislite.falkordb_client`
- `sentence_transformers`

`doctor` also reports a non-required `model_warmup` check. If it shows
`failed` or `invalid`, run:

```bash
autopsy model-warmup
```

Then inspect the model warmup log path shown by `doctor`.

## Installed Command Is Wrong

If `autopsy doctor` reports that `autopsy` is missing, shadowed, or still the
legacy app wrapper, reinstall the Homebrew package and rerun setup:

```bash
brew update
brew reinstall autopsy-memory
autopsy install
which autopsy
autopsy version --json
```

On macOS prereleases, Homebrew may require explicit trust for third-party taps:

```bash
brew trust --formula naveenshaji/autopsy/autopsy-memory
brew reinstall --build-from-source naveenshaji/autopsy/autopsy-memory
```

If Homebrew itself cannot update, upgrade, or reinstall on that macOS release,
download a release tarball and run the bundled installer instead:

```bash
AUTOPSY_VERSION="${AUTOPSY_VERSION:-$(curl -fsSL https://api.github.com/repos/naveenshaji/autopsy/releases/latest | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)}"
tmpdir="$(mktemp -d)"
curl -fsSL "https://codeload.github.com/naveenshaji/autopsy/tar.gz/refs/tags/$AUTOPSY_VERSION" | tar -xz -C "$tmpdir"
"$tmpdir/autopsy-${AUTOPSY_VERSION#v}/scripts/install-global.sh"
```

`autopsy install` repairs Homebrew PATH linkage when it can do so safely. If
`doctor` reports a valid Homebrew command shadowed later on PATH, move
Homebrew's bin directory earlier in your shell PATH or remove the earlier
legacy wrapper.

After repair, run:

```bash
autopsy install --smoke-test
```

## Falkor Fails To Start

Check the configured DB path:

```bash
autopsy doctor
```

If using embedded FalkorDBLite, make sure the parent directory is writable and
inspect the Redis log path shown by `doctor`. Homebrew installs should show a
native module path in `AUTOPSY_FALKORDB_MODULE_PATH`; if not, reinstall:

```bash
brew reinstall autopsy-memory
autopsy doctor
```

Normal CLI commands detach from embedded FalkorDBLite instead of shutting down
the Redis process, so concurrent local reads can share the same runtime. Use
`autopsy doctor --cleanup-workers` when stale worker or RedisLite processes need
explicit cleanup.

If commands report `workflow.status: rollback_detected`, Autopsy found an
embedded FalkorDBLite snapshot older than the durable guard sidecar and refused
to read or write memory. Inspect the guard log first:

```bash
autopsy diagnostics --log memory-guard --limit 5
autopsy repair-embedded-snapshot --dry-run
```

`autopsy health` also treats backup freshness as a readiness check for non-empty
graphs. The newest default backup must be valid and within the 24-hour freshness
window; backups older than 7 days are reported as critical stale recovery risk.
When health reports `checks.backup_status` as `missing`, `invalid`, `stale`, or
`critical_stale`, create a fresh backup after runtime health is restored and
compare any stale-snapshot salvage before accepting data loss.
Successful semantic write commands and non-dry-run restores create a validated
post-write default backup automatically, even when a previous backup is still
fresh. New backups include the embedded guard graph generation when Autopsy can
inspect it, so rollback repair can prefer exact generation coverage over
timestamp-only freshness. Disable this only for deliberate testing with
`AUTOPSY_AUTO_BACKUP_AFTER_WRITE=0`.

The dry run lists recent validated `backup_candidates`. Inspect each candidate's
`recovery_risk`; `covers_guard_generation` is stronger evidence than timestamp
freshness, while `generation_gap` or timestamp-only stale results may omit memory
written after the backup. The `backup_candidates.recovery_summary.best_candidate`
field ranks valid backups by recovery evidence so an older guard-covered backup
can outrank a newer timestamp-only backup. To repair, quarantine the stale
embedded database files instead of lowering the guard:

```bash
autopsy repair-embedded-snapshot --salvage-output ~/Desktop/autopsy-stale-snapshot.json
```

The salvage export is read from the stale embedded snapshot and the loaded
snapshot is closed with NOSAVE. Confirmed repair creates this importable
salvage export automatically before quarantine; pass `--salvage-output` when
you want to choose the path during dry-run, or `--skip-salvage` only when you
intentionally do not want the extra recovery point.

When a backup and salvage export both exist, compare them before choosing a
restore path:

```bash
autopsy compare-backups <backup.json> ~/Desktop/autopsy-stale-snapshot.json
```

The comparison does not open FalkorDB. It reports item keys only in each file,
changed shared keys, relation differences, and salvage guard metadata so you can
decide whether to restore a backup first and merge reviewed salvage afterward.

```bash
autopsy repair-embedded-snapshot --yes --accept-data-loss
```

If you have a semantic backup to import after quarantine, restore it in the
repair flow. While `workflow.status` is `rollback_detected`, ordinary
`autopsy restore <backup.json> --dry-run --offline` validates the JSON file
without opening Falkor at all. Plain `autopsy restore <backup.json> --dry-run`
falls back to offline validation if the guard blocks runtime access, but it
cannot compute existing-key counts, new/update counts, or relation endpoint
effects against the guarded graph. `repair-embedded-snapshot --dry-run`
validates recent default backup candidates, and `--restore-backup` validates the
selected file before import.

```bash
autopsy repair-embedded-snapshot --yes --accept-data-loss --restore-backup <backup.json>
```

To use the newest valid default backup shown by the dry run:

```bash
autopsy repair-embedded-snapshot --yes --accept-data-loss --restore-latest-backup
```

If using external FalkorDB, set:

```bash
export AUTOPSY_FALKORDB_HOST=127.0.0.1
export AUTOPSY_FALKORDB_PORT=6379
```

When host or port are explicitly set, the embedded lite path is not used.

## Consult Is Slow

Use a more specific query first.

For local debugging, disable reranking:

```bash
export AUTOPSY_MEMORY_CLI_RERANK=0
```

If a large graph is involved, run:

```bash
autopsy benchmark --sample-size 5 --include-sync
```

## No-Match Queries Return Results

Use `consult`, not raw `search`, when you need abstention behavior:

```bash
autopsy consult --query "specific unlikely thing"
```

If unrelated results still appear, capture the query and benchmark output before changing retrieval thresholds.

If `consult` reports `workflow.status: weak_signals_only`, do not treat the side-channel candidates as a usable answer. Refine the query or inspect exact items with `autopsy item`, `autopsy timeline`, or `autopsy neighbors`.

## Restore Safety

Always validate backup files before importing:

```bash
autopsy restore <backup.json> --dry-run
```

Default restore mode is merge. Replace mode is intentionally explicit:

```bash
autopsy restore <backup.json> --replace --yes
```

Replace mode deletes only keys present in the restore file before re-importing them.

## MCP Bridge Cannot Start Worker

Run:

```bash
autopsy-memory-mcp --print-config
```

Then inspect:

```text
~/Library/Application Support/Autopsy/CLI/mcp-worker.stderr.log
```

## Release Check Fails

Run the release check script from the repository root:

```bash
./scripts/release-check.sh
```

The script intentionally avoids writing to a live memory graph. Run the full benchmark separately before claiming memory health:

```bash
autopsy benchmark --sample-size 5 --include-sync
```
