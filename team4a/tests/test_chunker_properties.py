"""Task 6.2: Optional property-based tests for the Chunker (Properties 12-15).

Covers exactly the four official correctness properties assigned to Task
6.2, using their real names and wording as verified directly against the
official specification document (Properties section):

    Property 12: Chunking size and overlap invariants (Requirements 4.1, 4.4)
    Property 13: Sentence boundary preservation (Requirement 4.2)
    Property 14: Uniform chunk output format (Requirement 4.3)
    Property 15: Text normalization idempotence (Requirement 4.5)

IMPORTANT CORRECTION MADE DURING THIS TASK 6.2 AUDIT: this file previously
had a section literally titled "Property 14: Short Text Handling" -- that
is not the official Property 14. The official Property 14 is "Uniform
chunk output format": "the Chunker output SHALL contain exactly three
fields: text (non-empty string), chunk_index (integer >= 0), and
total_chunks (positive integer where chunk_index < total_chunks)"
(Validates: Requirement 4.3). "Short text handling" is Requirement 4.4,
which the real Property 12 already validates alongside 4.1 -- the
mislabeled section's tests are still valid and useful, so they were kept
and simply retitled as part of Property 12 rather than being deleted; a
genuine, dedicated Property 14 test section was added (see the bottom of
this file) to actually cover the real Property 14, which previously had
no Hypothesis-based coverage at all -- only two fixed-example tests in
tests/test_chunker.py (`test_output_uses_existing_chunk_model_with_exactly_three_fields`,
`test_identical_output_format_regardless_of_hypothetical_source`).

NOTE ON FIELD NAMES: the real Chunk model (Task 1.2) and the official
Property 14 text both use `text`, `chunk_index`, `total_chunks` -- not
"token_count"/"position", which do not appear anywhere in the official
specification. Some delegated task instructions have used that
terminology; it is not used here, per this task's own instruction that
the official specification (not a paraphrase of it) is the source of
truth. See the Task 6.2 report for the full analysis.

These tests exercise the real `Chunker` (the Task 1.2 `Chunk` model, the
Task 1.1 `Settings`, and the corrected Task 6.1 `_assemble_chunk_texts`
budget-based overlap logic) via its public `chunk()` method wherever
possible. `Chunker._normalize()` is called directly only where the
specification property is explicitly about normalization's own behavior
(idempotence) and cannot be verified through `chunk()` alone.

No network, Redis, Docker, FFmpeg, Whisper, Qdrant, or other external
services are used anywhere in this file.

No production code was changed to write these tests -- see the Task 6.2
report for the reasoning behind every assertion, in particular how
Property 12/13's tests correctly distinguish the corrected implementation
from the original chunk_size+overlap bug while still tolerating the
documented oversized-single-sentence exception.
"""

from __future__ import annotations

import string
import unicodedata
from types import SimpleNamespace

from hypothesis import HealthCheck, assume, given, settings as hyp_settings
from hypothesis import strategies as st

from app.pipeline.chunker import Chunker

# ---------------------------------------------------------------------------
# Shared generation strategies
# ---------------------------------------------------------------------------

_WORD_ALPHABET = string.ascii_lowercase
_TERMINAL_PUNCTUATION = ".!?"

_word_strategy = st.text(alphabet=_WORD_ALPHABET, min_size=1, max_size=8)


@st.composite
def _sentence(draw, min_words: int = 1, max_words: int = 8):
    """A generated "sentence": a run of lowercase words ending in . ! or ?

    Deliberately synthetic (not real language) so the generated text's
    sentence count and word count are exactly known and controllable,
    while still genuinely exercising the real `_split_sentences` regex
    (which only cares about terminal punctuation, not real grammar).
    """

    words = draw(st.lists(_word_strategy, min_size=min_words, max_size=max_words))
    punctuation = draw(st.sampled_from(_TERMINAL_PUNCTUATION))
    return " ".join(words) + punctuation


@st.composite
def _sentences(draw, min_sentences: int = 3, max_sentences: int = 15, min_words: int = 1, max_words: int = 8):
    return draw(
        st.lists(_sentence(min_words=min_words, max_words=max_words), min_size=min_sentences, max_size=max_sentences)
    )


