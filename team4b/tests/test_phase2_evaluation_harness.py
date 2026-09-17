"""Focused tests for scripts/phase2_multilingual_embedding_evaluation.py
(EduCopilot M6 Phase 2 -- multilingual embedding evaluation harness).

Scope: the harness's own control flow, safety guards, ground truth
validation, metrics, and configuration/data handling. Deliberately does
NOT require a live Qdrant server, MongoDB, Redis, or network access to
huggingface.co -- every Qdrant interaction goes through an in-memory
`FakeQdrantClient` (implements `QdrantClientProtocol`, following the same
convention as `tests/test_vector_store.py`'s own fake), and every
embedding-model interaction goes through injected fakes
(`dimension_discovery`/`embedder_factory` on `evaluate_model`, and
monkeypatched `sentence_transformers.SentenceTransformer` for
`discover_model_dimension` itself). None of these tests touch the
canonical `educopilot_chunks` collection or any real embedding model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import pytest
from qdrant_client.models import Distance, FieldCondition, Filter, MatchAny, MatchValue, PointStruct, VectorParams

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from phase2_multilingual_embedding_evaluation import (  # noqa: E402
    CanonicalCollectionWriteRefusedError,
    GroundTruthEntry,
    GroundTruthValidationError,
    ModelUnavailableError,
    assert_safe_write_target,
    copy_canonical_chunks,
    delete_temp_collection,
    discover_model_dimension,
    embed_and_index_chunks,
    evaluate_model,
    group_by_language_pair,
    load_ground_truth,
    make_temp_collection_name,
    reciprocal_rank,
    recall_at_k,
    run_query,
    summarize,
    validate_environment,
    validate_ground_truth_chunk_ids_exist,
)
from app.core.config import Settings
from app.models.retrieval import RetrievalResult
from app.services.vector_store import ContextChunk, VectorStoreManager


# ---------------------------------------------------------------------------
# In-memory fake Qdrant client -- real scroll/search/upsert semantics,
# no live server. Mirrors tests/test_vector_store.py's own fake
# convention (independently written, not shared code).
# ---------------------------------------------------------------------------


def _matches_filter(payload: dict[str, Any], query_filter: Filter | None) -> bool:
    if query_filter is None:
        return True
    for condition in query_filter.must or []:
        assert isinstance(condition, FieldCondition)
        value = payload.get(condition.key)
        match = condition.match
        if isinstance(match, MatchValue):
            if value != match.value:
                return False
        elif isinstance(match, MatchAny):
            if value not in match.any:
                return False
    return True


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class FakeQdrantClient:
    """Implements QdrantClientProtocol (plus `delete_collection`, used
    only by the harness's optional `--cleanup` path) without a live
    Qdrant server."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.deleted_collections: list[str] = []

    def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name=name) for name in self.collections])

    def get_collection(self, collection_name: str) -> Any:
        collection = self.collections[collection_name]
        vectors = SimpleNamespace(size=collection["size"], distance=collection["distance"])
        config = SimpleNamespace(params=SimpleNamespace(vectors=vectors))
        return SimpleNamespace(config=config, points_count=len(collection["points"]))

    def create_collection(self, collection_name: str, vectors_config: VectorParams) -> Any:
        self.collections[collection_name] = {
            "size": vectors_config.size,
            "distance": vectors_config.distance,
            "points": {},
        }
        return True

    def create_payload_index(self, collection_name: str, field_name: str, field_schema: Any) -> Any:
        return True

    def upsert(self, collection_name: str, points: Sequence[PointStruct]) -> Any:
        collection = self.collections[collection_name]
        for point in points:
            collection["points"][point.id] = point
        return True

    def search(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        limit: int,
        score_threshold: float | None = None,
        query_filter: Any | None = None,
    ) -> Any:
        collection = self.collections[collection_name]
        scored = []
        for point in collection["points"].values():
            if not _matches_filter(point.payload, query_filter):
                continue
            score = _cosine(query_vector, point.vector)
            if score_threshold is not None and score < score_threshold:
                continue
            scored.append(SimpleNamespace(id=point.id, payload=point.payload, score=score))
        scored.sort(key=lambda item: -item.score)
        return scored[:limit]

    def delete(self, collection_name: str, points_selector: Any) -> Any:
        return True

    def scroll(self, collection_name: str, limit: int, offset: Any | None = None) -> Any:
        collection = self.collections[collection_name]
        all_points = list(collection["points"].values())
        start = offset or 0
        batch = all_points[start : start + limit]
        next_offset = start + limit if start + limit < len(all_points) else None
        return batch, next_offset

    def delete_collection(self, collection_name: str) -> Any:
        self.deleted_collections.append(collection_name)
        del self.collections[collection_name]
        return True


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {"_env_file": None}
    defaults.update(overrides)
    return Settings(**defaults)


