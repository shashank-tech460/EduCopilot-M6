"""Task 7.2: Optional property-based tests for the Embedder (Properties 16-19).

Covers exactly the four official correctness properties assigned to Task
7.2, using their real names and numbering as verified directly against
the official specification document:

    Property 16: Embedding dimensionality invariant (Requirement 5.2)
    Property 17: Embedding batch correctness (Requirement 5.3)
    Property 18: Embedding L2 normalization (Requirement 5.5)
    Property 19: Embedding truncation for oversized input (Requirement 5.4)

IMPORTANT CORRECTION MADE DURING THIS TASK 7.2 AUDIT: this file previously
had Properties 17 and 18 swapped throughout its section headers, module
docstring, and test function names -- the batch-correctness tests were
labeled "Property 18" and the L2-normalization tests were labeled
"Property 17", backwards from the official document (confirmed directly:
"Property 17: Embedding batch correctness ... Validates: Requirements
5.3" and "Property 18: Embedding L2 normalization ... Validates:
Requirements 5.5"). The test *content* itself was already correct and
thorough for both concepts -- only the numbering/labeling was wrong, and
has been corrected throughout this file (function names, section
headers, this docstring). No test logic or assertion was changed.

These tests exercise the real, approved Task 7.1 `Embedder` through its
public `embed()` method, using the same behaviorally-realistic
`FakeEmbeddingModel` test double already established in
`tests/test_embedder.py` (imported from there, not duplicated) -- it
genuinely batches, genuinely L2-normalizes, and genuinely truncates
oversized input by word count against a configurable `max_seq_length`,
so these tests verify real behavior rather than mocked call assertions.

Per Task 7.2's explicit instruction, Property 17 (batch correctness) does
NOT require `Embedder` to contain a manual batching loop -- it verifies
the PUBLIC contract (order preserved, correct count, configured batch
size reaches the model, batch output matches individual-input output)
against the approved delegate-to-the-model architecture.

No network access, no real model download, no Qdrant/publisher/API/
orchestration code. No production code was changed to write these tests.
"""

from __future__ import annotations

import math
import string

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from app.config.settings import Settings
from app.models.exceptions import EmbeddingDimensionMismatchError
from app.pipeline.embedder import Embedder
from tests.test_embedder import FakeEmbeddingModel

# ---------------------------------------------------------------------------
# Shared generation strategies
# ---------------------------------------------------------------------------

_text_strategy = st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=40).filter(
    lambda s: s.strip() != ""
)
_texts_strategy = st.lists(_text_strategy, min_size=0, max_size=15)


# ---------------------------------------------------------------------------
# Property 16: Embedding Dimension
# ---------------------------------------------------------------------------


@given(texts=st.lists(_text_strategy, min_size=1, max_size=15))
@hyp_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_16_default_dimension_384_for_every_embedding(texts):
    embedder = Embedder(model=FakeEmbeddingModel(dimension=384))

    embeddings = embedder.embed(texts)

    assert len(embeddings) == len(texts)
    for embedding in embeddings:
        assert len(embedding) == 384


@given(
    texts=st.lists(_text_strategy, min_size=1, max_size=12),
    dimension=st.sampled_from([64, 128, 256, 512, 768, 1024]),
)
@hyp_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_16_configured_alternate_dimension_is_honored(texts, dimension):
    """When Settings and the injected model agree on a non-default
    dimension, every embedding must have exactly that dimension -- the
    property must verify actual *configuration*, not a hardcoded 384.
    """

    settings = Settings(embedding_dimensions=dimension, _env_file=None)
    embedder = Embedder(settings=settings, model=FakeEmbeddingModel(dimension=dimension))

    embeddings = embedder.embed(texts)

    assert len(embeddings) == len(texts)
    for embedding in embeddings:
        assert len(embedding) == dimension


def test_property_16_single_input_has_configured_dimension():
    embedder = Embedder(model=FakeEmbeddingModel(dimension=384))
    embeddings = embedder.embed(["a single input"])
    assert len(embeddings) == 1
    assert len(embeddings[0]) == 384


