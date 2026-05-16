# CLI

## Health

```bash
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
