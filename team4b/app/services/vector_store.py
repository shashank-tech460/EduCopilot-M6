"""Team 4B Vector_Store layer (Task 2.1).

Implements Requirement 1 (Vector Database Management) against the shared
production Qdrant collection, per the approved Final Architecture/
Contract Checkpoint:

    Team 4A ingestion -> shared production Qdrant collection
        -> Team 4B VectorStoreManager -> (later) HybridRetriever/RAG

Team 4B reads Team 4A's actual, already-published records directly out of
this shared collection. There is no republishing/synchronization
pipeline, and this module never modifies Team 4A or Team 4C.

SCOPE NOTE (Task 2.1 only): this module implements VectorStoreManager and
its own read-side normalization adapter. It does NOT implement:
  - Task 2.2's property-based tests (P1-P3) -- see tests/test_vector_store.py
    for the focused unit/integration/error-path tests that *are* in scope
    for this task.
  - Task 3.x (BM25, HybridRetriever, Reciprocal Rank Fusion).
  - Task 4.x (ConversationManager).
  - Any later task.

TWO DOCUMENTED SCOPE DEVIATIONS FROM THE LITERAL DESIGN-DOC SKELETON,
both direct, approved consequences of prior decisions (not new, silent
contract expansions):

1. The official design document's method skeletons take a `collection:
   str` parameter on every call (`upsert_chunk(self, collection, chunk)`,
   `search_similar(self, collection, ...)`, etc.). The approved
   Partitioning Strategy decision (Final Checkpoint, part F) settled that
   partitioning is achieved via payload-field filtering (`source_type`,
   `document_id`) within ONE shared collection, not multiple physical
   collections. Accepting a free-form `collection` argument would reopen a
   question that's already been decided, so every method here operates on
   the single collection name configured in `Settings`
   (`qdrant_collection_name`) instead. This is a direct, approved
   consequence of an already-made decision, not a new one made here.

2. `ContextChunk` is referenced by name in the design document's method
   skeletons (`upsert_chunk(self, collection, chunk: ContextChunk)`) but
   its fields are never defined anywhere in the official Requirements or
   Design documents -- unlike `RetrievalResult`, which is given as a
   complete, concrete dataclass. Rather than inventing a speculative
   field list, `ContextChunk` here is built directly and only from what
   Requirement 1.1 itself states in words ("its embedding vector, text
   content, and source metadata (document identifier, page number,
   timestamp, and chunk identifier)"): a chunk_id, its text, its
   embedding vector, and a single open `metadata: dict` carrying
   whatever source metadata fields apply -- deliberately mirroring how
   Team 4A's own verified `_build_point()` already assembles a payload
   (`{"text": ..., **metadata_fields}`). This keeps Team 4B's write path
   shape-compatible with the exact records it also reads from the same
   shared collection, without asserting a field list neither official
   document actually specifies. Flagging this per the instruction to
   "stop and report" ambiguities rather than silently inventing a
   contract.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, Sequence, cast

from app.core.config import Settings, get_settings
from app.models.retrieval import RetrievalResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Read-side normalization adapter (approved contract, Final Checkpoint §F/H/I)
#
# Lives entirely on the read path, per the approved architecture: Team 4A's
# write path (Publisher) is never touched, and there is no republishing
# pipeline. Every function here is a pure, deterministic function of a
# payload dict -- no network calls, no side effects.
# ---------------------------------------------------------------------------

#: Team 4A's raw SourceType vocabulary -> Team 4B's normalized vocabulary.
#: Approved Final Checkpoint §H.
_SOURCE_TYPE_NORMALIZATION: dict[str, str] = {
    "pdf": "document",
    "mp4": "video",
    "youtube": "video",
}

#: Reverse mapping, used only to translate a Team 4B-facing
#: `collection_filter` value (e.g. "document") back into the raw
#: `source_type` value(s) actually stored in the shared collection's
#: payload (e.g. ["pdf"]), since Qdrant can only filter on the field as
#: Team 4A actually wrote it.
_NORMALIZED_TO_RAW_SOURCE_TYPES: dict[str, list[str]] = {
    "document": ["pdf"],
    "video": ["mp4", "youtube"],
}


def normalize_source_type(raw_source_type: str) -> str:
    """pdf -> document; mp4/youtube -> video. Approved Final Checkpoint §H."""

    return _SOURCE_TYPE_NORMALIZATION.get(raw_source_type, raw_source_type)


def resolve_document_title(payload: dict[str, Any]) -> str | None:
    """PDF/MP4: filename. YouTube: video_title, falling back to filename.

    Approved Final Checkpoint item 7 / §F.
    """

    if payload.get("source_type") == "youtube":
        return payload.get("video_title") or payload.get("filename")
    return payload.get("filename")


def select_section_heading(headings: list[dict[str, Any]] | None) -> str | None:
    """Text of the lowest-`level` Heading; first in list order on a tie;
    None if the list is empty or absent.

    `min()` with `key=` is stable -- it keeps the first element seen when
    multiple share the same minimal key -- which is exactly the "first on
    tie" rule, with no separate index bookkeeping needed. Approved Final
    Checkpoint item 8 / §I.
    """

    if not headings:
        return None
    return cast(str, min(headings, key=lambda heading: heading["level"])["text"])


def resolve_youtube_end_timestamp(payload: dict[str, Any]) -> float | None:
    """start_timestamp + per-segment duration, only when end_timestamp is
    genuinely absent (None) -- never when it's falsy, since 0.0 is a
    valid timestamp. Approved Final Checkpoint item 9.

    `duration` here is the per-segment `ChunkMetadata.duration` (sourced
    from `YouTubeSegment.duration`), not `YouTubeMetadata.duration_seconds`
    (whole-video duration) -- confirmed from Team 4A's actual schemas.py
    and recorded in docs/CONTRACT_DECISIONS.md.
    """

    if payload.get("source_type") != "youtube":
        return cast("float | None", payload.get("end_timestamp"))

    end_timestamp = payload.get("end_timestamp")
    if end_timestamp is not None:
        return cast(float, end_timestamp)

    start_timestamp = payload.get("start_timestamp")
    duration = payload.get("duration")
    if start_timestamp is None or duration is None:
        # Genuinely missing inputs -- nothing to compute from. Left as
        # None rather than fabricated; Team 4A's own ChunkMetadata
        # validator requires both fields for YouTube chunks, so this
        # branch should not occur for chunks Team 4A actually published,
        # but is handled explicitly rather than assumed.
        return None
    return cast(float, start_timestamp) + cast(float, duration)


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the full approved read-side adapter to one raw Qdrant payload.

    Returns a new dict: a copy of the raw payload (minus `text`, which
    `RetrievalResult` carries separately) with the adapter-computed
    fields applied on top -- `document_title`, `source_type`
    (normalized), and `end_timestamp` (YouTube fallback). `section_heading`
    is added as a new field; the raw `headings` list is preserved
    alongside it rather than deleted, so no information Team 4A actually
    captured is silently discarded.

    CORRECTED (MVP M3 identity correction): `document_id` is NO LONGER
    remapped from `job_id`. `docs/CONTRACT_DECISIONS.md` item 1 recorded
    that remapping as a deliberate, EXPLICITLY TEMPORARY compromise --
    "Team 4A does not expose a stable logical document identifier" --
    true at the time it was written, and no longer true: Team 4A's Phase
    1/2C canonical ingestion path now publishes a real, stable, permanent
    `document_id` (Team 4C's own File._id) directly in every canonical
    chunk's payload, distinct from `job_id` (one ingestion attempt) --
    confirmed directly against Team 4A's actual canonical payload shape,
    not assumed. `job_id` itself is left completely untouched in the
    payload (this function only ever ADDS/overwrites specific keys it
    names explicitly; it was never the source of `job_id`, only ever the
    thing `document_id` was incorrectly copied FROM). A payload that
    genuinely has no `document_id` key at all (e.g., a stale record from
    before this correction, or from the legacy collection this function
    is still also used for) simply has no `document_id` key in the
    returned dict either -- `dict.get("document_id")` then correctly
    reads as absent/`None` downstream, never silently substituting
    `job_id` back in as a disguised fallback.
    """

    normalized = {key: value for key, value in payload.items() if key != "text"}

    normalized["document_title"] = resolve_document_title(payload)

    raw_source_type = payload.get("source_type")
    if raw_source_type is not None:
        normalized["source_type"] = normalize_source_type(raw_source_type)

    normalized["section_heading"] = select_section_heading(payload.get("headings"))

    normalized["end_timestamp"] = resolve_youtube_end_timestamp(payload)

    return normalized


