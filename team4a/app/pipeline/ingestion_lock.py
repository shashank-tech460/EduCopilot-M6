"""Phase 1 -- Ingestion ownership lock and monotonic generation issuance.

Implements exactly the mechanism specified by the approved Rev.4.4
architecture (§8.2, §8.2.1, §8.2.2), and no more:

  - one active ingestion attempt per `document_id` at a time, with a
    monotonically increasing generation number issued ATOMICALLY WITH
    acquisition itself -- both effects produced by a single Redis Lua
    script (`_ACQUIRE_SCRIPT`), corrected in the Phase 1 final safety pass
    from an earlier two-round-trip `SET NX EX` + `INCR` design specifically
    to close the (however narrow) gap between "lock acquired" and
    "generation issued" that two separate operations necessarily left;
  - a dedicated, randomly-generated owner token per attempt, distinct
    from `job_id` and from `document_id`;
  - the generation counter itself lives in a *separate, never-expiring*
    key from the lock -- it must outlive any individual lock's lease,
    since its whole purpose is to keep counting upward across a
    document's entire lifetime, including across re-ingestions;
  - RENEW and RELEASE as single, atomic, owner-checked Lua scripts (never
    a `GET` -> compare -> `EXPIRE`/`DEL` sequence, which has an
    unavoidable gap between the read and the write for another worker to
    intervene in);
  - RENEW doubles as the "mutation gate" this module's callers must
    re-run immediately before every externally-visible mutation (a Qdrant
    publish batch, the delete-old-generations cleanup call, the Mongo
    completion-time claim) -- not merely on a periodic timer.

IMPORTANT -- what this module explicitly does NOT do:

  - Redis is NOT treated as the authority for "which generation is
    currently visible" -- it only issues generation numbers and
    coordinates who is allowed to be working on a document right now.
    MongoDB's `File.currentIngestionGeneration` (see
    `app/pipeline/mongo_authority.py`) is the sole authority for that.
  - This module never talks to Qdrant or Mongo directly -- it is a pure
    Redis-coordination primitive, reused as-is by the orchestration layer
    (`app/pipeline/canonical_ingestion.py`) that actually performs
    mutations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import redis


def _lock_key(document_id: str) -> str:
    return f"lock:ingestion:{document_id}"


def _generation_counter_key(document_id: str) -> str:
    # Deliberately a *different* key from the lock itself, and configured
    # with NO expiry anywhere in this module -- it must keep counting
    # upward for the document's entire lifetime, independent of any one
    # lock's lease.
    return f"generation:ingestion:{document_id}"


# -- Atomic Lua scripts (Rev.4.4 §8.2) --------------------------------------
#
# ACQUIRE: combines the "is the lock free" check, the lock's `SET ... EX`,
# and the generation counter's `INCR` into ONE indivisible server-side
# operation. This is the fix for the prior version's real gap: `SET NX`
# and `INCR` were two separate round trips, which -- while the counter's
# own monotonicity made generation *values* still safe (§8.2.2's original
# reasoning) -- did not satisfy Rev.4.4's actual requirement that
# generation issuance occur atomically WITH acquisition itself, and left
# a window (however narrow) that was not, structurally, a single Redis
# operation. Returns {1, generation} on success, {0, 0} if the lock was
# already held -- and critically, the generation counter is NEVER
# incremented on that failure path, because the script returns before
# ever reaching the INCR call.
_ACQUIRE_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 1 then
    return {0, 0}
end
local generation = redis.call("INCR", KEYS[2])
redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
return {1, generation}
"""

# RENEW: re-confirms ownership and extends the lease in one indivisible
# server-side operation. A return of 0 means the caller no longer owns
# the lock (someone else's SET NX already replaced the value, or the key
# does not exist at all) -- the caller MUST treat this as an unconditional
# signal to stop performing further mutations (see canonical_ingestion.py).
_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""

# RELEASE: deletes the lock only if the caller still, verifiably, owns it
# at the moment of the check-and-delete. A worker that no longer owns the
# lock performs a safe no-op here, never accidentally deleting a newer
# worker's lock.
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


@dataclass(frozen=True)
class LockHandle:
    """Everything a worker needs to carry for the remainder of its execution
    after successfully acquiring the ingestion lock for one `document_id`.
    """

    document_id: str
    owner_token: str
    generation: int


class LockNotOwnedError(RuntimeError):
    """Raised by `renew()`/`release()` when the caller no longer owns the
    lock. Callers MUST treat this as an unconditional signal to stop
    performing further externally-visible mutations for this attempt
    (Rev.4.4 §8.2.1's abort path) -- this is not a transient error to retry.
    """


