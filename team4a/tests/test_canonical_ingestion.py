"""Phase 1 tests -- app.pipeline.canonical_ingestion.CanonicalIngestionOrchestrator.

The full Rev.4.4 §17 lifecycle, exercised end-to-end against real
Redis-protocol (fakeredis) and real Mongo-protocol (mongomock) doubles, plus
an in-memory fake Qdrant publish/mutation client -- no live infrastructure
required, but every atomicity-dependent behavior (the Lua lock scripts, the
Mongo compare-and-swap) is genuinely executed, not hand-mocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import fakeredis
import mongomock
import pytest
from bson import ObjectId

from app.models.schemas import JobStatus, PDFSegment
from app.pipeline.canonical_ingestion import (
    CanonicalIngestionInput,
    CanonicalIngestionOrchestrator,
    CanonicalIngestionOutcome,
    TrustedIdentityContext,
)
from app.pipeline.chunker import Chunker
from app.pipeline.ingestion_lock import IngestionLock
from app.pipeline.metadata import MetadataEnricher
from app.pipeline.mongo_authority import MongoAuthorityClient
from app.pipeline.publisher import Publisher, chunk_id_to_point_id

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

# Real Team 4C File._id values are BSON ObjectIds (a live-Mongo finding,
# see the Phase 1 ObjectId-compatibility correction) -- MongoAuthorityClient
# now validates document_id as a serialized ObjectId hex string before
# issuing any Mongo query, so every document_id used in these
# orchestrator-level tests must be a real, valid ObjectId string, not an
# arbitrary readable label like the DOC_A-style placeholders used before
# that correction. Fixed constants (not freshly generated per test run) so
# failure output is stable and greppable across runs.
DOC_A = str(ObjectId("aaaaaaaaaaaaaaaaaaaaaaaa"))
DOC_B = str(ObjectId("bbbbbbbbbbbbbbbbbbbbbbbb"))
DOC_XYZ = str(ObjectId("cccccccccccccccccccccccc"))


class FakeQdrantClient:
    """Implements BOTH QdrantClientProtocol (upsert, for Publisher) and
    QdrantMutationClientProtocol (delete_points_by_id /
    delete_points_by_generation_filter, for canonical_mutations) against a
    single in-memory point store -- letting these tests observe the real,
    end-to-end effect of publish-then-cleanup or publish-then-self-heal on
    one shared, consistent view of "what's actually in the collection".
    """

    def __init__(self):
        self.points_by_collection: dict[str, dict[str, object]] = {}

    def upsert(self, collection_name, points):
        bucket = self.points_by_collection.setdefault(collection_name, {})
        for point in points:
            bucket[point.id] = point
        return {"status": "acknowledged"}

    def delete_points_by_id(self, collection_name, point_ids):
        bucket = self.points_by_collection.get(collection_name, {})
        for pid in point_ids:
            bucket.pop(pid, None)

    def delete_points_by_generation_filter(self, collection_name, document_id, less_than_generation):
        bucket = self.points_by_collection.get(collection_name, {})
        to_delete = [
            pid
            for pid, point in bucket.items()
            if point.payload.get("document_id") == document_id
            and point.payload.get("ingestion_generation", 0) < less_than_generation
        ]
        for pid in to_delete:
            bucket.pop(pid, None)

    def points_for(self, collection_name):
        return list(self.points_by_collection.get(collection_name, {}).values())


def make_settings(**overrides):
    defaults = dict(
        qdrant_collection_name="team4a_ingested_chunks",  # legacy -- must never be written to by this orchestrator
        qdrant_publish_batch_size=100,
        publisher_retry_count=1,
        publisher_initial_backoff_seconds=0.01,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_enriched_chunks(job_id="job-1", filename="doc.pdf", page_numbers=(1, 2)):
    chunker = Chunker()
    enricher = MetadataEnricher()
    enriched = []
    for page in page_numbers:
        segment = PDFSegment(text=f"Distinct content for page {page} of this canonical test document.", page_number=page)
        chunks = chunker.chunk(segment.text)
        enriched.extend(enricher.enrich_pdf_chunks(job_id, filename, NOW, segment, chunks))
    return enriched


@pytest.fixture()
def qdrant():
    return FakeQdrantClient()


@pytest.fixture()
def redis_client():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture()
def mongo_raw():
    return mongomock.MongoClient()


@pytest.fixture()
def mongo_authority(mongo_raw):
    return MongoAuthorityClient(mongo_raw, database_name="test_db", collection_name="files")


def seed_file(mongo_raw, *document_ids: str) -> None:
    """Simulates Team 4C having already created a File document for each
    given `document_id`, BEFORE Team 4A ever attempts a claim against it --
    the real, required ordering per the corrected ownership model
    (Team 4C creates; Team 4A only ever conditionally updates an
    already-existing document, per the audit follow-up correction in
    app.pipeline.mongo_authority). Every orchestrator-level test below
    seeds its document(s) this way, rather than relying on
    MongoAuthorityClient to (incorrectly) create them itself.

    `_id` is stored as a real `bson.ObjectId` -- matching the real Team 4C
    schema's actual storage type (the live-Mongo finding behind the
    ObjectId-compatibility correction) -- not a plain string, even though
    `document_id` itself is always passed around as a `str` everywhere
    else in these tests, exactly matching Team 4A's own domain contract.
    """

    collection = mongo_raw["test_db"]["files"]
    for document_id in document_ids:
        collection.insert_one({"_id": ObjectId(document_id), "currentIngestionGeneration": 0})


def make_orchestrator(qdrant, redis_client, mongo_authority, canonical_collection="educopilot_chunks", lease_seconds=60):
    lock = IngestionLock(redis_client)
    publisher = Publisher(settings=make_settings(), qdrant_client=qdrant)
    return CanonicalIngestionOrchestrator(
        lock=lock,
        publisher=publisher,
        mutation_client=qdrant,
        mongo_authority=mongo_authority,
        canonical_collection_name=canonical_collection,
        lease_seconds=lease_seconds,
    )


def make_input(document_id=DOC_A, workspace_id="ws-1", user_id="user-1", job_id="job-1"):
    enriched = make_enriched_chunks(job_id=job_id)
    embeddings = [[0.1] * 384 for _ in enriched]
    identity = TrustedIdentityContext(document_id=document_id, workspace_id=workspace_id, user_id=user_id)
    return CanonicalIngestionInput(identity=identity, enriched_chunks=enriched, embeddings=embeddings)


# -- A. Identity --------------------------------------------------------------


def test_document_id_workspace_id_user_id_are_preserved_exactly(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_XYZ)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    result = orchestrator.run(make_input(document_id=DOC_XYZ, workspace_id="ws-42", user_id="user-99"))

    assert result.outcome == CanonicalIngestionOutcome.COMPLETED
    points = qdrant.points_for("educopilot_chunks")
    assert points, "expected canonical points to be published"
    for point in points:
        assert point.payload["document_id"] == DOC_XYZ
        assert point.payload["workspace_id"] == "ws-42"
        assert point.payload["user_id"] == "user-99"


def test_job_id_and_ingestion_generation_are_both_present_and_distinct(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    result = orchestrator.run(make_input(document_id=DOC_A, job_id="job-abc"))

    points = qdrant.points_for("educopilot_chunks")
    for point in points:
        assert point.payload["job_id"] == "job-abc"
        assert point.payload["ingestion_generation"] == 1
        assert point.payload["job_id"] != str(point.payload["ingestion_generation"])


def test_source_metadata_remains_intact_alongside_new_identity_fields(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    orchestrator.run(make_input())
    points = qdrant.points_for("educopilot_chunks")
    for point in points:
        assert point.payload["source_type"] == "pdf"
        assert "page_number" in point.payload
        assert "filename" in point.payload
        # And the new fields are present too -- neither list displaced the other.
        assert "document_id" in point.payload
        assert "ingestion_generation" in point.payload


# -- B. Generation --------------------------------------------------------------


def test_first_ingestion_gets_generation_one(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A)
    result = make_orchestrator(qdrant, redis_client, mongo_authority).run(make_input())
    assert result.generation == 1


def test_sequential_re_ingestions_get_increasing_generations(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    r1 = orchestrator.run(make_input(document_id=DOC_A, job_id="job-1"))
    r2 = orchestrator.run(make_input(document_id=DOC_A, job_id="job-2"))
    r3 = orchestrator.run(make_input(document_id=DOC_A, job_id="job-3"))
    assert (r1.generation, r2.generation, r3.generation) == (1, 2, 3)
    assert all(r.outcome == CanonicalIngestionOutcome.COMPLETED for r in (r1, r2, r3))


# -- E. Qdrant ------------------------------------------------------------------


def test_new_points_go_to_canonical_collection_only(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority, canonical_collection="educopilot_chunks")
    orchestrator.run(make_input())
    assert qdrant.points_for("educopilot_chunks"), "expected canonical points"
    assert qdrant.points_for("team4a_ingested_chunks") == [], "legacy collection must receive NO new writes"
    assert qdrant.points_for("team4b_shared_production_chunks") == [], "must never touch 4B's collection either"


def test_point_ids_are_the_existing_deterministic_uuid5_scheme(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A)
    result = make_orchestrator(qdrant, redis_client, mongo_authority).run(make_input())
    points = qdrant.points_for("educopilot_chunks")
    expected_ids = {chunk_id_to_point_id(p.payload["chunk_id"]) for p in points}
    assert {p.id for p in points} == expected_ids


def test_point_ids_do_not_collide_across_generations_for_the_same_document(qdrant, redis_client, mongo_authority, mongo_raw):
    """chunk_id is derived per ingestion attempt (job-scoped) by the
    existing, unmodified Chunker/MetadataEnricher -- confirming Phase 1
    does not introduce a collision even across many re-ingestions of the
    same logical document."""

    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    all_point_ids: set[str] = set()
    for job_id in ("job-1", "job-2", "job-3"):
        result = orchestrator.run(make_input(document_id=DOC_A, job_id=job_id))
        new_points = qdrant.points_for("educopilot_chunks")
        new_ids = {p.id for p in new_points if p.payload["ingestion_generation"] == result.generation}
        assert not (new_ids & all_point_ids), f"point ID collision detected at generation {result.generation}"
        all_point_ids |= new_ids


# -- F. Cleanup -------------------------------------------------------------


def test_successful_generation_removes_only_strictly_older_generations(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    orchestrator.run(make_input(document_id=DOC_A, job_id="job-1"))  # generation 1
    orchestrator.run(make_input(document_id=DOC_A, job_id="job-2"))  # generation 2, should clean up gen 1

    points = qdrant.points_for("educopilot_chunks")
    generations_present = {p.payload["ingestion_generation"] for p in points if p.payload["document_id"] == DOC_A}
    assert generations_present == {2}


def test_another_document_is_untouched_by_cleanup(qdrant, redis_client, mongo_authority, mongo_raw):
    seed_file(mongo_raw, DOC_A, DOC_B)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    # Distinct job_id per call, matching real usage: every real ingestion
    # attempt (even for a different document) always gets a fresh,
    # unique job_id (already guaranteed, pre-Phase-1, by the existing
    # Celery task/job-creation code -- not something this orchestrator
    # introduces or relies on newly). Reusing the same job_id across
    # attempts for different documents, as an earlier draft of this test
    # accidentally did, produced colliding chunk_ids/point_ids purely as
    # a test-fixture artifact -- see the Phase 1 report's Point-ID-Safety
    # section for the full analysis this failure prompted.
    orchestrator.run(make_input(document_id=DOC_A, job_id="job-a1"))
    orchestrator.run(make_input(document_id=DOC_B, job_id="job-b1"))
    orchestrator.run(make_input(document_id=DOC_A, job_id="job-a2"))  # doc-A generation 2

    points = qdrant.points_for("educopilot_chunks")
    doc_b_generations = {p.payload["ingestion_generation"] for p in points if p.payload["document_id"] == DOC_B}
    assert doc_b_generations == {1}, "doc-B must be completely unaffected by doc-A's cleanup"


# -- G. Race / failure --------------------------------------------------------


def test_qdrant_publication_success_but_lost_mongo_claim_self_heals_exact_points_only(
    qdrant, redis_client, mongo_authority, mongo_raw
):
    """The exact scenario named throughout Rev.4.4: publish succeeds, but a
    higher generation already won the Mongo authority race. The losing
    attempt must self-heal by exact point ID and must never touch the
    winner's chunks."""

    # Simulate generation 11 already having won authority for doc-A before
    # generation 10's (this test's) claim attempt.
    seed_file(mongo_raw, DOC_A)
    mongo_authority.claim(document_id=DOC_A, generation=11)

    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    # Force this attempt's lock-issued generation to 10 by pre-consuming
    # generations 1-9 on the same document via the real counter mechanism,
    # then completing (and releasing) nine throwaway attempts so the lock
    # itself is free for this test's real attempt.
    lock = orchestrator._lock  # test-only introspection, not production code
    for _ in range(9):
        handle = lock.acquire(DOC_A, lease_seconds=60)
        lock.release(handle)

    result = orchestrator.run(make_input(document_id=DOC_A))

    assert result.generation == 10
    assert result.outcome == CanonicalIngestionOutcome.ABORTED_AUTHORITY_LOST
    # Every point this losing attempt published must have been deleted.
    remaining = qdrant.points_for("educopilot_chunks")
    assert all(p.payload.get("ingestion_generation") != 10 for p in remaining), (
        "the losing generation's points must be fully self-healed, never left dangling"
    )


