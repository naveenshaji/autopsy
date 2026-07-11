from __future__ import annotations

import unittest
from unittest import mock

from autopsy_memory import cli


class RecordingGraph:
    name = "embedding-unit"

    def __init__(self):
        self.calls = []

    def query(self, query, params=None):
        self.calls.append((query, params or {}))
        return type("Result", (), {"result_set": []})()


class VectorCandidateGraph:
    def __init__(self, name, row):
        self.name = name
        self.row = row
        self.calls = []

    def query(self, query, params=None):
        self.calls.append((query, params or {}))
        if "RETURN count(node)" in query:
            rows = [[1]]
        elif "db.idx.vector.queryNodes" in query:
            rows = [self.row]
        else:
            rows = []
        return type("Result", (), {"result_set": rows})()


class VectorTool:
    embedding_provider_available = staticmethod(lambda _config: (True, None))
    embed_texts_with_provider = staticmethod(lambda _texts, _config: [[1.0, 0.0, 0.0]])


class EmbeddingWriteTests(unittest.TestCase):
    def config(self, *, dimension=3):
        config = dict(cli.EMBEDDINGS_CONFIG_DEFAULT)
        config.update({
            "dimension": dimension,
            "model": "unit/model",
            "model_revision": "unit-revision",
            "text_template_version": "unit-template-v1",
        })
        return config

    def test_batch_preparation_uses_one_provider_call_and_records_provenance(self):
        records = [
            {
                "stable_key": "one",
                "kind": "decision",
                "label": "One",
                "summary": "First memory",
                "detail_content": "alpha",
                "timestamp": "2026-01-01T00:00:00Z",
            },
            {
                "stable_key": "two",
                "kind": "observation",
                "label": "Two",
                "summary": "Second memory",
                "detail_content": "beta",
                "timestamp": "2026-01-02T00:00:00Z",
            },
        ]
        with (
            mock.patch.object(
                cli,
                "embed_texts_with_provider",
                return_value=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            ) as embed,
            mock.patch.object(cli, "utc_now_iso", return_value="2026-07-11T12:00:00Z"),
        ):
            prepared = cli.prepare_memory_embedding_batch(records, self.config())

        embed.assert_called_once()
        self.assertEqual(set(prepared), {"one", "two"})
        self.assertEqual(prepared["one"]["status"], "ready")
        self.assertEqual(prepared["one"]["revision"], "unit-revision")
        self.assertEqual(prepared["one"]["template"], "unit-template-v1")
        self.assertEqual(prepared["one"]["source_updated_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(prepared["one"]["updated_at"], "2026-07-11T12:00:00Z")
        self.assertEqual(len(prepared["one"]["text_sha256"]), 64)

    def test_create_writes_vecf32_and_versioned_source_fingerprint(self):
        graph = RecordingGraph()
        with mock.patch.object(cli, "embed_texts_with_provider", return_value=[[1.0, 0.0, 0.0]]):
            result = cli.create_memory_node(
                graph,
                entity_id=1,
                kind="decision",
                stable_key="decision:one",
                label="Use arm64",
                summary="Native packaging is faster",
                detail_content="Replace the emulated runner.",
                confidence=1.0,
                source_kind="unit",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
                origin="unit",
                embedding_config=self.config(),
            )

        query, params = graph.calls[-1]
        self.assertIn("embedding: vecf32($embedding)", query)
        self.assertEqual(params["embedding_status"], "ready")
        self.assertEqual(params["embedding_model_revision"], "unit-revision")
        self.assertEqual(params["embedding_source_updated_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(result["dimension"], 3)

    def test_failed_content_update_clears_stale_vector_and_defers_repair(self):
        graph = RecordingGraph()
        with (
            mock.patch.object(cli, "lookup_node_by_stable_key", return_value={"memory_tags": "", "metadata": {}}),
            mock.patch.object(cli, "embed_texts_with_provider", side_effect=RuntimeError("provider offline")),
        ):
            result = cli.update_memory_node(
                graph,
                stable_key="decision:one",
                kind="decision",
                label="Updated policy",
                summary="New content",
                detail_content="A prior vector must not survive this edit.",
                confidence=1.0,
                source_kind="unit",
                updated_at="2026-01-02T00:00:00Z",
                origin="unit",
                embedding_config=self.config(),
            )

        query, params = graph.calls[-1]
        self.assertIn("node.embedding = null", query)
        self.assertEqual(params["embedding_status"], "deferred")
        self.assertIn("provider offline", params["embedding_error"])
        self.assertEqual(result["status"], "deferred")

    def test_cosine_distance_is_converted_to_higher_is_better_similarity(self):
        self.assertEqual(cli.vector_distance_to_similarity(0.0, "cosine"), 1.0)
        self.assertEqual(cli.vector_distance_to_similarity(1.0, "cosine"), 0.0)
        self.assertEqual(cli.vector_distance_to_similarity(2.0, "cosine"), -1.0)
        self.assertGreater(
            cli.vector_distance_to_similarity(0.2, "cosine"),
            cli.vector_distance_to_similarity(0.8, "cosine"),
        )

    def test_runtime_index_type_is_checked_for_the_requested_property_only(self):
        class IndexGraph:
            def query(self, _query, params=None):
                del params
                row = [
                    "SemanticItem",
                    ["search_text", "embedding"],
                    {"search_text": ["FULLTEXT"], "embedding": ["VECTOR"]},
                    {"embedding": {"dimension": 3, "similarityFunction": "cosine"}},
                    "english",
                    [],
                    "NODE",
                    "OPERATIONAL",
                ]
                return type("Result", (), {"result_set": [row]})()

        graph = IndexGraph()
        self.assertTrue(cli.runtime_index_has_type(
            graph,
            label="SemanticItem",
            property_name="embedding",
            index_type="VECTOR",
        ))
        self.assertFalse(cli.runtime_index_has_type(
            graph,
            label="SemanticItem",
            property_name="search_text",
            index_type="VECTOR",
        ))
        self.assertTrue(cli.check_runtime_vector_index(graph, self.config()))
        self.assertFalse(cli.check_runtime_vector_index(graph, self.config(dimension=4)))

    def vector_row(self, **overrides):
        values = {
            "entity_id": 1,
            "stable_key": "decision:current-vector",
            "kind": "decision",
            "title": "Current vector",
            "summary": "Only current-profile vectors are eligible.",
            "updated_at": "2026-01-02T00:00:00Z",
            "source_kind": "unit",
            "expired_at": "",
            "score": 0.2,
            "status": "ready",
            "provider": "sentence_transformers",
            "model": "unit/model",
            "revision": "unit-revision",
            "template": "unit-template-v1",
            "dimension": 3,
            "source_updated_at": "2026-01-02T00:00:00Z",
        }
        values.update(overrides)
        return [
            values["entity_id"],
            values["stable_key"],
            values["kind"],
            values["title"],
            values["summary"],
            values["updated_at"],
            values["source_kind"],
            values["expired_at"],
            values["score"],
            values["status"],
            values["provider"],
            values["model"],
            values["revision"],
            values["template"],
            values["dimension"],
            values["source_updated_at"],
        ]

    def fetch_vectors(self, graph):
        cli._GRAPH_VECTOR_AVAILABILITY.clear()
        with mock.patch.object(cli, "check_runtime_vector_index", return_value=True):
            return cli.fetch_vector_candidates(
                graph,
                VectorTool,
                "current embedding profile",
                self.config(),
                limit=5,
            )

    def test_vector_query_pushes_the_complete_active_embedding_profile(self):
        graph = VectorCandidateGraph("vector-current-profile", self.vector_row())

        items, _elapsed = self.fetch_vectors(graph)

        self.assertEqual([item["stable_key"] for item in items], ["decision:current-vector"])
        vector_query, params = next(
            (query, params)
            for query, params in graph.calls
            if "db.idx.vector.queryNodes" in query
        )
        for predicate in (
            "node.embedding_status",
            "node.embedding_provider",
            "node.embedding_model",
            "node.embedding_model_revision",
            "node.embedding_text_template",
            "node.embedding_dimension",
            "node.embedding_source_updated_at",
        ):
            self.assertIn(predicate, vector_query)
        self.assertEqual(params["embedding_provider"], "sentence_transformers")
        self.assertEqual(params["embedding_model"], "unit/model")
        self.assertEqual(params["embedding_revision"], "unit-revision")
        self.assertEqual(params["embedding_template"], "unit-template-v1")
        self.assertEqual(params["embedding_dimension"], 3)

    def test_vector_retrieval_excludes_stale_source_embeddings(self):
        graph = VectorCandidateGraph(
            "vector-stale-source",
            self.vector_row(source_updated_at="2026-01-01T00:00:00Z"),
        )

        items, _elapsed = self.fetch_vectors(graph)

        self.assertEqual(items, [])

    def test_vector_retrieval_excludes_mixed_and_wrong_profile_embeddings(self):
        wrong_profiles = {
            "status": {"status": "deferred"},
            "provider": {"provider": "other_provider"},
            "model": {"model": "unit/other-model"},
            "revision": {"revision": "old-revision"},
            "template": {"template": "old-template"},
            "dimension": {"dimension": 4},
        }
        for label, overrides in wrong_profiles.items():
            with self.subTest(label=label):
                graph = VectorCandidateGraph(
                    f"vector-wrong-{label}",
                    self.vector_row(**overrides),
                )
                items, _elapsed = self.fetch_vectors(graph)
                self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
