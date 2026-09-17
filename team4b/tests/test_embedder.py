"""Focused tests for Task 3.1's Embedder.

Scope: unit, boundary, and error-path tests for query-time embedding
generation and its dimension-compatibility enforcement against the
approved Team 4A integration contract. Does NOT test HybridRetriever or
search-mode routing (Task 3.2).

IMPORTANT LIMITATION, documented rather than worked around: none of
these tests download or run the real all-MiniLM-L6-v2 model. This
sandbox's network allowlist does not include huggingface.co (only
pypi.org/files.pythonhosted.org and a handful of other package/code
registries), so a real `SentenceTransformer(...)` load is not reachable
here regardless of whether the `sentence-transformers` package itself is
installed. Every test therefore injects a fake implementing
`EmbeddingModelProtocol` -- the same dependency-injection pattern already
used for `VectorStoreManager`'s Qdrant client (Task 2.1) -- to exercise
`Embedder`'s own logic (lazy loading, dimension verification, query
embedding) without a live model. `RealEmbeddingModel`'s actual
`SentenceTransformer` integration is therefore verified only by
inspection/type-checking here, not by execution -- flagged explicitly in
the Task 3.1 report rather than presented as tested.
"""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from app.core.config import Settings
from app.services.embedder import (
    Embedder,
    EmbeddingModelDimensionMismatchError,
    EmbeddingModelProtocol,
)


class FakeEmbeddingModel:
    """A minimal EmbeddingModelProtocol implementation for tests.

    Returns deterministic, fixed-dimension vectors (one float per input
    character-count, scaled) so tests can assert on shape/values without
    any real model math -- the point of these tests is Embedder's own
    control flow (lazy loading, dimension check, call shape), not
    embedding quality.
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self.encode_calls: list[list[str]] = []
        self.dimension_check_calls = 0

    def encode(self, sentences: Sequence[str], **kwargs: Any) -> Any:
        self.encode_calls.append(list(sentences))
        return [[float(i) for i in range(self.dimension)] for _ in sentences]

    def get_sentence_embedding_dimension(self) -> int | None:
        self.dimension_check_calls += 1
        return self.dimension


class FakeEmbeddingModelWithUnknownDimension:
    """Simulates a model that can't report its own dimension ahead of
    encoding (get_sentence_embedding_dimension() -> None), which real
    sentence-transformers models can do before the underlying model is
    fully resolved."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def encode(self, sentences: Sequence[str], **kwargs: Any) -> Any:
        return [[0.0] * self.dimension for _ in sentences]

    def get_sentence_embedding_dimension(self) -> int | None:
        return None


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


class TestEmbedderConfiguration:
    def test_uses_configured_model_name_default(self):
        settings = _settings()
        assert settings.embedding_model_name == "all-MiniLM-L6-v2"

    def test_uses_configured_dimension_default(self):
        settings = _settings()
        assert settings.embedding_dimensions == 384

    def test_model_name_and_dimension_are_overridable(self):
        settings = _settings(embedding_model_name="all-mpnet-base-v2", embedding_dimensions=768)
        model = FakeEmbeddingModel(dimension=768)
        embedder = Embedder(settings=settings, model=model)

        vector = embedder.embed_query("test query")

        assert len(vector) == 768


class TestEmbedderLazyLoading:
    def test_constructing_embedder_does_not_touch_the_model(self):
        model = FakeEmbeddingModel(dimension=384)
        Embedder(settings=_settings(), model=model)

        assert model.encode_calls == []
        assert model.dimension_check_calls == 0

    def test_dimension_is_verified_only_once_across_multiple_queries(self):
        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(), model=model)

        embedder.embed_query("first")
        embedder.embed_query("second")
        embedder.embed_query("third")

        assert model.dimension_check_calls == 1  # checked once, not per call


class TestEmbedQuery:
    def test_returns_vector_of_configured_dimension(self):
        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(), model=model)

        vector = embedder.embed_query("what is retrieval augmented generation")

        assert len(vector) == 384
        assert all(isinstance(component, float) for component in vector)

    def test_passes_query_text_through_to_model(self):
        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(), model=model)

        embedder.embed_query("hello world")

        assert model.encode_calls == [["hello world"]]

    def test_empty_query_string_is_still_embedded(self):
        # Embedding an empty string is a valid (if degenerate) query --
        # Embedder does not special-case or reject it; that's a decision
        # for whatever validates QueryRequest.query at the API layer
        # (Task 1.2/8.1), not this component.
        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(), model=model)

        vector = embedder.embed_query("")

        assert len(vector) == 384


