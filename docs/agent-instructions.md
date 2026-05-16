# Agent Instructions

Use Autopsy memory for nontrivial repo work, debugging, releases, architecture questions, and any task where prior decisions may matter.

Default behavior is system-wide. Do not pass `--workspace` unless explicitly debugging workspace resolution.

## Before Substantial Work

Run:

```bash
autopsy status --current-only
autopsy consult --current-only --query "<task/context query>"
```

Prefer `consult` over `search` when relying on memory.

Compatibility form:

```bash
autopsy memory status --current-only
autopsy memory consult --current-only --query "<task/context query>"
```

## Repo-Specific Work

Use repo scope when only one repository should influence the answer:

```bash
autopsy consult --scope repo --repo <repo-root> --query "<query>"
```

If running inside a known repo, Autopsy can infer and boost the current repo automatically.

Use system scope for cross-repo conventions, user preferences, release patterns, or machine-level debugging history:

```bash
autopsy consult --scope system --query "<query>"
```

## Reading Memory

Inspect `workflow.complete`.

If `workflow.complete` is `false`, follow suggested next steps before relying on the result.

Use exact inspection commands when the answer depends on a specific memory:

```bash
autopsy item <stable-key>
autopsy timeline <stable-key>
autopsy neighbors --stable-key <stable-key>
```

Treat memory as evidence, not absolute truth. Verify drift-prone facts against code, config, git, or external sources.

## Writing Memory

After material work, write durable outcomes:

```bash
autopsy capture-outcome --outcome decision --title "..." --content "..."
autopsy capture-outcome --outcome attempt --title "..." --content "..."
autopsy capture-outcome --outcome plan --title "..." --content "..."
autopsy capture-outcome --outcome preference --title "..." --content "..."
autopsy capture-outcome --outcome question --title "..." --content "..."
autopsy capture-outcome --outcome resolved-question --title "..." --content "..."
autopsy capture-outcome --outcome reverted-attempt --title "..." --content "..."
```

For repo work, attribute writes:

```bash
autopsy capture-outcome --outcome decision --repository-root-path <repo-root> --title "..." --content "..."
```

Add explicit relations when possible:

```bash
autopsy capture-outcome \
  --outcome decision \
  --title "..." \
  --content "..." \
  --informed-by <stable-key> \
  --supersedes <stable-key> \
  --depends-on <stable-key> \
  --implements <stable-key> \
  --constrains <stable-key> \
  --refines <stable-key>
```

Supported relation flags:

```text
--informed-by
--answers
--supersedes
--reverts
--depends-on
--implements
--constrains
--refines
```

## Memory-System Changes

Run:

```bash
autopsy benchmark --sample-size 5 --include-sync
```

Do not claim memory health unless the benchmark passes or failures are explicitly reported.

Run `autopsy doctor` when Falkor, dependency, or data-path issues are suspected.