class DocumentAlreadyLockedError(RuntimeError):
    """Raised by `acquire()` when another attempt already holds the lock
    for this `document_id`. Callers should surface this as `409
    INGESTION_ALREADY_ACTIVE` at the API boundary (a future-phase concern;
    this module itself has no HTTP awareness).
    """


class IngestionLock:
    """One document's ingestion ownership lock plus its generation counter.

    A single instance is stateless with respect to any particular
    document -- `document_id` is passed to every method, so one
    `IngestionLock` (backed by one Redis connection/pool) safely serves
    every concurrent ingestion attempt across every document.
    """

    def __init__(self, redis_client: "redis.Redis") -> None:
        self._redis = redis_client
        # Deliberately NOT `redis_client.register_script(...)`: that helper
        # relies on the server supporting EVALSHA-with-fallback-to-EVAL,
        # which not every Redis-protocol-compatible server implements
        # (confirmed during this phase's own test development against an
        # in-memory Redis double). Calling `eval()` directly, every time,
        # sends the (short, fixed) script text on each call instead of a
        # cached SHA -- a negligible cost for a lock that is acquired/
        # renewed/released a handful of times per ingestion attempt, not a
        # true per-request hot path -- and works against every
        # Redis-protocol server, not only ones that support script caching.
        self._acquire_script_body = _ACQUIRE_SCRIPT
        self._renew_script_body = _RENEW_SCRIPT
        self._release_script_body = _RELEASE_SCRIPT

    def _eval(self, script_body: str, keys: list[str], args: list[object]) -> object:
        return self._redis.eval(script_body, len(keys), *keys, *args)

    def acquire(self, document_id: str, lease_seconds: int) -> LockHandle:
        """Attempt to acquire the ingestion lock for `document_id`.

        CORRECTED (Phase 1 final safety correction, Issue 2): lock
        acquisition and generation issuance now happen as ONE atomic Redis
        Lua script (`_ACQUIRE_SCRIPT`), not two separate round trips. This
        closes the gap between "is the lock free" and "increment the
        generation counter" entirely -- there is no window, of any size,
        in which another client's operations could interleave with this
        one. A failed acquisition (lock already held) returns `{0, 0}`
        from the script and, critically, never reaches the script's own
        `INCR` call at all -- so a failed attempt provably never consumes
        a generation number, verified structurally by the script's own
        control flow, not merely by caller-side discipline.

        Raises `DocumentAlreadyLockedError` if another attempt already
        holds the lock.
        """

        owner_token = uuid.uuid4().hex
        acquired, generation = self._eval(
            self._acquire_script_body,
            keys=[_lock_key(document_id), _generation_counter_key(document_id)],
            args=[owner_token, lease_seconds],
        )
        if not acquired:
            raise DocumentAlreadyLockedError(
                f"An ingestion attempt is already active for document_id={document_id!r}"
            )

        return LockHandle(document_id=document_id, owner_token=owner_token, generation=generation)

    def renew(self, handle: LockHandle, lease_seconds: int) -> None:
        """Atomically re-confirm ownership and extend the lease.

        This is the "mutation gate" callers must invoke immediately
        before each individual externally-visible mutation (not merely on
        a periodic timer) -- see `canonical_ingestion.py`.

        Raises `LockNotOwnedError` if the caller no longer owns the lock.
        Callers MUST treat this as terminal for the current attempt, not
        as a transient failure to retry.
        """

        result = self._eval(
            self._renew_script_body,
            keys=[_lock_key(handle.document_id)],
            args=[handle.owner_token, lease_seconds],
        )
        if not result:
            raise LockNotOwnedError(
                f"Lock for document_id={handle.document_id!r} is no longer owned by "
                f"owner_token={handle.owner_token!r} (lease expired and/or reacquired by another attempt)"
            )

    def release(self, handle: LockHandle) -> None:
        """Atomically release the lock, but ONLY if the caller still owns it.

        A safe no-op if ownership was already lost -- this deliberately
        never raises, since a worker in the abort path (Rev.4.4 §8.2.1)
        explicitly should NOT attempt release at all, and a worker that
        legitimately still owns the lock releasing it is the normal,
        successful-completion case, where a no-op would indicate a bug
        elsewhere worth surfacing via the return value, not an exception.
        """

        self._eval(
            self._release_script_body,
            keys=[_lock_key(handle.document_id)],
            args=[handle.owner_token],
        )
