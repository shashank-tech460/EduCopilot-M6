"""Focused tests for Task 4.1's ConversationManager.

Scope: unit/integration-style tests (against a genuinely-stateful fake
Redis client) for session creation, append/read behavior, ordering,
serialization/validation, TTL, window bounds, isolation, and error
handling. Explicitly NOT Task 4.2's Property 13/14 tests -- those remain
reserved for that task and are not implemented, labeled, or claimed here.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.services.conversation import (
    ConversationHistoryCorruptionError,
    ConversationManager,
    ConversationStoreUnavailableError,
    ConversationTurn,
    InvalidConversationRoleError,
)
from tests.fakes import FakeRedisClient


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _manager(
    redis_client: FakeRedisClient | None = None, clock: Any = None, **settings_overrides: Any
) -> tuple[ConversationManager, FakeRedisClient]:
    client = redis_client or FakeRedisClient()
    manager = ConversationManager(settings=_settings(**settings_overrides), redis_client=client, clock=clock)
    return manager, client


class _FakeClock:
    """Deterministic, manually-advanced clock for timestamp tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


# ---------------------------------------------------------------------------
# Redis key format
# ---------------------------------------------------------------------------


class TestSessionKeyFormat:
    def test_session_key_matches_official_format(self):
        manager, client = _manager()

        manager.append_turn("abc123", "user", "hello")

        assert client.raw_entries("session:abc123") != []
        assert client.raw_entries("abc123") == []  # not stored under the bare session_id


# ---------------------------------------------------------------------------
# New session / implicit creation
# ---------------------------------------------------------------------------


class TestNewSessionBehavior:
    def test_session_does_not_exist_before_first_append(self):
        manager, _client = _manager()

        assert manager.session_exists("brand-new") is False
        assert manager.get_history("brand-new") == []

    def test_first_append_creates_the_session(self):
        manager, _client = _manager()

        manager.append_turn("s1", "user", "hi")

        assert manager.session_exists("s1") is True

    def test_get_history_on_nonexistent_session_returns_empty_not_error(self):
        manager, _client = _manager()

        assert manager.get_history("never-created") == []

    def test_get_windowed_history_on_nonexistent_session_returns_empty(self):
        manager, _client = _manager()

        assert manager.get_windowed_history("never-created") == []


# ---------------------------------------------------------------------------
# Append user / assistant turns, ordering
# ---------------------------------------------------------------------------


class TestAppendAndOrdering:
    def test_append_user_turn(self):
        manager, _client = _manager()

        turn = manager.append_turn("s1", "user", "What is RAG?")

        assert turn.role == "user"
        assert turn.content == "What is RAG?"
        history = manager.get_history("s1")
        assert len(history) == 1
        assert history[0] == turn

    def test_append_assistant_turn(self):
        manager, _client = _manager()

        turn = manager.append_turn("s1", "assistant", "RAG stands for...")

        assert turn.role == "assistant"
        assert manager.get_history("s1")[0].role == "assistant"

    def test_multiple_turns_preserve_append_order(self):
        manager, _client = _manager()

        manager.append_turn("s1", "user", "first")
        manager.append_turn("s1", "assistant", "second")
        manager.append_turn("s1", "user", "third")

        history = manager.get_history("s1")
        assert [t.content for t in history] == ["first", "second", "third"]

    def test_repeated_appends_remain_correct_over_many_turns(self):
        manager, _client = _manager()

        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            manager.append_turn("s1", role, f"turn {i}")

        history = manager.get_history("s1")
        assert len(history) == 20
        assert [t.content for t in history] == [f"turn {i}" for i in range(20)]
        assert history[0].role == "user"
        assert history[1].role == "assistant"


# ---------------------------------------------------------------------------
# Role validation
# ---------------------------------------------------------------------------