class TestEmbedQueries:
    def test_embeds_multiple_queries_in_one_model_call(self):
        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(), model=model)

        vectors = embedder.embed_queries(["first query", "second query"])

        assert len(vectors) == 2
        assert all(len(vector) == 384 for vector in vectors)
        assert len(model.encode_calls) == 1  # one batched call, not two separate ones

    def test_empty_list_returns_empty_list_without_touching_model(self):
        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(), model=model)

        vectors = embedder.embed_queries([])

        assert vectors == []
        assert model.encode_calls == []
        assert model.dimension_check_calls == 0


class TestDimensionMismatchEnforcement:
    def test_matching_dimension_does_not_raise(self):
        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(embedding_dimensions=384), model=model)

        embedder.embed_query("fine")  # should not raise

    def test_mismatched_dimension_raises_before_returning_a_vector(self):
        model = FakeEmbeddingModel(dimension=768)  # model produces 768-dim
        embedder = Embedder(settings=_settings(embedding_dimensions=384), model=model)  # but 384 is expected

        with pytest.raises(EmbeddingModelDimensionMismatchError):
            embedder.embed_query("this should fail before touching the vector")

    def test_mismatch_error_message_names_both_dimensions(self):
        model = FakeEmbeddingModel(dimension=768)
        embedder = Embedder(
            settings=_settings(embedding_dimensions=384, embedding_model_name="some-other-model"), model=model
        )

        with pytest.raises(EmbeddingModelDimensionMismatchError) as exc_info:
            embedder.embed_query("query")

        message = str(exc_info.value)
        assert "384" in message
        assert "768" in message
        assert "some-other-model" in message

    def test_embed_queries_also_enforces_dimension_check(self):
        model = FakeEmbeddingModel(dimension=768)
        embedder = Embedder(settings=_settings(embedding_dimensions=384), model=model)

        with pytest.raises(EmbeddingModelDimensionMismatchError):
            embedder.embed_queries(["a", "b"])

    def test_model_unable_to_report_dimension_ahead_of_time_is_not_treated_as_a_mismatch(self):
        # get_sentence_embedding_dimension() -> None means "unknown", not
        # "zero" -- must not be misinterpreted as a mismatch against a
        # nonzero configured dimension.
        model = FakeEmbeddingModelWithUnknownDimension(dimension=384)
        embedder = Embedder(settings=_settings(embedding_dimensions=384), model=model)

        vector = embedder.embed_query("fine")  # should not raise

        assert len(vector) == 384

    def test_default_settings_and_default_model_dimension_agree(self):
        """Sanity check on the approved integration default itself: a
        model reporting exactly 384 dimensions (matching Team 4A's
        verified all-MiniLM-L6-v2 output) must be accepted under
        Settings' own default embedding_dimensions=384 with no
        overrides at all.
        """

        model = FakeEmbeddingModel(dimension=384)
        embedder = Embedder(settings=_settings(), model=model)  # no overrides -- pure defaults

        embedder.embed_query("fine")  # should not raise


class TestRealEmbeddingModelIsLazyAndTypeCompatible:
    """RealEmbeddingModel's actual sentence-transformers integration
    cannot be executed in this environment (see module docstring), but
    its lazy-construction contract and protocol compatibility can still
    be verified without ever downloading model weights.
    """

    def test_constructing_real_embedding_model_does_not_import_sentence_transformers_eagerly(self):
        from app.services.embedder import RealEmbeddingModel

        # If this imported sentence_transformers (and tried to resolve a
        # model) at construction time rather than lazily inside
        # _ensure_model(), this call itself would attempt a network
        # request and fail/hang in this sandbox. Succeeding here is
        # itself the assertion.
        model = RealEmbeddingModel("all-MiniLM-L6-v2")
        assert model._model is None  # not loaded yet

    def test_real_embedding_model_satisfies_the_protocol_shape(self):
        from app.services.embedder import RealEmbeddingModel

        model: EmbeddingModelProtocol = RealEmbeddingModel("all-MiniLM-L6-v2")
        assert hasattr(model, "encode")
        assert hasattr(model, "get_sentence_embedding_dimension")