def _seed_canonical_collection(client: FakeQdrantClient, settings: Settings, chunks: list[dict[str, Any]]) -> None:
    """Directly populate `client` as if it were the real canonical
    collection -- a one-hot vector per chunk (dimension =
    settings.embedding_dimensions) is enough to exercise real
    search/scroll control flow without a real embedding model."""

    client.create_collection(
        settings.canonical_qdrant_collection_name,
        VectorParams(size=settings.embedding_dimensions, distance=Distance.COSINE),
    )
    for index, chunk in enumerate(chunks):
        vector = [0.0] * settings.embedding_dimensions
        vector[index % settings.embedding_dimensions] = 1.0
        payload = {"text": chunk["text"], "chunk_id": chunk["chunk_id"], **chunk.get("metadata", {})}
        client.collections[settings.canonical_qdrant_collection_name]["points"][chunk["chunk_id"]] = PointStruct(
            id=chunk["chunk_id"], vector=vector, payload=payload
        )


# ---------------------------------------------------------------------------
# Safe temporary collection naming
# ---------------------------------------------------------------------------


class TestMakeTempCollectionName:
    def test_name_is_prefixed_and_contains_model_slug(self):
        name = make_temp_collection_name("all-MiniLM-L6-v2", "abc123")
        assert name.startswith("phase2_eval_")
        assert "all_minilm_l6_v2" in name
        assert "abc123" in name

    def test_different_run_ids_produce_different_names(self):
        assert make_temp_collection_name("model-x", "run1") != make_temp_collection_name("model-x", "run2")

    def test_name_never_equals_canonical_collection_name(self):
        assert make_temp_collection_name("educopilot_chunks", "abc123") != "educopilot_chunks"


# ---------------------------------------------------------------------------
# Refusal to write to the canonical collection
# ---------------------------------------------------------------------------


class TestAssertSafeWriteTarget:
    def test_raises_on_exact_match(self):
        with pytest.raises(CanonicalCollectionWriteRefusedError):
            assert_safe_write_target("educopilot_chunks", "educopilot_chunks")

    def test_raises_on_case_insensitive_match(self):
        with pytest.raises(CanonicalCollectionWriteRefusedError):
            assert_safe_write_target("EduCopilot_Chunks", "educopilot_chunks")

    def test_raises_on_whitespace_padded_match(self):
        with pytest.raises(CanonicalCollectionWriteRefusedError):
            assert_safe_write_target("  educopilot_chunks  ", "educopilot_chunks")

    def test_does_not_raise_for_a_genuinely_different_name(self):
        assert_safe_write_target("phase2_eval_all_minilm_l6_v2_abc123", "educopilot_chunks")

    def test_delete_temp_collection_refuses_to_delete_canonical(self):
        settings = _settings()
        with pytest.raises(CanonicalCollectionWriteRefusedError):
            delete_temp_collection("educopilot_chunks", "educopilot_chunks", settings)


# ---------------------------------------------------------------------------
# Dynamic dimension discovery
# ---------------------------------------------------------------------------


