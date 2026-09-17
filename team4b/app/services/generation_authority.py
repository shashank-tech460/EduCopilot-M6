"""MVP M4 -- Team 4B's read-only Mongo generation-authority component.

============================================================
THE NARROW ARCHITECTURE EXCEPTION THIS MODULE EXISTS TO SATISFY
============================================================

Team 4C is the system of record; Team 4B does not otherwise touch Mongo
at all. The approved architecture carves out ONE narrow, explicit
exception: Team 4B may READ `File.currentIngestionGeneration` from
Team 4C's own `files` collection, to determine which ingestion
generation of a document is currently authoritative, so stale
(superseded, not-yet-cleaned-up) Qdrant chunks never enter retrieval.

This module is the ENTIRE surface of that exception:

  - `GenerationAuthorityClient.get_current_generations()` is the ONLY
    method here that touches Mongo, and it only ever issues a single,
    read-only `find()` query against `File`, restricted to
    `_id in {candidate document_ids}` AND `workspaceId == <the already-
    authenticated workspace>`.
  - There is no method here, or anywhere else in this codebase, that
    writes, creates, or mutates a `File` document, a user, or a
    workspace. `pymongo`'s write methods (`insert_one`, `update_one`,
    `delete_one`, etc.) are never called on the collection object this
    class holds.
  - `Settings.mongo_url`/`mongo_database_name`/`mongo_files_collection_name`
    (app/core/config.py) are the only Mongo configuration Team 4B has.

============================================================
FAIL-CLOSED CONTRACT
============================================================

`get_current_generations()` returns a `dict[str, int]` mapping ONLY the
document_ids it could positively, freshly verify as belonging to the
given workspace and having a valid `currentIngestionGeneration`. Every
failure mode -- Mongo unavailable, timeout, the File not found, a
malformed `document_id`, a missing/null/non-integer
`currentIngestionGeneration` -- results in that document_id being
ABSENT from the returned mapping, never present with a guessed,
fallback, or Qdrant-derived value. Callers (`HybridRetriever`) MUST
treat "not in the returned mapping" as "exclude this candidate" -- this
module never raises for an individual bad candidate (only for a total
Mongo connection failure, see below), specifically so one malformed ID
among many candidates cannot abort the whole batch.

A total failure to reach Mongo at all (connection refused, DNS failure,
etc. -- as opposed to a per-document lookup simply not finding anything)
raises `GenerationAuthorityUnavailableError`. `HybridRetriever` catches
this and treats it exactly like "every candidate in this batch failed to
verify" -- i.e., still fail-closed, never a fallback to trusting
unverified candidates.

============================================================
FRESHNESS / CONSISTENCY
============================================================

No result is ever cached across calls -- there is no cache of any kind
in this class, module-level or instance-level. Every call to
`get_current_generations()` issues a brand-new Mongo query. `pymongo`'s
own default read preference is `PRIMARY` (strong consistency) unless a
client explicitly overrides it -- this module never does, and the
verifying test (`tests/test_generation_authority.py`) asserts this
directly against the constructed `MongoClient`.

============================================================
IDENTITY / OBJECTID CONVERSION
============================================================

Team 4C's `File._id`/`File.workspaceId` are both BSON `ObjectId` in the
real database (confirmed directly against `models/File.ts`); Team 4B's
own domain representation of both `document_id` and `workspace_id`
remains a plain `str` everywhere outside this module, exactly mirroring
Team 4A's own, already-approved `mongo_authority.py` boundary pattern
(no code is shared between the two separate repositories, but the
CONVERSION DISCIPLINE is identical, deliberately, per the instruction
not to introduce a second, inconsistent conversion mechanism):
`_to_object_id()` below is the one and only place this module ever
constructs an `ObjectId`, and a malformed string is rejected immediately
(the affected document_id is simply excluded from the batch), never
passed through to the Mongo driver in a way that could cause an
unexpected query shape or an unhandled driver-level exception.
"""

from __future__ import annotations

import logging

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


class GenerationAuthorityUnavailableError(RuntimeError):
    """Raised only for a TOTAL failure to reach Mongo at all (connection
    error, timeout at the connection level, server selection failure) --
    never for an individual candidate simply not being found or having
    invalid data, which are handled by omitting that one document_id from
    the returned mapping instead. Callers must treat this the same as
    "no candidates verified" -- fail closed, never fall back to trusting
    unverified candidates. The message is safe to log (no connection
    string, no credentials) -- see `__str__`.
    """

    def __init__(self) -> None:
        super().__init__(
            "Generation authority Mongo lookup failed -- treating all candidates in this "
            "batch as unverified (fail-closed)."
        )


