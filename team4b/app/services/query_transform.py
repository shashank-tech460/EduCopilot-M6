"""Phase 5A -- generic, deterministic query-variant generation for
cross-script retrieval evaluation.

NOT wired into production. This module is imported only by the Phase 5A
evaluation script/tests (see
`team4b/scripts/phase5a_cross_script_retrieval_evaluation.py` and
`team4b/tests/test_phase5a_cross_script_retrieval_evaluation.py`). It is
not referenced by `app/api/dependencies.py` or `app/services/rag_service.py`,
so it changes no production request path or default.

SCOPE: Phase 4D found that the multilingual embedding candidate model's
isolated semantic-recall improvement for English/Hinglish queries
against Hindi-script source content largely disappeared inside the real
hybrid BM25+RRF pipeline. This module evaluates the next generalized
candidate: transforming the QUERY side rather than the embedding model,
using only a mechanism that is genuinely available offline in this
environment (see the Phase 5A review markdown for the full local-
capability inspection).

WHY TRANSLITERATION, NOT TRANSLATION: no translation model or library
(MarianMT, NLLB, argos-translate, indic-nlp, googletrans, etc.) is
installed or cached locally in this environment, and this phase
deliberately does not download one -- large model downloads for a
single evaluation phase are exactly the "unnecessary infrastructure"
this phase's own instructions warn against. A deterministic, rule-based
Latin-to-Devanagari TRANSLITERATION (mapping phonetic sound, not
meaning) is fully offline, reproducible, and requires no model at all.
It is linguistically well-suited to romanized Hindi/Hinglish queries
(where the Latin letters already encode Hindi phonemes) but is NOT
translation: it cannot help queries written in genuine English
vocabulary, since transliterating English letter-by-letter does not
produce a meaningful Hindi word. That asymmetry is an expected,
honestly-reported limitation of this specific mechanism, not a defect
in the implementation -- see the Phase 5A review's acceptance-criteria
answers for the measured, not assumed, consequence of this.

GENERALIZATION: the mapping tables below encode Devanagari PHONETICS
(consonants, vowels, matras) -- universal properties of the script,
independent of subject matter, workspace, document, or which academic
subject a query happens to be about. Nothing here references any
particular course, textbook, or benchmark-specific vocabulary. The same
function applies identically to a query about any subject at all.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Devanagari phonetic mapping tables. Ordering within each table does not
# matter for correctness (lookup keys are re-sorted by length below) --
# grouped here by linguistic category for readability only.
# ---------------------------------------------------------------------------

_INDEPENDENT_VOWELS: dict[str, str] = {
    "aa": "आ", "ee": "ई", "ii": "ई", "oo": "ऊ", "uu": "ऊ",
    "ai": "ऐ", "au": "औ",
    "a": "अ", "i": "इ", "u": "उ", "e": "ए", "o": "ओ",
}

_MATRAS: dict[str, str] = {
    "aa": "ा", "ee": "ी", "ii": "ी", "oo": "ू", "uu": "ू",
    "ai": "ै", "au": "ौ",
    "a": "", "i": "ि", "u": "ु", "e": "े", "o": "ो",
}

_CONSONANTS: dict[str, str] = {
    # Aspirated / multi-letter digraphs and conjunct-adjacent clusters
    # first (longest-match order is computed below, not by dict order).
    "ksh": "क्ष", "gy": "ज्ञ", "jn": "ज्ञ", "shh": "ष",
    "chh": "छ", "sh": "श", "ch": "च",
    "kh": "ख", "gh": "घ", "ng": "ङ",
    "th": "थ", "dh": "ध", "ph": "फ", "bh": "भ",
    "Th": "ठ", "Dh": "ढ", "ny": "ञ",
    # Single-letter consonants
    "k": "क", "g": "ग", "j": "ज", "t": "त", "d": "द",
    "T": "ट", "D": "ड", "n": "न", "N": "ण", "p": "प",
    "b": "ब", "m": "म", "y": "य", "r": "र", "l": "ल",
    "v": "व", "w": "व", "s": "स", "h": "ह", "f": "फ़", "z": "ज़",
}

_VOWEL_KEYS: tuple[str, ...] = tuple(sorted(_INDEPENDENT_VOWELS, key=len, reverse=True))
_CONSONANT_KEYS: tuple[str, ...] = tuple(sorted(_CONSONANTS, key=len, reverse=True))

_VIRAMA = "्"


def transliterate_latin_to_devanagari(text: str) -> str:
    """Deterministic, generic, offline Latin-script -> Devanagari-script
    phonetic transliteration. Word-splits on spaces and transliterates
    each word independently; non-alphabetic characters (digits,
    punctuation, already-Devanagari text) pass through unchanged, so
    calling this on non-Latin or mixed text never raises and never
    fabricates a transformation it can't perform.

    Not case-sensitive on input (Hinglish is typed in any case); output
    depends only on the lowercase phonetic reading.
    """

    return " ".join(_transliterate_word(word) if word else word for word in text.split(" "))


def _transliterate_word(word: str) -> str:
    lowered = word.lower()
    length = len(lowered)
    position = 0
    output: list[str] = []
    pending_consonant: str | None = None

    def flush_pending(*, with_virama: bool) -> None:
        nonlocal pending_consonant
        if pending_consonant is not None:
            output.append(pending_consonant)
            if with_virama:
                output.append(_VIRAMA)
            pending_consonant = None

    while position < length:
        consonant_key = next((key for key in _CONSONANT_KEYS if lowered.startswith(key, position)), None)
        if consonant_key is not None:
            flush_pending(with_virama=True)
            pending_consonant = _CONSONANTS[consonant_key]
            position += len(consonant_key)
            continue

        vowel_key = next((key for key in _VOWEL_KEYS if lowered.startswith(key, position)), None)
        if vowel_key is not None:
            if pending_consonant is not None:
                output.append(pending_consonant)
                matra = _MATRAS[vowel_key]
                if matra:
                    output.append(matra)
                pending_consonant = None
            else:
                output.append(_INDEPENDENT_VOWELS[vowel_key])
            position += len(vowel_key)
            continue

        # Unknown symbol (digit, punctuation, already-Devanagari
        # character, or a Latin letter not covered by the tables above,
        # e.g. 'x', 'q'): preserve it verbatim rather than guessing.
        flush_pending(with_virama=True)
        output.append(word[position])
        position += 1

    # A trailing bare consonant keeps Devanagari's own inherent short
    # "a" sound (no virama) -- matches how a word actually ending in a
    # consonant + implicit vowel is conventionally written.
    flush_pending(with_virama=False)
    return "".join(output)


@dataclass(frozen=True)
class QueryVariant:
    """One candidate query text to retrieve with, plus which
    transformation (if any) produced it. `source` is attached to every
    `RetrievalResult` this variant contributes to (see
    `multi_query_retrieval.py`), so provenance is always inspectable --
    never silently merged away."""

    text: str
    source: str


ORIGINAL_QUERY_SOURCE = "original"
LATIN_TO_DEVANAGARI_SOURCE = "latin_to_devanagari_transliteration"


def generate_query_variants(query: str) -> list[QueryVariant]:
    """Always includes the original query, unchanged. Adds the
    transliterated variant only when it actually differs from the
    original -- e.g. a query already written in Devanagari, or a query
    of only digits/punctuation, transliterates to itself and gets no
    second, redundant retrieval pass. This is a purely mechanical,
    content-blind check (string equality), not a language-detection
    heuristic and not a subject-specific rule.
    """

    variants = [QueryVariant(text=query, source=ORIGINAL_QUERY_SOURCE)]
    transliterated = transliterate_latin_to_devanagari(query)
    if transliterated and transliterated != query:
        variants.append(QueryVariant(text=transliterated, source=LATIN_TO_DEVANAGARI_SOURCE))
    return variants