class TestDiscoverModelDimension:
    def test_returns_the_models_actual_reported_dimension(self, monkeypatch):
        class FakeModel:
            def get_sentence_embedding_dimension(self):
                return 512

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", lambda name: FakeModel())

        assert discover_model_dimension("some-model") == 512

    def test_never_hardcodes_384(self, monkeypatch):
        class FakeModel:
            def get_sentence_embedding_dimension(self):
                return 999

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", lambda name: FakeModel())

        assert discover_model_dimension("some-model") == 999

    def test_raises_model_unavailable_when_load_fails(self, monkeypatch):
        def _raise(name):
            raise OSError("no network access to huggingface.co")

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", _raise)

        with pytest.raises(ModelUnavailableError):
            discover_model_dimension("unreachable-model")

    def test_raises_model_unavailable_when_dimension_is_none(self, monkeypatch):
        class FakeModel:
            def get_sentence_embedding_dimension(self):
                return None

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", lambda name: FakeModel())

        with pytest.raises(ModelUnavailableError):
            discover_model_dimension("some-model")


# ---------------------------------------------------------------------------
# Ground truth validation
# ---------------------------------------------------------------------------


_VALID_ENTRY = {
    "query_id": "q1",
    "query": "What is process scheduling?",
    "query_language": "english",
    "source_language": "english",
    "workspace_id": "ws-1",
    "relevant_chunk_ids": ["chunk-1", "chunk-2"],
    "source_type": "pdf",
    "subject": "operating systems",
}


class TestLoadGroundTruth:
    def test_loads_a_valid_file(self, tmp_path: Path):
        path = tmp_path / "gt.json"
        path.write_text(json.dumps([_VALID_ENTRY]), encoding="utf-8")

        entries = load_ground_truth(path)

        assert len(entries) == 1
        entry = entries[0]
        assert entry.query_id == "q1"
        assert entry.relevant_chunk_ids == frozenset({"chunk-1", "chunk-2"})
        assert entry.query_language == "english"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(tmp_path / "does_not_exist.json")

    def test_invalid_json_raises(self, tmp_path: Path):
        path = tmp_path / "gt.json"
        path.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(path)

    def test_non_array_top_level_raises(self, tmp_path: Path):
        path = tmp_path / "gt.json"
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(path)

    def test_empty_array_raises(self, tmp_path: Path):
        path = tmp_path / "gt.json"
        path.write_text(json.dumps([]), encoding="utf-8")

        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(path)

    @pytest.mark.parametrize("missing_field", ["query_id", "query", "query_language", "source_language", "workspace_id"])
    def test_missing_required_field_raises(self, tmp_path: Path, missing_field: str):
        entry = dict(_VALID_ENTRY)
        del entry[missing_field]
        path = tmp_path / "gt.json"
        path.write_text(json.dumps([entry]), encoding="utf-8")

        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(path)

    def test_invalid_query_language_raises(self, tmp_path: Path):
        entry = dict(_VALID_ENTRY, query_language="french")
        path = tmp_path / "gt.json"
        path.write_text(json.dumps([entry]), encoding="utf-8")

        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(path)

    def test_empty_relevant_chunk_ids_raises(self, tmp_path: Path):
        entry = dict(_VALID_ENTRY, relevant_chunk_ids=[])
        path = tmp_path / "gt.json"
        path.write_text(json.dumps([entry]), encoding="utf-8")

        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(path)

    def test_duplicate_query_id_raises(self, tmp_path: Path):
        path = tmp_path / "gt.json"
        path.write_text(json.dumps([_VALID_ENTRY, _VALID_ENTRY]), encoding="utf-8")

        with pytest.raises(GroundTruthValidationError):
            load_ground_truth(path)

    def test_optional_fields_may_be_absent(self, tmp_path: Path):
        entry = dict(_VALID_ENTRY)
        del entry["source_type"]
        del entry["subject"]
        path = tmp_path / "gt.json"
        path.write_text(json.dumps([entry]), encoding="utf-8")

        entries = load_ground_truth(path)

        assert entries[0].source_type is None
        assert entries[0].subject is None


class TestValidateGroundTruthChunkIdsExist:
    def test_no_problems_when_all_chunk_ids_known(self):
        entry = GroundTruthEntry("q1", "query", "english", "english", "ws-1", frozenset({"c1", "c2"}))
        problems = validate_ground_truth_chunk_ids_exist([entry], known_chunk_ids={"c1", "c2", "c3"})
        assert problems == []

    def test_reports_missing_chunk_ids(self):
        entry = GroundTruthEntry("q1", "query", "english", "english", "ws-1", frozenset({"c1", "missing-chunk"}))
        problems = validate_ground_truth_chunk_ids_exist([entry], known_chunk_ids={"c1"})
        assert len(problems) == 1
        assert "missing-chunk" in problems[0]
        assert "q1" in problems[0]


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------


