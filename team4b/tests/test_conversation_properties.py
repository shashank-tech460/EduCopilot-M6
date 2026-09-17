"""Task 4.2 -- official ConversationManager correctness properties P13-P14.

    Property 13: Conversation history append round-trip
    Property 14: Conversation window bound

TEST-ONLY task: no production code in `app/services/conversation.py` is
modified here (see the Task 4.2 report for confirmation). These tests
exercise ConversationManager's PUBLIC interface only
(`append_turn`/`get_history`/`get_windowed_history`) against the
existing `FakeRedisClient` from `tests/fakes.py` (reused, not
reimplemented) via the existing `_manager`/`_settings` helpers already
defined in `tests/test_conversation.py` (reused, not duplicated).

ANTI-CIRCULARITY, stated explicitly: in every property below, the
"expected" value is built directly from the Hypothesis-generated raw
input tuples via `ConversationTurn(*tuple)` -- a plain dataclass
constructor call, never a call into `append_turn`, `get_history`,
`get_windowed_history`, or any serialization/deserialization code path.
Python's list slicing (`turns[-window_size:]`) is used to derive P14's
expected window, independently of `get_windowed_history`'s own slicing
logic (`_read_range(start=-size, end=-1)` inside conversation.py) --
same mathematical result, computed by different code, which is exactly
what makes this a genuine check rather than a restatement of the
implementation.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from app.services.conversation import ConversationTurn
from tests.test_conversation import _manager, _settings

_HYP = hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])

# ---------------------------------------------------------------------------
# Shared Hypothesis strategies
# ---------------------------------------------------------------------------

_role = st.sampled_from(["user", "assistant"])

# Arbitrary valid content: Unicode, whitespace, punctuation, quotes,
# newlines, and empty strings are all valid per the actual
# ConversationTurn/ConversationManager contract (no non-empty
# constraint exists anywhere in app/services/conversation.py -- checked
# directly, not assumed).
_content = st.text(min_size=0, max_size=200)

# Valid timestamps per the ConversationTurn contract: finite floats.
# NaN/infinity are excluded -- not because the dataclass itself forbids
# them structurally, but because they are not "valid" conversation data
# in any meaningful sense (a timestamp cannot be NaN), and because
# strict-mode JSON doesn't represent them, which would conflate a
# genuine round-trip property with a JSON-representability property.
_timestamp = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e12, max_value=1e12)

_turn_tuple = st.tuples(_role, _content, _timestamp)

# A valid window size per Settings.conversation_window_size's own
# validation (`gt=0`, checked directly in app/core/config.py) --
# deliberately not inventing a stricter or looser bound than the actual
# configuration constraint.
_valid_window_size = st.integers(min_value=1, max_value=30)


def _expected_turns(raw_tuples: list[tuple[str, str, float]]) -> list[ConversationTurn]:
    """Independent oracle: wraps generated raw tuples directly in
    `ConversationTurn` -- no call into any ConversationManager method,
    no serialization/deserialization involved.
    """

    return [
        ConversationTurn(role=cast(Literal["user", "assistant"], role), content=content, timestamp=timestamp)
        for role, content, timestamp in raw_tuples
    ]


def _append_all(manager: Any, session_id: str, raw_tuples: list[tuple[str, str, float]]) -> None:
    for role, content, timestamp in raw_tuples:
        manager.append_turn(session_id, role, content, timestamp=timestamp)


# ===========================================================================
# Property 13: Conversation history append round-trip
#
# "For any sequence of valid turns appended to a session, retrieving the
#  complete history SHALL return turns with identical role, content, and
#  timestamp, in the exact order appended." (Validates Requirements 4.3,
#  5.2)
# ===========================================================================


class TestPropertyThirteenAppendRoundTrip:
    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=0, max_size=15))
    def test_complete_history_round_trips_exactly(self, turns: list[tuple[str, str, float]]) -> None:
        manager, _client = _manager()
        session_id = "p13-session"

        _append_all(manager, session_id, turns)
        retrieved = manager.get_history(session_id)

        expected = _expected_turns(turns)
        assert retrieved == expected

    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=1, max_size=15))
    def test_round_trip_preserves_append_order_even_when_content_repeats(
        self, turns: list[tuple[str, str, float]]
    ) -> None:
        """Distinguishes ordering from mere set-membership: forces every
        turn to share identical content/timestamp except for a per-index
        marker baked into the role/content pairing, so a shuffle or
        reversal bug would be caught even if Hypothesis happens to draw
        turns that are pairwise very similar.
        """

        manager, _client = _manager()
        session_id = "p13-order-session"
        indexed_turns = [(role, f"{i}:{content}", timestamp) for i, (role, content, timestamp) in enumerate(turns)]

        _append_all(manager, session_id, indexed_turns)
        retrieved = manager.get_history(session_id)

        assert [t.content for t in retrieved] == [f"{i}:{content}" for i, (_role, content, _ts) in enumerate(turns)]

    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=0, max_size=15))
    def test_round_trip_preserves_exact_length(self, turns: list[tuple[str, str, float]]) -> None:
        manager, _client = _manager()
        session_id = "p13-length-session"

        _append_all(manager, session_id, turns)
        retrieved = manager.get_history(session_id)

        assert len(retrieved) == len(turns)

    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=1, max_size=15))
    def test_role_is_never_altered_by_round_trip(self, turns: list[tuple[str, str, float]]) -> None:
        manager, _client = _manager()
        session_id = "p13-role-session"

        _append_all(manager, session_id, turns)
        retrieved = manager.get_history(session_id)

        assert [t.role for t in retrieved] == [role for role, _content, _ts in turns]

    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=1, max_size=15))
    def test_content_is_never_altered_by_round_trip(self, turns: list[tuple[str, str, float]]) -> None:
        manager, _client = _manager()
        session_id = "p13-content-session"

        _append_all(manager, session_id, turns)
        retrieved = manager.get_history(session_id)

        assert [t.content for t in retrieved] == [content for _role, content, _ts in turns]

    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=1, max_size=15))
    def test_timestamp_is_never_altered_by_round_trip(self, turns: list[tuple[str, str, float]]) -> None:
        manager, _client = _manager()
        session_id = "p13-timestamp-session"

        _append_all(manager, session_id, turns)
        retrieved = manager.get_history(session_id)

        assert [t.timestamp for t in retrieved] == [timestamp for _role, _content, timestamp in turns]

    def test_empty_sequence_round_trips_to_empty_history(self) -> None:
        manager, _client = _manager()

        assert manager.get_history("p13-empty-session") == []

    def test_single_turn_round_trip(self) -> None:
        manager, _client = _manager()

        manager.append_turn("p13-single", "user", "hello", timestamp=1.0)

        assert manager.get_history("p13-single") == [ConversationTurn(role="user", content="hello", timestamp=1.0)]

    @_HYP
    @given(
        turns=st.lists(_turn_tuple, min_size=2, max_size=15),
        session_a_id=st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=10),
        session_b_id=st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=10),
    )
    def test_round_trip_holds_independently_per_session(
        self, turns: list[tuple[str, str, float]], session_a_id: str, session_b_id: str
    ) -> None:
        """A weaker global fake-Redis bug (e.g. accidentally sharing
        storage across keys) would be invisible to a single-session
        round-trip test but caught here."""

        if session_a_id == session_b_id:
            session_b_id = session_b_id + "-b"

        manager, _client = _manager()
        _append_all(manager, session_a_id, turns)
        _append_all(manager, session_b_id, turns)

        expected = _expected_turns(turns)
        assert manager.get_history(session_a_id) == expected
        assert manager.get_history(session_b_id) == expected


# ===========================================================================
# Property 14: Conversation window bound
#
# "For any conversation history of length N and configured/explicit
#  window size W, the windowed history returned for downstream prompting
#  SHALL contain at most W turns, corresponding to the W most recent
#  turns in original chronological order, and the complete stored
#  history SHALL remain unaffected." (Validates Requirement 5.3)
# ===========================================================================


class TestPropertyFourteenWindowBound:
    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=0, max_size=20), window_size=_valid_window_size)
    def test_window_never_exceeds_configured_bound(
        self, turns: list[tuple[str, str, float]], window_size: int
    ) -> None:
        manager, _client = _manager()
        session_id = "p14-bound-session"

        _append_all(manager, session_id, turns)
        windowed = manager.get_windowed_history(session_id, window_size=window_size)

        assert len(windowed) <= window_size

    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=0, max_size=20), window_size=_valid_window_size)
    def test_window_contains_exactly_the_most_recent_turns_in_chronological_order(
        self, turns: list[tuple[str, str, float]], window_size: int
    ) -> None:
        manager, _client = _manager()
        session_id = "p14-content-session"

        _append_all(manager, session_id, turns)
        windowed = manager.get_windowed_history(session_id, window_size=window_size)

        # Independent oracle: plain Python slicing on the generated raw
        # tuples, never a call into get_windowed_history or any shared
        # helper -- naturally handles every length relationship (window
        # smaller than, equal to, or larger than history) uniformly,
        # since `list[-W:]` on a list shorter than W returns the whole
        # list. This also directly encodes "most recent, in original
        # chronological order, oldest-of-the-window first" -- e.g. for
        # history=[t1..t6], W=3, this yields [t4, t5, t6], not [t6, t5, t4].
        expected_window = _expected_turns(turns[-window_size:] if window_size > 0 else [])

        assert windowed == expected_window

    @_HYP
    @given(turns=st.lists(_turn_tuple, min_size=0, max_size=20), window_size=_valid_window_size)
    def test_full_history_remains_intact_after_windowed_reads(
        self, turns: list[tuple[str, str, float]], window_size: int
    ) -> None:
        manager, _client = _manager()
        session_id = "p14-integrity-session"

        _append_all(manager, session_id, turns)
        manager.get_windowed_history(session_id, window_size=window_size)
        manager.get_windowed_history(session_id, window_size=window_size)  # a second read, for good measure

        full_history = manager.get_history(session_id)
        assert full_history == _expected_turns(turns)

    @_HYP
    @given(
        turns=st.lists(_turn_tuple, min_size=0, max_size=20),
        configured_window_size=_valid_window_size,
    )
    def test_configured_default_window_size_is_respected_when_not_overridden(
        self, turns: list[tuple[str, str, float]], configured_window_size: int
    ) -> None:
        """Same property as above, but exercising `Settings.conversation_window_size`
        as the source of the bound (no explicit `window_size` argument),
        fuzzing the CONFIGURED value itself rather than a per-call
        override -- proving the property holds regardless of which of
        the two ways a caller can supply a window size.
        """

        manager, _client = _manager(conversation_window_size=configured_window_size)
        session_id = "p14-configured-session"

        _append_all(manager, session_id, turns)
        windowed = manager.get_windowed_history(session_id)  # no window_size argument

        assert len(windowed) <= configured_window_size
        assert windowed == _expected_turns(turns[-configured_window_size:])

    # -- Explicit boundary cases -------------------------------------------

    def test_boundary_empty_history(self) -> None:
        manager, _client = _manager()

        assert manager.get_windowed_history("p14-empty", window_size=5) == []

    def test_boundary_one_turn(self) -> None:
        manager, _client = _manager()
        manager.append_turn("p14-one", "user", "hello", timestamp=1.0)

        windowed = manager.get_windowed_history("p14-one", window_size=5)

        assert windowed == [ConversationTurn(role="user", content="hello", timestamp=1.0)]

    def test_boundary_history_shorter_than_window(self) -> None:
        manager, _client = _manager()
        for i in range(3):
            manager.append_turn("p14-short", "user", f"turn {i}", timestamp=float(i))

        windowed = manager.get_windowed_history("p14-short", window_size=10)

        assert len(windowed) == 3

    def test_boundary_history_equal_to_window(self) -> None:
        manager, _client = _manager()
        for i in range(5):
            manager.append_turn("p14-equal", "user", f"turn {i}", timestamp=float(i))

        windowed = manager.get_windowed_history("p14-equal", window_size=5)

        assert len(windowed) == 5
        assert [t.content for t in windowed] == [f"turn {i}" for i in range(5)]

    def test_boundary_history_larger_than_window(self) -> None:
        manager, _client = _manager()
        for i in range(10):
            manager.append_turn("p14-large", "user", f"turn {i}", timestamp=float(i))

        windowed = manager.get_windowed_history("p14-large", window_size=3)

        assert [t.content for t in windowed] == ["turn 7", "turn 8", "turn 9"]

    def test_boundary_window_size_one(self) -> None:
        manager, _client = _manager()
        for i in range(5):
            manager.append_turn("p14-window-one", "user", f"turn {i}", timestamp=float(i))

        windowed = manager.get_windowed_history("p14-window-one", window_size=1)

        assert [t.content for t in windowed] == ["turn 4"]

    def test_boundary_default_configured_window_size_of_5(self) -> None:
        # Approved default, per Settings.conversation_window_size.
        manager, _client = _manager()  # no override -- uses the real default (5)
        for i in range(8):
            manager.append_turn("p14-default", "user", f"turn {i}", timestamp=float(i))

        windowed = manager.get_windowed_history("p14-default")

        assert len(windowed) == 5
        assert [t.content for t in windowed] == ["turn 3", "turn 4", "turn 5", "turn 6", "turn 7"]

    def test_example_from_task_brief_six_turns_window_three(self) -> None:
        """The exact worked example given in the task instructions:
        history=[t1..t6], W=3 -> [t4, t5, t6], not [t6, t5, t4]."""

        manager, _client = _manager()
        for i in range(1, 7):
            manager.append_turn("p14-example", "user", f"t{i}", timestamp=float(i))

        windowed = manager.get_windowed_history("p14-example", window_size=3)

        assert [t.content for t in windowed] == ["t4", "t5", "t6"]
