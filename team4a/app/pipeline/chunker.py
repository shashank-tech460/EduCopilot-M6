"""Team 4A Chunker.

Location and class name match the official design document:
    "app/pipeline/chunker.py ... class Chunker"

Implements Requirement 4:
    4.1 Split normalized text into chunks of configurable size (default:
        512 tokens) with configurable overlap (default: 50 tokens).
    4.2 Preserve sentence boundaries when splitting, avoiding mid-sentence
        breaks where possible.
    4.3 Produce chunks in an identical output format (text, chunk_index,
        total_chunks) regardless of source type.
    4.4 Emit text shorter than the configured chunk size as a single chunk,
        without padding.
    4.5 Normalize whitespace, remove control characters, and apply UTF-8
        encoding before chunking.

Does not implement embedding, metadata enrichment, or Qdrant publication
-- those belong to later tasks (7.1, 8.1, 8.2). Adds no fields to the
existing `Chunk` model (Task 1.2) and invents no downstream metadata.
"""

from __future__ import annotations

import re

from app.config.settings import Settings, get_settings
from app.models.schemas import Chunk

#: Matches C0/C1 control characters, excluding tab/newline/carriage-return
#: (those are handled by whitespace normalization instead, since collapsing
#: them into spaces is more useful than deleting them outright).
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")

#: Collapses any run of whitespace (including the tab/newline/carriage-
#: return left alone by _CONTROL_CHAR_PATTERN) into a single space.
_WHITESPACE_PATTERN = re.compile(r"\s+")

#: A deliberately simple, dependency-free "word or punctuation mark" token
#: definition. See the Task 6.1 report for why this was chosen over a
#: model-specific subword tokenizer (e.g. the embedding model's tokenizer,
#: introduced only in Task 7.1).
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

#: A sentence is one or more non-terminal characters followed by one or
#: more terminal punctuation marks, OR (as a fallback for text with no
#: terminal punctuation at all, e.g. the tail of a transcript) any
#: remaining non-terminal text up to the end of the string.
_SENTENCE_PATTERN = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")

#: Punctuation tokens that should be attached directly to the preceding
#: token with no space in between, when reconstructing text from tokens
#: for the overlap window. This is an approximation for readability, not
#: a full detokenizer -- see the Task 6.1 report.
_NO_SPACE_BEFORE = frozenset(".,!?;:')]}%")


