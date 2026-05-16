# Privacy And Security

Autopsy Memory is local-first.

Default local paths:

```text
~/Library/Application Support/Autopsy/FalkorDB/autopsy-memory.db
~/Library/Application Support/Autopsy/Config/memory-settings.json
```

Autopsy does not require hosted sync for local operation.

## Model Downloads

If the `ml` extra is installed, sentence-transformer models may be downloaded by the model provider. If you need a no-download setup, install without the `ml` extra and rely on lexical/Falkor retrieval.

## Secrets

Do not store secrets, API keys, credentials, private keys, or tokens in memory. Treat the graph as local durable context, not a secrets manager.

## Backups

Back up the FalkorDBLite path if you need durable recovery. Do not copy the DB while a process is actively writing unless you understand the storage engine behavior.

For a portable JSON backup, run:

```bash
autopsy backup
```

For a specific path:

```bash
autopsy export --output ~/Desktop/autopsy-memory-export.json
```

## Failure Policy

Autopsy fails loudly when Falkor cannot initialize. It does not silently switch to another local persistence backend.
