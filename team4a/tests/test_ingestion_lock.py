"""Phase 1 tests -- app.pipeline.ingestion_lock.

Uses `fakeredis` -- a real, in-memory Redis-protocol implementation
(including Lua `EVAL` support) -- so the atomic RENEW/RELEASE scripts are
genuinely executed and evaluated, not hand-mocked. This is real evidence
that the Lua scripts themselves are correct, not merely that Python calls
them in the right order.
"""

from __future__ import annotations

import fakeredis
import pytest

from app.pipeline.ingestion_lock import (
    DocumentAlreadyLockedError,
    IngestionLock,
    LockNotOwnedError,
)


@pytest.fixture()
def redis_client():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture()
def lock(redis_client):
    return IngestionLock(redis_client)


# -- Generation issuance -----------------------------------------------------


def test_first_generation_is_one(lock):
    handle = lock.acquire("doc-A", lease_seconds=60)
    assert handle.generation == 1


def test_sequential_generations_are_monotonic(lock):
    h1 = lock.acquire("doc-A", lease_seconds=60)
    lock.release(h1)
    h2 = lock.acquire("doc-A", lease_seconds=60)
    lock.release(h2)
    h3 = lock.acquire("doc-A", lease_seconds=60)
    assert (h1.generation, h2.generation, h3.generation) == (1, 2, 3)


def test_different_documents_have_independent_generation_sequences(lock):
    a1 = lock.acquire("doc-A", lease_seconds=60)
    lock.release(a1)
    a2 = lock.acquire("doc-A", lease_seconds=60)
    b1 = lock.acquire("doc-B", lease_seconds=60)
    assert a2.generation == 2
    assert b1.generation == 1  # doc-B's own independent sequence, not global


def test_a_losing_acquisition_attempt_never_consumes_a_generation_number(lock):
    winner = lock.acquire("doc-A", lease_seconds=60)
    with pytest.raises(DocumentAlreadyLockedError):
        lock.acquire("doc-A", lease_seconds=60)
    lock.release(winner)
    next_handle = lock.acquire("doc-A", lease_seconds=60)
    # If the failed attempt above had consumed a generation number, this
    # would be 3, not 2.
    assert next_handle.generation == 2


# -- Locking: ownership, duplicate acquisition -------------------------------


def test_duplicate_concurrent_ingestion_is_rejected(lock):
    lock.acquire("doc-A", lease_seconds=60)
    with pytest.raises(DocumentAlreadyLockedError):
        lock.acquire("doc-A", lease_seconds=60)


def test_owner_token_is_required_and_unique_per_attempt(lock):
    h1 = lock.acquire("doc-A", lease_seconds=60)
    lock.release(h1)
    h2 = lock.acquire("doc-A", lease_seconds=60)
    assert h1.owner_token != h2.owner_token


def test_correct_owner_can_renew(lock):
    handle = lock.acquire("doc-A", lease_seconds=60)
    lock.renew(handle, lease_seconds=60)  # must not raise


def test_wrong_owner_token_cannot_renew(lock, redis_client):
    handle = lock.acquire("doc-A", lease_seconds=60)
    forged = type(handle)(document_id=handle.document_id, owner_token="not-the-real-token", generation=handle.generation)
    with pytest.raises(LockNotOwnedError):
        lock.renew(forged, lease_seconds=60)


def test_wrong_owner_token_cannot_release(lock, redis_client):
    handle = lock.acquire("doc-A", lease_seconds=60)
    forged = type(handle)(document_id=handle.document_id, owner_token="not-the-real-token", generation=handle.generation)
    lock.release(forged)  # safe no-op, never raises
    # The REAL owner must still be able to renew afterwards -- proving the
    # forged release did not actually delete the real lock.
    lock.renew(handle, lease_seconds=60)


# -- Takeover after lease expiry ----------------------------------------------


def test_expired_lock_can_be_taken_over_by_a_new_worker(lock, redis_client):
    handle = lock.acquire("doc-A", lease_seconds=1)
    redis_client.delete("lock:ingestion:doc-A")  # simulate real TTL expiry deterministically
    new_handle = lock.acquire("doc-A", lease_seconds=60)
    assert new_handle.owner_token != handle.owner_token
    assert new_handle.generation == 2  # the counter kept counting; expiry didn't reset it


def test_old_owner_cannot_release_new_owners_lock_after_takeover(lock, redis_client):
    old_handle = lock.acquire("doc-A", lease_seconds=1)
    redis_client.delete("lock:ingestion:doc-A")
    new_handle = lock.acquire("doc-A", lease_seconds=60)

    lock.release(old_handle)  # must be a safe no-op

    # Prove the new owner's lock survived: it can still be renewed.
    lock.renew(new_handle, lease_seconds=60)


