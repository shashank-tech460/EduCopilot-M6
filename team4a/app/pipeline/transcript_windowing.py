"""M6 correction -- shared, source-agnostic timestamped transcript
segment windowing.

ROOT CAUSE THIS FIXES: `canonical_extraction.py`'s video/YouTube
extraction functions previously called `Chunker.chunk()` independently
on each RAW transcript segment. A raw segment (one entry from
`youtube_transcript_api`, or one Whisper transcription segment) is
typically only a few words -- a fragment of a sentence, not a
self-contained unit of meaning. Chunking each one in isolation produced
incoherent, fragment-level "chunks" (including, in the worst case, a
single filler word like "okay" becoming its own retrievable chunk) --
directly observed via a real live query citing an isolated "okay" as if
it were substantive content.

FIX: group consecutive raw segments into coherent WINDOWS of
transcript text (target size comparable to, but somewhat larger than,
`Settings.chunk_size`, so the existing sentence-aware `Chunker` still has
meaningful room to do its own splitting/overlap work), THEN call
`Chunker.chunk()` once per WINDOW instead of once per raw segment. Every
chunk produced from a given window inherits that window's own, real
timestamp range (min start / max end across the segments the window was
built from) -- never a fabricated, per-video-wide, or arbitrary fixed
range.

DELIBERATELY GENERIC: this module has no awareness of YouTube, MP4, or
any Pydantic model type (`VideoSegment`, `YouTubeSegment`) at all -- it
operates purely on plain `(text, start, end)` tuples, so the exact same
algorithm serves both source types without any source-specific branching
here. Each caller (`extract_video_for_canonical_ingestion`,
`extract_youtube_for_canonical_ingestion`) is responsible for the thin,
few-line adaptation to and from its own segment model's specific field
names (`end_time` vs. `start_time + duration`) -- this module never sees
those field names.

DOES NOT TOUCH: `Chunker` itself (unmodified, still receives plain text
and has no awareness this windowing step exists), `MetadataEnricher`
(unmodified -- callers feed it synthetic, window-level segments built
with the SAME Pydantic model type it already expects, so its own
per-segment metadata-construction code needs no changes at all), the PDF
extraction path (a PDF "segment" is already a whole page -- a
substantial, coherent unit where per-segment chunking is correct by
design, not a case this module is ever invoked for).

TEXT FIDELITY: windows are built by concatenating original segment text
verbatim (joined with a single space) -- no summarization, paraphrasing,
translation, LLM rewriting, or invented content of any kind. A segment
with empty/whitespace-only text (e.g. a `transcription_failed=True`
placeholder segment, which Requirement 2.6 already represents with
`text=""`) contributes nothing to any window -- not text, not a
timestamp boundary -- exactly like it already contributes nothing when
chunked directly (`Chunker.chunk("")` returns `[]`).

FRAGMENT/NOISE HANDLING: no word is ever deleted or filtered based on
its content (no denylist of "okay"/"yes"/"so"/etc. -- these are
preserved verbatim wherever they genuinely occur in the transcript).
The fix is coherent aggregation, not destructive text cleaning: a
standalone filler segment is absorbed into the surrounding window's
text as one word among many, so it can no longer become its own
isolated, near-content-free retrieval unit merely because it happened to
be one raw timing entry.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptWindow:
    """One coherent, merged window of transcript text, ready to be
    chunked -- the plain, source-agnostic output of
    `group_segments_into_windows()`. `start`/`end` are the real min/max
    timestamps across every original segment folded into this window,
    never fabricated or estimated.
    """

    text: str
    start: float
    end: float


def _word_count(text: str) -> int:
    """A simple, dependency-free whitespace word count -- used only for
    this module's own window-sizing decision, not as a stand-in for
    `Chunker`'s own token accounting (which the chunker still applies,
    unmodified, to each window's resulting text once this module hands
    it over).
    """

    return len(text.split())


def group_segments_into_windows(
    segments: list[tuple[str, float, float]],
    target_window_words: int,
    min_window_words: int,
) -> list[TranscriptWindow]:
    """Groups consecutive `(text, start, end)` segments into coherent
    `TranscriptWindow`s, each targeting roughly `target_window_words`
    words of real transcript text.

    Segments with empty/whitespace-only text are skipped entirely --
    they contribute no text and do not extend any window's timestamp
    range (see module docstring's "text fidelity"/"fragment handling"
    sections for why).

    A window accumulates consecutive (non-empty) segments until adding
    the next one would exceed `target_window_words` -- at which point
    the current window is finalized and a new one begins with that next
    segment. A single segment longer than `target_window_words` on its
    own still becomes (at minimum) its own whole window -- this function
    never truncates or drops segment text to enforce the target.

    If the FINAL window ends up smaller than `min_window_words` (e.g.
    the transcript's tail end trails off into just a few remaining
    words) and a previous window exists, it is merged into that previous
    window instead of being left as its own small, isolated trailing
    window -- directly preventing the "standalone filler/fragment
    becomes an independent retrieval unit" failure mode for the common
    case of a short tail, without ever discarding real transcript text.

    Returns an empty list if every segment was empty/whitespace-only (or
    `segments` itself is empty).
    """

    non_empty = [(text.strip(), start, end) for text, start, end in segments if text.strip()]
    if not non_empty:
        return []

    windows: list[TranscriptWindow] = []
    current_texts: list[str] = []
    current_start: float | None = None
    current_end: float | None = None
    current_words = 0

    def _finalize_current() -> None:
        assert current_start is not None and current_end is not None  # noqa: S101 -- internal invariant, not user input
        windows.append(TranscriptWindow(text=" ".join(current_texts), start=current_start, end=current_end))

    for text, start, end in non_empty:
        segment_words = _word_count(text)

        if current_texts and current_words + segment_words > target_window_words:
            _finalize_current()
            current_texts = []
            current_start = None
            current_end = None
            current_words = 0

        if not current_texts:
            current_start = start
        current_texts.append(text)
        current_end = end
        current_words += segment_words

    _finalize_current()

    if len(windows) > 1 and _word_count(windows[-1].text) < min_window_words:
        last = windows.pop()
        second_to_last = windows.pop()
        windows.append(
            TranscriptWindow(
                text=f"{second_to_last.text} {last.text}",
                start=second_to_last.start,
                end=last.end,
            )
        )

    return windows