class TestRoleValidation:
    def test_invalid_role_rejected(self):
        manager, _client = _manager()

        with pytest.raises(InvalidConversationRoleError):
            manager.append_turn("s1", "system", "not allowed")  # type: ignore[arg-type]

    def test_empty_string_role_rejected(self):
        manager, _client = _manager()

        with pytest.raises(InvalidConversationRoleError):
            manager.append_turn("s1", "", "content")  # type: ignore[arg-type]

    def test_invalid_role_does_not_write_to_redis(self):
        manager, client = _manager()

        with pytest.raises(InvalidConversationRoleError):
            manager.append_turn("s1", "system", "not allowed")  # type: ignore[arg-type]

        assert client.raw_entries("session:s1") == []


# ---------------------------------------------------------------------------
# Timestamp handling
# ---------------------------------------------------------------------------


class TestTimestampHandling:
    def test_timestamp_defaults_to_injected_clock(self):
        clock = _FakeClock(start=12345.0)
        manager, _client = _manager(clock=clock)

        turn = manager.append_turn("s1", "user", "hi")

        assert turn.timestamp == 12345.0

    def test_explicit_timestamp_overrides_clock(self):
        clock = _FakeClock(start=12345.0)
        manager, _client = _manager(clock=clock)

        turn = manager.append_turn("s1", "user", "hi", timestamp=999.0)

        assert turn.timestamp == 999.0

    def test_timestamp_is_a_float_after_round_trip(self):
        manager, _client = _manager(clock=_FakeClock(start=42.0))

        manager.append_turn("s1", "user", "hi")
        history = manager.get_history("s1")

        assert isinstance(history[0].timestamp, float)

    def test_advancing_clock_produces_increasing_timestamps(self):
        clock = _FakeClock(start=100.0)
        manager, _client = _manager(clock=clock)

        manager.append_turn("s1", "user", "first")
        clock.advance(5.0)
        manager.append_turn("s1", "assistant", "second")

        history = manager.get_history("s1")
        assert history[0].timestamp == 100.0
        assert history[1].timestamp == 105.0


# ---------------------------------------------------------------------------
# Serialization / deserialization, data integrity
# ---------------------------------------------------------------------------


class TestSerializationRoundTrip:
    def test_stored_entry_is_valid_json_with_exact_required_fields(self):
        import json

        manager, client = _manager(clock=_FakeClock(start=1.0))

        manager.append_turn("s1", "user", "hello")

        raw = client.raw_entries("session:s1")[0]
        data = json.loads(raw)
        assert data == {"role": "user", "content": "hello", "timestamp": 1.0}

    def test_round_trip_preserves_unicode_content(self):
        manager, _client = _manager()

        manager.append_turn("s1", "user", "日本語のテスト 🎉")

        assert manager.get_history("s1")[0].content == "日本語のテスト 🎉"

    def test_round_trip_preserves_content_with_embedded_quotes_and_newlines(self):
        manager, _client = _manager()
        tricky_content = 'He said "hello"\nwith a newline and a \\ backslash'

        manager.append_turn("s1", "user", tricky_content)

        assert manager.get_history("s1")[0].content == tricky_content


class TestCorruptedDataHandling:
    def test_malformed_json_raises_corruption_error(self):
        manager, client = _manager()
        client.inject_raw_entry("session:s1", "not valid json{{{")

        with pytest.raises(ConversationHistoryCorruptionError):
            manager.get_history("s1")

    def test_missing_required_field_raises_corruption_error(self):
        manager, client = _manager()
        client.inject_raw_entry("session:s1", '{"role": "user", "content": "hi"}')  # missing timestamp

        with pytest.raises(ConversationHistoryCorruptionError):
            manager.get_history("s1")

    def test_invalid_role_in_stored_data_raises_corruption_error(self):
        manager, client = _manager()
        client.inject_raw_entry("session:s1", '{"role": "system", "content": "hi", "timestamp": 1.0}')

        with pytest.raises(ConversationHistoryCorruptionError):
            manager.get_history("s1")

    def test_non_string_content_raises_corruption_error(self):
        manager, client = _manager()
        client.inject_raw_entry("session:s1", '{"role": "user", "content": 42, "timestamp": 1.0}')

        with pytest.raises(ConversationHistoryCorruptionError):
            manager.get_history("s1")

    def test_non_numeric_timestamp_raises_corruption_error(self):
        manager, client = _manager()
        client.inject_raw_entry("session:s1", '{"role": "user", "content": "hi", "timestamp": "not-a-number"}')

        with pytest.raises(ConversationHistoryCorruptionError):
            manager.get_history("s1")

    def test_json_array_instead_of_object_raises_corruption_error(self):
        manager, client = _manager()
        client.inject_raw_entry("session:s1", "[1, 2, 3]")

        with pytest.raises(ConversationHistoryCorruptionError):
            manager.get_history("s1")

    def test_corruption_is_also_raised_for_windowed_history(self):
        manager, client = _manager()
        client.inject_raw_entry("session:s1", "garbage")

        with pytest.raises(ConversationHistoryCorruptionError):
            manager.get_windowed_history("s1")


