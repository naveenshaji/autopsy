import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autopsy_memory import cli, id_repair  # noqa: E402


def node(key, kind, *, created="2026-11-26T00:00:00Z", updated=None, label="", metadata="{}", parent=None, session=None, source=""):
    return {"key": key, "kind": kind, "source": source, "created": created, "updated": updated or created,
            "label": label, "metadata": metadata, "parent": parent, "session": session}


def rel(rel_type, relation, a, b, *, origin, created="2026-11-26T00:00:00Z", fact_text=""):
    return {"id": 1, "type": rel_type, "edge_id": 1, "origin": origin, "relation": relation, "created_at": created,
            "from_entity_id": 1, "to_entity_id": 2, "fact_text": fact_text, "from_id": 1, "to_id": 2, "from": a, "to": b}


class ClassifyTests(unittest.TestCase):
    session = node("claude-session:s1", "timeline", metadata='{"cwd": "/home/me/repo/sub", "project": "repo"}')
    event = node("claude-session:s1#e1", "timeline_event", session="claude-session:s1", metadata='{"cwd": "/home/me/repo"}')
    passage = node("claude-session:s1#e1/p1", "passage", parent="claude-session:s1#e1", session="claude-session:s1")
    other_event = node("claude-session:s2#e9", "timeline_event", session="claude-session:s2", metadata='{"cwd": "/home/me/other", "project": "other"}')
    old_note = node("graph-note:old", "observation", created="2026-09-01T00:00:00Z")
    repo = node("/home/me/repo", "repository")

    def verdict(self, *args, **kwargs):
        return id_repair.classify_relationship(rel(*args, **kwargs))[0]

    def test_import_edges_stay_inside_one_session(self):
        self.assertTrue(self.verdict("PART_OF", "part_of", self.passage, self.event, origin="claude_code_import"))
        self.assertFalse(self.verdict("PART_OF", "part_of", self.passage, self.old_note, origin="claude_code_import"))
        self.assertFalse(self.verdict("PART_OF", "part_of", self.old_note, self.event, origin="claude_code_import"))
        self.assertFalse(self.verdict("FOLLOWS", "follows", self.event, self.other_event, origin="claude_code_import"))
        self.assertTrue(self.verdict("CAPTURES", "captures", self.session, self.event, origin="claude_code_import"))

    def test_passage_belongs_to_its_parent_only(self):
        sibling = node("claude-session:s1#e2", "timeline_event", session="claude-session:s1")
        self.assertFalse(self.verdict("PART_OF", "part_of", self.passage, sibling, origin="claude_code_import"))

    def test_session_about_repository_by_cwd_or_project(self):
        self.assertTrue(self.verdict("ABOUT", "about", self.event, self.repo, origin="claude_code_import"))
        self.assertFalse(self.verdict("ABOUT", "about", self.other_event, self.repo, origin="claude_code_import"))
        imported = node("claude-session:s3", "timeline", metadata='{"cwd": "/home/elsewhere/code/repo", "project": "repo"}')
        self.assertTrue(self.verdict("ABOUT", "about", imported, self.repo, origin="claude_code_import"))

    def test_fact_edges_match_their_recorded_keys(self):
        target = node("graph-note:target", "decision")
        text = "graph-note:old informed_by graph-note:target"
        self.assertTrue(self.verdict("FACT_EDGE", "informed_by", self.old_note, target, origin="falkor", fact_text=text))
        self.assertFalse(self.verdict("FACT_EDGE", "informed_by", self.event, target, origin="falkor", fact_text=text))

    def test_note_episode_pairs_and_written_with_source(self):
        moment = "2026-11-26T00:06:07Z"
        note = node("graph-note:new", "decision", created=moment, label="Title")
        episode = node("episode:9", "episode", created=moment, label="Title")
        self.assertTrue(self.verdict("CAPTURED_IN", "captured_in", note, episode, origin="falkor", created=moment))
        self.assertFalse(self.verdict("CAPTURED_IN", "captured_in", self.old_note, episode, origin="falkor", created=moment))
        self.assertFalse(self.verdict("CAPTURES", "captures", episode, self.passage, origin="falkor", created=moment))
        updated_later = node("graph-note:upd", "decision", created="2026-11-01T00:00:00Z", updated="2026-11-27T00:00:00Z")
        self.assertTrue(self.verdict("ABOUT", "about", updated_later, self.repo, origin="falkor", created=moment))
        self.assertFalse(self.verdict("ABOUT", "about", self.old_note, self.repo, origin="falkor", created=moment))

    def test_history_points_at_its_target(self):
        history = node("memory-history:h", "memory_history_event", metadata='{"target_stable_key": "graph-note:old"}')
        self.assertTrue(self.verdict("HISTORY_OF", "history_of", history, self.old_note, origin="falkor"))
        self.assertFalse(self.verdict("HISTORY_OF", "history_of", history, self.event, origin="falkor"))
        self.assertFalse(self.verdict("HISTORY_OF", "history_of", self.old_note, self.event, origin="falkor"))


