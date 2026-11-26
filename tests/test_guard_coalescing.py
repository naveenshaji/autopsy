import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autopsy_memory import cli  # noqa: E402

WORKSPACE = {"id": "/tmp/ws", "workspace_key": "/tmp/ws", "slug": "ws", "title": "ws", "root_path": "/tmp/ws"}


class Result:
    def __init__(self, rows):
        self.result_set = rows


class FakeGraph:
    """Answers the guard's own queries; counts user writes and SAVEs."""

    name = "unit"

    def __init__(self):
        self.generation = 0
        self.user_mutations = 0
        self.save_calls = 0
        self.client = types.SimpleNamespace(save=self.save)

    def save(self):
        self.save_calls += 1

    def query(self, query, params=None):
        params = params or {}
        if "MATCH (guard:AutopsyMemoryGuard" in query and "RETURN coalesce(guard.generation, 0)" in query:
            return Result([[self.generation]] if self.generation else [])
        if "MATCH (guard:AutopsyMemoryGuard" in query and "RETURN guard.stable_key" in query:
            return Result([[cli.MEMORY_DATABASE_GUARD_STABLE_KEY]] if self.generation else [])
        if "CREATE (:AutopsyMemoryGuard" in query or "SET guard.policy" in query:
            self.generation = int(params["generation"])
            return Result([])
        if cli.graph_query_looks_mutating(query):
            self.user_mutations += 1
        return Result([])


class CoalescedSaveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.lite_path = str(Path(self.temporary.name) / "autopsy-memory.db")
        self.raw = FakeGraph()
        self.graph = cli.guarded_falkor_graph(self.raw, lite_path=self.lite_path, graph_name="unit")
        environment = mock.patch.dict(os.environ, {"AUTOPSY_MEMORY_GUARD_DISABLED": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def sidecar_generation(self):
        return cli.read_memory_database_guard_sidecar(self.lite_path)["graphs"]["unit"]["generation"]

    def test_writes_outside_an_operation_still_save_each_time(self):
        for _ in range(3):
            self.graph.query("CREATE (:Probe)")
        self.assertEqual((self.raw.save_calls, self.raw.generation, self.sidecar_generation()), (3, 3, 3))

    def test_an_operation_saves_once_at_the_end(self):
        with self.graph.coalesced_saves(max_interval=3600):
            for _ in range(50):
                self.graph.query("CREATE (:Probe)")
            self.graph.query("MATCH (n:Probe) RETURN n")
            self.assertEqual(self.raw.save_calls, 0)
        self.assertEqual(self.raw.user_mutations, 50)
        self.assertEqual((self.raw.save_calls, self.raw.generation, self.sidecar_generation()), (1, 1, 1))

    def test_long_operations_save_on_an_interval(self):
        with self.graph.coalesced_saves(max_interval=0):
            for _ in range(4):
                self.graph.query("CREATE (:Probe)")
        self.assertEqual(self.raw.save_calls, 4)  # every write was past the interval; nothing left at the end

    def test_reads_only_operations_do_not_save(self):
        with self.graph.coalesced_saves():
            self.graph.query("MATCH (n) RETURN count(n)")
        self.assertEqual(self.raw.save_calls, 0)

    def test_nested_operations_save_once_and_a_failure_still_saves(self):
        with self.assertRaises(RuntimeError):
            with self.graph.coalesced_saves(max_interval=3600):
                with cli.coalesced_guard_saves(self.graph):
                    self.graph.query("CREATE (:Probe)")
                self.assertEqual(self.raw.save_calls, 0)
                self.graph.query("CREATE (:Probe)")
                raise RuntimeError("operation failed after writing")
        self.assertEqual((self.raw.user_mutations, self.raw.save_calls, self.sidecar_generation()), (2, 1, 1))

    def test_other_threads_keep_saving_per_write(self):
        with self.graph.coalesced_saves(max_interval=3600):
            self.graph.query("CREATE (:Probe)")
            worker = threading.Thread(target=self.graph.query, args=("CREATE (:Other)",))
            worker.start()
            worker.join()
            self.assertEqual(self.raw.save_calls, 1)  # the other thread's write saved (with ours in it)
        self.assertEqual(self.raw.save_calls, 2)

    def test_rollback_is_still_refused_inside_an_operation(self):
        cli.write_memory_database_guard_sidecar(self.lite_path, graph_name="unit", generation=7, updated_at="2026-11-26T00:00:00Z")
        with self.assertRaises(cli.MemoryDatabaseRollbackError):
            with self.graph.coalesced_saves():
                self.graph.query("CREATE (:Probe)")
        self.assertEqual(self.raw.user_mutations, 0)

    def test_disabled_guard_and_plain_graphs_pass_through(self):
        with mock.patch.dict(os.environ, {"AUTOPSY_MEMORY_GUARD_DISABLED": "1"}):
            with self.graph.coalesced_saves():
                self.graph.query("CREATE (:Probe)")
        self.assertEqual(self.raw.save_calls, 0)
        plain = FakeGraph()
        with cli.coalesced_guard_saves(plain) as same:
            self.assertIs(same, plain)

    def test_bulk_writers_coalesce(self):
        for func in (cli.restore_memory_payload, cli.build_import_claude_code_payload, cli.build_import_session_payload,
                     cli.create_graph_note_payload, cli.update_graph_item_payload, cli.embed_pending_items):
            self.assertTrue(hasattr(func, "__wrapped__"), func.__name__)


class EmbeddedServerEnvironmentTests(unittest.TestCase):
    def test_malloc_arenas_are_capped_unless_set(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MALLOC_ARENA_MAX", None)
            cli.configure_falkordb_lite_server_environment()
            self.assertEqual(os.environ["MALLOC_ARENA_MAX"], "2")
            os.environ["MALLOC_ARENA_MAX"] = "8"
            cli.configure_falkordb_lite_server_environment()
            self.assertEqual(os.environ["MALLOC_ARENA_MAX"], "8")


class RestoreSaveCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import redislite.falkordb_client  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("the embedded Falkor round trip needs the installed runtime dependencies")
        cls.temporary = tempfile.TemporaryDirectory(prefix="autopsy-guard-coalesce-")
        cli.configure_falkordblite_runtime()
        cls.lite_path = str(Path(cls.temporary.name) / "test.db")
        cls.client = cli.load_falkordblite()(cls.lite_path)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temporary.cleanup()

    def saves(self):
        return int(self.client.select_graph("target").client.info("commandstats").get("cmdstat_save", {}).get("calls", 0))

    def test_restore_saves_once_instead_of_per_write(self):
        source = self.client.select_graph("source")
        for entity_id in range(1, 41):
            cli.create_memory_node(source, entity_id=entity_id, kind="observation", stable_key=f"graph-note:{entity_id}",
                                   label=f"note {entity_id}", summary="s", detail_content="d", confidence=1.0, source_kind="unit",
                                   created_at="2026-11-26T00:00:00Z", updated_at="2026-11-26T00:00:00Z", origin="unit", tags=[], metadata={})
        for entity_id in range(2, 41):
            cli.create_structural_edge(source, from_entity_id=entity_id, to_entity_id=1, relation="about",
                                       timestamp="2026-11-26T00:00:00Z", origin="unit")
        payload = cli.export_memory_payload(source, workspace=WORKSPACE, include_operational=True)
        target = cli.guarded_falkor_graph(self.client.select_graph("target"), lite_path=self.lite_path, graph_name="target")
        with mock.patch.dict(os.environ, {"AUTOPSY_MEMORY_GUARD_DISABLED": ""}):
            before = self.saves()
            result = cli.restore_memory_payload(target, workspace=WORKSPACE, input_path="unit.json", payload=payload,
                                                dry_run=False, replace=False, include_operational=True)
            saves = self.saves() - before
            state = cli.memory_database_guard_state(target._autopsy_guard_raw_graph, self.lite_path, graph_name="target")
        self.assertEqual(result["counts"]["created_items"], 40)
        self.assertEqual(target.query("MATCH ()-[r:ABOUT]->() RETURN count(r)").result_set[0][0], 39)
        self.assertLessEqual(saves, 3)
        # The same restore without coalescing saves once per write.
        control = cli.guarded_falkor_graph(self.client.select_graph("control"), lite_path=self.lite_path, graph_name="control")
        with mock.patch.dict(os.environ, {"AUTOPSY_MEMORY_GUARD_DISABLED": ""}):
            before = self.saves()
            cli.restore_memory_payload.__wrapped__(control, workspace=WORKSPACE, input_path="unit.json", payload=payload,
                                                   dry_run=False, replace=False, include_operational=True)
            self.assertGreater(self.saves() - before, 80)
        self.assertTrue(state["ok"])
        self.assertEqual(state["graph_generation"], state["sidecar_generation"])


if __name__ == "__main__":
    unittest.main()