def test_concurrent_ingestion_of_the_same_document_is_rejected(qdrant, redis_client, mongo_authority):
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    lock = orchestrator._lock
    handle = lock.acquire(DOC_A, lease_seconds=60)  # simulate an in-flight attempt

    from app.pipeline.ingestion_lock import DocumentAlreadyLockedError

    with pytest.raises(DocumentAlreadyLockedError):
        orchestrator.run(make_input(document_id=DOC_A))

    lock.release(handle)


def test_lock_lost_before_publication_never_mutates_qdrant(qdrant, redis_client, mongo_authority, monkeypatch):
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)

    # Force the mutation gate (renew) to fail on its first call, simulating
    # the lock having been taken over by another worker between acquire()
    # and the first mutation gate check.
    original_renew = orchestrator._lock.renew

    def failing_renew(handle, lease_seconds):
        from app.pipeline.ingestion_lock import LockNotOwnedError

        raise LockNotOwnedError("simulated takeover")

    monkeypatch.setattr(orchestrator._lock, "renew", failing_renew)

    result = orchestrator.run(make_input(document_id=DOC_A))

    assert result.outcome == CanonicalIngestionOutcome.ABORTED_LOCK_LOST
    assert qdrant.points_for("educopilot_chunks") == [], "no mutation may occur once the gate reports lock loss"


