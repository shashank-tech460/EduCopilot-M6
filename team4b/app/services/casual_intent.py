"""MVP M6 correction -- deterministic pre-retrieval casual-intent gate.

PROBLEM (live-reproduced, twice): a casual message like "Hi" or "Hi how
are you?" was reaching `HybridRetriever.retrieve()` unconditionally,
occasionally matching some Qdrant/BM25 chunk above `score_threshold`
purely by coincidental embedding similarity, which `response_assembly.py`
then converted into real, workspace-authentic (not fabricated) but
PRODUCT-INCORRECT citations attached to a conversational reply.

FIX (round 2 -- expanded coverage, same architecture): still a single,
pure, deterministic function -- no LLM call, no framework, no
fuzzy/semantic matching, no token-bag/word-set classification -- checked
BEFORE retrieval ever runs. `_CASUAL_MESSAGES` is a deliberately curated,
closed set of WHOLE-PHRASE entries (matched against the entire
normalized query, never a substring/keyword search), organized here by
category purely for readability -- the matching logic itself does not
know or care about categories.

WHY WHOLE-PHRASE MATCHING, NOT A WORD-SET/BAG-OF-WORDS CLASSIFIER:
a "does every word in the message belong to a casual vocabulary" check
was considered and rejected. It cannot correctly satisfy the explicit
requirement that standalone "good" is NOT casual while "good morning" /
"good night" / "good afternoon" / "good evening" ARE -- "good" is a
genuine, necessary word inside several legitimate casual phrases, so a
word-set approach would either wrongly include standalone "good" or
require ad hoc per-word exceptions that reintroduce the same
reactive-patching problem this correction exists to avoid. Whole-phrase
matching against a curated set has no such conflict: "good" alone is
simply not an entry.

DELIBERATELY EXCLUDED (ambiguous, must reach RAG/tutor context, NOT
made casual in M6 -- see the module-level test file and the task's own
explicit list): "yes", "yeah", "yep", "yup", "no", "nope", "ok", "okay",
"done", "good", "great", "sure", "right", "correct", "exactly", and
bare option letters "A"/"B"/"C"/"D". Every one of these can be a
meaningful answer to a tutor/quiz question (e.g. "Which option is
correct?" -> "B"), so none may be swallowed by this gate. Resolving
these correctly requires actual conversation-mode/state awareness (was
the previous turn a quiz question?) -- an explicitly future,
NOT-implemented-here architecture (a conversation-mode router with an
`idle`/`casual`/`academic_qa`/`quiz_active` state machine). Adding any
of them here now would be exactly the kind of premature, ungrounded
guess this module's own design deliberately avoids.
"""

from __future__ import annotations

import re

_CASUAL_MESSAGES: frozenset[str] = frozenset(
    {
        # -- Greetings --
        "hi",
        "hello",
        "hey",
        "hi there",
        "hello there",
        "hey there",
        "good morning",
        "good afternoon",
        "good evening",
        "how are you",
        "how are you doing",
        "how's it going",
        "hows it going",
        "how are things",
        "what's up",
        "whats up",
        "hey how are you",
        "hi how are you",
        "hello how are you",
        "hey how are you doing",
        "hi how are you doing",
        "hello how are you doing",
        # -- Thanks / appreciation --
        "thanks",
        "thank you",
        "thanks a lot",
        "thank you so much",
        "thanks so much",
        "much appreciated",
        "appreciate it",
        "thanks for the help",
        "thank you for the help",
        "thanks for explaining",
        "thank you for explaining",
        # -- Clear acknowledgements (standalone "ok"/"okay" deliberately excluded) --
        "got it",
        "got it thanks",
        "understood",
        "i understand",
        "makes sense",
        "that makes sense",
        "all clear",
        "clear",
        "understood thanks",
        "okay thanks",
        "ok thanks",
        # -- Positive reactions (standalone "good"/"great" deliberately excluded) --
        "nice",
        "awesome",
        "perfect",
        "excellent",
        "cool",
        "great job",
        "nice work",
        "well done",
        "that's great",
        "thats great",
        "that's nice",
        "thats nice",
        "that's interesting",
        "thats interesting",
        "sounds good",
        "looks good",
        "very nice",
        "amazing",
        "wonderful",
        "fantastic",
        # -- Farewells --
        "bye",
        "goodbye",
        "see you",
        "see you later",
        "see you soon",
        "take care",
        "good night",
        "goodnight",
        "talk to you later",
        # -- Polite conversational phrases --
        "please",
        "thanks again",
        "thank you again",
        "no problem",
        "you're welcome",
        "you are welcome",
        "that's helpful",
        "thats helpful",
        "helpful",
        "gotcha",
        # -- MVP M6 correction: clearly casual Hindi/Hinglish phrases
        # (romanized, matching how these actually appear in real
        # Hinglish typing) -- whole-phrase entries, same discipline as
        # every other entry in this set. Deliberately NOT a "Hindi ->
        # casual" language rule: a technical Hinglish query (e.g. "FCFS
        # scheduling kya hai?", "process scheduling kya hota hai?") is
        # simply a different, longer/distinct string that was never a
        # candidate for whole-phrase matching against these entries,
        # exactly the same structural reason "OS?" was never at risk of
        # matching "hi" -- not a separate, additional safety mechanism.
        "hi kaise ho",
        "hello kaise ho",
        "kya haal hai",
        "kaise ho",
        "kaise chal raha hai",
        "dhanyavaad",
        "shukriya",
    }
)

# Strips ALL occurrences (not merely trailing) of these punctuation
# characters -- so "Hey, how are you?" and "hey how are you" normalize
# identically. Apostrophes are deliberately NOT stripped (needed for
# "that's"/"you're" entries above, which are listed alongside their
# apostrophe-free equivalents rather than relying on apostrophe removal).
_PUNCTUATION = re.compile(r"[!?.,]")
_WHITESPACE = re.compile(r"\s+")


def _normalize(query: str) -> str:
    """Lowercases, removes `!?.,` wherever they appear (not just at the
    end), collapses any run of whitespace to a single space, and strips
    leading/trailing whitespace. "Hey, how are you?" and "hey how are
    you" both normalize to "hey how are you"; "OS?" normalizes to "os"
    (still not in the allow-list); "What is an operating system?"
    normalizes to "what is an operating system" (also not in the
    allow-list, independent of the "?").
    """

    without_punctuation = _PUNCTUATION.sub("", query.lower())
    return _WHITESPACE.sub(" ", without_punctuation).strip()


def is_casual_message(query: str) -> bool:
    """Returns True only when the ENTIRE normalized query exactly
    matches one of `_CASUAL_MESSAGES` -- never a substring/keyword
    match. A message that combines a greeting with a substantive
    academic request (e.g. "Hi, what is a process in an operating
    system?", "thanks, now explain process scheduling") normalizes to a
    string that is NOT itself in `_CASUAL_MESSAGES`, so it correctly
    falls through to the normal RAG/academic path -- this is a direct,
    structural consequence of whole-string matching, not a special case.
    """

    return _normalize(query) in _CASUAL_MESSAGES