class TestRecallAtK:
    def test_hit_within_k_scores_full_recall_for_single_relevant_item(self):
        assert recall_at_k(["c2", "c1", "c3"], frozenset({"c1"}), k=3) == 1.0

    def test_miss_scores_zero(self):
        assert recall_at_k(["c2", "c3"], frozenset({"c1"}), k=3) == 0.0

    def test_only_counts_within_top_k(self):
        assert recall_at_k(["c2", "c3", "c1"], frozenset({"c1"}), k=2) == 0.0
        assert recall_at_k(["c2", "c3", "c1"], frozenset({"c1"}), k=3) == 1.0

    def test_partial_recall_with_multiple_relevant_items(self):
        assert recall_at_k(["c1", "c9"], frozenset({"c1", "c2"}), k=2) == 0.5

    def test_empty_relevant_set_scores_zero(self):
        assert recall_at_k(["c1"], frozenset(), k=5) == 0.0


class TestReciprocalRank:
    def test_first_position_hit_scores_one(self):
        assert reciprocal_rank(["c1", "c2"], frozenset({"c1"})) == 1.0

    def test_second_position_hit_scores_half(self):
        assert reciprocal_rank(["c9", "c1"], frozenset({"c1"})) == 0.5

    def test_no_hit_scores_zero(self):
        assert reciprocal_rank(["c9", "c8"], frozenset({"c1"})) == 0.0


class TestSummarize:
    def test_empty_pairs_returns_zeroed_summary(self):
        summary = summarize([])
        assert summary.query_count == 0
        assert summary.mrr == 0.0
        assert all(value == 0.0 for value in summary.recall_at_k.values())

    def test_averages_across_multiple_queries(self):
        entry_hit = GroundTruthEntry("q1", "query", "english", "english", "ws-1", frozenset({"c1"}))
        entry_miss = GroundTruthEntry("q2", "query", "english", "english", "ws-1", frozenset({"c9"}))
        from phase2_multilingual_embedding_evaluation import QueryOutcome

        outcome_hit = QueryOutcome("q1", 0.0, 0.01, ["c1"], [0.9])
        outcome_miss = QueryOutcome("q2", 0.0, 0.01, ["c2"], [0.5])

        summary = summarize([(entry_hit, outcome_hit), (entry_miss, outcome_miss)])

        assert summary.query_count == 2
        assert summary.recall_at_k[1] == 0.5
        assert summary.mrr == 0.5


class TestGroupByLanguagePair:
    def test_groups_entries_by_query_and_source_language(self):
        from phase2_multilingual_embedding_evaluation import QueryOutcome

        hindi_to_english = GroundTruthEntry("q1", "q", "hindi", "english", "ws-1", frozenset({"c1"}))
        english_to_english = GroundTruthEntry("q2", "q", "english", "english", "ws-1", frozenset({"c2"}))
        outcome = QueryOutcome("q", 0.0, 0.01, [], [])

        groups = group_by_language_pair([(hindi_to_english, outcome), (english_to_english, outcome)])

        assert set(groups.keys()) == {("hindi", "english"), ("english", "english")}
        assert len(groups[("hindi", "english")]) == 1


# ---------------------------------------------------------------------------
# Environment validation / unavailable Qdrant behavior
# ---------------------------------------------------------------------------


