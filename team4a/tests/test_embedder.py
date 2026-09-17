"""Unit tests for Task 7.1: Embedder.

No network access, no real model download: `FakeEmbeddingModel` implements
the same `EmbeddingModel` protocol as the real `SentenceTransformerModel`,
so these tests exercise Embedder's real control flow -- batching
forwarding, ordering, dimension validation, output conversion -- against
a realistic (not trivial) fake rather than only asserting a mocked method
was called.
"""

from __future__ import annotations

import math

import pytest

from app.config.settings import Settings, get_settings
from app.models.exceptions import EmbeddingDimensionMismatchError
from app.pipeline.embedder import Embedder, SentenceTransformerModel


class FakeEmbeddingModel:
    def __init__(self, dimension: int = 384, max_seq_length: int = 20) -> None:
        self.dimension = dimension
        self.max_seq_length = max_seq_length
        self.batch_sizes_seen: list[int] = []
        self.encode_call_count = 0

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts, batch_size, normalize_embeddings, convert_to_numpy):
        self.encode_call_count += 1
        texts = list(texts)
        results: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            self.batch_sizes_seen.append(len(batch))
            for text in batch:
                results.append(self._embed_one(text, normalize_embeddings))
        return results

    def _embed_one(self, text, normalize):
        truncated = " ".join(text.split()[: self.max_seq_length])
        seed = sum(ord(c) for c in truncated) or 1
        vector = [((seed * (i + 1)) % 97) / 97.0 + 0.01 for i in range(self.dimension)]
        if normalize:
            norm = math.sqrt(sum(c * c for c in vector))
            if norm > 0:
                vector = [c / norm for c in vector]
        return vector


def make_embedder(model=None, settings=None):
    return Embedder(settings=settings, model=model or FakeEmbeddingModel())


def test_default_settings_match_official_requirement():
    settings = get_settings()
    assert settings.embedding_model_name == "all-MiniLM-L6-v2"
    assert settings.embedding_batch_size == 32
    assert settings.embedding_dimensions == 384
    assert settings.embedding_device == "cpu"


def test_embedder_uses_default_settings_when_none_provided():
    embedder = Embedder()
    assert embedder._settings.embedding_model_name == "all-MiniLM-L6-v2"
    assert embedder._settings.embedding_batch_size == 32
    assert embedder._settings.embedding_dimensions == 384
    assert embedder._settings.embedding_device == "cpu"


def test_embedder_uses_default_real_model_type_when_not_injected():
    embedder = Embedder()
    assert isinstance(embedder._model, SentenceTransformerModel)
    assert embedder._model._model_name == "all-MiniLM-L6-v2"
    assert embedder._model._device == "cpu"


def test_custom_settings_are_respected():
    settings = Settings(
        embedding_model_name="some-other-model",
        embedding_batch_size=8,
        embedding_dimensions=768,
        embedding_device="cuda",
        _env_file=None,
    )
    embedder = Embedder(settings=settings)
    assert embedder._settings.embedding_model_name == "some-other-model"
    assert embedder._settings.embedding_batch_size == 8
    assert embedder._settings.embedding_dimensions == 768
    assert embedder._settings.embedding_device == "cuda"
    assert embedder._model._model_name == "some-other-model"
    assert embedder._model._device == "cuda"


def test_custom_model_can_be_injected():
    fake = FakeEmbeddingModel(dimension=384)
    embedder = Embedder(model=fake)
    assert embedder._model is fake


def test_correct_number_of_embeddings_returned():
    embedder = make_embedder()
    texts = ["one", "two", "three", "four", "five"]
    vectors = embedder.embed(texts)
    assert len(vectors) == len(texts)


def test_input_ordering_is_preserved():
    model = FakeEmbeddingModel()
    embedder = make_embedder(model=model)
    texts = ["alpha", "bravo", "charlie", "delta"]
    vectors = embedder.embed(texts)
    for i, text in enumerate(texts):
        solo_vector = embedder.embed([text])[0]
        assert vectors[i] == solo_vector


def test_default_dimension_is_384():
    embedder = make_embedder(model=FakeEmbeddingModel(dimension=384))
    vectors = embedder.embed(["hello world"])
    assert len(vectors[0]) == 384


def test_dimension_mismatch_raises_clear_error():
    mismatched_model = FakeEmbeddingModel(dimension=768)
    embedder = make_embedder(model=mismatched_model)
    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        embedder.embed(["hello"])
    assert exc_info.value.status_code == "EmbeddingDimensionMismatch"
    assert exc_info.value.detail == {"expected": 384, "actual": 768}


def test_dimension_check_only_happens_once():
    model = FakeEmbeddingModel(dimension=384)
    embedder = make_embedder(model=model)
    embedder.embed(["first"])
    embedder.embed(["second"])
    embedder.embed(["third"])
    assert embedder._dimension_checked is True


def test_configured_batch_size_is_respected():
    settings = Settings(embedding_batch_size=3, _env_file=None)
    model = FakeEmbeddingModel()
    embedder = make_embedder(model=model, settings=settings)
    embedder.embed([f"text {i}" for i in range(10)])
    assert model.batch_sizes_seen == [3, 3, 3, 1]