def test_worker_crash_then_retry_produces_a_clean_new_generation(qdrant, redis_client, mongo_authority, mongo_raw):
    """Simulates a worker crash (lock lease simply expires, never
    released) followed by a retry -- the retry must succeed cleanly with
    the next generation number, per Rev.4.4's crash/retry semantics."""

    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority, lease_seconds=1)
    lock = orchestrator._lock
    crashed_handle = lock.acquire(DOC_A, lease_seconds=1)
    # Simulate real lease expiry deterministically (fakeredis doesn't
    # advance wall-clock time within a test).
    redis_client.delete(f"lock:ingestion:{DOC_A}")

    result = orchestrator.run(make_input(document_id=DOC_A))

    assert result.outcome == CanonicalIngestionOutcome.COMPLETED
    assert result.generation == 2  # the crashed attempt's generation (1) was never released, but the counter moved on


# -- MissingFileError self-heal (Phase 1 final safety correction, Issue 1) --


def test_missing_file_error_after_publication_self_heals_exact_point_ids(qdrant, redis_client, mongo_authority):
    """The exact scenario the correction names: Qdrant publish succeeds,
    the mutation gate passes, but MongoAuthorityClient.claim() raises
    MissingFileError because no File document exists for this
    document_id. The orchestrator must self-heal by exact point ID --
    never leave the published points dangling."""

    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    # Deliberately do NOT seed a File for DOC_A -- this is the "File does
    # not exist" case.

    result = orchestrator.run(make_input(document_id=DOC_A))

    assert result.outcome == CanonicalIngestionOutcome.ABORTED_MISSING_FILE
    assert result.publication is not None and result.publication.status == JobStatus.COMPLETED, (
        "publication must have genuinely succeeded for this to be the scenario under test"
    )
    remaining = qdrant.points_for("educopilot_chunks")
    assert not any(p.payload.get("document_id") == DOC_A for p in remaining), (
        "every point this attempt published must have been self-healed"
    )