# ---------------------------------------------------------------------------
# Write-path input model (Task 2.1 scope only -- see module docstring,
# deviation 2, for why this is intentionally minimal)
# ---------------------------------------------------------------------------


@dataclass
class ContextChunk:
    """Team 4B-side write-path representation of a Context_Chunk.

    Deliberately minimal -- see module docstring, deviation 2, for why
    only chunk_id/text/embedding/metadata are asserted here rather than a
    speculative full field list.
    """

    chunk_id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VectorStoreUnavailableError(Exception):
    """Raised when the Vector_Store is unreachable after exhausting
    retries, per Requirement 1.5: "IF the Vector_Store becomes
    unreachable during an indexing or query operation, THEN THE
    RAG_Service SHALL return an error response with a
    VectorStoreUnavailable status code and retry the operation up to 3
    times with exponential backoff."
    """

    status_code: str = "VectorStoreUnavailable"

    def __init__(self, message: str, *, last_error: Exception | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


class VectorStoreConfigurationError(Exception):
    """Raised when the shared production collection already exists but
    its vector configuration (size/distance) does not match this
    service's configured expectation.

    Not part of the official Requirement text verbatim -- this is a
    necessary internal safety check (implementation detail, not a new
    API/behavioral contract) to fail loudly on a genuine misconfiguration
    rather than silently searching/writing against an incompatible
    vector space.
    """


# ---------------------------------------------------------------------------
# Qdrant client abstraction (mirrors -- independently, not by sharing code
# -- the same lazy-construction / injectable-protocol pattern already used
# in Team 4A's own Publisher, so unit tests never require a live Qdrant
# server)
# ---------------------------------------------------------------------------


class QdrantClientProtocol(Protocol):
    """The minimal interface VectorStoreManager needs from a Qdrant client."""

    def get_collections(self) -> Any: ...

    def get_collection(self, collection_name: str) -> Any: ...

    def create_collection(self, collection_name: str, vectors_config: Any) -> Any: ...

    def create_payload_index(self, collection_name: str, field_name: str, field_schema: Any) -> Any: ...

    def upsert(self, collection_name: str, points: Sequence[Any]) -> Any: ...

    def search(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        limit: int,
        score_threshold: float | None = None,
        query_filter: Any | None = None,
    ) -> Any: ...

    def delete(self, collection_name: str, points_selector: Any) -> Any: ...

    def scroll(
        self,
        collection_name: str,
        limit: int,
        offset: Any | None = None,
    ) -> Any: ...


class RealQdrantClient:
    """Real qdrant-client integration.

    Constructed lazily inside `_ensure_client()`, matching this project's
    (and Team 4A's) established convention: importing this module, or
    even constructing a VectorStoreManager, never opens a connection;
    only an actual method call does.
    """

    def __init__(self, url: str, api_key: str | None) -> None:
        self._url = url
        self._api_key = api_key
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=self._url,
                api_key=self._api_key,
                check_compatibility=False,
            )
        return self._client

    def get_collections(self) -> Any:
        return self._ensure_client().get_collections()

    def get_collection(self, collection_name: str) -> Any:
        return self._ensure_client().get_collection(
            collection_name=collection_name
        )

    def create_collection(
        self,
        collection_name: str,
        vectors_config: Any,
    ) -> Any:
        return self._ensure_client().create_collection(
            collection_name=collection_name,
            vectors_config=vectors_config,
        )

    def create_payload_index(
        self,
        collection_name: str,
        field_name: str,
        field_schema: Any,
    ) -> Any:
        return self._ensure_client().create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
        )

    def upsert(
        self,
        collection_name: str,
        points: Sequence[Any],
    ) -> Any:
        return self._ensure_client().upsert(
            collection_name=collection_name,
            points=list(points),
        )

    def search(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        limit: int,
        score_threshold: float | None = None,
        query_filter: Any | None = None,
    ) -> Any:
        """Vector similarity search.

        IMPORTANT QDRANT 1.19.0 COMPATIBILITY:

        The installed qdrant-client version used by the Team 4B runtime
        does not expose the legacy `QdrantClient.search()` method.
        Modern qdrant-client uses `query_points()`.

        This adapter intentionally keeps the Team 4B-facing interface
        stable as `.search(...)`, while translating that call internally
        to the modern raw-client `.query_points(...)` API.

        `query_points()` returns a QueryResponse wrapper whose `.points`
        attribute contains the actual ScoredPoint results. This method
        unwraps that response so callers continue receiving the same
        list-shaped result that the old `.search()` API returned.

        The conversion is intentionally kept here, at the concrete
        Qdrant adapter boundary. VectorStoreManager must call this
        adapter's `.search(...)` method rather than calling
        `.query_points(...)` directly.
        """

        response = self._ensure_client().query_points(
            collection_name=collection_name,
            query=list(query_vector),
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
        return response.points

    def delete(
        self,
        collection_name: str,
        points_selector: Any,
    ) -> Any:
        return self._ensure_client().delete(
            collection_name=collection_name,
            points_selector=points_selector,
        )

    def scroll(
        self,
        collection_name: str,
        limit: int,
        offset: Any | None = None,
    ) -> Any:
        return self._ensure_client().scroll(
            collection_name=collection_name,
            limit=limit,
            offset=offset,
        )


# ---------------------------------------------------------------------------
# VectorStoreManager
# ---------------------------------------------------------------------------


class VectorStoreManager:
    """Team 4B's Vector_Store layer (Requirement 1) against the shared
    production Qdrant collection.

    Collection name, batch size, retry count, and backoff base are all
    read from `Settings` (never hardcoded), per the approved
    Contract Checkpoint and this project's established convention.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        qdrant_client: QdrantClientProtocol | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = qdrant_client or RealQdrantClient(
            url=self._settings.qdrant_url,
            api_key=self._settings.qdrant_api_key,
        )

        # Injectable so unit tests never actually sleep for the real,
        # exponentially growing backoff duration.
        self._sleep = sleep_fn or time.sleep
        self._collection_name = self._settings.qdrant_collection_name

        # Tracks whether ensure_collection()/canonical verification has
        # successfully run for each collection served by this manager.
        #
        # This is a SET rather than a single boolean because the manager
        # can serve both:
        #   - its configured legacy collection, and
        #   - the canonical collection passed explicitly by the M3/M6
        #     query path.
        self._ensured_collections: set[str] = set()

    # -- Collection provisioning / verification (Requirement 1) ----------

    def check_health(self) -> bool:
        """ADDED IN TASK 10.1. Lightweight Qdrant reachability check for
        `GET /health`.

        A single attempt, no retry. Health checks deliberately remain
        lightweight and side-effect-free.
        """

        try:
            self._client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure_collection(self) -> None:
        """Create the shared production collection if it does not exist;
        if it already exists, verify its vector size/distance match this
        service's configuration.

        Per the approved Checkpoint (§B/§D): Team 4B owns/provisions the
        shared production collection. Team 4A's own local/demo collection
        is never touched by this method.
        """

        existing_names = {
            collection.name
            for collection in self._client.get_collections().collections
        }

        if self._collection_name not in existing_names:
            from qdrant_client.models import Distance, VectorParams

            distance = self._distance_enum()

            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=self._settings.embedding_dimensions,
                    distance=distance,
                ),
            )

            logger.info(
                "Created shared production Qdrant collection",
                extra={
                    "collection": self._collection_name,
                    "vector_size": self._settings.embedding_dimensions,
                    "distance": self._settings.embedding_distance,
                },
            )

            self._ensure_payload_indexes()
            return

        self._verify_existing_collection_compatibility()
        self._ensure_payload_indexes()

    def _verify_existing_collection_compatibility(self) -> None:
        info = self._client.get_collection(
            collection_name=self._collection_name
        )

        # qdrant-client's CollectionInfo shape:
        # info.config.params.vectors is either a single VectorParams
        # (unnamed vector) or a dict of named vectors.
        vectors_config = info.config.params.vectors

        actual_size = getattr(vectors_config, "size", None)
        actual_distance = getattr(vectors_config, "distance", None)

        expected_size = self._settings.embedding_dimensions
        expected_distance = self._distance_enum()

        if (
            actual_size != expected_size
            or (
                actual_distance is not None
                and actual_distance != expected_distance
            )
        ):
            raise VectorStoreConfigurationError(
                f"Shared production collection {self._collection_name!r} "
                f"already exists with vector_size={actual_size!r}, "
                f"distance={actual_distance!r}, but this service is "
                f"configured for vector_size={expected_size!r}, "
                f"distance={expected_distance!r}. Refusing to proceed "
                "against a mismatched vector space -- this must be "
                "resolved by configuration, not silently ignored."
            )

    def _verify_canonical_collection_compatibility(
        self,
        collection_name: str,
    ) -> None:
        """Verify canonical collection existence and vector compatibility.

        This method NEVER creates the canonical collection and NEVER
        provisions payload indexes on it.

        `educopilot_chunks` is provisioned by Phase 0.A's dedicated
        process. Team 4B only verifies that the collection exists and
        matches the configured vector space.
        """

        existing_names = {
            collection.name
            for collection in self._client.get_collections().collections
        }

        if collection_name not in existing_names:
            raise VectorStoreConfigurationError(
                f"Canonical collection {collection_name!r} does not exist. "
                "This collection is provisioned separately (Phase 0.A) -- "
                "Team 4B's VectorStoreManager will never create it "
                "automatically. Verify Qdrant provisioning before starting "
                "the query service."
            )

        info = self._client.get_collection(
            collection_name=collection_name
        )

        vectors_config = info.config.params.vectors

        actual_size = getattr(vectors_config, "size", None)
        actual_distance = getattr(vectors_config, "distance", None)

        expected_size = self._settings.embedding_dimensions
        expected_distance = self._distance_enum()

        if (
            actual_size != expected_size
            or (
                actual_distance is not None
                and actual_distance != expected_distance
            )
        ):
            raise VectorStoreConfigurationError(
                f"Canonical collection {collection_name!r} already exists "
                f"with vector_size={actual_size!r}, "
                f"distance={actual_distance!r}, but this service is "
                f"configured for vector_size={expected_size!r}, "
                f"distance={expected_distance!r}. Refusing to proceed "
                "against a mismatched vector space -- this must be "
                "resolved by configuration, not silently ignored."
            )

    def _ensure_payload_indexes(self) -> None:
        """Create payload indexes required by the approved filtering/
        deletion strategy.

        Idempotent: creating an index that already exists is treated as
        a successful no-op.
        """

        from qdrant_client.models import PayloadSchemaType

        for field_name in ("job_id", "source_type"):
            try:
                self._client.create_payload_index(
                    collection_name=self._collection_name,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "create_payload_index no-op or already exists",
                    extra={
                        "field_name": field_name,
                        "error": str(exc),
                    },
                )

    def _distance_enum(self) -> Any:
        from qdrant_client.models import Distance

        return {
            "Cosine": Distance.COSINE,
            "Dot": Distance.DOT,
            "Euclid": Distance.EUCLID,
        }[self._settings.embedding_distance]

    # -- Write path (Requirement 1.1-1.3) ---------------------------------

    def upsert_chunk(self, chunk: ContextChunk) -> None:
        """Persist a single Context_Chunk."""

        self.upsert_batch([chunk])

    def upsert_batch(self, chunks: list[ContextChunk]) -> None:
        """Persist Context_Chunks in configured Qdrant batches.

        Larger lists are split into multiple underlying Qdrant calls.
        """

        if not chunks:
            return

        batch_size = self._settings.qdrant_publish_batch_size

        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start : batch_start + batch_size]
            points = [self._build_point(chunk) for chunk in batch]

            def _do_upsert(
                points: list[Any] = points,
            ) -> Any:
                return self._client.upsert(
                    collection_name=self._collection_name,
                    points=points,
                )

            self._with_retry(
                _do_upsert,
                operation="upsert",
            )

    def _build_point(self, chunk: ContextChunk) -> Any:
        from qdrant_client.models import PointStruct

        payload = {
            "text": chunk.text,
            "chunk_id": chunk.chunk_id,
            **chunk.metadata,
        }

        return PointStruct(
            id=self._point_id_for(chunk.chunk_id),
            vector=chunk.embedding,
            payload=payload,
        )

    @staticmethod
    def _point_id_for(chunk_id: str) -> str:
        """Deterministically map a chunk_id to a Qdrant-valid point ID."""

        import uuid

        namespace = uuid.UUID(
            "2f6a8e2a-9b3a-4b7a-8b0a-3e9c7d6a1f10"
        )

        return str(uuid.uuid5(namespace, chunk_id))

    # -- Delete path (Requirement 1.6) ------------------------------------

    def delete_by_document(self, document_id: str) -> None:
        """Remove all Context_Chunks for `document_id`."""

        from qdrant_client.models import (
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        points_selector = FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(
                        key="job_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            )
        )

        self._with_retry(
            lambda: self._client.delete(
                collection_name=self._collection_name,
                points_selector=points_selector,
            ),
            operation="delete_by_document",
        )

    # -- Read path ---------------------------------------------------------

    def scroll_all_chunks(
        self,
        batch_size: int = 256,
        *,
        collection_name: str | None = None,
    ) -> list[RetrievalResult]:
        """Page through every point currently in the target collection.

        The same read-side normalization adapter used by
        `search_similar()` is applied to every payload.
        """

        results: list[RetrievalResult] = []
        offset: Any = None
        target_collection = (
            collection_name or self._collection_name
        )

        while True:

            def _do_scroll(
                offset: Any = offset,
            ) -> Any:
                return self._client.scroll(
                    collection_name=target_collection,
                    limit=batch_size,
                    offset=offset,
                )

            points, next_offset = self._with_retry(
                _do_scroll,
                operation="scroll_all_chunks",
                collection_name=target_collection,
            )

            for point in points:
                payload = dict(point.payload or {})
                text = payload.get("text", "")
                metadata = normalize_payload(payload)
                chunk_id = payload.get(
                    "chunk_id",
                    str(point.id),
                )

                results.append(
                    RetrievalResult(
                        chunk_id=chunk_id,
                        text=text,
                        relevance_score=0.0,
                        metadata=metadata,
                    )
                )

            if next_offset is None:
                break

            offset = next_offset

        return results

    def search_similar(
        self,
        query_vector: list[float],
        top_k: int,
        score_threshold: float,
        collection_filter: list[str] | None = None,
        *,
        workspace_id: str,
        collection_name: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Vector similarity search.

        Workspace scoping is mandatory. Optional source-type and
        document-level filters are combined into the same Qdrant Filter.

        IMPORTANT QDRANT 1.19.0 FIX:

        VectorStoreManager deliberately calls the abstraction's
        `.search(...)` method here.

        It must NOT call `.query_points(...)` directly because
        `self._client` is a `QdrantClientProtocol` implementation.
        The concrete `RealQdrantClient` intentionally exposes `.search(...)`
        and internally translates that operation to the modern raw
        Qdrant `.query_points(...)` API.

        This preserves the abstraction boundary and makes the runtime
        path:

            VectorStoreManager.search_similar()
                -> RealQdrantClient.search()
                -> QdrantClient.query_points()

        instead of incorrectly attempting:

            VectorStoreManager
                -> RealQdrantClient.query_points()

        which does not exist.
        """

        # Deliberately narrow an explicitly supplied empty document scope
        # to zero candidates. It must never mean "no restriction".
        if document_ids is not None and len(document_ids) == 0:
            return []

        query_filter = self._build_workspace_and_collection_filter(
            workspace_id,
            collection_filter,
            document_ids,
        )

        target_collection = (
            collection_name or self._collection_name
        )

        # CRITICAL FIX:
        # Call the protocol/adapter's `search()` method.
        #
        # RealQdrantClient.search() is responsible for translating this
        # stable interface into raw QdrantClient.query_points(), which is
        # the API available in qdrant-client 1.19.0.
        results = self._with_retry(
            lambda: self._client.search(
                collection_name=target_collection,
                query_vector=list(query_vector),
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=query_filter,
            ),
            operation="search_similar",
            collection_name=target_collection,
        )

        retrieval_results: list[RetrievalResult] = []

        for point in results:
            payload = dict(point.payload or {})
            text = payload.get("text", "")
            metadata = normalize_payload(payload)

            chunk_id = payload.get(
                "chunk_id",
                str(point.id),
            )

            retrieval_results.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    text=text,
                    relevance_score=float(point.score),
                    metadata=metadata,
                )
            )

        return retrieval_results

    def _build_workspace_and_collection_filter(
        self,
        workspace_id: str,
        collection_filter: list[str] | None,
        document_ids: list[str] | None = None,
    ) -> Any:
        """Build the single Qdrant Filter used by search_similar()."""

        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        must_conditions: list[Any] = [
            FieldCondition(
                key="workspace_id",
                match=MatchValue(value=workspace_id),
            )
        ]

        if document_ids:
            must_conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchAny(any=document_ids),
                )
            )

        collection_only_filter = self._build_collection_filter(
            collection_filter
        )

        if collection_only_filter is not None:
            must_conditions.extend(
                collection_only_filter.must
            )

        return Filter(must=must_conditions)

    def _build_collection_filter(
        self,
        collection_filter: list[str] | None,
    ) -> Any | None:
        if not collection_filter:
            return None

        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchAny,
        )

        raw_source_types: list[str] = []

        for normalized_value in collection_filter:
            raw_source_types.extend(
                _NORMALIZED_TO_RAW_SOURCE_TYPES.get(
                    normalized_value,
                    [normalized_value],
                )
            )

        return Filter(
            must=[
                FieldCondition(
                    key="source_type",
                    match=MatchAny(any=raw_source_types),
                )
            ]
        )

    # -- Retry / backoff ---------------------------------------------------

    def _with_retry(
        self,
        operation_fn: Callable[[], Any],
        *,
        operation: str,
        collection_name: str | None = None,
    ) -> Any:
        """Execute a Qdrant operation with provisioning/verification
        and exponential retry behavior.

        The target collection is ensured once per VectorStoreManager
        instance.

        The configured legacy collection is created/verified through
        `ensure_collection()`.

        Any explicitly supplied alternate collection -- in practice the
        canonical `educopilot_chunks` collection -- is verified only and
        is never automatically created or modified.
        """

        target_collection = (
            collection_name
            if collection_name is not None
            else self._collection_name
        )

        max_retries = self._settings.vector_store_retry_count
        attempt = 0

        while True:
            try:
                if target_collection not in self._ensured_collections:
                    if target_collection == self._collection_name:
                        self.ensure_collection()
                    else:
                        self._verify_canonical_collection_compatibility(
                            target_collection
                        )

                    self._ensured_collections.add(
                        target_collection
                    )

                return operation_fn()

            except VectorStoreConfigurationError:
                # Configuration errors are permanent and actionable.
                # Do not convert them into transient availability errors
                # or waste retry attempts.
                raise

            except Exception as exc:  # noqa: BLE001
                attempt += 1

                if attempt > max_retries:
                    logger.error(
                        "Vector_Store operation permanently failed",
                        extra={
                            "operation": operation,
                            "attempts": attempt,
                        },
                    )

                    raise VectorStoreUnavailableError(
                        f"Vector_Store unreachable during "
                        f"{operation!r} after {max_retries} retries",
                        last_error=exc,
                    ) from exc

                delay = self._backoff_delay(attempt)

                logger.warning(
                    "Retrying Vector_Store operation after transient failure",
                    extra={
                        "operation": operation,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "backoff_seconds": delay,
                    },
                )

                self._sleep(delay)

    def _backoff_delay(
        self,
        retry_number: int,
    ) -> float:
        """delay = initial_backoff * 2^(retry_number - 1)."""

        initial_backoff: float = (
            self._settings.vector_store_initial_backoff_seconds
        )

        return initial_backoff * (
            2.0 ** (retry_number - 1)
        )