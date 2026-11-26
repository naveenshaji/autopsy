"""Find and repair memory nodes that share an entity id.

Before 0.1.36, entity ids were allocated as ``max(entity_id) + 1`` in one query and used in a
later one, with nothing in between to stop another writer. Two writers running at the same time
(an import next to a restore, two worker threads) could therefore give two nodes the same id.

Edges are created by matching entity ids, so every edge written to or from that id afterwards
attached to all the nodes that had it: one intended relationship fanned out into two (one side
shared) or four (both sides shared), all with the same ``edge_id``.

The repair:

1. groups the relationships around shared ids by the write that created them (same type, edge
   id, origin, time and recorded entity ids);
2. in each fanned-out group keeps the relationships that are consistent with how that writer
   creates edges and deletes the copies (``classify_relationship``);
3. gives every node of a shared id but one a fresh id, and rewrites the entity ids recorded on
   its remaining edges;
4. gives the extra relationships kept from one group their own edge ids.

Groups no rule can settle are left untouched and reported as unresolved.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Callable

SESSION_KEY_PREFIXES = ("claude-session:", "codex-session:")
IMPORT_ORIGINS = {"claude_code_import"}
CONTAINER_KINDS = {"repository", "workspace", "thread"}
HISTORY_KIND = "memory_history_event"
# Renumbered nodes take ids well above the current maximum, so a writer still running an older
# Autopsy (which takes max + 1 without the counter) cannot land on one of them mid-repair.
RENUMBER_MARGIN = 1000
EXAMPLE_LIMIT = 12

_NODE_FIELDS = ("key", "kind", "source", "created", "updated", "label", "metadata", "parent", "session")
_NODE_RETURN = (
    "{v}.stable_key, {v}.kind, {v}.source_kind, {v}.created_at, {v}.updated_at, {v}.label, "
    "{v}.memory_metadata, {v}.parent_stable_key, {v}.session_stable_key"
)


def _rows(result) -> list[list[Any]]:
    return list(getattr(result, "result_set", None) or [])


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _session_of(key: Any) -> str | None:
    text = _text(key)
    if text.startswith(SESSION_KEY_PREFIXES):
        return text.split("#", 1)[0]
    return None


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(_text(value) or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _path_within(path: str, root: str) -> bool:
    path, root = path.rstrip("/"), root.rstrip("/")
    return bool(path and root) and (path == root or path.startswith(root + "/"))


def _is_key_fact_text(fact_text: str, relation: str) -> bool:
    """fact_text in the "<from key> <relation> <to key>" form (hand-written facts are left alone)."""
    parts = fact_text.split(" ")
    return len(parts) == 3 and parts[1] == relation and ":" in parts[0] and bool(parts[2])


def _node(row: list[Any], offset: int) -> dict[str, Any]:
    return dict(zip(_NODE_FIELDS, row[offset:offset + len(_NODE_FIELDS)]))


def load_duplicate_state(graph) -> dict[str, Any]:
    """Shared ids, their nodes, and every relationship touching those nodes."""
    groups = [
        (int(row[0]), sorted(int(node_id) for node_id in row[1]))
        for row in _rows(graph.query(
            """
            MATCH (node:MemoryNode)
            WITH node.entity_id AS entity_id, collect(id(node)) AS ids
            WHERE entity_id IS NOT NULL AND size(ids) > 1
            RETURN entity_id, ids
            """
        ))
    ]
    node_ids = sorted({node_id for _, ids in groups for node_id in ids})
    nodes: dict[int, dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    if node_ids:
        for row in _rows(graph.query(
            f"MATCH (n:MemoryNode) WHERE id(n) IN $ids RETURN id(n), n.entity_id, {_NODE_RETURN.format(v='n')}",
            params={"ids": node_ids},
        )):
            nodes[int(row[0])] = {"id": int(row[0]), "entity_id": int(row[1]), **_node(row, 2)}
        for row in _rows(graph.query(
            f"""
            MATCH (a:MemoryNode)-[r]->(b:MemoryNode)
            WHERE id(a) IN $ids OR id(b) IN $ids
            RETURN id(r), type(r), r.edge_id, r.origin, r.relation, r.created_at,
                   r.from_entity_id, r.to_entity_id, r.fact_text, id(a), id(b),
                   {_NODE_RETURN.format(v='a')}, {_NODE_RETURN.format(v='b')}
            """,
            params={"ids": node_ids},
        )):
            width = len(_NODE_FIELDS)
            relationships.append({
                "id": int(row[0]), "type": _text(row[1]), "edge_id": row[2], "origin": _text(row[3]),
                "relation": _text(row[4]), "created_at": _text(row[5]),
                "from_entity_id": row[6], "to_entity_id": row[7], "fact_text": _text(row[8]),
                "from_id": int(row[9]), "to_id": int(row[10]),
                "from": _node(row, 11), "to": _node(row, 11 + width),
            })
    return {"groups": groups, "nodes": nodes, "relationships": relationships}


def classify_relationship(rel: dict[str, Any]) -> tuple[bool | None, str]:
    """Whether this relationship is one its writer meant to create: True, False, or None (unknown).

    Each rule mirrors how a writer builds the edge, so a copy that landed on the wrong node of a
    shared id fails it.
    """
    a, b = rel["from"], rel["to"]
    relation, origin, created = rel["relation"], rel["origin"], rel["created_at"]
    if rel["type"] == "FACT_EDGE" and _is_key_fact_text(rel["fact_text"], relation):
        # Written relations record "<from key> <relation> <to key>".
        return rel["fact_text"] == f"{_text(a['key'])} {relation} {_text(b['key'])}", "fact_text"
    if origin in IMPORT_ORIGINS:
        # The session importer only links nodes of one session, and a session to its repo/workspace.
        sessions = [_session_of(node["key"]) for node in (a, b)]
        for node, session in zip((a, b), sessions):
            if session is None and _text(node["kind"]) not in CONTAINER_KINDS:
                return False, "import_links_session_nodes"
        if sessions[0] and sessions[1] and sessions[0] != sessions[1]:
            return False, "import_links_one_session"
        if relation == "part_of" and _text(a["kind"]) == "passage":
            return _text(a["parent"]) == _text(b["key"]), "passage_parent"
        if relation == "part_of" and sessions[0] and sessions[1]:
            return _text(a["session"]) in ("", _text(b["key"])), "event_session"
        if relation == "captures" and sessions[0] and sessions[1]:
            return _text(b["session"]) in ("", _text(a["key"])), "session_captures_event"
        if relation in ("about", "belongs_to") and sessions[0] and not sessions[1]:
            if _text(b["kind"]) == "repository":
                return _session_in_repository(_metadata(a["metadata"]), _text(b["key"])), "session_in_repository"
            return True, "session_container"
        return True, "same_session"
    if relation == "history_of":
        if _text(a["kind"]) != HISTORY_KIND:
            return False, "history_target"
        target = _text(_metadata(a["metadata"]).get("target_stable_key"))
        return (target == _text(b["key"]) if target else None), "history_target"
    if relation in ("captured_in", "captures") and created:
        # Note writes and updates create a source episode at the moment of the write and link it
        # to the note they write: the episode dates from the edge, the note existed by then.
        episode, note = (a, b) if _text(a["kind"]) == "episode" else (b, a)
        if _text(episode["kind"]) != "episode" or _session_of(note["key"]):
            return False, "note_episode_pair"
        return _text(episode["created"]) == created and _existed_at(note, created), "note_episode_pair"
    if relation in ("about", "belongs_to") and created:
        # Written with the note or episode it starts from, which existed by then and was not
        # last changed before it.
        if _session_of(a["key"]):
            return False, "written_with_source"
        return _existed_at(a, created), "written_with_source"
    return None, "no_rule"


def _session_in_repository(metadata: dict[str, Any], repository: str) -> bool | None:
    """Whether a session ran in this repository: by its working directory, or by project name for
    sessions imported from another machine (whose paths differ)."""
    cwd = _text(metadata.get("cwd")).rstrip("/")
    project = _text(metadata.get("project"))
    name = repository.rstrip("/").rsplit("/", 1)[-1]
    if not cwd and not project:
        return None
    if _path_within(cwd, repository):
        return True
    return bool(name) and (project == name or name in cwd.split("/"))


def _existed_at(node: dict[str, Any], moment: str) -> bool:
    """Created at or before ``moment`` and not last updated before it (ISO timestamps sort)."""
    created = _text(node["created"])
    updated = max(created, _text(node["updated"]))
    return bool(created) and created <= moment <= updated


def _creation_key(rel: dict[str, Any]) -> tuple:
    return (rel["type"], _text(rel["edge_id"]), rel["origin"], rel["created_at"],
            _text(rel["from_entity_id"]), _text(rel["to_entity_id"]))


def _describe(rel: dict[str, Any], reason: str = "") -> dict[str, Any]:
    return {
        "relationship_id": rel["id"], "type": rel["type"], "relation": rel["relation"],
        "edge_id": rel["edge_id"], "origin": rel["origin"], "created_at": rel["created_at"],
        "from": _text(rel["from"]["key"]), "to": _text(rel["to"]["key"]),
        "from_node_id": rel["from_id"], "to_node_id": rel["to_id"], "reason": reason,
    }


def build_repair_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Decide what to delete, renumber and re-id; nothing is written."""
    by_creation: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for rel in state["relationships"]:
        by_creation[_creation_key(rel)].append(rel)
    delete: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    reassign_edge_ids: list[dict[str, Any]] = []
    kept_from_fanout = 0
    for rels in by_creation.values():
        if len(rels) == 1:
            continue  # only one node had the id when this edge was written
        verdicts = [(rel, *classify_relationship(rel)) for rel in rels]
        valid = [rel for rel, verdict, _ in verdicts if verdict is True]
        unknown = [rel for rel, verdict, _ in verdicts if verdict is None]
        if valid:
            keep = valid
        elif len(unknown) == 1:
            keep = unknown
        elif not unknown:
            keep = []  # every copy contradicts its writer: the intended node is gone (deleted since)
        else:
            unresolved.append({"candidates": [_describe(rel, reason) for rel, _, reason in verdicts]})
            continue
        keep_ids = {rel["id"] for rel in keep}
        for rel, verdict, reason in verdicts:
            if rel["id"] not in keep_ids:
                delete.append(_describe(rel, reason))
        kept_from_fanout += len(keep)
        for rel in sorted(keep, key=lambda item: item["id"])[1:]:
            reassign_edge_ids.append(_describe(rel))
    renumber: list[dict[str, Any]] = []
    for entity_id, node_ids in state["groups"]:
        keeper, *others = node_ids
        for node_id in others:
            node = state["nodes"].get(node_id, {})
            renumber.append({
                "node_id": node_id, "entity_id": entity_id, "stable_key": _text(node.get("key")),
                "kind": _text(node.get("kind")), "keeps_id": _text(state["nodes"].get(keeper, {}).get("key")),
            })
    return {
        "duplicate_entity_ids": len(state["groups"]),
        "nodes_sharing_ids": sum(len(ids) for _, ids in state["groups"]),
        "relationships_examined": len(state["relationships"]),
        "fanned_out_writes": sum(1 for rels in by_creation.values() if len(rels) > 1),
        "relationships_kept_from_fanout": kept_from_fanout,
        "delete": delete,
        "renumber": renumber,
        "reassign_edge_ids": reassign_edge_ids,
        "unresolved": unresolved,
    }