def test_missing_file_error_self_heal_never_touches_another_document(qdrant, redis_client, mongo_authority, mongo_raw):
    """No other document's points may be deleted by this self-heal."""

    seed_file(mongo_raw, DOC_B)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)

    # First, a normal, successful ingestion for DOC_B (a real File exists for it).
    good_result = orchestrator.run(make_input(document_id=DOC_B, job_id="job-good"))
    assert good_result.outcome == CanonicalIngestionOutcome.COMPLETED

    # Then, a MissingFileError attempt for DOC_A (no File seeded for it).
    bad_result = orchestrator.run(make_input(document_id=DOC_A, job_id="job-bad"))
    assert bad_result.outcome == CanonicalIngestionOutcome.ABORTED_MISSING_FILE

    # DOC_B's points must be completely unaffected.
    remaining = qdrant.points_for("educopilot_chunks")
    doc_b_points = [p for p in remaining if p.payload.get("document_id") == DOC_B]
    assert len(doc_b_points) > 0, "doc-B's legitimately-published points must still be present"
    assert not any(p.payload.get("document_id") == DOC_A for p in remaining), "doc-A's points must be self-healed"


def test_missing_file_error_does_not_create_a_mongo_file(qdrant, redis_client, mongo_authority, mongo_raw):
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    orchestrator.run(make_input(document_id=DOC_A))

    files_collection = mongo_raw["test_db"]["files"]
    assert files_collection.count_documents({}) == 0, "no File document may be created as a side effect of this failure"


