import json
import types
import unittest
from unittest import mock

from autopsy_memory import cli


class RetrievalFilterReliabilityTests(unittest.TestCase):
    def graph_for(self, records):
        queries = []

        def query(statement, params=None):
            queries.append((statement, params))
            keys = params["stable_keys"]
            # Support both the old split hydration reads and the combined read.
            if "detail_content" in statement:
                rows = [[key, "decision", "Release recovery", "Verified recovery", "Full recovery details",
                         record["tags"], json.dumps(record["metadata"]), "", "", ""]
                        for key, record in records.items() if key in keys]
            elif "memory_tags" in statement and "memory_metadata" in statement:
                rows = [[key, record["tags"], json.dumps(record["metadata"])]
                        for key, record in records.items() if key in keys]
            elif "memory_tags" in statement:
                rows = [[key, record["tags"]] for key, record in records.items() if key in keys]
            else:
                rows = [[key, json.dumps(record["metadata"])] for key, record in records.items() if key in keys]
            return types.SimpleNamespace(result_set=rows)

        return types.SimpleNamespace(query=query), queries

    def test_namespace_scope_and_metadata_filters_share_complete_hydration(self):
        metadata = {"namespaces": ["release"], "user_id": "alice", "score": 9, "owner": "active"}
        graph, queries = self.graph_for({"graph-note:match": {"tags": "release", "metadata": metadata}})
        original = {"stable_key": "graph-note:match", "kind": "decision"}
        filters = cli.build_consult_filters(None, tags=["release"], namespaces=["release"],
                                            entity_scopes=["user:alice"], metadata=["score>=8"])

        result = cli.filter_candidates_by_metadata(graph, [original], filters)

        self.assertEqual([item["stable_key"] for item in result], ["graph-note:match"])
        self.assertEqual(result[0]["metadata"], metadata)
        self.assertEqual(original, {"stable_key": "graph-note:match", "kind": "decision"})
        self.assertEqual(len(queries), 1)
        self.assertEqual(cli.filter_candidates_by_metadata(graph, result, filters), result)
        self.assertEqual(len(queries), 1, "already hydrated candidates must not be fetched again")

    def test_existing_tags_do_not_hide_namespaces_stored_in_metadata(self):
        graph, _ = self.graph_for({"graph-note:match": {
            "tags": "release", "metadata": {"namespaces": ["production"], "score": 9}}})
        result = cli.filter_candidates_by_metadata(
            graph, [{"stable_key": "graph-note:match", "kind": "decision", "tags": ["release"]}],
            cli.build_consult_filters(None, namespaces=["production"]))
        self.assertEqual([item["stable_key"] for item in result], ["graph-note:match"])
        self.assertEqual(result[0]["metadata"]["score"], 9)

    def test_existing_metadata_does_not_hide_scopes_stored_in_tags(self):
        graph, _ = self.graph_for({"graph-note:match": {
            "tags": "namespace:entity/user/alice", "metadata": {"score": 9}}})
        result = cli.filter_candidates_by_metadata(
            graph, [{"stable_key": "graph-note:match", "kind": "decision", "metadata": {"score": 9}}],
            cli.build_consult_filters(None, entity_scopes=["user:alice"], metadata=["score>=8"]))
        self.assertEqual([item["stable_key"] for item in result], ["graph-note:match"])
        self.assertEqual(result[0]["metadata"], {"score": 9})

    def test_combined_filters_exclude_partial_matches(self):
        graph, queries = self.graph_for({
            "graph-note:match": {"tags": "release", "metadata": {"namespaces": ["production"], "score": 9}},
            "graph-note:low": {"tags": "release", "metadata": {"namespaces": ["production"], "score": 2}},
            "graph-note:other": {"tags": "release", "metadata": {"namespaces": ["staging"], "score": 9}},
        })
        items = [{"stable_key": key, "kind": "decision"} for key in ("graph-note:match", "graph-note:low", "graph-note:other")]
        result = cli.filter_candidates_by_metadata(
            graph, items, cli.build_consult_filters(None, tags=["release"], namespaces=["production"], metadata=["score>=8"]))
        self.assertEqual([item["stable_key"] for item in result], ["graph-note:match"])
        self.assertEqual(len(queries), 1)

    def test_missing_local_metadata_is_a_nonmatch_without_graph(self):
        result = cli.filter_candidates_by_metadata(
            None, [{"stable_key": "graph-note:missing", "kind": "decision"}],
            cli.build_consult_filters(None, tags=["release"], metadata=["score>=8"]))
        self.assertEqual(result, [])

    def test_tags_only_filter_does_not_fetch_unused_metadata(self):
        graph = types.SimpleNamespace(query=mock.Mock(side_effect=AssertionError("unexpected hydration")))
        item = {"stable_key": "graph-note:match", "kind": "decision", "tags": ["release"]}
        result = cli.filter_candidates_by_metadata(graph, [item], cli.build_consult_filters(None, tags=["release"]))
        self.assertEqual(result, [item])
        graph.query.assert_not_called()

    def test_json_expression_and_namespace_share_full_item_hydration(self):
        graph, queries = self.graph_for({"graph-note:match": {
            "tags": "release", "metadata": {"namespaces": ["production"], "score": 9}}})
        filters = cli.build_consult_filters(None, namespaces=["production"], filter_json={
            "AND": [{"metadata": {"score": {"gte": 8}}}, {"title": {"icontains": "recovery"}}]})
        result = cli.filter_candidates_by_metadata(
            graph, [{"stable_key": "graph-note:match", "kind": "decision"}], filters)
        self.assertEqual([item["stable_key"] for item in result], ["graph-note:match"])
        self.assertEqual(len(queries), 1)


class VectorRetrievalReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.cache_patch = mock.patch.dict(cli._GRAPH_VECTOR_AVAILABILITY, {}, clear=True)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.tool = types.SimpleNamespace(
            embedding_provider_available=mock.Mock(return_value=(True, None)),
            embed_texts_with_provider=mock.Mock(return_value=[[0.1, 0.2]]),
        )

    def graph_for(self, probe_results=None, vector_results=None):
        probes = mock.Mock(side_effect=probe_results or [types.SimpleNamespace(result_set=[[1]])])
        vectors = mock.Mock(side_effect=vector_results or [types.SimpleNamespace(result_set=[[
            1, "graph-note:vector", "decision", "Recovery", "Verified recovery procedure", "", "graph_note", "", 0.8]])])

        def query(statement, params=None):
            return vectors() if "queryNodes" in statement else probes()

        return types.SimpleNamespace(name="vector-test", query=query), probes, vectors

    def test_transient_probe_failure_is_retried_on_next_read(self):
        graph, probes, _ = self.graph_for(probe_results=[RuntimeError("temporary connection failure"), types.SimpleNamespace(result_set=[[1]])])
        self.assertEqual(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0], [])
        self.assertEqual(len(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0]), 1)
        self.assertEqual(probes.call_count, 2)

    def test_transient_vector_query_failure_is_retried_on_next_read(self):
        row = types.SimpleNamespace(result_set=[[1, "graph-note:vector", "decision", "Recovery", "Verified recovery", "", "graph_note", "", 0.8]])
        graph, _, vectors = self.graph_for(
            probe_results=[types.SimpleNamespace(result_set=[[1]]), types.SimpleNamespace(result_set=[[1]])],
            vector_results=[RuntimeError("index temporarily unavailable"), row])
        self.assertEqual(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0], [])
        self.assertEqual(len(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0]), 1)
        self.assertEqual(vectors.call_count, 2)

    def test_empty_vector_cache_expires_after_external_embedding_write(self):
        graph, probes, _ = self.graph_for(probe_results=[types.SimpleNamespace(result_set=[]), types.SimpleNamespace(result_set=[[1]])])
        with mock.patch.object(cli.time, "monotonic", return_value=100):
            self.assertEqual(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0], [])
        with mock.patch.object(cli.time, "monotonic", return_value=101):
            self.assertEqual(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0], [])
        self.assertEqual(probes.call_count, 1)
        with mock.patch.object(cli.time, "monotonic", return_value=161):
            self.assertEqual(len(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0]), 1)
        self.assertEqual(probes.call_count, 2)

    def test_embedding_failure_falls_back_without_poisoning_availability_cache(self):
        graph, _, _ = self.graph_for()
        self.tool.embed_texts_with_provider.side_effect = [RuntimeError("model temporarily unavailable"), [[0.1, 0.2]]]
        self.assertEqual(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0], [])
        self.assertEqual(len(cli.fetch_vector_candidates(graph, self.tool, "recovery", {}, limit=3)[0]), 1)


if __name__ == "__main__":
    unittest.main()