# ---------------------------------------------------------------------------
# TTL: configured default, renewal, no permanent TTL
# ---------------------------------------------------------------------------


class TestTTLBehavior:
    def test_ttl_uses_configured_default_of_30_minutes(self):
        manager, client = _manager()  # default session_ttl_minutes = 30

        manager.append_turn("s1", "user", "hi")

        assert client.ttl_for("session:s1") == 30 * 60

    def test_ttl_is_configurable(self):
        manager, client = _manager(session_ttl_minutes=5)

        manager.append_turn("s1", "user", "hi")

        assert client.ttl_for("session:s1") == 5 * 60

    def test_ttl_is_set_on_first_append_not_left_permanent(self):
        manager, client = _manager()

        manager.append_turn("s1", "user", "hi")

        assert client.ttl_for("session:s1") is not None

    def test_ttl_is_renewed_on_every_append(self):
        manager, client = _manager()

        manager.append_turn("s1", "user", "first")
        manager.append_turn("s1", "assistant", "second")

        assert len(client.expire_calls) == 2
        assert all(seconds == 30 * 60 for _key, seconds in client.expire_calls)

    def test_reading_history_does_not_renew_ttl(self):
        manager, client = _manager()
        manager.append_turn("s1", "user", "hi")
        calls_after_append = len(client.expire_calls)

        manager.get_history("s1")
        manager.get_windowed_history("s1")

        assert len(client.expire_calls) == calls_after_append  # unchanged -- reads don't touch TTL


# ---------------------------------------------------------------------------
# Conversation window
# ---------------------------------------------------------------------------


class TestConversationWindow:
    def test_default_window_is_5_turns(self):
        manager, _client = _manager()  # default conversation_window_size = 5
        for i in range(8):
            manager.append_turn("s1", "user", f"turn {i}")

        windowed = manager.get_windowed_history("s1")

        assert len(windowed) == 5
        assert [t.content for t in windowed] == ["turn 3", "turn 4", "turn 5", "turn 6", "turn 7"]

    def test_window_is_configurable(self):
        manager, _client = _manager(conversation_window_size=3)
        for i in range(8):
            manager.append_turn("s1", "user", f"turn {i}")

        windowed = manager.get_windowed_history("s1")

        assert len(windowed) == 3
        assert [t.content for t in windowed] == ["turn 5", "turn 6", "turn 7"]

    def test_explicit_window_size_overrides_configured_default(self):
        manager, _client = _manager(conversation_window_size=5)
        for i in range(8):
            manager.append_turn("s1", "user", f"turn {i}")

        windowed = manager.get_windowed_history("s1", window_size=2)

        assert [t.content for t in windowed] == ["turn 6", "turn 7"]

    def test_window_larger_than_history_returns_everything(self):
        manager, _client = _manager(conversation_window_size=10)
        manager.append_turn("s1", "user", "only turn")

        windowed = manager.get_windowed_history("s1")

        assert len(windowed) == 1

    def test_window_size_zero_returns_empty_list(self):
        manager, _client = _manager()
        manager.append_turn("s1", "user", "hi")

        assert manager.get_windowed_history("s1", window_size=0) == []

    def test_full_history_is_never_trimmed_by_windowed_reads(self):
        manager, _client = _manager(conversation_window_size=2)
        for i in range(10):
            manager.append_turn("s1", "user", f"turn {i}")

        manager.get_windowed_history("s1")  # bounded read
        manager.get_windowed_history("s1")  # again

        full_history = manager.get_history("s1")
        assert len(full_history) == 10  # nothing was ever LTRIM'd away


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