class TestValidateEnvironment:
    def test_reports_unreachable_qdrant(self):
        class BrokenClient:
            def get_collections(self):
                raise ConnectionError("connection refused")

        settings = _settings()
        result = validate_environment(BrokenClient(), settings)

        assert result.ok is False
        assert result.qdrant_reachable is False
        assert any("unreachable" in error for error in result.errors)

    def test_reports_missing_canonical_collection(self):
        client = FakeQdrantClient()
        settings = _settings()

        result = validate_environment(client, settings)

        assert result.ok is False
        assert result.qdrant_reachable is True
        assert result.canonical_collection_exists is False

    def test_reports_empty_canonical_collection(self):
        client = FakeQdrantClient()
        settings = _settings()
        client.create_collection(
            settings.canonical_qdrant_collection_name, VectorParams(size=384, distance=Distance.COSINE)
        )

        result = validate_environment(client, settings)

        assert result.ok is False
        assert result.canonical_collection_exists is True
        assert result.canonical_point_count == 0

    def test_ok_when_canonical_collection_has_points(self):
        client = FakeQdrantClient()
        settings = _settings()
        _seed_canonical_collection(
            client, settings, [{"chunk_id": "c1", "text": "hello", "metadata": {"workspace_id": "ws-1"}}]
        )

        result = validate_environment(client, settings)

        assert result.ok is True
        assert result.canonical_point_count == 1


# ---------------------------------------------------------------------------
# Canonical data copy (read-only) and metadata/chunk-id preservation
# ---------------------------------------------------------------------------


class TestCopyCanonicalChunks:
    def test_copies_real_chunk_text_and_metadata(self):
        client = FakeQdrantClient()
        settings = _settings()
        _seed_canonical_collection(
            client,
            settings,
            [
                {"chunk_id": "c1", "text": "process scheduling", "metadata": {"workspace_id": "ws-1", "document_id": "d1"}},
                {"chunk_id": "c2", "text": "system calls", "metadata": {"workspace_id": "ws-2", "document_id": "d2"}},
            ],
        )
        reader = VectorStoreManager(settings=settings, qdrant_client=client)

        chunks = copy_canonical_chunks(reader, settings.canonical_qdrant_collection_name)

        assert {chunk.chunk_id for chunk in chunks} == {"c1", "c2"}
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        assert by_id["c1"].text == "process scheduling"
        assert by_id["c1"].metadata["workspace_id"] == "ws-1"
        assert by_id["c1"].metadata["document_id"] == "d1"

    def test_scopes_by_workspace_id_when_given(self):
        client = FakeQdrantClient()
        settings = _settings()
        _seed_canonical_collection(
            client,
            settings,
            [
                {"chunk_id": "c1", "text": "a", "metadata": {"workspace_id": "ws-1"}},
                {"chunk_id": "c2", "text": "b", "metadata": {"workspace_id": "ws-2"}},
            ],
        )
        reader = VectorStoreManager(settings=settings, qdrant_client=client)

        chunks = copy_canonical_chunks(reader, settings.canonical_qdrant_collection_name, workspace_ids={"ws-1"})

        assert {chunk.chunk_id for chunk in chunks} == {"c1"}

    def test_never_writes_to_the_canonical_collection(self):
        """copy_canonical_chunks must only ever call scroll -- the
        canonical collection's point set must be unchanged afterward."""

        client = FakeQdrantClient()
        settings = _settings()
        _seed_canonical_collection(client, settings, [{"chunk_id": "c1", "text": "a", "metadata": {}}])
        reader = VectorStoreManager(settings=settings, qdrant_client=client)
        before = dict(client.collections[settings.canonical_qdrant_collection_name]["points"])

        copy_canonical_chunks(reader, settings.canonical_qdrant_collection_name)

        after = client.collections[settings.canonical_qdrant_collection_name]["points"]
        assert after.keys() == before.keys()