class Chunker:
    """Splits normalized text into uniform, sentence-aware, overlapping chunks.

    Chunk size and overlap are read from `Settings` (never hardcoded), per
    Requirement 4.1's "configurable size"/"configurable overlap" and this
    project's established pattern (see PDFProcessor, VideoProcessor,
    YouTubeProcessor).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(self, text: str) -> list[Chunk]:
        """Split `text` into a list of uniform `Chunk` objects.

        Args:
            text: Raw text from any source (PDF, MP4 transcript, YouTube
                transcript). This function does not care which -- it only
                consumes plain text, matching Requirement 4.3's "identical
                output format regardless of source type."

        Returns:
            An empty list if `text` normalizes to nothing (e.g. it was
            empty or all whitespace/control characters). Otherwise, one or
            more `Chunk` objects in deterministic left-to-right order,
            with `chunk_index` 0..N-1 and `total_chunks` == N.
        """

        chunk_size = self._settings.chunk_size
        overlap = self._settings.chunk_overlap

        normalized = self._normalize(text)
        if not normalized:
            return []

        sentences = self._split_sentences(normalized)
        chunk_texts = self._assemble_chunk_texts(sentences, chunk_size, overlap)

        total_chunks = len(chunk_texts)
        return [
            Chunk(text=text, chunk_index=index, total_chunks=total_chunks)
            for index, text in enumerate(chunk_texts)
        ]

    # ------------------------------------------------------------------
    # Normalization (Requirement 4.5)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize whitespace, strip control characters, enforce UTF-8.

        Idempotent: normalizing already-normalized text is a no-op, since
        the result contains no control characters and no consecutive
        whitespace for the pattern to further collapse.
        """

        text = text.encode("utf-8", errors="ignore").decode("utf-8")
        text = _CONTROL_CHAR_PATTERN.sub("", text)
        text = _WHITESPACE_PATTERN.sub(" ", text).strip()
        return text

    # ------------------------------------------------------------------
    # Tokenization (for size/overlap accounting only -- see report)
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split text into word and punctuation-mark tokens.

        This is a simple, deterministic, dependency-free stand-in for
        "tokens" as used by `chunk_size`/`chunk_overlap`. It is not the
        embedding model's own subword tokenizer -- see the Task 6.1 report
        for why that distinction is intentional at this stage.
        """

        return _TOKEN_PATTERN.findall(text)

    @staticmethod
    def _detokenize(tokens: list[str]) -> str:
        """Reconstruct readable text from a token list (used for overlap text).

        Approximate by design: word tokens get a preceding space, most
        punctuation marks attach directly to the previous token. It does
        not aim for perfect typographic reconstruction (e.g. opening
        brackets/quotes may get an extra space) -- only to produce
        deterministic, meaningful, non-empty overlap text.
        """

        pieces: list[str] = []
        for index, token in enumerate(tokens):
            if index == 0 or token in _NO_SPACE_BEFORE:
                pieces.append(token)
            else:
                pieces.append(" ")
                pieces.append(token)
        return "".join(pieces)

    # ------------------------------------------------------------------
    # Sentence splitting (Requirement 4.2)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split already-normalized text into sentences.

        A lightweight regex splitter (terminal punctuation: . ! ?), not a
        full NLP sentence tokenizer -- sufficient to "avoid mid-sentence
        breaks where possible" (Requirement 4.2) without adding an NLP
        dependency (see the Task 6.1 report).
        """

        return [match.strip() for match in _SENTENCE_PATTERN.findall(text) if match.strip()]

    # ------------------------------------------------------------------
    # Chunk assembly (Requirements 4.1, 4.2, 4.4)
    # ------------------------------------------------------------------

    def _assemble_chunk_texts(self, sentences: list[str], chunk_size: int, overlap: int) -> list[str]:
        """Build chunk texts so that overlap counts *inside* `chunk_size`, not on top of it.

        For every chunk after the first, the token budget available for
        *new* sentence content is `chunk_size - len(overlap_tokens)`, so
        that `overlap tokens + new content <= chunk_size` for any normal
        chunk (Property 12: chunks, except possibly the last, fall within
        [chunk_size - overlap, chunk_size] tokens). The first chunk has no
        overlap to make room for, so its full budget is `chunk_size`.

        A single sentence is still never split across chunks, even if it
        alone exceeds its budget -- Requirement 4.2's explicit exception,
        preserved unchanged by this fix. This can still make a chunk
        exceed `chunk_size` in that specific case, exactly as before; what
        changed is that overlap itself no longer *causes* an otherwise-full
        chunk to overflow.

        Overlap tokens are drawn from the *previous chunk's own new
        content* (not including whatever overlap that previous chunk
        itself carried forward), so overlap does not compound/grow across
        many consecutive chunks.
        """

        sentence_token_lists = [self._tokenize(sentence) for sentence in sentences]

        chunk_texts: list[str] = []
        previous_new_tokens: list[str] = []
        index = 0
        total_sentences = len(sentences)

        while index < total_sentences:
            is_first_chunk = not chunk_texts

            if is_first_chunk or overlap <= 0:
                overlap_tokens: list[str] = []
            else:
                overlap_tokens = previous_new_tokens[-overlap:]
                # Pathological configuration guard (e.g. overlap >= chunk_size):
                # always leave room for at least one token of new content, so
                # a chunk is never *only* recycled overlap with no new text
                # and the loop always makes forward progress.
                if len(overlap_tokens) >= chunk_size:
                    overlap_tokens = overlap_tokens[-(chunk_size - 1) :] if chunk_size > 1 else []

            new_content_budget = chunk_size - len(overlap_tokens)

            new_group: list[str] = []
            new_token_count = 0
            while index < total_sentences:
                sentence_tokens = sentence_token_lists[index]
                sentence_token_count = len(sentence_tokens)

                if new_group and new_token_count + sentence_token_count > new_content_budget:
                    break

                new_group.append(sentences[index])
                new_token_count += sentence_token_count
                index += 1

            if not new_group:
                # The next sentence alone exceeds the budget -- keep it
                # whole rather than splitting it mid-sentence.
                new_group = [sentences[index]]
                index += 1

            new_group_text = " ".join(new_group)
            new_group_tokens = self._tokenize(new_group_text)

            if overlap_tokens:
                overlap_text = self._detokenize(overlap_tokens)
                chunk_text = f"{overlap_text} {new_group_text}".strip()
            else:
                chunk_text = new_group_text

            chunk_texts.append(chunk_text)
            previous_new_tokens = new_group_tokens

        return chunk_texts
