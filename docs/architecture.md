# Architecture

Autopsy Memory is a local-first graph memory runtime.

## Components

- `autopsy_memory.cli`: command-line interface and the core graph operations.
- `autopsy_memory.worker`: local HTTP worker used by UI clients and the MCP bridge.
- `autopsy_memory.mcp_bridge`: stdio MCP server exposing product-level memory tools.
- FalkorDB or FalkorDBLite: authoritative graph backend.
- Optional sentence-transformer models: semantic embeddings and reranking.

## Storage Model

Memory is stored as graph nodes and typed relation edges.

Important node categories:

- Semantic items: decisions, attempts, plans, preferences, questions, summaries, and memory notes.
- Operational nodes: workspaces, repositories, threads, worktrees, and branches.
- Context nodes: adjacent context such as episodes.

Important relation categories:

- Structural relations: workspace/repo/thread attachment and capture lineage.
- Fact relations: `informed_by`, `answers`, `supersedes`, `reverts`, `depends_on`, `implements`, `constrains`, and `refines`.

## Retrieval

`consult` is the default agent-facing read path. It combines lexical, exact, graph, and optional semantic retrieval. It returns:

- candidate hits
- inspected items
- workflow completeness
- suggested next steps when coverage is weak

Agents should prefer `consult` over raw search because `consult` is designed for evidence-backed work.

## Failure Policy

Falkor is required. Autopsy does not fall back to another local database when Falkor is unavailable. This is intentional because silent backend changes create stale or split-brain memory.

Use `autopsy doctor` for dependency and path checks.

## Compatibility

The standalone CLI supports both:

```bash
autopsy consult --query "..."
autopsy memory consult --query "..."
```

The first form is preferred for the standalone product. The second form exists for existing agents and instructions.