def summarize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    reasons: dict[str, int] = defaultdict(int)
    for item in plan["delete"]:
        reasons[item["reason"]] += 1
    return {
        "duplicate_entity_ids": plan["duplicate_entity_ids"],
        "nodes_sharing_ids": plan["nodes_sharing_ids"],
        "nodes_to_renumber": len(plan["renumber"]),
        "relationships_examined": plan["relationships_examined"],
        "fanned_out_writes": plan["fanned_out_writes"],
        "relationships_to_delete": len(plan["delete"]),
        "relationships_kept_from_fanout": plan["relationships_kept_from_fanout"],
        "edge_ids_to_reassign": len(plan["reassign_edge_ids"]),
        "unresolved_writes": len(plan["unresolved"]),
        "delete_reasons": dict(sorted(reasons.items())),
        "delete_examples": plan["delete"][:EXAMPLE_LIMIT],
        "unresolved_examples": plan["unresolved"][:EXAMPLE_LIMIT],
    }


def apply_repair_plan(
    graph,
    plan: dict[str, Any],
    *,
    reserve_entity_ids: Callable[[int], int],
    reserve_edge_ids: Callable[[int], int],
) -> dict[str, Any]:
    """Write the plan. Every write re-checks the element it targets, so a stale plan does nothing."""
    deleted = 0
    for item in plan["delete"]:
        result = graph.query(
            """
            MATCH (a) WHERE id(a) = $from_id
            MATCH (a)-[r]->(b) WHERE id(r) = $rel_id AND id(b) = $to_id AND type(r) = $type
            DELETE r
            RETURN count(r)
            """,
            params={"from_id": item["from_node_id"], "to_id": item["to_node_id"], "rel_id": item["relationship_id"], "type": item["type"]},
        )
        deleted += int((_rows(result) or [[0]])[0][0] or 0)
    renumbered: list[dict[str, Any]] = []
    if plan["renumber"]:
        first = reserve_entity_ids(len(plan["renumber"]))
        for offset, item in enumerate(plan["renumber"]):
            new_id = first + offset
            result = graph.query(
                "MATCH (n:MemoryNode) WHERE id(n) = $node_id AND n.entity_id = $old SET n.entity_id = $new RETURN count(n)",
                params={"node_id": item["node_id"], "old": item["entity_id"], "new": new_id},
            )
            if int((_rows(result) or [[0]])[0][0] or 0):
                graph.query(
                    "MATCH (n) WHERE id(n) = $node_id MATCH (n)-[r]->() SET r.from_entity_id = $new",
                    params={"node_id": item["node_id"], "new": new_id},
                )
                graph.query(
                    "MATCH (n) WHERE id(n) = $node_id MATCH ()-[r]->(n) SET r.to_entity_id = $new",
                    params={"node_id": item["node_id"], "new": new_id},
                )
                renumbered.append({**item, "new_entity_id": new_id})
    reassigned = 0
    if plan["reassign_edge_ids"]:
        first = reserve_edge_ids(len(plan["reassign_edge_ids"]))
        for offset, item in enumerate(plan["reassign_edge_ids"]):
            result = graph.query(
                """
                MATCH (a) WHERE id(a) = $from_id
                MATCH (a)-[r]->() WHERE id(r) = $rel_id
                SET r.edge_id = $new
                RETURN count(r)
                """,
                params={"from_id": item["from_node_id"], "rel_id": item["relationship_id"], "new": first + offset},
            )
            reassigned += int((_rows(result) or [[0]])[0][0] or 0)
    return {"deleted_relationships": deleted, "renumbered_nodes": len(renumbered), "reassigned_edge_ids": reassigned, "renumbered": renumbered}
