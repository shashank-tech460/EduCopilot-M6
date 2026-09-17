"""Phase 1 -- the narrow, explicitly-scoped Mongo generation-authority claim.

Rev.4.4 §15/§16: MongoDB's `File.currentIngestionGeneration` is the SOLE
authoritative record of which generation is currently visible/current for a
document. This module is the only place in Team 4A that ever touches Mongo,
and it touches exactly one field, on exactly one collection, keyed by
`document_id` (= Team 4C's `File._id`). No broader Mongo access is
introduced anywhere by this module or by anything that calls it.

The claim itself is expressed as a single, atomic conditional `update_one`
call using the monotonic filter Rev.4.4 requires:

    currentIngestionGeneration <= my_generation   -> claim succeeds
    currentIngestionGeneration >  my_generation   -> claim fails

Never `!=` -- that condition was explicitly identified as unsafe (it can
let a stale, lower generation's claim attempt match and overwrite a
genuinely newer, already-authoritative generation, purely as an artifact
of the two values happening to differ, regardless of which one is
actually more recent).

CORRECTED (Phase 1 audit follow-up -- ownership boundary):

Team 4C, and only Team 4C, creates `File` documents. Team 4A must never
insert one, under any circumstance, including as a defensive bootstrap.
The previous version of this module violated this: it used
`update_one(..., upsert=True)` as an "idempotent existence bootstrap"
before the real claim, which -- if ever called with a `document_id` that
did not correspond to a real, pre-existing Team 4C `File` -- would create a
minimal, two-field document inside Team 4C's `files` collection. That is
corrected below: `claim()` now performs a read-only existence check first
and raises `MissingFileError` -- without ever writing anything -- if no
File exists. Team 4A's write path can now, structurally, never create a
document, because no `upsert=True` call exists anywhere in this module.

CORRECTED AGAIN (Phase 1 live-Mongo finding -- ObjectId compatibility):

The real Team 4C `File` collection stores `_id` as a BSON `ObjectId`, not
a plain string. Team 4A's own domain/service contract, correctly and
deliberately, represents `document_id` as `str` everywhere outside this
module (Qdrant payloads, `TrustedIdentityContext`, the orchestrator, every
test) -- that representation is NOT changed by this correction. The
incompatibility was narrowly localized to this module's own Mongo query,
which compared a plain Python `str` against a field actually stored as
`ObjectId` -- a comparison that never matches in real MongoDB, regardless
of whether the "right" document exists, because BSON's type-aware
equality does not treat a string and an `ObjectId` with the same
hex characters as equal.

The fix: `claim()` now converts a valid, serialized ObjectId-hex
`document_id` string into a real `bson.ObjectId` immediately before
building each Mongo filter -- and ONLY there, at this one boundary. This
conversion is not stored, cached, or propagated anywhere else; every
public method on this class still accepts and returns plain `str`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymongo
from bson import ObjectId
from bson.errors import InvalidId


class MissingFileError(RuntimeError):
    """Raised by `claim()` when no `File` document exists for `document_id`
    (a well-formed identifier that simply does not correspond to any real
    File -- distinct from `InvalidDocumentIdError`, below, which is raised
    for an identifier that isn't even a validly-shaped Mongo `ObjectId`).

    Team 4A does not, and must never, create a `File` document to recover
    from this -- creation is exclusively Team 4C's responsibility. The
    caller (the canonical-ingestion orchestrator) must treat this as a
    hard failure of the ingestion attempt: no authority can be claimed,
    and Mongo is left completely unmutated by this call.

    This is also the exact condition an EXISTING real `File` document that
    predates the `currentIngestionGeneration` field being added would NOT
    hit -- that document does exist, so the existence check below passes;
    it would instead fail the later compare-and-swap filter (because a
    missing field does not satisfy a `$lte` comparison) and `claim()`
    would return `succeeded=False`, not raise this error. See this
    module's docstring on `claim()` for the full explanation of that
    distinct case, which this phase does not attempt to fix or migrate.
    """


class InvalidDocumentIdError(ValueError):
    """Raised by `claim()` when `document_id` is not a validly-shaped,
    serialized MongoDB `ObjectId` string (e.g. wrong length, non-hex
    characters).

    Raised BEFORE any Mongo query is issued at all -- an invalid shape
    can never correspond to a real document, so there is no reason to
    query, and every reason not to: passing a malformed value into a
    driver-level query could otherwise raise an opaque, lower-level
    `bson.errors.InvalidId` deep inside a query call, or (in some
    driver/version combinations) silently fail to match anything for a
    reason that isn't obvious from the caller's side. Raising a clear,
    named, domain-level error immediately -- and only ever from this one
    validation point, before any I/O -- is the deliberate, minimal fix.
    """


@dataclass(frozen=True)
class AuthorityClaimResult:
    """The outcome of one completion-time authority claim attempt."""

    succeeded: bool
    document_id: str
    generation: int


def _to_object_id(document_id: str) -> ObjectId:
    """The one, single place in this module (and in all of Team 4A) where
    a `document_id` string is ever converted into a Mongo `ObjectId`.

    Never stored, never returned, never propagated past the immediate
    Mongo filter/query it is built for -- every method here still takes
    and returns plain `str`, and Qdrant's own `document_id` payload field
    is completely unaffected (it remains a string, exactly as the
    canonical schema already specifies).
    """

    try:
        return ObjectId(document_id)
    except (InvalidId, TypeError) as exc:
        raise InvalidDocumentIdError(
            f"document_id={document_id!r} is not a valid, serialized MongoDB ObjectId "
            "(expected a 24-character hex string). No Mongo query was issued."
        ) from exc


class MongoAuthorityClient:
    """The one, narrow Mongo client Team 4A is permitted to hold.

    Scoped to exactly `{database}.{collection}.currentIngestionGeneration`,
    keyed by `document_id` (normalized to `ObjectId` only at the query
    boundary, via `_to_object_id`, above). Never used for, and never
    exposes a method for, any other Mongo read or write. Structurally
    incapable of creating a document: no method in this class ever calls
    `update_one`/`find_one_and_update` with `upsert=True`, or `insert_one`,
    at all.
    """

    def __init__(
        self,
        mongo_client: "pymongo.MongoClient",
        database_name: str,
        collection_name: str,
    ) -> None:
        self._collection = mongo_client[database_name][collection_name]

    def claim(self, document_id: str, generation: int) -> AuthorityClaimResult:
        """Attempt to establish `generation` as the authoritative current
        generation for `document_id`.

        Three steps, in order:

        0. Validate `document_id`'s shape and convert it to `ObjectId`
           (`_to_object_id`). If it isn't a validly-shaped ObjectId
           string, raises `InvalidDocumentIdError` immediately -- no
           Mongo query of any kind is issued for a malformed ID.

        1. A read-only existence check (`find_one`, projecting only `_id`
           -- the minimum possible read, never touching any other File
           field). If no document is found, raises `MissingFileError`
           immediately. No write of any kind has occurred by this point.

        2. If (and only if) steps 0-1 both pass: the actual atomic
           compare-and-swap claim, a single `update_one` call with
           `upsert` at its default (`False`) -- it is therefore
           structurally impossible for this call to create a document,
           independent of whether step 1 ran correctly; it can only ever
           conditionally modify a document that already exists. This one
           call is what provides the true, single-operation atomicity
           Rev.4.4 requires (§8.2.2.2) -- there is no window between
           checking the current value and writing the new one for a
           racing claim to slip through.

        Existing File documents that predate `currentIngestionGeneration`
        being added: step 1's existence check passes (the document
        exists), so no error is raised here. Step 2's filter,
        `{"currentIngestionGeneration": {"$lte": generation}}`, does NOT
        match a document where that field is entirely absent (MongoDB's
        `$lte` does not treat a missing field as satisfying the
        comparison) -- so `claim()` returns `succeeded=False` for every
        such File, every time, until Team 4C's own migration adds the
        field. This is a safe, conservative, fail-closed consequence of
        the design, not a new behavior added to compensate for it -- Team
        4A does not detect this case specially, does not default the
        field, and does not treat it as equivalent to `MissingFileError`.
        Backfilling `currentIngestionGeneration = 0` onto pre-existing
        File documents remains explicitly a Team 4C/Mongo migration
        concern, not performed by this module, and NOT performed as part
        of this correction either.
        """

        mongo_id = _to_object_id(document_id)

        existing = self._collection.find_one({"_id": mongo_id}, {"_id": 1})
        if existing is None:
            raise MissingFileError(
                f"No File document exists for document_id={document_id!r}. "
                "Team 4A does not create File documents -- this document_id must "
                "already exist as a Team-4C-created File before an authority claim "
                "can be attempted."
            )

        update_result = self._collection.update_one(
            filter={
                "_id": mongo_id,
                "currentIngestionGeneration": {"$lte": generation},
            },
            update={"$set": {"currentIngestionGeneration": generation}},
        )
        succeeded = update_result.matched_count == 1
        return AuthorityClaimResult(succeeded=succeeded, document_id=document_id, generation=generation)


