# Context quality and private evaluation

System-wide search remains the default. When invoked inside a Git repository, the CLI supplies that project as a hint. A bounded 15% ranking boost favors relevant current-project evidence without excluding stronger evidence from other projects. `--repo /path/to/project` supplies the hint explicitly; add `--scope repo` for an exclusive project read. Linked local worktrees and symlinks share project identity. Missing paths retain exact path identity; repository names alone never establish equivalence.

Context labels evidence as current project, other project, or unattributed. Unattributed evidence is not assumed to be a global preference. Repository ownership follows direct links or source episodes and does not travel through shared workspaces. No existing repository nodes are migrated.

## Resuming work

Use `autopsy context --current-only --query 'where did we leave off' --repo /path/to/project` for a compact context block and `core.resume` with open work, recent outcomes, decisions, and conflicts. Add `--scope repo` to exclude other projects. These are bounded recent-memory sections, not an exhaustive task tracker.

Record completion only when its evidence exists:

```sh
autopsy capture-outcome --outcome observation \
  --title 'Release verified' --content 'Describe the result, verification, and remaining limitations.' \
  --completes graph-note:ATTEMPT_KEY --informed-by graph-note:VERIFICATION_KEY \
  --repo /path/to/project
```

Use `--reopens graph-note:ATTEMPT_KEY` on a new outcome when work resumes. Targets must be attempts or plans; questions continue to use `--answers`. Original attempts remain readable, with their content and history intact. Completion is derived from explicit relations, including effective dates and expiration. Same-time contradictory events produce a conflict requiring inspection. An `informed-by` relationship does not prove completion.

## Recording provenance

Existing metadata options can record `--metadata environment=production`, `--metadata source_commit=COMMIT`, `--metadata verified_at=ISO_TIMESTAMP`, and `--metadata valid_until=ISO_TIMESTAMP`. Context surfaces these fields from inspected evidence. New repository-attributed notes also record their supplied worktree path. These fields describe recorded evidence; they do not automatically verify a deployment or enforce an expiration. Use `expire` or relation expiration for lifecycle enforcement.

## Private evaluation

Write a private suite outside your checkout:

```json
{
  "schema_version": 1,
  "gold_review": "reviewed by owner",
  "as_of": "2026-09-12T07:56:13Z",
  "cases": [
    {
      "id": "release-verification",
      "query": "Which verification passed for our last release?",
      "category": "releases",
      "repo": "/path/to/project",
      "expected_any": ["graph-note:VERIFIED_RELEASE"],
      "forbidden": ["graph-note:SUPERSEDED_RELEASE"]
    },
    {
      "id": "unknown-project",
      "query": "What did we decide for nonexistent project QXZ-999?",
      "category": "abstention",
      "must_abstain": true
    }
  ]
}
```

Take a backup, then run:

```sh
autopsy evaluate /private/suite.json --snapshot /private/backup.json --report /private/baseline.json
autopsy evaluate /private/suite.json --snapshot /private/backup.json --report /private/candidate.json --baseline /private/baseline.json
```

Each run restores into a temporary database, suppresses access-counter writes, and verifies that evaluation did not mutate its snapshot. An optional `--frozen-db` accepts a previously restored `evaluation` graph and copies it before use; its complete portable content and relationships must match the backup. Never supply a database that is being written by another process.

The evaluator uses the local lexical route and reports full retrieval evidence separately from context size. It does not score generated answers or guarantee that every retrieved item fits in the rendered context budget. Review expected keys and phrasing before treating scores as an acceptance gate. Include ordinary paraphrases, project and environment boundaries, dated questions, superseded facts, and questions that should abstain. Keep the suite frozen during a comparison, and reserve additional questions for later evaluation rather than tuning everything against the same set.

The existing `autopsy benchmark` remains the runtime integrity check. Passing it and passing a private retrieval suite are different claims.