@st.composite
def _chunk_config(draw, min_chunk_size: int = 5, max_chunk_size: int = 40):
    """A (chunk_size, overlap) pair with 0 <= overlap < chunk_size.

    Bounded to keep generated examples fast, per Task 6.2's explicit
    "practical and bounded" instruction. The pathological overlap >=
    chunk_size configuration is already covered by Task 6.1's existing
    example-based tests and is not re-covered here.
    """

    chunk_size = draw(st.integers(min_value=min_chunk_size, max_value=max_chunk_size))
    overlap = draw(st.integers(min_value=0, max_value=chunk_size - 1))
    return chunk_size, overlap


def _make_chunker(chunk_size: int, overlap: int) -> Chunker:
    return Chunker(settings=SimpleNamespace(chunk_size=chunk_size, chunk_overlap=overlap))


# ---------------------------------------------------------------------------
# Property 12: Chunk Size and Overlap
# ---------------------------------------------------------------------------


@given(sentences=_sentences(min_sentences=5, max_sentences=20), config=_chunk_config())
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_chunk_structure_invariants(sentences, config):
    """Basic structural invariants that must hold for ANY generated input:
    no empty chunks, sequential indices, consistent total_chunks.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)
    text = " ".join(sentences)

    chunks = chunker.chunk(text)

    assert len(chunks) >= 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.total_chunks == len(chunks)
        assert chunk.text != ""
        assert chunk.text.strip() != ""


@given(sentences=_sentences(min_sentences=8, max_sentences=25, min_words=1, max_words=4), config=_chunk_config())
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_overlap_does_not_add_on_top_of_chunk_size_budget(sentences, config):
    """The corrected Task 6.1 behavior, generalized over generated inputs:
    overlap must count INSIDE chunk_size, not be added on top of it.

    A chunk's token count may legitimately exceed `chunk_size` only when a
    single generated sentence's own token count is too large to fit in
    the budget available after subtracting overlap -- the documented
    Requirement 4.2 exception. This test derives a bound purely from the
    generated inputs (chunk_size, overlap, and the longest single
    generated sentence's token count), not from the implementation's
    internal algorithm, and that bound is only satisfiable by the
    corrected implementation:

        token_count(chunk) <= max(chunk_size, overlap + longest_sentence_tokens)

    Under the ORIGINAL (pre-correction) bug -- which appended a full
    `overlap` tokens on top of an already `chunk_size`-token group built
    from many small sentences -- a normal chunk could reach
    `chunk_size + overlap` tokens. For generated inputs where chunk_size
    exceeds any single sentence's length (the common case for the small
    synthetic sentences used here), `chunk_size + overlap` exceeds this
    bound and the test would correctly fail against the old bug.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)
    text = " ".join(sentences)

    longest_sentence_tokens = max(len(chunker._tokenize(s)) for s in sentences)
    bound = max(chunk_size, overlap + longest_sentence_tokens)

    chunks = chunker.chunk(text)

    for chunk in chunks:
        token_count = len(chunker._tokenize(chunk.text))
        assert token_count <= bound, (
            f"chunk {chunk.chunk_index} has {token_count} tokens, exceeding the bound {bound} "
            f"(chunk_size={chunk_size}, overlap={overlap}, longest_sentence_tokens={longest_sentence_tokens}) "
            "-- this is the exact shape of the original chunk_size+overlap bug."
        )


