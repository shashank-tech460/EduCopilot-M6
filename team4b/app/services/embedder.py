"""Team 4B query-time embedding generation (Task 3.1).

Implements the semantic-search leg's embedding needed by Requirement 2
(Hybrid Search), specifically the design document's:

    3.1 Implement BM25 index and embedding generation
        Create app/services/embedder.py wrapping sentence-transformers
        for query embedding
        Requirements: 2.1

SCOPE NOTE (Task 3.1 only): this module generates QUERY-time embeddings
only. It does not implement HybridRetriever, RRF, or search-mode routing
(Task 3.2) or property tests (Task 3.3). It also has nothing to do with
embedding chunks at ingestion time -- that is Team 4A's job (its own
Embedding Generator, Requirement 5, already implemented and out of
Team 4B's scope entirely).

INTEGRATION CONSTRAINT (approved architecture, docs/CONTRACT_DECISIONS.md
items 2-4): Team 4B searches the SAME shared production Qdrant collection
Team 4A publishes into -- there is no republishing pipeline. A query
vector is only meaningful against that collection's vectors if it comes
from the same embedding model and dimension Team 4A used to write them:
all-MiniLM-L6-v2, 384 dimensions, Cosine distance. This is the default
here (via `Settings.embedding_model_name` / `Settings.embedding_dimensions`,
Task 1.1), and is enforced, not just documented: `Embedder` validates the
actual loaded model's output dimension against
`Settings.embedding_dimensions` the first time it's used, and raises
rather than silently proceeding on a mismatch -- the same "fail loudly on
a real mismatch" pattern already used by
`VectorStoreManager.ensure_collection()` (Task 2.1), independently
implemented here for a different mismatch (model output vs. configured
expectation, rather than existing-collection vs. configured expectation).

Configuration remains environment-overridable per Task 1.1 -- the
approved defaults are defaults, not hard-coded values; a deployment that
deliberately changes Team 4A's embedding model would need to change both
services' configuration consistently, which is outside Team 4B's control
and not something this module can detect on its own.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from app.core.config import Settings, get_settings


class EmbeddingModelDimensionMismatchError(Exception):
    """Raised when the loaded embedding model's actual output dimension
    does not match `Settings.embedding_dimensions`.

    Not part of the official Requirement text verbatim -- like
    `VectorStoreConfigurationError` in Task 2.1, this is a necessary
    internal safety check (implementation detail, not a new API/
    behavioral contract): query vectors that don't match the shared
    collection's actual vector space would make every search silently
    meaningless rather than simply fail, which is worse.
    """


class EmbeddingModelProtocol(Protocol):
    """The minimal interface Embedder needs from a sentence-transformers
    model (or a test fake standing in for one), matching
    `SentenceTransformer`'s own real method names so `RealEmbeddingModel`
    below is a thin, direct pass-through.
    """

    def encode(self, sentences: Sequence[str], **kwargs: Any) -> Any: ...

    def get_sentence_embedding_dimension(self) -> int | None: ...


class RealEmbeddingModel:
    """Real sentence-transformers integration.

    Constructed lazily inside `_ensure_model()`, matching this project's
    established convention (Team 4A's own Whisper/sentence-transformers
    loading, and this codebase's `RealQdrantClient` in Task 2.1):
    importing this module, or even constructing an `Embedder`, never
    loads model weights; only an actual `encode`/dimension check does.

    Model weight downloads require network access to huggingface.co,
    which is not available in every environment this code runs in
    (notably not in the sandbox used to build/test this task -- see the
    Task 3.1 report's "assumptions/limitations" for how this was
    verified without a live download).
    """

    def __init__(self, model_name: str, revision: str | None = None) -> None:
        self._model_name = model_name
        self._revision = revision
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, revision=self._revision)
        return self._model

    def encode(self, sentences: Sequence[str], **kwargs: Any) -> Any:
        return self._ensure_model().encode(list(sentences), **kwargs)

    def get_sentence_embedding_dimension(self) -> int | None:
        dimension = self._ensure_model().get_sentence_embedding_dimension()
        return int(dimension) if dimension is not None else None


class Embedder:
    """Generates query-time embeddings for Hybrid_Retriever's semantic
    search leg (Requirement 2.1).

    Model name and expected dimension are both read from `Settings`
    (never hardcoded), matching this project's established convention.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        model: EmbeddingModelProtocol | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._model = model or RealEmbeddingModel(self._settings.embedding_model_name)
        self._dimension_verified = False

    def _verify_dimension(self) -> None:
        """Check the loaded model's actual output dimension against
        `Settings.embedding_dimensions` exactly once per Embedder
        instance (not on every call -- the model's dimension cannot
        change between calls, so re-checking would only add repeated
        cost without ever catching anything new).
        """

        if self._dimension_verified:
            return

        actual_dimension = self._model.get_sentence_embedding_dimension()
        expected_dimension = self._settings.embedding_dimensions

        if actual_dimension is not None and actual_dimension != expected_dimension:
            raise EmbeddingModelDimensionMismatchError(
                f"Configured embedding model {self._settings.embedding_model_name!r} produces "
                f"{actual_dimension}-dimensional vectors, but Settings.embedding_dimensions is "
                f"{expected_dimension!r}. Query vectors generated at this dimension would not be "
                "comparable to the shared production Qdrant collection's actual vector space -- "
                "refusing to proceed rather than silently returning meaningless search results."
            )

        self._dimension_verified = True

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. Raises
        `EmbeddingModelDimensionMismatchError` if the configured model's
        actual output dimension doesn't match `Settings.embedding_dimensions`.
        """

        self._verify_dimension()
        vector = self._model.encode([text], convert_to_numpy=False)[0]
        return [float(component) for component in vector]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed multiple query strings in one model call. Returns an
        empty list for an empty input without loading the model at all
        -- there is nothing to verify or embed.
        """

        if not texts:
            return []

        self._verify_dimension()
        vectors = self._model.encode(list(texts), convert_to_numpy=False)
        return [[float(component) for component in vector] for vector in vectors]