def test_default_batch_size_32_used_when_not_overridden():
    model = FakeEmbeddingModel()
    embedder = make_embedder(model=model)
    embedder.embed([f"text {i}" for i in range(70)])
    assert model.batch_sizes_seen == [32, 32, 6]


def test_final_partial_batch_is_processed_correctly():
    settings = Settings(embedding_batch_size=5, _env_file=None)
    model = FakeEmbeddingModel()
    embedder = make_embedder(model=model, settings=settings)
    texts = [f"text {i}" for i in range(12)]
    vectors = embedder.embed(texts)
    assert model.batch_sizes_seen == [5, 5, 2]
    assert len(vectors) == 12


def test_exactly_batch_size_inputs():
    settings = Settings(embedding_batch_size=4, _env_file=None)
    model = FakeEmbeddingModel()
    embedder = make_embedder(model=model, settings=settings)
    vectors = embedder.embed(["a", "b", "c", "d"])
    assert model.batch_sizes_seen == [4]
    assert len(vectors) == 4


def test_single_input_below_batch_size():
    embedder = make_embedder()
    vectors = embedder.embed(["only one"])
    assert len(vectors) == 1


def test_no_inputs_dropped_or_duplicated_across_multiple_batches():
    settings = Settings(embedding_batch_size=7, _env_file=None)
    model = FakeEmbeddingModel()
    embedder = make_embedder(model=model, settings=settings)
    texts = [f"unique-text-{i}" for i in range(23)]
    vectors = embedder.embed(texts)
    assert len(vectors) == len(texts)
    assert sum(model.batch_sizes_seen) == len(texts)


def test_empty_input_returns_empty_output():
    embedder = make_embedder()
    assert embedder.embed([]) == []


def test_empty_input_does_not_call_the_model():
    model = FakeEmbeddingModel()
    embedder = make_embedder(model=model)
    embedder.embed([])
    assert model.encode_call_count == 0


def test_l2_normalization_is_applied():
    embedder = make_embedder()
    vectors = embedder.embed(["hello world", "a different sentence here"])
    for vector in vectors:
        norm = math.sqrt(sum(c * c for c in vector))
        assert norm == pytest.approx(1.0, abs=1e-9)


def test_normalize_embeddings_flag_passed_to_model():
    class RecordingModel(FakeEmbeddingModel):
        def encode(self, texts, batch_size, normalize_embeddings, convert_to_numpy):
            self.last_normalize_embeddings = normalize_embeddings
            self.last_convert_to_numpy = convert_to_numpy
            return super().encode(texts, batch_size, normalize_embeddings, convert_to_numpy)

    model = RecordingModel()
    embedder = make_embedder(model=model)
    embedder.embed(["hello"])
    assert model.last_normalize_embeddings is True
    assert model.last_convert_to_numpy is True


def test_oversized_input_does_not_crash_and_produces_an_embedding():
    model = FakeEmbeddingModel(max_seq_length=10)
    embedder = make_embedder(model=model)
    oversized_text = " ".join(f"word{i}" for i in range(500))
    vectors = embedder.embed([oversized_text])
    assert len(vectors) == 1
    assert len(vectors[0]) == model.dimension


def test_oversized_input_mixed_with_normal_inputs_all_produce_embeddings():
    model = FakeEmbeddingModel(max_seq_length=10)
    embedder = make_embedder(model=model)
    texts = [
        "a short normal sentence",
        " ".join(f"word{i}" for i in range(1000)),
        "another short one",
    ]
    vectors = embedder.embed(texts)
    assert len(vectors) == 3
    for vector in vectors:
        assert len(vector) == model.dimension


def test_normal_sized_inputs_unaffected_by_truncation_logic():
    model = FakeEmbeddingModel(max_seq_length=50)
    embedder = make_embedder(model=model)
    short_text = "just a few words here"
    vector_via_embed = embedder.embed([short_text])[0]
    vector_direct = model._embed_one(short_text, normalize=True)
    assert vector_via_embed == vector_direct


def test_oversized_input_still_normalized_and_correct_dimension():
    model = FakeEmbeddingModel(dimension=384, max_seq_length=5)
    embedder = make_embedder(model=model)
    oversized_text = " ".join(f"tok{i}" for i in range(2000))
    vector = embedder.embed([oversized_text])[0]
    assert len(vector) == 384
    norm = math.sqrt(sum(c * c for c in vector))
    assert norm == pytest.approx(1.0, abs=1e-9)


def test_sentence_transformer_model_does_not_load_on_construction():
    model = SentenceTransformerModel(model_name="all-MiniLM-L6-v2", device="cpu")
    assert model._model is None


def test_embedder_construction_does_not_load_the_real_model():
    embedder = Embedder()
    assert embedder._model._model is None


def test_output_is_plain_json_serializable_floats():
    import json

    embedder = make_embedder()
    vectors = embedder.embed(["hello", "world"])
    assert isinstance(vectors, list)
    for vector in vectors:
        assert isinstance(vector, list)
        for component in vector:
            assert isinstance(component, float)
    json.dumps(vectors)


def test_output_is_not_numpy_arrays():
    embedder = make_embedder()
    vectors = embedder.embed(["hello"])
    assert type(vectors) is list
    assert type(vectors[0]) is list
