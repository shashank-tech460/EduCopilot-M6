"""Unit tests for Task 6.1: Chunker.

Focused tests only -- optional Task 6.2 property-based tests are not
implemented here.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.config.settings import Settings, get_settings
from app.models.schemas import Chunk
from app.pipeline.chunker import Chunker


def make_chunker(chunk_size: int = 10, chunk_overlap: int = 3) -> Chunker:
    return Chunker(settings=SimpleNamespace(chunk_size=chunk_size, chunk_overlap=chunk_overlap))


def test_default_settings_match_official_requirement():
    settings = get_settings()
    assert settings.chunk_size == 512
    assert settings.chunk_overlap == 50


def test_chunker_uses_default_settings_when_none_provided():
    chunker = Chunker()
    assert chunker._settings.chunk_size == 512
    assert chunker._settings.chunk_overlap == 50


def test_chunker_uses_configured_settings_not_hardcoded_values():
    settings = Settings(chunk_size=20, chunk_overlap=5, _env_file=None)
    chunker = Chunker(settings=settings)
    assert chunker._settings.chunk_size == 20
    assert chunker._settings.chunk_overlap == 5


def test_text_under_default_chunk_size_produces_a_single_chunk():
    chunker = Chunker()
    text = "A short paragraph. It has only a few sentences. Nothing close to 512 tokens."

    chunks = chunker.chunk(text)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1


def test_long_text_is_split_into_multiple_chunks_with_default_settings():
    chunker = Chunker()
    text = " ".join(f"This is sentence number {i}." for i in range(1, 201))

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.total_chunks == len(chunks)


def test_chunks_do_not_split_a_sentence_in_the_middle():
    chunker = make_chunker(chunk_size=8, chunk_overlap=0)
    text = "Alpha bravo charlie delta echo. Foxtrot golf hotel india juliett kilo lima."

    chunks = chunker.chunk(text)

    for chunk in chunks:
        assert chunk.text.rstrip().endswith((".", "!", "?")) or chunk is chunks[-1]


def test_sentence_boundaries_preserved_across_multiple_chunks():
    chunker = make_chunker(chunk_size=6, chunk_overlap=0)
    text = "One two three. Four five six seven. Eight nine ten eleven twelve."

    chunks = chunker.chunk(text)

    reconstructed = " ".join(c.text for c in chunks)
    assert "One two three." in reconstructed
    assert "Four five six seven." in reconstructed
    assert "Eight nine ten eleven twelve." in reconstructed


def test_oversized_single_sentence_is_kept_whole_not_split():
    chunker = make_chunker(chunk_size=3, chunk_overlap=0)
    text = "This one sentence has many more than three words in it."

    chunks = chunker.chunk(text)

    assert len(chunks) == 1
    assert chunks[0].text == text


def test_short_text_emitted_as_single_chunk_without_padding():
    chunker = make_chunker(chunk_size=512, chunk_overlap=50)
    text = "Just one short sentence."

    chunks = chunker.chunk(text)

    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1


def test_empty_text_produces_no_chunks():
    chunker = Chunker()
    assert chunker.chunk("") == []


def test_whitespace_only_text_produces_no_chunks():
    chunker = Chunker()
    assert chunker.chunk("   \n\t  ") == []


def test_normalize_collapses_whitespace():
    chunker = Chunker()
    assert chunker._normalize("Hello    world.\n\nThis  is\ttabbed.") == "Hello world. This is tabbed."


def test_normalize_removes_control_characters():
    chunker = Chunker()
    result = chunker._normalize("Hello\x00World\x01Test\x1f.")
    assert "\x00" not in result
    assert "\x01" not in result
    assert "\x1f" not in result


def test_normalize_strips_leading_and_trailing_whitespace():
    chunker = Chunker()
    assert chunker._normalize("   padded text.   ") == "padded text."


def test_normalize_is_idempotent():
    chunker = Chunker()
    messy = "Hello\x00World.\t\tExtra   whitespace\nhere."
    once = chunker._normalize(messy)
    twice = chunker._normalize(once)
    assert once == twice


def test_chunking_applies_normalization_before_splitting():
    chunker = make_chunker(chunk_size=512, chunk_overlap=0)
    text = "Hello\x00World.   Extra    spaces\tand\ncontrol\x01chars here."

    chunks = chunker.chunk(text)

    assert len(chunks) == 1
    assert "\x00" not in chunks[0].text
    assert "\x01" not in chunks[0].text
    assert "  " not in chunks[0].text


def test_chunk_indices_are_sequential_and_ordered():
    chunker = make_chunker(chunk_size=6, chunk_overlap=1)
    text = " ".join(f"Sentence number {i} is here." for i in range(1, 11))

    chunks = chunker.chunk(text)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunking_is_deterministic_across_repeated_calls():
    chunker = make_chunker(chunk_size=8, chunk_overlap=2)
    text = "First sentence here. Second sentence follows. Third one arrives. Fourth is last."

    result_a = chunker.chunk(text)
    result_b = chunker.chunk(text)

    assert [c.model_dump() for c in result_a] == [c.model_dump() for c in result_b]


def test_no_chunk_has_empty_text():
    chunker = make_chunker(chunk_size=5, chunk_overlap=2)
    text = " ".join(f"Word{i} sentence number {i} here." for i in range(1, 20))

    chunks = chunker.chunk(text)

    for chunk in chunks:
        assert chunk.text != ""
        assert chunk.text.strip() != ""


def test_all_chunks_pass_chunk_model_validation():
    chunker = make_chunker(chunk_size=5, chunk_overlap=2)
    text = " ".join(f"Sentence {i} follows along nicely." for i in range(1, 15))

    chunks = chunker.chunk(text)

    for chunk in chunks:
        assert isinstance(chunk, Chunk)
        assert chunk.chunk_index < chunk.total_chunks


def test_overlap_adds_trailing_context_from_previous_chunk():
    chunker = make_chunker(chunk_size=5, chunk_overlap=2)
    text = "Alpha bravo charlie delta echo. Foxtrot golf hotel india juliett."

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    first_chunk_tokens = chunker._tokenize(chunks[0].text)
    second_chunk_tokens = chunker._tokenize(chunks[1].text)
    overlap_tokens = first_chunk_tokens[-2:]
    assert second_chunk_tokens[: len(overlap_tokens)] == overlap_tokens


def test_zero_overlap_produces_no_shared_content_between_chunks():
    chunker = make_chunker(chunk_size=5, chunk_overlap=0)
    text = "Alpha bravo charlie delta echo. Foxtrot golf hotel india juliett."

    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    # Compare word tokens only -- shared punctuation (e.g. both sentences
    # ending in ".") is not "shared content" in the sense this test cares about.
    first_chunk_words = {t for t in chunker._tokenize(chunks[0].text) if t.isalnum()}
    second_chunk_words = {t for t in chunker._tokenize(chunks[1].text) if t.isalnum()}
    assert first_chunk_words.isdisjoint(second_chunk_words)


def test_overlap_larger_than_previous_chunk_does_not_crash():
    chunker = make_chunker(chunk_size=3, chunk_overlap=100)
    text = "One two three. Four five six. Seven eight nine."

    chunks = chunker.chunk(text)

    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.text.strip() != ""


# ---------------------------------------------------------------------------
# Chunk-size / overlap interaction (correction: overlap must count *inside*
# chunk_size, not be added on top of an already-full chunk)
# ---------------------------------------------------------------------------


def test_overlap_does_not_push_normal_chunks_over_configured_chunk_size():
    # This is the exact defect scenario: chunk_size=512, overlap=50 used to
    # allow a 512-token group plus 50 overlap tokens on top, i.e. 562
    # tokens. Every normal (non-oversized-sentence) chunk must now respect
    # chunk_size as the true maximum.
    chunker = Chunker()  # real defaults: chunk_size=512, chunk_overlap=50
    text = " ".join(f"This is sentence number {i} in the document." for i in range(1, 200))

    chunks = chunker.chunk(text)

    assert len(chunks) > 1  # must actually exercise multi-chunk + overlap
    for chunk in chunks:
        token_count = len(chunker._tokenize(chunk.text))
        assert token_count <= 512, f"chunk {chunk.chunk_index} has {token_count} tokens, exceeds chunk_size=512"


def test_overlap_does_not_push_configured_chunk_size_over_the_limit():
    chunker = make_chunker(chunk_size=10, chunk_overlap=4)
    # Short sentences (well under the chunk_size-overlap=6-token budget)
    # so this test isolates the overlap-accounting fix, not the separate
    # "sentence longer than budget" edge case (see the dedicated test below).
    text = " ".join(f"Word{i} runs fast." for i in range(1, 20))

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    for chunk in chunks:
        token_count = len(chunker._tokenize(chunk.text))
        assert token_count <= 10


def test_sentence_longer_than_available_budget_but_not_longer_than_chunk_size_is_a_known_edge_case():
    """Documents an inherent, expected edge case (not a defect):

    A sentence can be <= chunk_size on its own, but longer than the
    *reduced* budget available once overlap is subtracted
    (chunk_size - overlap) for a non-first chunk. Since sentences are
    never split (Requirement 4.2), that chunk's total token count
    (overlap + that whole sentence) can still exceed chunk_size in this
    specific situation -- the same "avoid mid-sentence breaks where
    possible" exception that already applies to a sentence exceeding
    chunk_size outright, just triggered by the smaller post-overlap
    budget instead. This is different from -- and does not reintroduce --
    the original defect, where overlap pushed *every* normal chunk over
    chunk_size regardless of sentence length.
    """

    chunker = make_chunker(chunk_size=10, chunk_overlap=4)
    # Each sentence is 8 tokens: fits within chunk_size=10 alone, but
    # exceeds the 6-token budget (10-4) available to a non-first chunk.
    text = "Word1 number one sentence follows here now. Word2 number two sentence follows here now."

    chunks = chunker.chunk(text)

    assert len(chunks) == 2
    # The second chunk legitimately exceeds chunk_size here, because its
    # one sentence (8 tokens) plus overlap (4 tokens) cannot both fit
    # without breaking the sentence -- and the sentence must not be broken.
    second_chunk_tokens = len(chunker._tokenize(chunks[1].text))
    assert second_chunk_tokens == 12
    # Both chunks are still well-formed: non-empty, whole sentences intact.
    for chunk in chunks:
        assert chunk.text.strip() != ""
        assert chunk.text.rstrip().endswith(".")


def test_overlap_plus_new_content_fits_within_chunk_size_for_normal_chunks():
    # A normal (non-first, non-oversized-sentence) chunk's own new content
    # should be budgeted as chunk_size - overlap, so total <= chunk_size.
    chunker = make_chunker(chunk_size=10, chunk_overlap=3)
    text = " ".join(f"Alpha{i} bravo{i} charlie{i} delta{i}." for i in range(1, 10))

    chunks = chunker.chunk(text)

    assert len(chunks) > 2
    for chunk in chunks[1:-1]:  # interior chunks (skip first and last)
        token_count = len(chunker._tokenize(chunk.text))
        assert token_count <= 10


def test_overlap_is_still_genuinely_preserved_after_the_fix():
    # The fix must not accidentally remove overlap entirely -- consecutive
    # chunks must still share the configured number of trailing/leading tokens.
    chunker = make_chunker(chunk_size=10, chunk_overlap=3)
    text = " ".join(f"Alpha{i} bravo{i} charlie{i} delta{i}." for i in range(1, 10))

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    first_tail = chunker._tokenize(chunks[0].text)[-3:]
    second_head = chunker._tokenize(chunks[1].text)[:3]
    assert first_tail == second_head


def test_default_512_50_produces_correctly_sized_and_overlapping_chunks():
    chunker = Chunker()  # chunk_size=512, chunk_overlap=50
    text = " ".join(f"This is sentence number {i} in a long document about testing." for i in range(1, 150))

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunker._tokenize(chunk.text)) <= 512

    # Overlap is present between consecutive chunks.
    for i in range(len(chunks) - 1):
        tail = chunker._tokenize(chunks[i].text)[-50:]
        head = chunker._tokenize(chunks[i + 1].text)[: len(tail)]
        assert tail == head


def test_overlap_fix_preserves_sentence_boundary_preference():
    chunker = make_chunker(chunk_size=10, chunk_overlap=3)
    text = "One two three four. Five six seven eight. Nine ten eleven twelve."

    chunks = chunker.chunk(text)

    reconstructed = " ".join(c.text for c in chunks)
    assert "One two three four." in reconstructed
    assert "Five six seven eight." in reconstructed
    assert "Nine ten eleven twelve." in reconstructed


def test_overlap_fix_preserves_deterministic_ordering():
    chunker = make_chunker(chunk_size=10, chunk_overlap=3)
    text = " ".join(f"Sentence number {i} appears here today." for i in range(1, 15))

    result_a = chunker.chunk(text)
    result_b = chunker.chunk(text)

    assert [c.model_dump() for c in result_a] == [c.model_dump() for c in result_b]
    assert [c.chunk_index for c in result_a] == list(range(len(result_a)))


def test_overlap_fix_produces_no_empty_chunks_even_with_small_chunk_size():
    chunker = make_chunker(chunk_size=2, chunk_overlap=1)
    text = " ".join(f"Word{i} follows here." for i in range(1, 15))

    chunks = chunker.chunk(text)

    for chunk in chunks:
        assert chunk.text.strip() != ""


def test_short_text_unaffected_by_overlap_fix():
    chunker = Chunker()  # defaults: chunk_size=512, chunk_overlap=50
    text = "Just one short sentence."

    chunks = chunker.chunk(text)

    assert len(chunks) == 1
    assert chunks[0].text == text


def test_output_uses_existing_chunk_model_with_exactly_three_fields():
    chunker = make_chunker(chunk_size=5, chunk_overlap=1)
    text = "First sentence here. Second sentence follows along."

    chunks = chunker.chunk(text)

    for chunk in chunks:
        assert isinstance(chunk, Chunk)
        payload = chunk.model_dump()
        assert set(payload.keys()) == {"text", "chunk_index", "total_chunks"}


def test_identical_output_format_regardless_of_hypothetical_source():
    chunker = make_chunker(chunk_size=512, chunk_overlap=50)
    pdf_like_text = "Extracted PDF paragraph text goes here as one sentence."
    video_like_text = "Transcribed video speech goes here as one sentence."
    youtube_like_text = "YouTube transcript speech goes here as one sentence."

    for text in (pdf_like_text, video_like_text, youtube_like_text):
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        payload = chunks[0].model_dump()
        assert set(payload.keys()) == {"text", "chunk_index", "total_chunks"}