def test_property_16_empty_input_produces_empty_output():
    embedder = Embedder(model=FakeEmbeddingModel(dimension=384))
    assert embedder.embed([]) == []


@given(
    configured_dimension=st.sampled_from([384]),
    actual_model_dimension=st.sampled_from([128, 256, 512, 768]),
)
@hyp_settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_16_mismatched_model_dimension_is_never_silently_accepted(
    configured_dimension, actual_model_dimension
):
    """A model whose real dimension disagrees with the configured
    `embedding_dimensions` must always be caught -- for any generated
    mismatch, not just the one example already in test_embedder.py.
    """

    settings = Settings(embedding_dimensions=configured_dimension, _env_file=None)
    embedder = Embedder(settings=settings, model=FakeEmbeddingModel(dimension=actual_model_dimension))

    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        embedder.embed(["some text"])

    assert exc_info.value.detail == {"expected": configured_dimension, "actual": actual_model_dimension}


@given(dimension=st.sampled_from([384, 128, 768]))
@hyp_settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_16_matching_dimension_never_raises(dimension):
    settings = Settings(embedding_dimensions=dimension, _env_file=None)
    embedder = Embedder(settings=settings, model=FakeEmbeddingModel(dimension=dimension))

    embeddings = embedder.embed(["consistent dimension text"])

    assert len(embeddings[0]) == dimension


# ---------------------------------------------------------------------------
# Property 18: L2 Normalization
# ---------------------------------------------------------------------------


@given(texts=st.lists(_text_strategy, min_size=1, max_size=20))
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_18_every_embedding_has_unit_l2_norm(texts):
    embedder = Embedder(model=FakeEmbeddingModel(dimension=384))

    embeddings = embedder.embed(texts)

    for embedding in embeddings:
        norm = math.sqrt(sum(component * component for component in embedding))
        # Explicit tolerance-based comparison -- never exact equality on
        # a floating-point norm.
        assert abs(norm - 1.0) <= 1e-5


@given(texts=st.lists(_text_strategy, min_size=40, max_size=90))
@hyp_settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_18_normalization_holds_independently_across_multiple_batches(texts):
    """With enough inputs to span several batches, every embedding --
    regardless of which batch it fell into -- must still be independently
    normalized.
    """

    settings = Settings(embedding_batch_size=10, _env_file=None)
    model = FakeEmbeddingModel(dimension=384)
    embedder = Embedder(settings=settings, model=model)

    embeddings = embedder.embed(texts)

    assert len(model.batch_sizes_seen) > 1  # genuinely spans multiple batches
    for embedding in embeddings:
        norm = math.sqrt(sum(c * c for c in embedding))
        assert abs(norm - 1.0) <= 1e-5


@given(text_a=_text_strategy, text_b=_text_strategy)
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_18_normalization_is_per_embedding_not_shared(text_a, text_b):
    """Confirms normalization is computed independently per vector (not,
    e.g., against a batch-wide norm) by checking two different inputs
    both land on the unit sphere regardless of their relationship.
    """

    embedder = Embedder(model=FakeEmbeddingModel(dimension=384))

    embeddings = embedder.embed([text_a, text_b])

    for embedding in embeddings:
        norm = math.sqrt(sum(c * c for c in embedding))
        assert abs(norm - 1.0) <= 1e-5


# ---------------------------------------------------------------------------
# Property 17: Batch Processing / Batch Correctness
# ---------------------------------------------------------------------------