class TestSessionIsolation:
    def test_independent_sessions_do_not_interfere(self):
        manager, _client = _manager()

        manager.append_turn("session-a", "user", "a's message")
        manager.append_turn("session-b", "user", "b's message")

        assert [t.content for t in manager.get_history("session-a")] == ["a's message"]
        assert [t.content for t in manager.get_history("session-b")] == ["b's message"]

    def test_sessions_with_shared_id_prefixes_do_not_interfere(self):
        manager, _client = _manager()

        manager.append_turn("abc", "user", "short id")
        manager.append_turn("abcdef", "user", "longer id sharing a prefix")

        assert len(manager.get_history("abc")) == 1
        assert len(manager.get_history("abcdef")) == 1


# ---------------------------------------------------------------------------
# Error handling: Redis failures
# ---------------------------------------------------------------------------


class TestRedisErrorHandling:
    def test_append_turn_raises_on_redis_failure(self):
        client = FakeRedisClient(fail_times={"pipeline_execute": 1})
        manager, _client = _manager(redis_client=client)

        with pytest.raises(ConversationStoreUnavailableError):
            manager.append_turn("s1", "user", "hi")

    def test_get_history_raises_on_redis_failure(self):
        client = FakeRedisClient(fail_times={"lrange": 1})
        manager, _client = _manager(redis_client=client)

        with pytest.raises(ConversationStoreUnavailableError):
            manager.get_history("s1")

    def test_session_exists_raises_on_redis_failure(self):
        client = FakeRedisClient(fail_times={"exists": 1})
        manager, _client = _manager(redis_client=client)

        with pytest.raises(ConversationStoreUnavailableError):
            manager.session_exists("s1")

    def test_redis_failure_is_not_silently_swallowed(self):
        # Explicit regression guard for the "do not silently swallow
        # Redis failures" instruction: no fallback value is ever
        # returned on failure -- the exception always propagates.
        client = FakeRedisClient(fail_times={"pipeline_execute": 100})
        manager, _client = _manager(redis_client=client)

        for _ in range(3):
            with pytest.raises(ConversationStoreUnavailableError):
                manager.append_turn("s1", "user", "hi")


# ---------------------------------------------------------------------------
# Task 10.1: check_health()
# ---------------------------------------------------------------------------


class TestCheckHealth:
    def test_returns_true_when_ping_succeeds(self):
        client = FakeRedisClient()
        manager, _client = _manager(redis_client=client)

        assert manager.check_health() is True

    def test_returns_false_when_ping_raises(self):
        client = FakeRedisClient(fail_times={"ping": 100})
        manager, _client = _manager(redis_client=client)

        assert manager.check_health() is False

    def test_returns_false_when_ping_responds_false_without_raising(self):
        # A distinct failure mode from an exception: Redis is reachable
        # enough to respond, but PING itself reports unhealthy.
        client = FakeRedisClient(ping_result=False)
        manager, _client = _manager(redis_client=client)

        assert manager.check_health() is False

    def test_never_raises_even_on_repeated_failure(self):
        client = FakeRedisClient(fail_times={"ping": 100})
        manager, _client = _manager(redis_client=client)

        for _ in range(3):
            assert manager.check_health() is False

    def test_does_not_mutate_any_session_state(self):
        client = FakeRedisClient()
        manager, _client = _manager(redis_client=client)
        manager.append_turn("s1", "user", "hi")

        manager.check_health()

        history = manager.get_history("s1")
        assert len(history) == 1  # unaffected -- check_health touched nothing
