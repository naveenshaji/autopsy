import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autopsy_memory import cli  # noqa: E402


class Result:
    def __init__(self, rows):
        self.result_set = rows


class Graph:
    """Just enough of a graph for note writes: nodes keyed by entity id, looked up by stable key."""

    name = "unit"

    def __init__(self):
        self.nodes: list[dict[str, object]] = []
        self.edges: list[dict[str, object]] = []

    def add(self, entity_id: int, stable_key: str, kind: str, label: str) -> None:
        self.nodes.append({"entity_id": entity_id, "stable_key": stable_key, "kind": kind, "label": label})

    def query(self, query, params=None):
        params = params or {}
        if "RETURN coalesce(max(node.entity_id), 0)" in query:
            return Result([[max((int(node["entity_id"]) for node in self.nodes), default=0)]])
        if "RETURN coalesce(max(edge.edge_id), 0)" in query:
            return Result([[len(self.edges)]])
        if "MATCH (node:MemoryNode {stable_key: $stable_key})" in query and "RETURN" in query:
            rows = [
                [node["entity_id"], node["stable_key"], node["kind"], node["label"], "", "{}"]
                for node in self.nodes
                if node["stable_key"] == params.get("stable_key")
            ]
            return Result(rows[:1])
        if "CREATE (" in query and "entity_id: $entity_id" in query:
            self.add(int(params["entity_id"]), str(params["stable_key"]), str(params["kind"]), str(params["label"]))
            return Result([])
        if "CREATE (src)-[:" in query:
            self.edges.append(dict(params))
            return Result([])
        return Result([])


class EpisodeKeyTests(unittest.TestCase):
    def test_free_key_follows_entity_id(self):
        self.assertEqual(cli.episode_stable_key(Graph(), 12), "episode:12")

    def test_taken_key_gets_unique_suffix(self):
        graph = Graph()
        graph.add(3, "episode:12", "episode", "Episode restored from another graph")
        key = cli.episode_stable_key(graph, 12)
        self.assertTrue(key.startswith("episode:12-"), key)
        self.assertNotEqual(key, "episode:12")

    def test_note_write_never_duplicates_a_restored_episode_key(self):
        graph = Graph()
        # A restored graph: entity ids were renumbered (max 1) but old episode keys were kept.
        graph.add(1, "episode:3", "episode", "Old episode from before the restore")
        original_detail = cli.build_graph_item_detail_payload
        original_history = cli.record_memory_history_event
        try:
            cli.build_graph_item_detail_payload = lambda _graph, **kwargs: {"item": {"stableKey": kwargs["stable_key"]}}
            cli.record_memory_history_event = lambda *_args, **_kwargs: {"event": "ADD"}
            cli.create_graph_note_payload(
                graph,
                tool=cli,
                workspace={"root_path": "/tmp/memory-root"},
                kind="decision",
                title="New decision",
                content="Written after the restore; its episode id is 3.",
                repository_root_path=None,
                thread_id=None,
            )
        finally:
            cli.build_graph_item_detail_payload = original_detail
            cli.record_memory_history_event = original_history

        keys = [str(node["stable_key"]) for node in graph.nodes]
        self.assertEqual(len(keys), len(set(keys)), keys)
        episodes = [node for node in graph.nodes if node["kind"] == "episode"]
        self.assertEqual(len(episodes), 2)
        self.assertIn("Old episode from before the restore", [node["label"] for node in episodes])


if __name__ == "__main__":
    unittest.main()
