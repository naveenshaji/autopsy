"""Read-time project provenance and explicit task state; never rewrites memories."""
import os
import subprocess
from pathlib import Path


def repository_identity(path):
    """Join local worktrees by Git common directory, never by repository basename."""
    if not path:
        return ""
    root = Path(path).expanduser().resolve(strict=False)
    if root.is_dir():
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True, text=True, timeout=2, check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                common = Path(result.stdout.strip()).resolve()
                stat = common.stat()
                return f"git:{stat.st_dev}:{stat.st_ino}"
            stat = root.stat()
            return f"directory:{stat.st_dev}:{stat.st_ino}"
        except (OSError, subprocess.SubprocessError):
            pass
    return os.path.normcase(str(root))


def repository_aliases(graph, requested, rows):
    if not requested:
        return []
    identity = repository_identity(requested)
    candidates = rows(graph.query("MATCH (repo:Repository) RETURN repo.stable_key"))
    return sorted({str(requested), *(str(row[0]) for row in candidates
                    if row[0] and repository_identity(str(row[0])) == identity)})


def repository_links(graph, keys, rows):
    if not keys:
        return {}
    # Never traverse a shared Workspace or a sibling memory to infer ownership.
    result = graph.query("""
        MATCH (node:MemoryNode)
        WHERE node.stable_key IN $stable_keys
        OPTIONAL MATCH (node)-[:ABOUT]->(direct:Repository)
        OPTIONAL MATCH (node)-[:CAPTURED_IN|PART_OF*1..2]->(source)-[:ABOUT]->(origin:Repository)
        RETURN node.stable_key, direct.stable_key, origin.stable_key
        """, params={"stable_keys": list(set(keys))})
    linked = {}
    for row in rows(result):
        linked.setdefault(str(row[0]), set()).update(str(value) for value in row[1:3] if value)
    return {key: sorted(values) for key, values in linked.items()}


def annotate_project(items, links, aliases, requested=""):
    aliases = set(aliases)
    for item in items:
        repositories = links.get(str(item.get("stable_key") or item.get("stableKey") or ""), [])
        current = bool(aliases.intersection(repositories))
        item["project_context"] = {
            "scope": "current_project" if current else "other_project" if repositories else "unattributed",
            "repositories": repositories,
            "current_repository": requested or None,
        }
    return items


def prioritize_project(items, base_score=None):
    """A bounded boost retains stronger cross-project evidence and original ties."""
    def score(item):
        base = base_score(item) if base_score else float(item.get("usage_rank_score") or 0.0)
        current = item.get("project_context", {}).get("scope") == "current_project"
        item["project_rank_multiplier"] = 1.15 if current else 1.0
        return base * item["project_rank_multiplier"]
    return sorted(items, key=score, reverse=True)


def task_states(graph, items, read_time, rows):
    keys = [str(item.get("stable_key") or "") for item in items
            if item.get("kind") in {"attempt", "plan", "open_question"}]
    states = {key: {"state": "open", "evidence": []} for key in keys if key}
    if not states:
        return states
    result = graph.query("""
        MATCH (evidence:MemoryNode)-[fact:FACT_EDGE]->(task:MemoryNode)
        WHERE task.stable_key IN $stable_keys
          AND fact.relation IN ['completes', 'reopens', 'answers', 'supersedes', 'reverts']
          AND coalesce(fact.created_at, '') <= $read_time
          AND coalesce(evidence.created_at, '') <= $read_time
          AND (coalesce(evidence.expired_at, '') = '' OR evidence.expired_at > $read_time)
          AND (coalesce(fact.valid_at, '') = '' OR fact.valid_at <= $read_time)
          AND (coalesce(fact.invalid_at, '') = '' OR fact.invalid_at > $read_time)
          AND (coalesce(fact.expired_at, '') = '' OR fact.expired_at > $read_time)
        RETURN task.stable_key, fact.relation, evidence.stable_key,
               CASE WHEN coalesce(fact.valid_at, '') = '' THEN coalesce(fact.created_at, '') ELSE fact.valid_at END, evidence.label
        """, params={"stable_keys": keys, "read_time": read_time})
    for row in rows(result):
        if str(row[0]) in states:
            states[str(row[0])]["evidence"].append({
                "relation": str(row[1]), "stable_key": str(row[2]),
                "effective_at": str(row[3] or ""), "title": str(row[4] or ""),
            })
    for state in states.values():
        evidence = sorted(state["evidence"], key=lambda event: event["effective_at"], reverse=True)
        if evidence:
            latest = [event for event in evidence if event["effective_at"] == evidence[0]["effective_at"]]
            results = {"open" if event["relation"] == "reopens" else "completed" if event["relation"] in {"completes", "answers"}
                       else "superseded" if event["relation"] == "supersedes" else "reverted" for event in latest}
            state["state"] = results.pop() if len(results) == 1 else "conflict"
        state["evidence"] = evidence[:6]
    return states


def annotation(item):
    context = item.get("project_context") or {}
    bits = []
    if context:
        scope = str(context.get("scope") or "unattributed").replace("_", " ")
        repos = context.get("repositories") or []
        bits.append(f"{scope}: {', '.join(repos)}" if repos else scope)
    if item.get("updated_at"):
        bits.append(f"recorded {item['updated_at']}; external state not reverified")
    provenance = item.get("evidence", {}).get("provenance", {})
    for name in ("environment", "source_commit", "verified_at", "valid_until", "worktree"):
        if provenance.get(name):
            bits.append(f"{name} {provenance[name]}")
    state = item.get("task_state") or {}
    if state:
        bits.append(f"task {state.get('state', 'unknown')}")
        if state.get("evidence"):
            bits.append(f"state evidence {state['evidence'][0]['stable_key']}")
    return f" [{'; '.join(bits)}]" if bits else ""
