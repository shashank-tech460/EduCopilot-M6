"""Phase 1 tests -- app.pipeline.mongo_authority.

Covers, in order of correction history:
  - the original CAS/monotonicity behavior;
  - the File-creation-prohibition correction (no upsert, MissingFileError);
  - the ObjectId-compatibility correction (this pass): the real Team 4C
    `File._id` is a BSON ObjectId, not a plain string, and `document_id`
    must be normalized to `ObjectId` at the Mongo boundary ONLY, never
    propagated as one anywhere else.

Uses `mongomock` -- an in-memory, pymongo-API-compatible database,
including real BSON `ObjectId` handling -- so this normalization is
genuinely exercised against real BSON typing/equality semantics, not
hand-mocked.

IMPORTANT: these tests prove the CLAIM MECHANISM's ObjectId handling and
ownership boundary are correct in isolation, against a fake Mongo. They do
NOT constitute integration verification against the real Team 4C `File`
collection -- that remains explicitly BLOCKED pending real-environment
live verification (see the Phase 1 live-verification report).
"""

from __future__ import annotations

import mongomock
import pytest
from bson import ObjectId

from app.pipeline.mongo_authority import (
    InvalidDocumentIdError,
    MissingFileError,
    MongoAuthorityClient,
)


@pytest.fixture()
def raw_collection():
    return mongomock.MongoClient()["test_db"]["files"]


@pytest.fixture()
def mongo_client(raw_collection):
    return MongoAuthorityClient(
        mongo_client=raw_collection.database.client,
        database_name="test_db",
        collection_name="files",
    )


def _create_file(raw_collection, object_id: ObjectId, **extra_fields):
    """Simulates a real Team-4C-created File document -- `_id` is a genuine
    `bson.ObjectId`, exactly matching the real Team 4C schema's actual
    storage type (the live finding this correction addresses), never a
    plain string."""

    doc = {"_id": object_id, "workspaceId": "ws-1", "userId": "user-1", "status": "processing"}
    doc.update(extra_fields)
    raw_collection.insert_one(doc)


# -- 1-2: ObjectId conversion at the Mongo boundary --------------------------


def test_string_document_id_converts_correctly_to_object_id_at_the_mongo_boundary(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=0)

    # Team 4A's domain contract: document_id passed in as a plain str
    # (the serialized hex form), exactly as every other Team 4A component
    # (Qdrant payloads, TrustedIdentityContext, the orchestrator) uses it.
    result = mongo_client.claim(document_id=str(real_id), generation=1)

    assert result.succeeded is True
    assert isinstance(result.document_id, str)  # the public contract stays str, never ObjectId
    stored = raw_collection.find_one({"_id": real_id})
    assert stored["currentIngestionGeneration"] == 1


def test_existing_file_with_object_id_id_can_be_claimed_end_to_end(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=0)

    r1 = mongo_client.claim(document_id=str(real_id), generation=1)
    r2 = mongo_client.claim(document_id=str(real_id), generation=2)

    assert (r1.succeeded, r2.succeeded) == (True, True)
    assert raw_collection.find_one({"_id": real_id})["currentIngestionGeneration"] == 2


# -- 3-4: monotonicity, unaffected by the ObjectId correction ----------------


def test_stale_generation_cannot_overwrite_a_newer_authoritative_generation(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=0)
    mongo_client.claim(document_id=str(real_id), generation=11)

    result = mongo_client.claim(document_id=str(real_id), generation=10)

    assert result.succeeded is False
    assert raw_collection.find_one({"_id": real_id})["currentIngestionGeneration"] == 11


def test_equal_generation_retry_succeeds(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=5)

    result = mongo_client.claim(document_id=str(real_id), generation=5)

    assert result.succeeded is True


def test_never_uses_not_equal_semantics(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=11)
    result = mongo_client.claim(document_id=str(real_id), generation=10)
    assert result.succeeded is False


def test_generation_10_then_11_then_12_then_13_sequence(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=0)
    for generation in (10, 11, 12, 13):
        assert mongo_client.claim(document_id=str(real_id), generation=generation).succeeded is True
    assert mongo_client.claim(document_id=str(real_id), generation=10).succeeded is False
    assert mongo_client.claim(document_id=str(real_id), generation=11).succeeded is False


def test_independent_documents_have_independent_authority(mongo_client, raw_collection):
    id_a, id_b = ObjectId(), ObjectId()
    _create_file(raw_collection, id_a, currentIngestionGeneration=0)
    _create_file(raw_collection, id_b, currentIngestionGeneration=0)
    mongo_client.claim(document_id=str(id_a), generation=5)
    result = mongo_client.claim(document_id=str(id_b), generation=1)
    assert result.succeeded is True