@given(
    num_inputs=st.integers(min_value=0, max_value=60),
    batch_size=st.integers(min_value=1, max_value=15),
)
@hyp_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_17_batch_size_respected_order_and_count_preserved(num_inputs, batch_size):
    """Covers zero/one/fewer-than/exactly/more-than batch_size, and
    multiple-batches-with-final-partial-batch, all via generated
    (num_inputs, batch_size) pairs rather than a handful of fixed examples.
    """

    settings = Settings(embedding_batch_size=batch_size, _env_file=None)
    model = FakeEmbeddingModel(dimension=384)
    embedder = Embedder(settings=settings, model=model)

    texts = [f"unique-text-{i}" for i in range(num_inputs)]
    embeddings = embedder.embed(texts)

    # No inputs dropped or duplicated.
    assert len(embeddings) == num_inputs

    if num_inputs == 0:
        assert model.batch_sizes_seen == []
        return

    # The configured batch size genuinely reached the model: every batch
    # except possibly the last is exactly `batch_size`, and the total
    # across all batches equals the input count (Task 7.2's explicit
    # "verify batch_size=N reaches the model" framing, checked via
    # observed behavior rather than a call-argument assertion alone).
    assert sum(model.batch_sizes_seen) == num_inputs
    for size in model.batch_sizes_seen[:-1]:
        assert size == batch_size
    assert 1 <= model.batch_sizes_seen[-1] <= batch_size

    # Ordering: re-embedding each text alone must reproduce the same
    # vector at the same position, proving output[i] genuinely
    # corresponds to input[i] and was not shuffled between batches.
    for i, text in enumerate(texts):
        assert embeddings[i] == embedder.embed([text])[0]


@given(batch_size=st.integers(min_value=1, max_value=20))
@hyp_settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_17_exact_batch_size_input_produces_single_full_batch(batch_size):
    settings = Settings(embedding_batch_size=batch_size, _env_file=None)
    model = FakeEmbeddingModel(dimension=384)
    embedder = Embedder(settings=settings, model=model)

    texts = [f"text-{i}" for i in range(batch_size)]
    embeddings = embedder.embed(texts)

    assert len(embeddings) == batch_size
    assert model.batch_sizes_seen == [batch_size]


@given(batch_size=st.integers(min_value=2, max_value=20))
@hyp_settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_17_input_smaller_than_batch_size_produces_one_partial_batch(batch_size):
    settings = Settings(embedding_batch_size=batch_size, _env_file=None)
    model = FakeEmbeddingModel(dimension=384)
    embedder = Embedder(settings=settings, model=model)

    texts = ["only one text"]
    embeddings = embedder.embed(texts)

    assert len(embeddings) == 1
    assert model.batch_sizes_seen == [1]


def test_property_17_zero_inputs_never_reach_the_model():
    model = FakeEmbeddingModel(dimension=384)
    embedder = Embedder(model=model)

    assert embedder.embed([]) == []
    assert model.encode_call_count == 0
    assert model.batch_sizes_seen == []


@given(num_full_batches=st.integers(min_value=2, max_value=5), batch_size=st.integers(min_value=1, max_value=10))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_17_multiple_complete_batches_with_no_remainder(num_full_batches, batch_size):
    settings = Settings(embedding_batch_size=batch_size, _env_file=None)
    model = FakeEmbeddingModel(dimension=384)
    embedder = Embedder(settings=settings, model=model)

    total = num_full_batches * batch_size
    texts = [f"t{i}" for i in range(total)]
    embeddings = embedder.embed(texts)

    assert len(embeddings) == total
    assert model.batch_sizes_seen == [batch_size] * num_full_batches


@given(num_inputs=st.integers(min_value=20, max_value=45))
@hyp_settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_17_real_default_batch_size_32_boundary_cases(num_inputs):
    """Exercises the *actual configured official default* batch size (32),
    not just arbitrary small Hypothesis-generated sizes -- Task 7.2
    explicitly calls for generated cases around N < 32, N = 32, and
    N > 32 relative to the real default, which the other Property 17
    tests (all using generated small batch sizes) do not directly cover.
    """

    embedder = Embedder(model=FakeEmbeddingModel(dimension=384))  # real default settings: batch_size=32
    assert embedder._settings.embedding_batch_size == 32

    texts = [f"default-batch-text-{i}" for i in range(num_inputs)]
    embeddings = embedder.embed(texts)

    assert len(embeddings) == num_inputs
    for i, text in enumerate(texts):
        assert embeddings[i] == embedder.embed([text])[0]


