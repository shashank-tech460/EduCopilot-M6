"""MVP M6 correction -- deterministic, domain-agnostic follow-up context
enrichment for retrieval.

PROBLEM: `HybridRetriever.retrieve()` always searches on the raw,
literal current-turn query alone. For an elliptical follow-up ("Explain
it simply.", "Why is it important?", "Give me an example.") that query
string carries almost no topical signal for embedding/BM25 to match
against, even though the LLM's own generation prompt already includes
full conversation history and could, in principle, understand what "it"
means -- the gap is entirely on the RETRIEVAL side.

FIX: a single, pure, deterministic classifier -- no LLM call, no
framework, no per-subject vocabulary of any kind (Operating Systems,
DBMS, Machine Learning, Computer Networks, Java, IoT, or any other
subject are never referenced here; this module only recognizes
syntactic English patterns -- pronouns, demonstratives, and a small set
of generic conversational-continuation phrases -- never subject-matter
nouns). When a query is classified as elliptical, `RAGService` (not this
module) is responsible for prepending the single most recent USER turn's
own text to the string sent to retrieval -- this module only classifies,
it never touches conversation history, retrieval, or the LLM itself.

SCOPE, DELIBERATELY NARROW (see `is_elliptical_query`'s own docstring
for the full reasoning): this module does NOT attempt to resolve WHICH
specific item an ordinal ("the second one") or ambiguous plural
("compare them", "which one") refers to -- it only decides whether
enrichment (giving retrieval more topical text to work with) is
appropriate at all. Exact referent resolution for those cases is
explicitly NOT claimed or attempted here.
"""

from __future__ import annotations

import re

# Whole-word pronoun/demonstrative markers -- checked as individual
# tokens, never substrings, so a query containing "this" as part of a
# longer, unrelated word could never match (not a realistic English
# concern here, but the token-based check makes it a non-issue either
# way). Domain-agnostic by construction: these are closed-class English
# function words, never subject-matter vocabulary.
_PRONOUN_WORDS: frozenset[str] = frozenset({"it", "this", "that", "them", "these", "those", "its", "their"})

# Elliptical phrases that do NOT necessarily contain one of the pronoun
# words above, matched as an exact whole-string match against the
# normalized query (the same discipline `casual_intent.py` already
# established) -- deliberately not a substring/prefix search, so a
# genuinely self-contained question that happens to start with "why" or
# "how" but has its own clear subject (e.g. "How does inheritance work
# in Java?") is never misclassified merely because of its first word.
_ELLIPTICAL_PHRASES: frozenset[str] = frozenset(
    {
        "why",
        "how",
        "give me an example",
        "give another example",
        "make it shorter",
        "make it simpler",
        "explain further",
        "elaborate",
        "tell me more",
        "go deeper",
        "continue",
        "what about it",
        "what about this",
        "compare them",
        "what's the difference",
        "whats the difference",
        "which one",
        "the first one",
        "the second one",
        "the third one",
        "the last one",
        "the previous one",
        "and why",
        "and how",
    }
)

# MVP M6 design-validation correction: relative-BACKWARD-TOPIC references
# -- distinct from the item-level ordinals above ("the previous one"
# refers to an ITEM within the current topic; "the previous topic"
# refers to an entirely different, EARLIER topic than the one most
# recently discussed). Enriching these with the MOST RECENT turn would
# be confidently WRONG (the most recent turn is, by definition, not
# "the previous topic" the user is asking to return to) -- worse than
# no enrichment at all. These are therefore explicitly EXCLUDED from
# triggering enrichment; a query matching one of these falls through to
# plain, unenriched retrieval instead (honest and imperfect, rather
# than confidently wrong). Matched as a substring of the normalized
# query (not a whole-string match like the other sets above), since
# these naturally appear inside longer sentences ("let's go back to the
# previous topic", "what about before that").
_RELATIVE_BACKWARD_TOPIC_PHRASES: tuple[str, ...] = (
    "the previous topic",
    "previous topic",
    "the previous concept",
    "previous concept",
    "earlier topic",
    "before that",
    "the above",
)

_PUNCTUATION = re.compile(r"[!?.,]")
_WHITESPACE = re.compile(r"\s+")


def _normalize(query: str) -> str:
    """Same normalization discipline as `casual_intent.py`'s own
    `_normalize()` (lowercase, strip `!?.,` everywhere, collapse
    whitespace) -- intentionally not shared/imported between the two
    modules, since they serve genuinely distinct, independent
    classification purposes and this project's own established
    convention (see `casual_intent.py`) is one small, self-contained
    module per concern.
    """

    without_punctuation = _PUNCTUATION.sub("", query.lower())
    return _WHITESPACE.sub(" ", without_punctuation).strip()


def references_earlier_topic(query: str) -> bool:
    """True when the query explicitly asks to return to an earlier,
    already-superseded topic (e.g. "go back to the previous topic",
    "what about before that") -- see `_RELATIVE_BACKWARD_TOPIC_PHRASES`'s
    own docstring for why these must NEVER be enriched with the most
    recent turn. `RAGService` uses this to skip enrichment entirely for
    these queries, falling through to plain retrieval.
    """

    normalized = _normalize(query)
    return any(phrase in normalized for phrase in _RELATIVE_BACKWARD_TOPIC_PHRASES)


def is_elliptical_query(query: str) -> bool:
    """True when the query looks like it relies on prior conversation
    context to be understood -- a pronoun/demonstrative appears as a
    whole word anywhere in it, OR the entire normalized query exactly
    matches one of the curated `_ELLIPTICAL_PHRASES`.

    Returns False for any query matching `references_earlier_topic` --
    those are a DIFFERENT case (see that function's docstring) and must
    never be enriched by the most-recent-turn mechanism this
    classification feeds into.

    Domain-agnostic by construction (see module docstring) -- this
    function has no awareness of any subject matter and never will,
    since it only inspects closed-class English function words and a
    small set of generic conversational phrases.

    Does NOT claim exact referent resolution for ordinals ("the second
    one") or ambiguous plurals ("compare them", "which one") -- it only
    decides that enrichment (more topical text for retrieval) is
    appropriate; RAGService and the LLM's own reasoning over full
    conversation history remain responsible for anything resembling
    actual resolution.
    """

    if references_earlier_topic(query):
        return False

    normalized = _normalize(query)
    if not normalized:
        return False

    if normalized in _ELLIPTICAL_PHRASES:
        return True

    words = normalized.split(" ")
    return any(word in _PRONOUN_WORDS for word in words)


def build_enriched_retrieval_query(current_query: str, previous_user_turn: str | None) -> str:
    """Builds the TEXT used for retrieval only -- never the query stored
    in conversation history, never what's shown to the user, never what
    generation's own "Current Question" section receives (RAGService
    keeps those as the original, verbatim query in every case).

    `previous_user_turn` is the single most recent USER turn's own
    content (never the assistant's answer -- see the accompanying task
    report for why: the assistant's prose is longer and dilutes the
    retrieval query, and using only one turn limits how far a stale
    topic can leak into a new query). If `previous_user_turn` is `None`
    (no usable prior context), the current query is returned unchanged
    -- callers are expected to have already routed that case to the
    missing-context clarification branch before ever reaching this
    function, but this function itself stays safe either way.
    """

    if not previous_user_turn:
        return current_query
    return f"{previous_user_turn} {current_query}"
