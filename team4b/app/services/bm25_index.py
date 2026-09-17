"""Team 4B BM25 keyword index (Task 3.1).

Implements the keyword-search leg needed by Requirement 2 (Hybrid
Search), specifically the design document's:

    3.1 Implement BM25 index and embedding generation
        Create app/services/bm25_index.py with in-memory BM25 index
        using rank-bm25
        Requirements: 2.1

SCOPE NOTE (Task 3.1 only): this module implements a standalone,
in-memory BM25 index. It does NOT implement:
  - Reciprocal Rank Fusion or search-mode routing (Task 3.2's
    HybridRetriever combines this with vector search).
  - Score normalization to [0.0, 1.0] (Property 7 is Hybrid_Retriever's
    responsibility, not this component's -- BM25 scores returned here
    are raw rank_bm25 scores, unbounded).
  - Any synchronization with the shared Qdrant collection or Team 4A's
    published chunks. Populating this index (from where, how often) is
    explicitly left to whatever calls it (Task 3.2 or later) -- inventing
    that synchronization here would be exactly the kind of
    "synchronization system" the current task instructions say not to
    build.

CORPUS FRESHNESS / REBUILD BEHAVIOR (Task 3.1 decision, since neither
official document defines one -- see docs/CONTRACT_DECISIONS.md and the
Phase 1 analysis's ambiguity #5, both of which flagged this as
unresolved):

    rank_bm25.BM25Okapi builds its index once from a fixed corpus and has
    no incremental-update API. This class therefore rebuilds its entire
    internal index -- an O(corpus size) operation -- on every call that
    changes the corpus (`add_documents`, `remove_documents`, `rebuild`).
    This is a correct, simple choice for Task 3.1's scope: a
    small/moderate in-memory corpus rebuilds fast enough that this isn't
    a real cost yet. It is NOT a decision about how or how often a real
    deployment's HybridRetriever should keep this index in sync with a
    live, growing Vector_Store -- that remains genuinely undefined by
    both official documents and is explicitly deferred, not silently
    resolved, here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Sequence

from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]  # rank_bm25 ships no type stubs / py.typed marker

# MVP M6 correction (Phase 1 -- BM25 multilingual lexical support): the
# tokenizer previously matched ASCII alphanumerics only ([A-Za-z0-9]+),
# so Hindi text written in Devanagari tokenized to nothing and could
# never be matched by BM25 at all. This adds a second alternative
# covering the Devanagari Unicode block (U+0900-U+097F), EXCLUDING the
# danda (U+0964) and double danda (U+0965) sentence-ending punctuation
# and the abbreviation sign / high spacing dot (U+0970, U+0971) -- those
# remain non-word separators, exactly like ASCII '.'/'!' already are,
# rather than becoming tokens themselves or silently fusing the words on
# either side of them. Devanagari vowel signs (matras) and virama fall
# inside the retained range, so a whole conjunct/matra word (e.g.
# "शेड्यूलिंग") still tokenizes as one token, not several fragments.
#
# The two alternatives are kept SEPARATE (rather than merged into one
# character class) so a script switch with no separating whitespace
# (e.g. "hindiहिंदी") still splits into distinct tokens instead of
# fusing into one nonsensical mixed-script token -- `re.findall` tries
# the first alternative at each position and only falls through to the
# second when the current character isn't ASCII alphanumeric.
#
# Romanized Hindi/Hinglish (e.g. "kya hai") needs no separate handling:
# it is already plain ASCII and matches the first alternative exactly as
# it always did -- this is a strict, additive superset of the previous
# pattern, not a replacement of it.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+" r"|[ऀ-ॣ०-९ॲ-ॿ]+")


def default_tokenizer(text: str) -> list[str]:
    """Lowercase, script-aware word tokenizer: ASCII alphanumeric runs
    and Devanagari (Hindi) word runs, each matched as separate tokens.

    Neither the official Requirements nor Design document specifies a
    tokenization scheme for BM25 -- this is a necessary implementation
    detail (not a new requirement): simple, deterministic, and adequate
    for rank-bm25's own expectation of a list of string tokens per
    document. Injectable (see `BM25Index.__init__`) so a more
    sophisticated tokenizer can replace it later without touching the
    index's own logic.

    Covers three of the product's required query/content languages with
    no per-query or per-document special-casing: English and Romanized
    English/Hinglish (both plain ASCII, matched by the `[A-Za-z0-9]+`
    alternative, unchanged from before this correction), and Hindi
    written in Devanagari (matched by the Devanagari-block alternative,
    see `_TOKEN_PATTERN`'s comment above). `str.lower()` is a no-op on
    Devanagari codepoints (the script has no case), so it only affects
    the ASCII alternative, exactly as before.
    """

    return _TOKEN_PATTERN.findall(text.lower())


@dataclass
class BM25Document:
    """One document to index: a Context_Chunk's identity, its text, and
    (MVP M3, additive) the workspace it belongs to.

    `workspace_id` defaults to `None` for backward compatibility with any
    existing caller/test that indexes documents without tenancy context
    -- but `BM25Index.search()` itself (below) REQUIRES a `workspace_id`
    argument with no default, so a document indexed with `workspace_id=None`
    can never be returned by any real search call; it would only ever
    match a (nonsensical, never-issued) search for the literal `None`
    workspace. This dataclass default exists for the field's own
    backward-compatible construction, not to create a bypass of the
    mandatory search-time filter.
    """

    chunk_id: str
    text: str
    workspace_id: str | None = None
    # MVP M6 (document-level retrieval scope, additive): the canonical
    # document_id this chunk belongs to -- `None` for backward
    # compatibility with any caller/test that doesn't set it, matching
    # `workspace_id`'s own precedent. A document indexed with
    # `document_id=None` can never be selected by a real
    # `document_ids`-scoped search (see `BM25Index.search()` below) --
    # again matching the same "field default is for construction
    # convenience, not a filter bypass" discipline `workspace_id`
    # already established.
    document_id: str | None = None
    # Phase 4E-F1 (source-selection isolation fix, additive): the
    # NORMALIZED source type this chunk belongs to (Team 4B's own
    # "document"/"video" vocabulary -- see
    # `vector_store.normalize_source_type()` -- not Team 4A's raw
    # "pdf"/"mp4"/"youtube" values). `None` for backward compatibility
    # with any caller/test that doesn't set it, matching
    # `workspace_id`/`document_id`'s own precedent. A document indexed
    # with `source_type=None` simply never matches a real
    # `collection_filter`-scoped search that names a specific type (see
    # `BM25Index.search()` below) -- same "field default is for
    # construction convenience, not a filter bypass" discipline as the
    # other two identity fields.
    source_type: str | None = None


class BM25Index:
    """In-memory BM25 keyword index over Context_Chunk text.

    Deliberately has no knowledge of the Vector_Store, Qdrant, or Team
    4A's payload shape -- it operates purely on (chunk_id, text,
    workspace_id) tuples handed to it, keeping it a small, independently
    testable unit. This matches the Design document's own module
    boundary (`app/services/bm25_index.py` is listed separately from
    `app/services/vector_store.py`).

    MVP M3 CORRECTION -- workspace isolation: `search()` now REQUIRES a
    `workspace_id` argument (no default) and computes BM25 scores from a
    FRESH, TEMPORARY index built from ONLY that workspace's documents,
    every call. This is a deliberate choice, not an accidental
    performance regression from the previous single, persistently-built
    global index: correct data isolation requires that a cross-workspace
    document can never appear in the candidate list BEFORE RRF fusion --
    filtering AFTER computing rank_bm25 scores against the full, mixed
    corpus would still be unsafe, since RRF must receive only
    workspace-valid candidates in the first place (the governing task's
    own explicit requirement), and because rank_bm25's own IDF statistics
    are computed from whatever corpus is passed to `BM25Okapi()` -- a
    global corpus's statistics would still indirectly reflect
    cross-workspace content even if results were filtered afterward.
    Building a small, per-workspace `BM25Okapi` instance per query is the
    same "just rebuild, it's simple and correct" philosophy this module's
    own docstring already applies to corpus updates (`rank_bm25` has no
    incremental-update API in either direction), extended to also apply
    per query rather than only per corpus change.
    """

    def __init__(self, tokenizer: Callable[[str], list[str]] = default_tokenizer) -> None:
        self._tokenizer = tokenizer
        # dict preserves insertion order (guaranteed since Python 3.7).
        # Stores the FULL BM25Document (text + workspace_id), not just
        # text, so search() can filter by workspace before scoring.
        self._documents: dict[str, BM25Document] = {}

    @property
    def size(self) -> int:
        """Number of documents currently indexed, across ALL workspaces
        (unchanged meaning from before this correction -- this property
        does not itself have a workspace concept; use `search()`'s own
        result count for a workspace-scoped count)."""

        return len(self._documents)

    def rebuild(self, documents: Sequence[BM25Document]) -> None:
        """Replace the entire corpus."""

        self._documents = {document.chunk_id: document for document in documents}

    def add_documents(self, documents: Sequence[BM25Document]) -> None:
        """Add new documents, or replace existing ones by chunk_id."""

        for document in documents:
            self._documents[document.chunk_id] = document

    def remove_documents(self, chunk_ids: Sequence[str]) -> None:
        """Remove documents by chunk_id (missing IDs are silently
        ignored, matching dict.pop's own no-op-on-missing-key semantics
        rather than raising for a caller that's simply uncertain whether
        a chunk was indexed)."""

        for chunk_id in chunk_ids:
            self._documents.pop(chunk_id, None)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        workspace_id: str,
        document_ids: list[str] | None = None,
        collection_filter: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Return (chunk_id, bm25_score) pairs, ranked descending by
        score, computed from ONLY the documents belonging to
        `workspace_id` (and, if `document_ids`/`collection_filter` are
        given, further narrowed to exactly those documents/source
        types).

        `workspace_id` is REQUIRED (keyword-only, no default) -- there is
        no code path in this method that scores against any document
        outside the given workspace, and no way to request "every
        workspace" (a missing/omitted workspace_id is a TypeError at the
        call site, not a silent global search).

        MVP M6 (document-level retrieval scope, additive):
        `document_ids=None` (the default) preserves the exact previous
        behavior -- every workspace-scoped document is a candidate.
        `document_ids=[]` (present but empty) is a DELIBERATE,
        non-widening narrowing to ZERO candidates -- never interpreted
        as "no restriction". `document_ids=[...]` restricts the
        candidate set to chunks whose `document_id` is in that list,
        applied TOGETHER with the mandatory workspace filter (a chunk
        must satisfy both) -- computed BEFORE this method builds the
        per-query `BM25Okapi` instance, so an out-of-scope document's
        text can never influence this query's IDF statistics or ranking
        at all, not merely be filtered out of the final result.

        Phase 4E-F1 (source-selection isolation fix, additive):
        `collection_filter` uses the SAME "falsy means no restriction"
        contract `VectorStoreManager._build_collection_filter()` already
        established for the semantic leg -- `None` or `[]` both apply no
        source-type restriction at all (this is deliberately NOT the
        same convention as `document_ids=[]`, which narrows to zero;
        the two parameters have always had different empty-value
        contracts, unchanged here, only extended to this leg).
        `collection_filter=["document", "video"]` restricts the
        candidate set to chunks whose (already-normalized, Team 4B
        vocabulary) `source_type` is in that list, applied TOGETHER with
        the workspace and document filters, again computed BEFORE the
        per-query `BM25Okapi` instance is built -- an excluded source
        type's text can never influence this query's IDF statistics or
        ranking, not merely be filtered out of the final result.

        Scores are raw, unbounded rank_bm25 scores -- NOT normalized to
        [0.0, 1.0]. Normalization is Reciprocal Rank Fusion's
        responsibility (Task 3.2, Property 7), not this component's.

        `top_k=None` (the default) returns every workspace-scoped
        indexed document ranked, since Task 3.2's RRF needs full ranked
        lists from both BM25 and vector search before applying any
        threshold/top_k limiting (Properties 5-6) -- limiting here would
        make that impossible later. A `top_k` is still accepted for
        callers (and tests) that want a bounded result directly from
        this component alone.
        """

        if document_ids is not None and len(document_ids) == 0:
            return []

        document_id_set = set(document_ids) if document_ids is not None else None
        source_type_set = set(collection_filter) if collection_filter else None
        workspace_documents = [
            doc
            for doc in self._documents.values()
            if doc.workspace_id == workspace_id
            and (document_id_set is None or doc.document_id in document_id_set)
            and (source_type_set is None or doc.source_type in source_type_set)
        ]
        if not workspace_documents:
            return []

        tokenized_corpus = [self._tokenizer(document.text) for document in workspace_documents]
        if not any(tokenized_corpus):
            # Same degenerate-corpus guard as before this correction,
            # now applied to the workspace-scoped subset specifically.
            return []

        tokenized_query = self._tokenizer(query)
        if not tokenized_query:
            return []

        workspace_bm25 = BM25Okapi(tokenized_corpus)
        scores = workspace_bm25.get_scores(tokenized_query)
        chunk_ids = [document.chunk_id for document in workspace_documents]
        ranked = sorted(zip(chunk_ids, scores), key=lambda pair: pair[1], reverse=True)
        if top_k is not None:
            ranked = ranked[:top_k]
        return [(chunk_id, float(score)) for chunk_id, score in ranked]