def test_claim_generation_1_on_an_existing_file_with_no_generation_field_yet(mongo_client, raw_collection):
    """An existing real File (as every real File is today, pre-migration)
    has no `currentIngestionGeneration` field at all -- the `$lte` filter
    does not match a missing field, so this claim correctly FAILS."""

    real_id = ObjectId()
    _create_file(raw_collection, real_id)  # no currentIngestionGeneration at all
    result = mongo_client.claim(document_id=str(real_id), generation=1)
    assert result.succeeded is False


# -- 5: malformed ObjectId ----------------------------------------------------


@pytest.mark.parametrize(
    "malformed",
    [
        "not-an-object-id",
        "",
        "12345",  # too short
        "zzzzzzzzzzzzzzzzzzzzzzzz",  # right length, non-hex characters
        "doc-A",  # a plain domain-style label, not a Mongo id at all
    ],
)
def test_malformed_document_id_raises_invalid_document_id_error(mongo_client, malformed):
    with pytest.raises(InvalidDocumentIdError):
        mongo_client.claim(document_id=malformed, generation=1)


def test_malformed_document_id_never_issues_a_mongo_query(mongo_client, raw_collection, monkeypatch):
    """No Mongo I/O of any kind for a malformed ID -- verified structurally,
    not just by the exception type."""

    calls = []
    monkeypatch.setattr(raw_collection, "find_one", lambda *a, **k: calls.append(("find_one", a, k)))
    monkeypatch.setattr(raw_collection, "update_one", lambda *a, **k: calls.append(("update_one", a, k)))

    with pytest.raises(InvalidDocumentIdError):
        mongo_client.claim(document_id="not-an-object-id", generation=1)

    assert calls == [], "a malformed document_id must never reach a Mongo query at all"


# -- 6-7: valid but nonexistent ObjectId -- the ownership boundary -----------


def test_nonexistent_valid_object_id_raises_missing_file_error(mongo_client):
    with pytest.raises(MissingFileError):
        mongo_client.claim(document_id=str(ObjectId()), generation=1)


def test_nonexistent_file_creates_nothing(mongo_client, raw_collection):
    nonexistent_id = ObjectId()
    with pytest.raises(MissingFileError):
        mongo_client.claim(document_id=str(nonexistent_id), generation=1)

    assert raw_collection.count_documents({}) == 0
    assert raw_collection.find_one({"_id": nonexistent_id}) is None


def test_nonexistent_file_does_not_affect_other_existing_documents(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=0)

    with pytest.raises(MissingFileError):
        mongo_client.claim(document_id=str(ObjectId()), generation=1)

    assert raw_collection.count_documents({}) == 1
    assert raw_collection.find_one({"_id": real_id})["currentIngestionGeneration"] == 0


# -- 8: no insert/upsert ever occurs ------------------------------------------


def test_the_client_never_calls_insert_one(monkeypatch, raw_collection):
    client = MongoAuthorityClient(raw_collection.database.client, "test_db", "files")

    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=0)  # the ONE legitimate insert, by the test

    original_insert_one = raw_collection.insert_one
    calls = []

    def tracking_insert_one(*args, **kwargs):
        calls.append((args, kwargs))
        return original_insert_one(*args, **kwargs)

    monkeypatch.setattr(raw_collection, "insert_one", tracking_insert_one)

    client.claim(document_id=str(real_id), generation=1)
    for bad_id in (str(ObjectId()), "not-an-object-id"):
        try:
            client.claim(document_id=bad_id, generation=1)
        except (MissingFileError, InvalidDocumentIdError):
            pass

    assert calls == [], "MongoAuthorityClient must never call insert_one, under any code path"


# -- 9: field-scoping -- Team 4A changes ONLY currentIngestionGeneration -----


def test_claim_modifies_only_currentIngestionGeneration_no_other_field(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(
        raw_collection,
        real_id,
        currentIngestionGeneration=0,
        workspaceId="ws-original",
        userId="user-original",
        status="processing",
        originalName="original.pdf",
        type="pdf",
        storageUrl="https://example.com/original.pdf",
        pageCount=7,
    )

    mongo_client.claim(document_id=str(real_id), generation=1)

    stored = raw_collection.find_one({"_id": real_id})
    assert stored["currentIngestionGeneration"] == 1
    assert stored["workspaceId"] == "ws-original"
    assert stored["userId"] == "user-original"
    assert stored["status"] == "processing"
    assert stored["originalName"] == "original.pdf"
    assert stored["type"] == "pdf"
    assert stored["storageUrl"] == "https://example.com/original.pdf"
    assert stored["pageCount"] == 7


def test_a_failed_claim_modifies_no_field_at_all(mongo_client, raw_collection):
    real_id = ObjectId()
    _create_file(raw_collection, real_id, currentIngestionGeneration=11, status="processing")
    mongo_client.claim(document_id=str(real_id), generation=10)

    stored = raw_collection.find_one({"_id": real_id})
    assert stored["currentIngestionGeneration"] == 11
    assert stored["status"] == "processing"