@given(sentences=_sentences(min_sentences=10, max_sentences=25, min_words=3, max_words=6), config=_chunk_config())
@hyp_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_normal_chunking_produces_multiple_chunks_when_content_exceeds_chunk_size(sentences, config):
    """Sanity check that this property suite actually exercises multi-chunk
    behavior (default 512/50 and smaller configured sizes alike), rather
    than only ever hitting the trivial single-chunk case.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)
    text = " ".join(sentences)

    total_tokens = len(chunker._tokenize(text))
    assume(total_tokens > chunk_size * 2)  # comfortably over the limit, not a borderline case

    chunks = chunker.chunk(text)

    assert len(chunks) > 1


def test_property_12_default_512_50_respects_the_budget_bound():
    """The real default configuration (512/50), not just small generated
    configs, must also satisfy the corrected budget invariant.
    """

    chunker = Chunker()  # real defaults: chunk_size=512, chunk_overlap=50
    text = " ".join(f"This is sentence number {i} in a reasonably long test document." for i in range(1, 300))

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    for chunk in chunks:
        token_count = len(chunker._tokenize(chunk.text))
        assert token_count <= 512


@given(overlap=st.integers(min_value=1, max_value=10))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_overlap_genuinely_preserved_when_sufficient_content_exists(overlap):
    """Where sufficient previous content exists, overlap must be genuinely
    present at the boundary between consecutive chunks -- the fix must
    not have accidentally removed overlap while removing the bug.

    Sentences are generated deliberately longer than `overlap` words each,
    guaranteeing "sufficient previous content" by construction rather than
    needing to infer it after the fact.
    """

    sentence_word_count = overlap + 4
    chunk_size = overlap + (sentence_word_count + 1) * 3
    chunker = _make_chunker(chunk_size, overlap)

    sentences = [" ".join(f"w{i}{j}" for j in range(sentence_word_count)) + "." for i in range(8)]
    text = " ".join(sentences)

    chunks = chunker.chunk(text)
    assume(len(chunks) >= 2)

    for i in range(len(chunks) - 1):
        tail = chunker._tokenize(chunks[i].text)[-overlap:]
        head = chunker._tokenize(chunks[i + 1].text)[:overlap]
        assert tail == head


@given(config=_chunk_config(min_chunk_size=3, max_chunk_size=20))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_overlap_zero_produces_no_shared_word_content(config):
    chunk_size, _overlap = config
    chunker = _make_chunker(chunk_size, overlap=0)

    sentences = [f"alpha{i} bravo{i} charlie{i} delta{i}." for i in range(6)]
    text = " ".join(sentences)

    chunks = chunker.chunk(text)
    assume(len(chunks) >= 2)

    for i in range(len(chunks) - 1):
        words_i = {t for t in chunker._tokenize(chunks[i].text) if t.isalnum()}
        words_next = {t for t in chunker._tokenize(chunks[i + 1].text) if t.isalnum()}
        assert words_i.isdisjoint(words_next)


@given(config=_chunk_config(min_chunk_size=3, max_chunk_size=8))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_oversized_sentence_exception_is_allowed_not_a_failure(config):
    """A sentence longer than chunk_size (and therefore longer than any
    possible post-overlap budget) must be kept whole -- explicitly
    allowed, not treated as a property violation.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)

    oversized_sentence = " ".join(f"word{i}" for i in range(chunk_size + 10)) + "."
    text = f"Short one. {oversized_sentence} Short two."

    chunks = chunker.chunk(text)

    assert any(oversized_sentence in chunk.text for chunk in chunks)
    for chunk in chunks:
        assert chunk.text.strip() != ""


# ---------------------------------------------------------------------------
# Property 13: Sentence Boundary Preservation
# ---------------------------------------------------------------------------


@given(sentences=_sentences(min_sentences=6, max_sentences=20), config=_chunk_config(min_chunk_size=4))
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_13_chunks_end_at_a_sentence_boundary(sentences, config):
    """Every chunk's own content ends at the end of a complete sentence
    (the chunk's *own* new content always consists of whole sentences --
    the corrected implementation never splits a sentence to fit a
    boundary). Overlap, which can legitimately start mid-sentence
    (documented in Task 6.1), affects only where a chunk's text *begins*,
    never where it *ends*.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)
    text = " ".join(sentences)

    chunks = chunker.chunk(text)

    for chunk in chunks:
        assert chunk.text.rstrip()[-1] in _TERMINAL_PUNCTUATION


@given(sentences=_sentences(min_sentences=6, max_sentences=20), config=_chunk_config(min_chunk_size=4))
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_13_every_original_sentence_survives_intact_somewhere(sentences, config):
    """No ordinary sentence is corrupted/split: every generated sentence
    appears verbatim in the reconstructed output.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)
    text = " ".join(sentences)

    chunks = chunker.chunk(text)
    reconstructed = " ".join(c.text for c in chunks)

    for sentence in sentences:
        assert sentence in reconstructed


