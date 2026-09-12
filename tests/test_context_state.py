import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from autopsy_memory import cli, context_state, evaluation


class ProjectIdentityTests(unittest.TestCase):
    def test_worktrees_and_symlinks_share_identity_but_other_repositories_do_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, other, tree = (root / name for name in ("repo", "other", "tree"))
            for path in (repo, other):
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "commit", "--allow-empty", "-qm", "initial"], check=True)
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-qb", "test", str(tree)], check=True)
            alias = root / "alias"
            alias.symlink_to(repo)
            self.assertEqual(context_state.repository_identity(repo), context_state.repository_identity(tree))
            self.assertEqual(context_state.repository_identity(repo), context_state.repository_identity(alias))
            self.assertNotEqual(context_state.repository_identity(repo), context_state.repository_identity(other))

    def test_project_boost_is_bounded_and_does_not_hide_other_projects(self):
        items = [{"stable_key": "global", "usage_rank_score": 10},
                 {"stable_key": "local", "usage_rank_score": 9},
                 {"stable_key": "strong-global", "usage_rank_score": 20}]
        context_state.annotate_project(items, {"local": ["repo"], "global": ["other"]}, ["repo"], "repo")
        self.assertEqual([item["stable_key"] for item in context_state.prioritize_project(items)],
                         ["strong-global", "local", "global"])
        self.assertEqual(items[0]["project_context"]["scope"], "other_project")
        self.assertEqual(items[2]["project_context"]["scope"], "unattributed")

    def test_new_relation_flags_validate_task_targets(self):
        args = cli.build_parser().parse_args(["capture-outcome", "--outcome", "observation", "--completes", "graph-note:task"])
        self.assertEqual(args.completes, ["graph-note:task"])
        self.assertTrue(cli.semantic_relation_ontology_result(source_kind="observation", relation="completes", target_kind="attempt")["allowed"])
        self.assertFalse(cli.semantic_relation_ontology_result(source_kind="observation", relation="completes", target_kind="preference")["allowed"])


class TaskGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import redislite.falkordb_client  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requires isolated Falkor runtime")
        cls.temporary = tempfile.TemporaryDirectory(prefix="autopsy-context-test-")
        cli.configure_falkordblite_runtime()
        cls.client = cli.load_falkordblite()(str(Path(cls.temporary.name) / "test.db"))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temporary.cleanup()

    def setUp(self):
        self.graph = self.client.select_graph(self._testMethodName)
        for identifier, key, kind in [(1, "task", "attempt"), (2, "completion", "observation"),
                                      (3, "reopened", "attempt"), (4, "repo-a", "repository"),
                                      (5, "repo-b", "repository"), (6, "workspace", "workspace"),
                                      (7, "episode", "episode"), (8, "indirect", "decision")]:
            cli.create_memory_node(self.graph, entity_id=identifier, kind=kind, stable_key=key, label=key,
                                   summary="Original evidence preserved", detail_content="Do not overwrite",
                                   confidence=1, source_kind="test", created_at="2026-01-01T00:00:00Z",
                                   updated_at="2026-01-01T00:00:00Z", origin="test")
        self.items = [{"stable_key": "task", "kind": "attempt"}]

    def relation(self, source, relation, timestamp, **kwargs):
        cli.create_fact_edge(self.graph, from_entity_id=source, to_entity_id=1, relation=relation,
                             predicate=relation.upper(), fact_text="Explicit evidence", timestamp=timestamp,
                             origin="test", **kwargs)

    def state(self, at="2026-09-12T00:00:00Z"):
        return context_state.task_states(self.graph, self.items, at, cli.result_rows)["task"]

    def test_completion_and_reopening_preserve_task_body_and_as_of_state(self):
        self.relation(2, "completes", "2026-02-01T00:00:00Z")
        self.relation(3, "reopens", "2026-03-01T00:00:00Z")
        self.assertEqual(self.state("2026-01-15T00:00:00Z")["state"], "open")
        self.assertEqual(self.state("2026-02-15T00:00:00Z")["state"], "completed")
        self.assertEqual(self.state()["state"], "open")
        self.assertEqual(self.state()["evidence"][0]["stable_key"], "reopened")
        self.assertEqual(cli.result_rows(self.graph.query("MATCH (n {stable_key:'task'}) RETURN n.detail_content"))[0][0], "Do not overwrite")

    def test_same_time_conflicting_evidence_is_visible(self):
        self.relation(2, "completes", "2026-02-01T00:00:00Z")
        self.relation(3, "reopens", "2026-02-01T00:00:00Z")
        self.assertEqual(self.state()["state"], "conflict")

    def test_expired_completion_does_not_close_task(self):
        self.relation(2, "completes", "2026-02-01T00:00:00Z", expired_at="2026-03-01T00:00:00Z")
        self.assertEqual(self.state()["state"], "open")
        self.assertEqual(self.state("2026-02-15T00:00:00Z")["state"], "completed")

    def test_informed_by_never_guesses_completion(self):
        self.relation(2, "informed_by", "2026-02-01T00:00:00Z")
        self.assertEqual(self.state()["state"], "open")

    def test_repository_filter_does_not_cross_shared_workspace(self):
        for source, target, relation in [(1, 4, "about"), (1, 6, "belongs_to"),
                                          (4, 6, "belongs_to"), (5, 6, "belongs_to"),
                                          (8, 7, "captured_in"), (7, 5, "about")]:
            cli.create_structural_edge(self.graph, from_entity_id=source, to_entity_id=target,
                                       relation=relation, timestamp="2026-01-01T00:00:00Z", origin="test")
        links = context_state.repository_links(self.graph, ["task", "indirect"], cli.result_rows)
        self.assertEqual(links, {"task": ["repo-a"], "indirect": ["repo-b"]})
        self.assertEqual(cli.stable_keys_linked_to_repository(self.graph, ["task", "indirect"], "repo-b"), {"indirect"})
        payload = cli.build_status_payload(self.graph, tool=cli.FalkorToolShim,
                    workspace={"id":"test", "slug":"test", "title":"test", "root_path":"/tmp/test"},
                    thread_id=None, limit=6, section_limit=3, recent_days=21,
                    filters={"scope":"repo", "repository_stable_key":"repo-a", "repository_aliases":["repo-a"]})
        self.assertEqual([item["stable_key"] for item in payload["status"]["open_loops"]], ["task"])

    def test_status_excludes_completed_task_before_section_limit(self):
        self.relation(2, "completes", "2026-02-01T00:00:00Z")
        payload = cli.build_status_payload(self.graph, tool=cli.FalkorToolShim,
                    workspace={"id":"test", "slug":"test", "title":"test", "root_path":"/tmp/test"},
                    thread_id=None, limit=6, section_limit=1, recent_days=21)
        self.assertNotIn("task", [item["stable_key"] for item in payload["status"]["open_loops"]])


class EvaluationTests(unittest.TestCase):
    def test_invalid_gold_is_rejected(self):
        for case in [{"id":"one", "query":"q"}, {"id":"one", "query":"q", "expected_any":["a"], "forbidden":["a"]}]:
            with self.assertRaises(ValueError):
                evaluation.validate_suite({"schema_version":1, "cases":[case]})

    def test_forbidden_and_stale_evidence_fail_even_when_expected_key_found(self):
        case = {"id":"one", "expected_any":["a"], "forbidden":["b"]}
        result = evaluation.score_case(case, {"retrieval":{"items":[{"stable_key":"a"}, {"stable_key":"b", "lineage":{"current":False}}]}}, 0.1)
        self.assertTrue(result["evidence_found"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["stale_keys"], ["b"])

    def test_abstention_requires_no_evidence_and_no_complete_claim(self):
        case = {"id":"none", "must_abstain":True}
        self.assertTrue(evaluation.score_case(case, {"workflow":{"complete":False}}, 0.1)["passed"])
        self.assertFalse(evaluation.score_case(case, {"retrieval":{"items":[{"stable_key":"irrelevant"}]}}, 0.1)["passed"])


if __name__ == "__main__":
    unittest.main()
