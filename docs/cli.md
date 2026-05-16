# CLI

## Global Install

```bash
./scripts/install-global.sh
autopsy version --json
autopsy doctor
```

The installer creates a versioned Homebrew-style layout under `/opt/homebrew` when writable, or `~/.local` otherwise. It backs up a non-standalone existing `autopsy` command before replacing it.

## Health

```bash
autopsy version
autopsy doctor
autopsy status --current-only
autopsy benchmark --sample-size 5 --include-sync
```

## Retrieval

```bash
autopsy consult --query "architecture decisions"
autopsy recall --query "release process"
autopsy search --query "Falkor"
```

Prefer `consult` when the answer will rely on memory.

## Inspection

```bash
autopsy item <stable-key>
autopsy timeline <stable-key>
autopsy neighbors --stable-key <stable-key>
autopsy snapshot <stable-key>
```

Use `timeline` before relying on memories that may have been superseded, reverted, or invalidated.

## Writes

```bash
autopsy capture-outcome --outcome decision --title "..." --content "..."
autopsy capture-outcome --outcome attempt --title "..." --content "..."
autopsy capture-outcome --outcome plan --title "..." --content "..."
autopsy decision --title "..." --content "..."
autopsy attempt --title "..." --content "..."
```

## Portability

```bash
autopsy export --output ~/Desktop/autopsy-memory-export.json
autopsy export --include-operational --limit 100
autopsy backup
```

`export` writes semantic memory and in-graph relations as JSON. `backup` writes the same export shape to a timestamped file under the Autopsy application-support backups directory unless `--output` is provided.

## Agent Setup

```bash
autopsy instructions
```

This prints the recommended `AGENTS.md` memory instructions.

Write with repo attribution:

```bash
autopsy capture-outcome \
  --outcome decision \
  --repository-root-path /path/to/repo \
  --title "..." \
  --content "..."
```

Write with relations:

```bash
autopsy capture-outcome \
  --outcome decision \
  --title "..." \
  --content "..." \
  --informed-by graph-note:abc \
  --refines graph-note:def
```

## Compatibility Prefix

Both forms are valid:

```bash
autopsy consult --query "..."
autopsy memory consult --query "..."
```

Standalone docs use the shorter top-level form.
