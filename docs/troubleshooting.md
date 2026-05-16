# Troubleshooting

## Check Dependencies

```bash
autopsy doctor
```

Required modules:

- `falkordb`
- `redis`
- `redislite.falkordb_client`

Optional module:

- `sentence_transformers`

## Falkor Fails To Start

Check the configured DB path:

```bash
autopsy doctor
```

If using embedded FalkorDBLite, make sure the parent directory is writable.

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

## MCP Bridge Cannot Start Worker

Run:

```bash
autopsy-memory-mcp --print-config
```

Then inspect:

```text
~/Library/Application Support/Autopsy/CLI/mcp-worker.stderr.log
```