class CounterGraph:
    """execute_command implements the counter script the way the server does, atomically."""

    name = "unit"

    def __init__(self):
        self.store: dict[str, int] = {}
        self.lock = threading.Lock()
        self.maximum = 40

    def execute_command(self, command, _script, _keys, key, floor, count):
        assert command == "EVAL"
        with self.lock:
            self.store[key] = max(self.store.get(key, 0), int(floor)) + int(count)
            return self.store[key]

    def query(self, _query, params=None):
        return type("Result", (), {"result_set": [[self.maximum]]})()


class CounterTests(unittest.TestCase):
    def test_counter_starts_above_the_current_maximum_and_reserves_blocks(self):
        graph = CounterGraph()
        self.assertEqual(cli.next_entity_id(graph), 41)
        self.assertEqual(cli.next_entity_id(graph, count=2), 42)
        self.assertEqual(cli.next_entity_id(graph), 44)
        graph.maximum = 100  # an older writer moved past the counter
        self.assertEqual(cli.next_entity_id(graph), 101)

    def test_concurrent_writers_never_share_an_id(self):
        graph = CounterGraph()
        taken: list[int] = []
        guard = threading.Lock()

        def writer():
            for _ in range(250):
                value = cli.next_entity_id(graph)
                with guard:
                    taken.append(value)

        threads = [threading.Thread(target=writer) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(taken), len(set(taken)))

    def test_graphs_without_a_server_keep_max_plus_one(self):
        class Plain:
            name = "plain"

            def query(self, _query, params=None):
                return type("Result", (), {"result_set": [[7]]})()

        self.assertEqual(cli.next_entity_id(Plain()), 8)


class GuardSaveTests(unittest.TestCase):
    def test_persist_waits_for_a_running_background_save(self):
        calls = []

        class Client:
            def save(self):
                calls.append("save")
                if len(calls) < 3:
                    raise RuntimeError("Background save already in progress")

        class Graph:
            client = Client()

        with unittest.mock.patch.object(cli.time, "sleep", lambda _seconds: None):
            cli.persist_memory_database_guard_graph(Graph())
        self.assertEqual(calls, ["save", "save", "save"])

    def test_persist_raises_other_errors(self):
        class Client:
            def save(self):
                raise RuntimeError("MISCONF disk full")

        class Graph:
            client = Client()

        with self.assertRaises(RuntimeError):
            cli.persist_memory_database_guard_graph(Graph())


class RepairRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import redislite.falkordb_client  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("the embedded Falkor round trip needs the installed runtime dependencies")
        cls.temporary = tempfile.TemporaryDirectory(prefix="autopsy-id-repair-")
        cli.configure_falkordblite_runtime()
        cls.client = cli.load_falkordblite()(str(Path(cls.temporary.name) / "test.db"))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temporary.cleanup()

    def add(self, graph, entity_id, key, kind, *, created="2026-11-25T23:40:00Z", metadata=None, **properties):
        cli.create_memory_node(graph, entity_id=entity_id, kind=kind, stable_key=key, label=key, summary="", detail_content="",
                               confidence=1.0, source_kind="unit", created_at=created, updated_at=created, origin="unit",
                               tags=[], metadata=metadata or {})
        if properties:
            graph.query("MATCH (n:MemoryNode {stable_key: $key}) SET n += $properties", params={"key": key, "properties": properties})

    def edges(self, graph, key, rel_type):
        return sorted(row[0] for row in graph.query(
            f"MATCH (a:MemoryNode {{stable_key: $key}})-[r:{rel_type}]->(b) RETURN b.stable_key", params={"key": key}).result_set)

    def test_repair_keeps_intended_edges_renumbers_and_is_idempotent(self):
        graph = self.client.select_graph("collision")
        old = "2026-09-01T00:00:00Z"
        session, event, passage = "claude-session:s1", "claude-session:s1#e1", "claude-session:s1#e1/p1"
        self.add(graph, 30, "graph-note:early", "decision", created=old)
        self.add(graph, 20, "graph-note:target", "decision", created=old)
        # Written before the collision below: only one node had id 30, so it must survive untouched.
        cli.create_fact_edge(graph, from_entity_id=30, to_entity_id=20, relation="refines", predicate="REFINES",
                             fact_text="graph-note:early refines graph-note:target", timestamp=old, origin="falkor")
        self.add(graph, 10, session, "timeline", metadata={"cwd": "/tmp/repo"})
        self.add(graph, 11, event, "timeline_event", metadata={"cwd": "/tmp/repo"}, session_stable_key=session)
        self.add(graph, 12, passage, "passage", parent_stable_key=event, session_stable_key=session)
        self.add(graph, 13, "/tmp/repo", "repository")
        # A restore running at the same time took the same ids for older notes.
        self.add(graph, 11, "graph-note:restored-a", "observation", created=old)
        self.add(graph, 12, "graph-note:restored-b", "procedure", created=old)
        self.add(graph, 30, "claude-session:s1#e2/p1", "passage", parent_stable_key="claude-session:s1#e2", session_stable_key=session)
        now = "2026-11-26T00:01:00Z"
        for source, target, relation in ((12, 11, "part_of"), (11, 10, "part_of"), (10, 11, "captures"), (11, 13, "about")):
            cli.create_structural_edge(graph, from_entity_id=source, to_entity_id=target, relation=relation, timestamp=now, origin="claude_code_import")
        cli.create_fact_edge(graph, from_entity_id=11, to_entity_id=20, relation="informed_by", predicate="INFORMED_BY",
                             fact_text="graph-note:restored-a informed_by graph-note:target", timestamp=now, origin="falkor")
        self.assertEqual(self.edges(graph, passage, "PART_OF"), sorted([event, "graph-note:restored-a"]))  # fanned out

        plan = id_repair.build_repair_plan(id_repair.load_duplicate_state(graph))
        self.assertEqual(plan["duplicate_entity_ids"], 3)
        self.assertEqual(plan["unresolved"], [])
        result = id_repair.apply_repair_plan(
            graph, plan,
            reserve_entity_ids=lambda count: cli.next_entity_id(graph, count=count),
            reserve_edge_ids=lambda count: cli.next_edge_id(graph, count=count),
        )
        self.assertEqual(result["renumbered_nodes"], 3)

        self.assertEqual(self.edges(graph, passage, "PART_OF"), [event])
        self.assertEqual(self.edges(graph, "graph-note:restored-b", "PART_OF"), [])
        self.assertEqual(self.edges(graph, event, "PART_OF"), [session])
        self.assertEqual(self.edges(graph, session, "CAPTURES"), [event])
        self.assertEqual(self.edges(graph, event, "ABOUT"), ["/tmp/repo"])
        self.assertEqual(self.edges(graph, "graph-note:restored-a", "ABOUT"), [])
        self.assertEqual(self.edges(graph, "graph-note:restored-a", "FACT_EDGE"), ["graph-note:target"])
        self.assertEqual(self.edges(graph, event, "FACT_EDGE"), [])
        self.assertEqual(self.edges(graph, "graph-note:early", "FACT_EDGE"), ["graph-note:target"])
        ids = [row[0] for row in graph.query("MATCH (n:MemoryNode) RETURN n.entity_id").result_set]
        self.assertEqual(len(ids), len(set(ids)))
        mismatched = graph.query(
            "MATCH (a)-[r]->(b) WHERE r.from_entity_id <> a.entity_id OR r.to_entity_id <> b.entity_id RETURN count(r)"
        ).result_set[0][0]
        self.assertEqual(mismatched, 0)
        again = id_repair.build_repair_plan(id_repair.load_duplicate_state(graph))
        self.assertEqual((again["duplicate_entity_ids"], again["delete"], again["renumber"]), (0, [], []))


if __name__ == "__main__":
    unittest.main()
