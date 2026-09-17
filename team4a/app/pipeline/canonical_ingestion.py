"""Phase 1 -- the canonical ingestion orchestrator.

This module is the ONLY new orchestration layer Phase 1 introduces. It sits
strictly AROUND the existing, frozen, unmodified pipeline stages -- it never
reimplements extraction, transcription, chunking, or embedding, and it
never mutates `MetadataEnricher`'s own output in place (it produces NEW
`EnrichedChunk`/`ChunkMetadata` instances via `.model_copy(update=...)`,
leaving the originals, and every existing test that constructs them,
completely unaffected).

Lifecycle implemented here (Rev.4.4 §17, exactly, in order):

    1. acquire the per-document ingestion lock; receive generation N
    2. (existing, unchanged) extraction -> chunking -> embedding happens
       BEFORE this orchestrator is even called -- see `CanonicalIngestionInput`
    3. attach document_id/workspace_id/user_id/ingestion_generation to
       each chunk's metadata (identity enrichment)
    4. mutation-gate check, then publish generation-N chunks to
       `educopilot_chunks` (never the legacy collection)
    5. mutation-gate check, then attempt the Mongo completion-time claim
    6a. SUCCESS -> run monotonic cleanup of generations < N, release the lock
    6b. FAILURE (lost the authority race, OR MongoAuthorityClient raises
        MissingFileError because no File exists for this document_id) ->
        self-heal by deleting exactly the points just published, mark the
        attempt aborted, do NOT release the lock (it is not this worker's
        lock anymore -- Rev.4.4 §8.2.1/§8.2.2.2)

IMPORTANT, explicit per the governing Phase 1 contract:

    MongoDB's `File.currentIngestionGeneration` is the authority this
    module claims against. As of this Phase 1 pass, Team 4C's actual
    `File` Mongoose schema (`models/File.ts`, inspected read-only) does
    NOT contain this field -- see the Phase 1 report's §6/§14 for the
    full analysis. This module is fully implemented and unit-tested
    against a real MongoDB-protocol double (mongomock), but its
    integration against the REAL Team 4C File collection is explicitly
    BLOCKED pending the documented, cross-team-approved schema addition.
    No workaround, substitute authority, or silent Team 4C modification
    was introduced to route around this.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from app.models.schemas import ChunkMetadata, EnrichedChunk, JobStatus, PublicationResult
from app.pipeline.canonical_mutations import (
    QdrantMutationClientProtocol,
    delete_exact_points,
    delete_older_generations,
)
from app.pipeline.ingestion_lock import IngestionLock, LockHandle, LockNotOwnedError
from app.pipeline.mongo_authority import MissingFileError, MongoAuthorityClient
from app.pipeline.publisher import Publisher, chunk_id_to_point_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrustedIdentityContext:
    """The identity values a trusted internal caller supplies for one
    ingestion attempt.

    Rev.4.4 provenance rule, enforced by this dataclass's own field
    names/types, not merely documented: `document_id` is caller-supplied
    resource identity (= Team 4C's `File._id`); `workspace_id`/`user_id`
    are caller-supplied tenant/actor identity (the eventual verified JWT
    claim). NONE of these are derived, generated, or defaulted by Team 4A
    anywhere in this module -- every field here is required, with no
    default, so a caller cannot accidentally omit one and have Team 4A
    silently fabricate a value.

    Phase 1 does NOT implement the JWT verification that will eventually
    populate this object in production -- constructing one today requires
    an explicit, visible call site (see `tests/test_canonical_ingestion.py`
    for the test-only construction pattern) that a future JWT-verification
    middleware replaces, without requiring any change to this dataclass or
    to `CanonicalIngestionOrchestrator` itself.
    """

    document_id: str
    workspace_id: str
    user_id: str


@dataclass(frozen=True)
class CanonicalIngestionInput:
    """Output of the existing, unmodified extraction/chunking/embedding
    pipeline, paired with the identity this attempt is being made under.

    `enriched_chunks`/`embeddings` are exactly what
    `app.pipeline.publisher.Publisher.publish()` already accepts today --
    this orchestrator does not reshape or reinterpret them, it only
    enriches their metadata with identity fields before handing them to
    the existing, unchanged `Publisher`.
    """

    identity: TrustedIdentityContext
    enriched_chunks: list[EnrichedChunk]
    embeddings: list[list[float]]


class CanonicalIngestionOutcome(str, Enum):
    COMPLETED = "completed"
    ABORTED_LOCK_LOST = "aborted_lock_lost"
    ABORTED_AUTHORITY_LOST = "aborted_authority_lost"
    ABORTED_MISSING_FILE = "aborted_missing_file"


@dataclass(frozen=True)
class CanonicalIngestionResult:
    outcome: CanonicalIngestionOutcome
    document_id: str
    generation: int
    published_point_ids: list[str]
    publication: PublicationResult | None
    cleanup_attempted: bool


class CanonicalIngestionOrchestrator:
    """Ties together the ingestion lock, canonical publication, and the
    Mongo completion-time authority claim -- the full Rev.4.4 §17
    lifecycle -- around the existing, unmodified publish/embedding stages.
    """

    def __init__(
        self,
        lock: IngestionLock,
        publisher: Publisher,
        mutation_client: QdrantMutationClientProtocol,
        mongo_authority: MongoAuthorityClient,
        canonical_collection_name: str,
        lease_seconds: int,
    ) -> None:
        self._lock = lock
        self._publisher = publisher
        self._mutation_client = mutation_client
        self._mongo_authority = mongo_authority
        self._collection = canonical_collection_name
        self._lease_seconds = lease_seconds

    def run(self, ingestion_input: CanonicalIngestionInput) -> CanonicalIngestionResult:
        identity = ingestion_input.identity

        # Step 1: acquire the per-document lock; receive generation N.
        # DocumentAlreadyLockedError is intentionally allowed to propagate
        # uncaught -- the caller (a future API/task boundary) maps it to
        # `409 INGESTION_ALREADY_ACTIVE`; this orchestrator has no HTTP
        # awareness of its own.
        handle = self._lock.acquire(identity.document_id, self._lease_seconds)

        try:
            # Step 3: identity enrichment. Never mutates the input chunks
            # in place -- produces new EnrichedChunk/ChunkMetadata
            # instances via model_copy, leaving MetadataEnricher's own
            # output (and every existing test asserting its shape)
            # completely untouched.
            canonical_chunks = [
                self._attach_identity(chunk, identity, handle.generation)
                for chunk in ingestion_input.enriched_chunks
            ]
            point_ids = [chunk_id_to_point_id(chunk.metadata.chunk_id) for chunk in canonical_chunks]

            # Step 4: mutation gate, then publish to the CANONICAL
            # collection only -- collection_name_override is what
            # guarantees this can never write to the legacy collection.
            try:
                self._lock.renew(handle, self._lease_seconds)
            except LockNotOwnedError:
                logger.warning(
                    "Lock lost before publication began; aborting without mutating Qdrant",
                    extra={"document_id": identity.document_id, "generation": handle.generation},
                )
                return CanonicalIngestionResult(
                    outcome=CanonicalIngestionOutcome.ABORTED_LOCK_LOST,
                    document_id=identity.document_id,
                    generation=handle.generation,
                    published_point_ids=[],
                    publication=None,
                    cleanup_attempted=False,
                )

            publication = self._publisher.publish(
                canonical_chunks, ingestion_input.embeddings, collection_name_override=self._collection
            )

            if publication.status != JobStatus.COMPLETED:
                # Publisher's own existing retry/backoff/publish_failed
                # contract already ran and exhausted itself -- this is a
                # genuine publish failure, not a lock-loss race. Whatever
                # partial batches succeeded before the failure are
                # self-healed by exact point ID, same as a lost-authority
                # claim, since they must not be left dangling as
                # unclaimed, un-authoritative chunks either.
                logger.error(
                    "Canonical publication failed; self-healing any partially-published points",
                    extra={"document_id": identity.document_id, "generation": handle.generation},
                )
                delete_exact_points(self._mutation_client, self._collection, point_ids)
                return CanonicalIngestionResult(
                    outcome=CanonicalIngestionOutcome.ABORTED_LOCK_LOST,
                    document_id=identity.document_id,
                    generation=handle.generation,
                    published_point_ids=[],
                    publication=publication,
                    cleanup_attempted=False,
                )

            # Step 5: mutation gate, then the completion-time Mongo claim.
            try:
                self._lock.renew(handle, self._lease_seconds)
            except LockNotOwnedError:
                logger.warning(
                    "Lock lost after publication but before the authority claim; self-healing",
                    extra={"document_id": identity.document_id, "generation": handle.generation},
                )
                delete_exact_points(self._mutation_client, self._collection, point_ids)
                return CanonicalIngestionResult(
                    outcome=CanonicalIngestionOutcome.ABORTED_LOCK_LOST,
                    document_id=identity.document_id,
                    generation=handle.generation,
                    published_point_ids=point_ids,
                    publication=publication,
                    cleanup_attempted=False,
                )

            claim = None
            try:
                claim = self._mongo_authority.claim(identity.document_id, handle.generation)
            except MissingFileError:
                # CORRECTED (Phase 1 final safety correction, Issue 1):
                # previously, MissingFileError could propagate straight
                # out of run() uncaught, leaving whatever this attempt had
                # just published sitting in Qdrant with no authority claim
                # and no self-heal -- exactly the dangling-chunks defect
                # this correction closes. Treated identically, in every
                # respect that matters, to a lost authority-claim race:
                # exact-point-ID self-heal only, no Mongo File is
                # created/upserted (MongoAuthorityClient's own claim()
                # already guarantees this on its own, unchanged, per its
                # own fail-closed contract -- this except block adds no
                # new Mongo interaction of any kind), no authority
                # generation is ever written, and the lock is NOT
                # released (Rev.4.4 §8.2.1: ownership of this attempt is
                # already effectively lost/invalid -- a File that doesn't
                # exist can never become authoritative, so releasing
                # cleanly as if this were a normal successful completion
                # would misrepresent what happened).
                logger.error(
                    "Mongo authority claim failed: no File document exists for this document_id; "
                    "self-healing published points -- Team 4A never creates a File to recover from this",
                    extra={"document_id": identity.document_id, "generation": handle.generation},
                )
                delete_exact_points(self._mutation_client, self._collection, point_ids)
                return CanonicalIngestionResult(
                    outcome=CanonicalIngestionOutcome.ABORTED_MISSING_FILE,
                    document_id=identity.document_id,
                    generation=handle.generation,
                    published_point_ids=point_ids,
                    publication=publication,
                    cleanup_attempted=False,
                )

            if not claim.succeeded:
                # Step 6b: a higher generation already won. Self-heal by
                # EXACT point ID only -- never a filter, never a range,
                # and never dependent on knowing anything about whoever
                # superseded this attempt.
                logger.warning(
                    "Mongo authority claim lost to a newer generation; self-healing",
                    extra={"document_id": identity.document_id, "generation": handle.generation},
                )
                delete_exact_points(self._mutation_client, self._collection, point_ids)
                return CanonicalIngestionResult(
                    outcome=CanonicalIngestionOutcome.ABORTED_AUTHORITY_LOST,
                    document_id=identity.document_id,
                    generation=handle.generation,
                    published_point_ids=point_ids,
                    publication=publication,
                    cleanup_attempted=False,
                )

            # Step 6a: confirmed winner. Mutation gate once more, then run
            # the monotonic (`<`, never `!=`) housekeeping cleanup. A
            # cleanup failure does not undo the already-successful claim
            # or publication -- correctness never depended on cleanup
            # succeeding (Rev.4.4's governing separation of correctness
            # from physical cleanup); it is logged and surfaced via
            # `cleanup_attempted=False`, not silently swallowed.
            cleanup_attempted = False
            try:
                self._lock.renew(handle, self._lease_seconds)
                delete_older_generations(
                    self._mutation_client,
                    self._collection,
                    identity.document_id,
                    current_generation=handle.generation,
                )
                cleanup_attempted = True
            except LockNotOwnedError:
                logger.warning(
                    "Lock lost before cleanup could run; authority claim remains valid, "
                    "cleanup deferred to a future successful generation's own housekeeping",
                    extra={"document_id": identity.document_id, "generation": handle.generation},
                )
            except Exception:  # noqa: BLE001 -- cleanup failure must never mask a successful claim
                logger.exception(
                    "Old-generation cleanup failed; authority claim remains valid regardless",
                    extra={"document_id": identity.document_id, "generation": handle.generation},
                )

            self._lock.release(handle)

            return CanonicalIngestionResult(
                outcome=CanonicalIngestionOutcome.COMPLETED,
                document_id=identity.document_id,
                generation=handle.generation,
                published_point_ids=point_ids,
                publication=publication,
                cleanup_attempted=cleanup_attempted,
            )
        except LockNotOwnedError:
            # Defensive: any other, not-explicitly-anticipated call site
            # in this method that raises LockNotOwnedError still results
            # in a clean abort, never a silent continuation.
            logger.warning(
                "Lock ownership lost during canonical ingestion; aborting",
                extra={"document_id": identity.document_id, "generation": handle.generation},
            )
            return CanonicalIngestionResult(
                outcome=CanonicalIngestionOutcome.ABORTED_LOCK_LOST,
                document_id=identity.document_id,
                generation=handle.generation,
                published_point_ids=[],
                publication=None,
                cleanup_attempted=False,
            )

    @staticmethod
    def _attach_identity(
        chunk: EnrichedChunk, identity: TrustedIdentityContext, generation: int
    ) -> EnrichedChunk:
        new_metadata: ChunkMetadata = chunk.metadata.model_copy(
            update={
                "document_id": identity.document_id,
                "workspace_id": identity.workspace_id,
                "user_id": identity.user_id,
                "ingestion_generation": generation,
            }
        )
        return chunk.model_copy(update={"metadata": new_metadata})