def test_property_13_multi_chunk_case_is_actually_exercised():
    """Guards against the property above being vacuously satisfied by
    text that always fits in a single chunk.
    """

    chunker = _make_chunker(chunk_size=10, overlap=2)
    sentences = [f"word{i}a word{i}b word{i}c word{i}d." for i in range(10)]
    text = " ".join(sentences)

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    for sentence in sentences:
        assert any(sentence in chunk.text for chunk in chunks)


@given(config=_chunk_config(min_chunk_size=3, max_chunk_size=10))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_13_oversized_sentence_kept_whole_with_neighboring_sentences(config):
    """Combines an oversized sentence with ordinary short sentences around
    it and confirms the "keep whole" behavior remains intact in context,
    not just in isolation.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)

    oversized = " ".join(f"big{i}" for i in range(chunk_size + 5)) + "."
    text = f"Small one here. Small two here. {oversized} Small three here. Small four here."

    chunks = chunker.chunk(text)

    assert any(oversized in chunk.text for chunk in chunks)
    for chunk in chunks:
        assert chunk.text.strip() != ""
        assert chunk.text.rstrip()[-1] in _TERMINAL_PUNCTUATION


# ---------------------------------------------------------------------------
# Property 12 (continued): short-text handling (Requirement 4.4)
#
# These tests were previously mislabeled in this file as a separate
# "Property 14: Short Text Handling" -- there is no such official
# property. Requirement 4.4 ("text segment shorter than chunk size ->
# single chunk without padding") is validated by the real Property 12
# alongside Requirement 4.1 (see this file's module docstring). The tests
# themselves are unchanged and remain valid Requirement 4.4 coverage.
# ---------------------------------------------------------------------------


@given(sentences=_sentences(min_sentences=1, max_sentences=5, min_words=1, max_words=6), buffer=st.integers(1, 100))
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_short_text_under_chunk_size_produces_exactly_one_chunk(sentences, buffer):
    """chunk_size is deliberately set (via `buffer`) to comfortably exceed
    the generated text's own token count, guaranteeing the "text shorter
    than chunk_size" scenario by construction for every generated example.
    """

    chunker_for_counting = Chunker()
    text = " ".join(sentences)
    token_count = len(chunker_for_counting._tokenize(text))
    chunk_size = token_count + buffer  # always strictly larger than the content

    chunker = _make_chunker(chunk_size, overlap=0)
    chunks = chunker.chunk(text)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1


@given(sentences=_sentences(min_sentences=1, max_sentences=5, min_words=1, max_words=6), buffer=st.integers(1, 100))
@hyp_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_12_short_text_single_chunk_matches_normalized_content_without_padding(sentences, buffer):
    chunker_for_counting = Chunker()
    text = " ".join(sentences)
    token_count = len(chunker_for_counting._tokenize(text))
    chunk_size = token_count + buffer

    chunker = _make_chunker(chunk_size, overlap=0)
    chunks = chunker.chunk(text)

    normalized = Chunker._normalize(text)
    assert chunks[0].text == normalized
    assert len(chunks[0].text) == len(normalized)


@given(whitespace=st.text(alphabet=" \t\n\r", min_size=0, max_size=30))
@hyp_settings(max_examples=50, deadline=None)
def test_property_12_short_text_empty_or_whitespace_only_produces_no_chunks(whitespace):
    chunker = Chunker()
    assert chunker.chunk(whitespace) == []


# ---------------------------------------------------------------------------
# Property 15: Normalization
# ---------------------------------------------------------------------------

_SAFE_CONTROL_CHARS = ["\x00", "\x01", "\x02", "\x1f", "\x7f", "\x0b", "\x0c", "\x8f", "\x9f"]
_WHITESPACE_RUNS = [" ", "  ", "   ", "\t", "\n", "\r", "\r\n", " \t ", "\n\n"]
_PUNCTUATION_CHARS = list(".,!?;:'\"()[]{}%-")


@st.composite
def _messy_text(draw):
    """Text mixing normal characters, whitespace runs, punctuation, and
    disallowed C0/C1 control characters, with optional leading/trailing
    whitespace -- bounded to a small number of fragments for speed.
    """

    fragment_count = draw(st.integers(min_value=0, max_value=10))
    fragments: list[str] = []
    for _ in range(fragment_count):
        kind = draw(st.integers(min_value=0, max_value=3))
        if kind == 0:
            fragments.append(draw(st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=8)))
        elif kind == 1:
            fragments.append(draw(st.sampled_from(_WHITESPACE_RUNS)))
        elif kind == 2:
            fragments.append(draw(st.sampled_from(_PUNCTUATION_CHARS)))
        else:
            fragments.append(draw(st.sampled_from(_SAFE_CONTROL_CHARS)))

    leading = draw(st.sampled_from(["", " ", "\t", "\n", "  \t"]))
    trailing = draw(st.sampled_from(["", " ", "\t", "\n", "  \t"]))
    return leading + "".join(fragments) + trailing


@given(text=_messy_text())
@hyp_settings(max_examples=100, deadline=None)
def test_property_15_normalization_removes_disallowed_control_characters(text):
    normalized = Chunker._normalize(text)
    assert all(unicodedata.category(ch) != "Cc" for ch in normalized)


@given(text=_messy_text())
@hyp_settings(max_examples=100, deadline=None)
def test_property_15_normalization_collapses_and_strips_whitespace(text):
    normalized = Chunker._normalize(text)

    assert normalized == normalized.strip()
    assert "  " not in normalized
    assert not any(c in normalized for c in "\t\n\r")


@given(text=_messy_text())
@hyp_settings(max_examples=100, deadline=None)
def test_property_15_normalization_is_idempotent(text):
    once = Chunker._normalize(text)
    twice = Chunker._normalize(once)
    assert once == twice


@given(text=_messy_text())
@hyp_settings(max_examples=50, deadline=None)
def test_property_15_chunking_the_same_input_is_deterministic(text):
    chunker = Chunker()
    result_a = chunker.chunk(text)
    result_b = chunker.chunk(text)
    assert [c.model_dump() for c in result_a] == [c.model_dump() for c in result_b]


@given(text=_messy_text())
@hyp_settings(max_examples=50, deadline=None)
def test_property_15_normalization_happens_before_chunking(text):
    """Whatever `chunk()` ultimately produces must itself already be free
    of control characters and consecutive whitespace, proving
    normalization is applied before (not skipped during) chunking.
    """

    chunker = Chunker()
    chunks = chunker.chunk(text)

    for chunk in chunks:
        assert all(unicodedata.category(ch) != "Cc" for ch in chunk.text)
        assert "  " not in chunk.text
        assert not any(c in chunk.text for c in "\t\n\r")


# ---------------------------------------------------------------------------
# Property 14: Uniform chunk output format (Requirement 4.3)
#
# "For any source type (PDF, MP4, YouTube), the Chunker output SHALL
#  contain exactly three fields: text (non-empty string), chunk_index
#  (integer >= 0), and total_chunks (positive integer where
#  chunk_index < total_chunks)."
#
# This is the genuinely new coverage added during the Task 6.2 audit --
# see the module docstring for why it was previously missing dedicated
# Hypothesis-based coverage (only two fixed-example tests existed, in
# tests/test_chunker.py).
# ---------------------------------------------------------------------------


@given(
    text=st.one_of(
        st.just(""),
        st.text(alphabet=" \t\n\r", min_size=0, max_size=15),
        _sentences(min_sentences=1, max_sentences=1, min_words=1, max_words=6).map(lambda s: " ".join(s)),
        _sentences(min_sentences=2, max_sentences=6, min_words=1, max_words=6).map(lambda s: " ".join(s)),
        _sentences(min_sentences=10, max_sentences=25, min_words=2, max_words=8).map(lambda s: " ".join(s)),
        _messy_text(),
    ),
    config=_chunk_config(min_chunk_size=4, max_chunk_size=30),
)
@hyp_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_14_output_has_exactly_the_official_three_fields(text, config):
    """For every generated input -- empty, whitespace-only, one sentence,
    several sentences, long multi-chunk text, or "messy" text with
    control characters/punctuation/whitespace runs -- every produced
    Chunk has exactly the three official fields (no more, no less):
    text, chunk_index, total_chunks. Uses the real Pydantic model's own
    field introspection (not a hand-rolled dict), so an accidentally
    added or removed field on the model itself would be caught here too.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)

    chunks = chunker.chunk(text)

    for chunk in chunks:
        payload = chunk.model_dump()
        assert set(payload.keys()) == {"text", "chunk_index", "total_chunks"}
        assert set(type(chunk).model_fields.keys()) == {"text", "chunk_index", "total_chunks"}