class TestEmbedAndIndexChunks:
    class _FakeEmbedder:
        def embed_queries(self, texts):
            # Deterministic one-hot-ish vectors so re-ranking is testable.
            return [[float(i == index) for i in range(4)] for index in range(len(texts))]

    def test_preserves_chunk_id_and_metadata_into_the_temp_collection(self):
        client = FakeQdrantClient()
        settings = _settings(embedding_dimensions=4, qdrant_collection_name="phase2_eval_temp")
        vector_store = VectorStoreManager(settings=settings, qdrant_client=client)
        chunks = [
            RetrievalResult(chunk_id="c1", text="hello", relevance_score=0.0, metadata={"workspace_id": "ws-1"}),
        ]

        timing = embed_and_index_chunks(chunks, self._FakeEmbedder(), vector_store)

        assert timing.chunk_count == 1
        stored_points = list(client.collections["phase2_eval_temp"]["points"].values())
        assert len(stored_points) == 1
        stored_point = stored_points[0]
        assert stored_point.payload["chunk_id"] == "c1"
        assert stored_point.payload["workspace_id"] == "ws-1"
        assert stored_point.payload["text"] == "hello"

    def test_empty_chunk_list_does_not_call_upsert_or_error(self):
        client = FakeQdrantClient()
        settings = _settings(embedding_dimensions=4, qdrant_collection_name="phase2_eval_temp_empty")
        vector_store = VectorStoreManager(settings=settings, qdrant_client=client)

        timing = embed_and_index_chunks([], self._FakeEmbedder(), vector_store)

        assert timing.chunk_count == 0
        assert "phase2_eval_temp_empty" not in client.collections


# ---------------------------------------------------------------------------
# Threshold handling
# ---------------------------------------------------------------------------


class TestRunQueryThresholdHandling:
    class _FakeEmbedder:
        def embed_query(self, text):
            return [1.0, 0.0, 0.0, 0.0]

    def test_lower_threshold_returns_at_least_as_many_results_as_higher_threshold(self):
        client = FakeQdrantClient()
        settings = _settings(embedding_dimensions=4, qdrant_collection_name="phase2_eval_threshold_test")
        vector_store = VectorStoreManager(settings=settings, qdrant_client=client)
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="close", text="a", embedding=[0.99, 0.01, 0.0, 0.0], metadata={"workspace_id": "ws-1"}),
                ContextChunk(chunk_id="far", text="b", embedding=[0.0, 0.0, 0.0, 1.0], metadata={"workspace_id": "ws-1"}),
            ]
        )
        entry = GroundTruthEntry("q1", "query", "english", "english", "ws-1", frozenset({"close"}))

        low_threshold_outcome = run_query(vector_store, self._FakeEmbedder(), entry, top_k=10, score_threshold=0.0, temp_collection_name="phase2_eval_threshold_test")
        high_threshold_outcome = run_query(vector_store, self._FakeEmbedder(), entry, top_k=10, score_threshold=0.99, temp_collection_name="phase2_eval_threshold_test")

        assert len(low_threshold_outcome.ranked_chunk_ids) >= len(high_threshold_outcome.ranked_chunk_ids)
        assert "close" in low_threshold_outcome.ranked_chunk_ids
        assert "far" not in high_threshold_outcome.ranked_chunk_ids


# ---------------------------------------------------------------------------
# evaluate_model: configuration loading, fair comparison, empty/missing
# ground truth, unavailable model handling
# ---------------------------------------------------------------------------


class _FakeEmbedderForEvaluate:
    def __init__(self, settings):
        self._settings = settings

    def embed_query(self, text):
        return [1.0] + [0.0] * (self._settings.embedding_dimensions - 1)

    def embed_queries(self, texts):
        return [[1.0] + [0.0] * (self._settings.embedding_dimensions - 1) for _ in texts]