def test_old_owner_cannot_renew_new_owners_lock_after_takeover(lock, redis_client):
    old_handle = lock.acquire("doc-A", lease_seconds=1)
    redis_client.delete("lock:ingestion:doc-A")
    new_handle = lock.acquire("doc-A", lease_seconds=60)

    with pytest.raises(LockNotOwnedError):
        lock.renew(old_handle, lease_seconds=60)

    # New owner's lock is unaffected by the old owner's failed renewal.
    lock.renew(new_handle, lease_seconds=60)


def test_stale_worker_resuming_after_takeover_is_rejected_not_silently_accepted(lock, redis_client):
    """Simulates scenario I/J from the master prompt: a stale worker
    resumes execution (attempts a renew) after a newer worker has already
    taken over -- it must be rejected, never silently treated as still
    valid."""

    stale = lock.acquire("doc-A", lease_seconds=1)
    redis_client.delete("lock:ingestion:doc-A")
    lock.acquire("doc-A", lease_seconds=60)  # a new worker takes over

    with pytest.raises(LockNotOwnedError):
        lock.renew(stale, lease_seconds=60)


# -- Atomic acquisition (Phase 1 final safety correction, Issue 2) -----------


def test_first_acquisition_gets_generation_one(lock):
    handle = lock.acquire("doc-A", lease_seconds=60)
    assert handle.generation == 1


def test_second_sequential_acquisition_gets_generation_two(lock):
    h1 = lock.acquire("doc-A", lease_seconds=60)
    lock.release(h1)
    h2 = lock.acquire("doc-A", lease_seconds=60)
    assert h2.generation == 2


def test_failed_concurrent_acquisition_does_not_increment_the_counter(lock, redis_client):
    winner = lock.acquire("doc-A", lease_seconds=60)  # generation 1

    with pytest.raises(DocumentAlreadyLockedError):
        lock.acquire("doc-A", lease_seconds=60)  # must fail, and must NOT touch the counter

    # Prove it directly against the counter's own raw Redis state, not just
    # by inference from a later acquisition -- the counter must read
    # exactly 1 right now, immediately after the failed attempt.
    assert int(redis_client.get("generation:ingestion:doc-A")) == 1

    lock.release(winner)
    next_handle = lock.acquire("doc-A", lease_seconds=60)
    assert next_handle.generation == 2  # not 3 -- the failed attempt truly consumed nothing


def test_expired_crashed_lock_followed_by_retry_gets_a_new_generation(lock, redis_client):
    crashed = lock.acquire("doc-A", lease_seconds=1)
    redis_client.delete("lock:ingestion:doc-A")  # simulate real TTL expiry deterministically

    retried = lock.acquire("doc-A", lease_seconds=60)

    assert retried.generation == 2
    assert retried.owner_token != crashed.owner_token


def test_lock_ownership_behavior_remains_correct_after_the_atomic_acquire_change(lock, redis_client):
    handle = lock.acquire("doc-A", lease_seconds=60)
    # Renew/release still work exactly as before -- the ACQUIRE change did
    # not touch these code paths at all, re-confirmed here explicitly.
    lock.renew(handle, lease_seconds=60)
    forged = type(handle)(document_id=handle.document_id, owner_token="wrong", generation=handle.generation)
    with pytest.raises(LockNotOwnedError):
        lock.renew(forged, lease_seconds=60)
    lock.release(forged)  # safe no-op
    lock.renew(handle, lease_seconds=60)  # real lock survived the forged release
    lock.release(handle)


def test_concurrent_acquisition_cannot_produce_duplicate_generations(lock):
    """Simulates many racing acquisition attempts (sequential in this
    single-threaded test, since fakeredis is not itself concurrent, but
    each acquisition-then-immediate-release cycle exercises the exact
    same atomic script a true concurrent race would hit) and confirms no
    two attempts ever receive the same generation number."""

    seen_generations = []
    for _ in range(25):
        handle = lock.acquire("doc-A", lease_seconds=60)
        seen_generations.append(handle.generation)
        lock.release(handle)

    assert seen_generations == list(range(1, 26)), "every generation must be unique and strictly increasing"


def test_atomic_acquire_script_never_reaches_incr_on_the_already_locked_path(lock, redis_client):
    """Structural guard: force the lock to already be held via a raw Redis
    SET (bypassing IngestionLock entirely), then confirm acquire() fails
    AND the generation counter remains completely untouched (not merely
    unchanged by coincidence)."""

    redis_client.set("lock:ingestion:doc-A", "some-other-owner", ex=60)
    assert redis_client.exists("generation:ingestion:doc-A") == 0  # counter doesn't exist yet at all

    with pytest.raises(DocumentAlreadyLockedError):
        lock.acquire("doc-A", lease_seconds=60)

    assert redis_client.exists("generation:ingestion:doc-A") == 0, (
        "the generation counter must not be created/incremented at all on a failed acquisition"
    )