@given(
    text=st.one_of(
        _sentences(min_sentences=1, max_sentences=1, min_words=1, max_words=6).map(lambda s: " ".join(s)),
        _sentences(min_sentences=3, max_sentences=8, min_words=1, max_words=6).map(lambda s: " ".join(s)),
        _sentences(min_sentences=10, max_sentences=25, min_words=2, max_words=8).map(lambda s: " ".join(s)),
    ),
    config=_chunk_config(min_chunk_size=4, max_chunk_size=30),
)
@hyp_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_14_field_types_and_values_are_correct(text, config):
    """For every non-empty generated chunk: `text` is a non-empty string,
    `chunk_index` is an int >= 0, `total_chunks` is a positive int, and
    `chunk_index < total_chunks` holds for every chunk -- exactly as the
    official property specifies.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)

    chunks = chunker.chunk(text)
    assert len(chunks) >= 1  # non-empty generated text always yields at least one chunk

    for chunk in chunks:
        assert isinstance(chunk.text, str)
        assert chunk.text != ""
        assert isinstance(chunk.chunk_index, int)
        assert chunk.chunk_index >= 0
        assert isinstance(chunk.total_chunks, int)
        assert chunk.total_chunks > 0
        assert chunk.chunk_index < chunk.total_chunks


@given(
    text=st.one_of(
        _sentences(min_sentences=3, max_sentences=8, min_words=1, max_words=6).map(lambda s: " ".join(s)),
        _sentences(min_sentences=10, max_sentences=25, min_words=2, max_words=8).map(lambda s: " ".join(s)),
    ),
    config=_chunk_config(min_chunk_size=4, max_chunk_size=20),
)
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_14_positions_are_ordered_and_consistent(text, config):
    """`chunk_index` values are exactly 0..N-1 in order (never skipped,
    duplicated, or reordered), and every chunk in the same output agrees
    on the same `total_chunks` value -- "uniform across generated inputs"
    and "positions are ordered appropriately", per the property's own
    wording.
    """

    chunk_size, overlap = config
    chunker = _make_chunker(chunk_size, overlap)

    chunks = chunker.chunk(text)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert len({c.total_chunks for c in chunks}) == 1  # every chunk agrees on the same total
    assert chunks[0].total_chunks == len(chunks)


def test_property_14_output_format_is_identical_regardless_of_source_type_text_shape():
    """Requirement 4.3's own framing: PDF-like, video-transcript-like, and
    YouTube-transcript-like text (different in style, not enforced by the
    Chunker itself, which is source-agnostic) all produce output with the
    identical three-field shape. This is a small, fixed-example
    reinforcement of the property above using text shaped like each real
    source, since the Chunker's genuine source-agnosticism is otherwise
    only demonstrated with synthetic generated text.
    """

    chunker = Chunker()  # real defaults: 512/50
    pdf_like = "Extracted PDF paragraph text goes here as one sentence."
    video_like = "Transcribed video speech goes here as one sentence."
    youtube_like = "YouTube transcript speech goes here as one sentence."

    for text in (pdf_like, video_like, youtube_like):
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        payload = chunks[0].model_dump()
        assert set(payload.keys()) == {"text", "chunk_index", "total_chunks"}
