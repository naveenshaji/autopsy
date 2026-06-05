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