# ---------------------------------------------------------------------------
# Property 19: Oversized Text Handling
# ---------------------------------------------------------------------------


@given(
    word_count=st.integers(min_value=200, max_value=2000),
    max_seq_length=st.integers(min_value=5, max_value=50),
)
@hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_19_oversized_input_produces_exactly_one_valid_embedding(word_count, max_seq_length):
    model = FakeEmbeddingModel(dimension=384, max_seq_length=max_seq_length)
    embedder = Embedder(model=model)

    oversized_text = " ".join(f"word{i}" for i in range(word_count))

    embeddings = embedder.embed([oversized_text])

    assert len(embeddings) == 1  # operation did not fail, exactly one output
    assert len(embeddings[0]) == 384  # correct dimension
    norm = math.sqrt(sum(c * c for c in embeddings[0]))
    assert abs(norm - 1.0) <= 1e-5  # still normalized


@given(
    normal_text=_text_strategy,
    word_count=st.integers(min_value=300, max_value=1500),
    max_seq_length=st.integers(min_value=5, max_value=30),
)
@hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_19_oversized_input_mixed_with_normal_input_both_succeed(normal_text, word_count, max_seq_length):
    model = FakeEmbeddingModel(dimension=384, max_seq_length=max_seq_length)
    embedder = Embedder(model=model)

    oversized_text = " ".join(f"tok{i}" for i in range(word_count))
    texts = [normal_text, oversized_text]

    embeddings = embedder.embed(texts)

    assert len(embeddings) == 2  # input/output count remains aligned
    for embedding in embeddings:
        assert len(embedding) == 384
        norm = math.sqrt(sum(c * c for c in embedding))
        assert abs(norm - 1.0) <= 1e-5


@given(max_seq_length=st.integers(min_value=10, max_value=100), short_word_count=st.integers(min_value=1, max_value=8))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_19_normal_sized_input_is_not_unnecessarily_truncated(max_seq_length, short_word_count):
    """A text well under max_seq_length must be embedded identically to
    itself, independent of any truncation logic being present -- proving
    truncation is a no-op path for normal-sized input, not something
    applied unconditionally.
    """

    model = FakeEmbeddingModel(dimension=384, max_seq_length=max_seq_length)
    embedder = Embedder(model=model)

    short_text = " ".join(f"w{i}" for i in range(short_word_count))
    assert short_word_count <= max_seq_length  # genuinely "normal-sized" relative to this model

    vector_via_embed = embedder.embed([short_text])[0]
    vector_direct_no_truncation_path = model._embed_one(short_text, normalize=True)

    assert vector_via_embed == vector_direct_no_truncation_path


@given(word_count=st.integers(min_value=100, max_value=800))
@hyp_settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_19_oversized_input_does_not_affect_other_inputs_in_the_same_batch(word_count):
    """One oversized input must not corrupt or drop the embeddings of the
    other, normal-sized inputs sharing its batch.
    """

    settings = Settings(embedding_batch_size=5, _env_file=None)
    model = FakeEmbeddingModel(dimension=384, max_seq_length=15)
    embedder = Embedder(settings=settings, model=model)

    oversized = " ".join(f"big{i}" for i in range(word_count))
    texts = ["normal one", "normal two", oversized, "normal three", "normal four"]

    embeddings = embedder.embed(texts)

    assert len(embeddings) == 5
    for embedding in embeddings:
        assert len(embedding) == 384
        norm = math.sqrt(sum(c * c for c in embedding))
        assert abs(norm - 1.0) <= 1e-5

    # The normal-sized entries' embeddings are unaffected by their
    # oversized neighbor -- each still matches its own solo embedding.
    for i, text in enumerate(texts):
        if text != oversized:
            assert embeddings[i] == embedder.embed([text])[0]