def _to_object_id(value: str) -> ObjectId | None:
    """The one, single place this module ever constructs an `ObjectId`.
    Returns `None` (never raises) for anything not a validly-shaped,
    24-character-hex ObjectId string -- callers treat `None` as "this
    identity cannot be resolved", which for `document_id` means "exclude
    this one candidate" and for `workspace_id` (always the already-
    authenticated JWT value, never caller-supplied per-candidate) would
    indicate a deeper, real bug upstream, not a normal per-candidate
    condition.
    """

    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


class GenerationAuthorityClient:
    """The narrow, read-only Mongo client described in this module's
    docstring. Holds a live `pymongo.MongoClient` (constructed once, like
    `VectorStoreManager`'s own Qdrant client) -- but every
    `get_current_generations()` call issues a fresh query; nothing about
    the RESULT is ever cached.
    """

    def __init__(self, mongo_client: MongoClient, database_name: str, collection_name: str) -> None:
        self._collection = mongo_client[database_name][collection_name]

    def get_current_generations(self, document_ids: set[str], *, workspace_id: str) -> dict[str, int]:
        """Batched, workspace-scoped, fresh authority read.

        Returns `{document_id: current_generation}` for exactly the
        subset of `document_ids` that:
          1. are validly-shaped ObjectId strings,
          2. correspond to a real `File` document,
          3. that `File` belongs to `workspace_id` (also validated as a
             real ObjectId -- if it is not, EVERY candidate in this call
             fails closed, since that indicates a deeper bug, not a
             per-candidate condition),
          4. and that `File` has a valid (present, non-null, integer)
             `currentIngestionGeneration`.

        Every other document_id is simply absent from the returned dict
        -- this method never raises for an individual bad candidate.
        """

        if not document_ids:
            return {}

        workspace_object_id = _to_object_id(workspace_id)
        if workspace_object_id is None:
            logger.warning("Generation authority lookup: workspace_id is not a valid ObjectId; excluding all candidates")
            return {}

        # Malformed document_ids are excluded individually here, BEFORE
        # ever reaching the Mongo query -- never passed through as raw
        # strings for the driver/server to reject at query time.
        object_id_by_document_id: dict[str, ObjectId] = {}
        for document_id in document_ids:
            object_id = _to_object_id(document_id)
            if object_id is not None:
                object_id_by_document_id[document_id] = object_id
            else:
                logger.warning("Generation authority lookup: excluding malformed document_id", extra={"document_id": document_id})

        if not object_id_by_document_id:
            return {}

        try:
            # Single, bounded, batched read -- never one query per
            # candidate. `read_preference` is left at pymongo's own
            # default (PRIMARY) deliberately -- never overridden to a
            # secondary/eventually-consistent preference anywhere in
            # this module.
            cursor = self._collection.find(
                {
                    "_id": {"$in": list(object_id_by_document_id.values())},
                    "workspaceId": workspace_object_id,
                },
                projection={"_id": 1, "currentIngestionGeneration": 1},
            )
            documents = list(cursor)
        except PyMongoError as exc:
            logger.error("Generation authority Mongo lookup failed", extra={"error": str(exc)})
            raise GenerationAuthorityUnavailableError() from exc

        object_id_to_document_id = {v: k for k, v in object_id_by_document_id.items()}

        result: dict[str, int] = {}
        for document in documents:
            document_id = object_id_to_document_id.get(document["_id"])
            if document_id is None:
                continue  # defensive; cannot actually happen given the query's own $in filter
            generation = document.get("currentIngestionGeneration")
            if not isinstance(generation, int) or isinstance(generation, bool):
                # Missing/null/non-integer currentIngestionGeneration
                # (including a pre-migration File that genuinely lacks
                # the field at all) -- fail closed for this one
                # document_id, not the whole batch. `bool` is explicitly
                # excluded despite being a subclass of `int` in Python --
                # a stray `True`/`False` value is not a valid generation
                # number under any real circumstance.
                logger.warning(
                    "Generation authority: File has missing/invalid currentIngestionGeneration; excluding",
                    extra={"document_id": document_id},
                )
                continue
            result[document_id] = generation

        return result