class TestEvaluateModel:
    def test_builds_a_per_model_settings_copy_without_mutating_the_base(self):
        client = FakeQdrantClient()
        base_settings = _settings()
        chunks = [RetrievalResult(chunk_id="c1", text="hello", relevance_score=0.0, metadata={"workspace_id": "ws-1"})]

        result = evaluate_model(
            model_name="candidate-model",
            role="candidate",
            base_settings=base_settings,
            shared_client=client,
            chunks=chunks,
            ground_truth=[],
            top_k=10,
            thresholds=[0.0],
            run_id="run1",
            dimension_discovery=lambda name: 4,
            embedder_factory=_FakeEmbedderForEvaluate,
        )

        assert result.dimension == 4
        assert result.model_name == "candidate-model"
        assert base_settings.embedding_model_name == "all-MiniLM-L6-v2"  # unmodified
        assert base_settings.embedding_dimensions == 384  # unmodified
        assert result.temp_collection_name != base_settings.canonical_qdrant_collection_name
        assert result.temp_collection_name in client.collections

    def test_empty_ground_truth_produces_zeroed_metrics_without_error(self):
        client = FakeQdrantClient()
        settings = _settings()
        chunks = [RetrievalResult(chunk_id="c1", text="hello", relevance_score=0.0, metadata={"workspace_id": "ws-1"})]

        result = evaluate_model(
            model_name="model-x",
            role="baseline",
            base_settings=settings,
            shared_client=client,
            chunks=chunks,
            ground_truth=[],
            top_k=10,
            thresholds=[0.0, 0.3],
            run_id="run2",
            dimension_discovery=lambda name: 4,
            embedder_factory=_FakeEmbedderForEvaluate,
        )

        assert len(result.thresholds) == 2
        for threshold_result in result.thresholds:
            assert threshold_result.overall.query_count == 0
            assert threshold_result.overall.mrr == 0.0

    def test_two_models_evaluated_against_the_same_chunks_get_isolated_collections(self):
        client = FakeQdrantClient()
        settings = _settings()
        chunks = [RetrievalResult(chunk_id="c1", text="hello", relevance_score=0.0, metadata={"workspace_id": "ws-1"})]

        baseline = evaluate_model(
            model_name="baseline-model",
            role="baseline",
            base_settings=settings,
            shared_client=client,
            chunks=chunks,
            ground_truth=[],
            top_k=10,
            thresholds=[0.0],
            run_id="run3",
            dimension_discovery=lambda name: 4,
            embedder_factory=_FakeEmbedderForEvaluate,
        )
        candidate = evaluate_model(
            model_name="candidate-model",
            role="candidate",
            base_settings=settings,
            shared_client=client,
            chunks=chunks,
            ground_truth=[],
            top_k=10,
            thresholds=[0.0],
            run_id="run3",
            dimension_discovery=lambda name: 4,
            embedder_factory=_FakeEmbedderForEvaluate,
        )

        assert baseline.temp_collection_name != candidate.temp_collection_name
        assert baseline.chunk_count == candidate.chunk_count == 1

    def test_model_unavailable_error_propagates_rather_than_being_swallowed(self):
        """evaluate_model itself must not silently invent a result when
        the model can't be loaded -- main() is responsible for catching
        ModelUnavailableError and reporting the limitation; evaluate_model
        must let it propagate."""

        client = FakeQdrantClient()
        settings = _settings()
        chunks = [RetrievalResult(chunk_id="c1", text="hello", relevance_score=0.0, metadata={"workspace_id": "ws-1"})]

        def _unavailable(name):
            raise ModelUnavailableError(f"{name} cannot be loaded")

        with pytest.raises(ModelUnavailableError):
            evaluate_model(
                model_name="unreachable-model",
                role="candidate",
                base_settings=settings,
                shared_client=client,
                chunks=chunks,
                ground_truth=[],
                top_k=10,
                thresholds=[0.0],
                run_id="run4",
                dimension_discovery=_unavailable,
                embedder_factory=_FakeEmbedderForEvaluate,
            )

    def test_refuses_when_dimension_discovery_or_naming_would_target_canonical(self, monkeypatch):
        """Defense in depth: even if a temp collection name were somehow
        made to collide with the canonical name, evaluate_model must
        refuse rather than proceed."""

        client = FakeQdrantClient()
        settings = _settings()
        chunks = [RetrievalResult(chunk_id="c1", text="hello", relevance_score=0.0, metadata={"workspace_id": "ws-1"})]

        monkeypatch.setattr(
            "phase2_multilingual_embedding_evaluation.make_temp_collection_name",
            lambda model_name, run_id: settings.canonical_qdrant_collection_name,
        )

        with pytest.raises(CanonicalCollectionWriteRefusedError):
            evaluate_model(
                model_name="any-model",
                role="baseline",
                base_settings=settings,
                shared_client=client,
                chunks=chunks,
                ground_truth=[],
                top_k=10,
                thresholds=[0.0],
                run_id="run5",
                dimension_discovery=lambda name: 4,
                embedder_factory=_FakeEmbedderForEvaluate,
            )