def test_missing_file_error_writes_no_authority_generation(qdrant, redis_client, mongo_authority):
    """Redundant with the prior test at the collection level, but asserts
    the specific, narrower claim directly: no authority value exists for
    this document_id afterward, under any key."""

    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    orchestrator.run(make_input(document_id=DOC_A))

    with pytest.raises(Exception):  # MissingFileError -- confirms no authority record was ever created
        mongo_authority.claim(document_id=DOC_A, generation=1)


def test_missing_file_error_does_not_incorrectly_release_the_lock(qdrant, redis_client, mongo_authority):
    """The lock must not be released after a MissingFileError -- ownership
    of this attempt is not this orchestrator's to relinquish cleanly, per
    the same reasoning as the lost-authority-race case."""

    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)
    orchestrator.run(make_input(document_id=DOC_A))

    # If the lock had been (incorrectly) released, a fresh acquisition
    # would succeed immediately. Since generation 1's attempt aborted via
    # MissingFileError and did NOT release, the lock is technically still
    # held by that (never-released) handle until its lease naturally
    # expires -- confirmed here by observing a second, immediate
    # acquisition attempt is rejected.
    from app.pipeline.ingestion_lock import DocumentAlreadyLockedError

    with pytest.raises(DocumentAlreadyLockedError):
        orchestrator._lock.acquire(DOC_A, lease_seconds=60)


def test_normal_successful_claim_behavior_is_unchanged_by_this_correction(qdrant, redis_client, mongo_authority, mongo_raw):
    """Regression guard: the happy path (a File genuinely exists) must be
    completely unaffected by wrapping the claim call in a
    MissingFileError handler."""

    seed_file(mongo_raw, DOC_A)
    orchestrator = make_orchestrator(qdrant, redis_client, mongo_authority)

    result = orchestrator.run(make_input(document_id=DOC_A))

    assert result.outcome == CanonicalIngestionOutcome.COMPLETED
    assert result.generation == 1
    assert result.cleanup_attempted is True

