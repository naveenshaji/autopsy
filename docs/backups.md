# Backup and recovery

Autopsy keeps FalkorDB local and authoritative. Version 0.1.32 creates a full JSON
recovery snapshot after each successful memory mutation, including source episodes,
history, repository lineage, and stored metadata. A backup made before a write is
never treated as covering that write simply because it is recent.

Snapshots use unique names, compact JSON, atomic publication, durable file flushes,
and SHA-256 sidecars (`.json.sha256`). Existing backup files are never overwritten
or automatically removed. Monitor available disk space as the archive grows.
Legacy JSON backups remain supported. Search indexes and embeddings are derived
data and can be regenerated after recovery.

## Enable iCloud Drive copies

```sh
autopsy backup --enable-icloud
autopsy backup --status
```

The default destination is `~/Library/Mobile Documents/com~apple~CloudDocs/Autopsy/Backups`.
iCloud Drive must already be available; Autopsy will not create a fake drive root.
For an existing custom destination within your iCloud Drive:

```sh
autopsy backup --enable-icloud --icloud-directory /path/to/iCloud/Autopsy/Backups
```

This opt-in is saved separately from agent instructions in Autopsy's
`Config/backup-settings.json`. Manual and automatic backups then create a verified
copy in the configured directory. Autopsy never mirrors the live database file.
Backups contain your private memory contents; the copies use your iCloud account.

The status distinguishes the latest copy attempt from the last successful copy.
`cloud_upload: unknown` means the local iCloud Drive copy was verified, but Apple's
server upload has not been confirmed. Offline access, exhausted storage, or disabled
iCloud syncing can delay upload. Local snapshots remain available when copying
fails, and the write response reports that recovery needs attention.

```sh
autopsy backup --retry-icloud
autopsy backup --retry-icloud --output /path/to/custom-backup.json
autopsy backup --disable-icloud
```

Retry copies the latest valid local snapshot without opening FalkorDB. Disabling
future copies preserves every existing local and iCloud file. Keep each JSON file
with its `.sha256` sidecar when transferring a backup.

## Restore without losing the current graph

First make another backup of the current state, then validate the selected input:

```sh
autopsy backup
autopsy restore /path/to/backup.json --dry-run --include-operational
autopsy restore /path/to/backup.json --include-operational
autopsy health
autopsy benchmark --sample-size 5 --include-sync
```

The default merge preserves existing keys. Review the dry-run counts before
restoring. `--include-operational` restores source episodes, history, and repository
context as well as semantic memories. Use `--dry-run --offline` for file validation
without touching the runtime; it cannot calculate target-graph effects.

Use `--replace --yes` only when intentionally replacing matching keys. It does not
mean replacing the entire graph. Backup checksums detect accidental alteration,
not malicious replacement of both the file and checksum. No backup system can
guarantee against every loss scenario; keep independent recovery copies and test
restores periodically.
