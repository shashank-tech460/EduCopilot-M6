"""Team 4A Embedder (Embedding_Generator).

Location matches the same pattern as the Chunker
(app/pipeline/chunker.py, Task 6.1): app/pipeline/embedder.py.

Implements Requirement 5:
    5.1 Use sentence-transformers with the all-MiniLM-L6-v2 model by
        default, configurable via Settings.
    5.2 Produce 384-dimension embeddings by default.
    5.3 Process embeddings in configurable batches (default 32).
    5.4 L2-normalize every embedding.
    5.5 Handle text exceeding the model's supported input length via
        tokenizer-aware truncation, not a hard failure.

Does not implement Qdrant publication, metadata enrichment, job
orchestration, or Celery tasks -- those belong to later tasks (8.1, 8.2,
10.x). Prepares for, but does not implement, the optional Task 7.2
correctness-property tests (Properties 16-19).
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from app.config.settings import Settings, get_settings
from app.models.exceptions import EmbeddingDimensionMismatchError


class EmbeddingModel(Protocol):
    """The minimal interface Embedder needs from an embedding model.

    `SentenceTransformerModel` (below) is the real implementation. Tests
    inject a fake implementing this same interface, so they exercise
    Embedder's real control flow (batching forwarding, dimension
    validation, output conversion) without downloading model weights.
    """

    def encode(
        self,
        texts: Sequence[str],
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> Any:
        """Return an array-like of one embedding vector per input text, in order."""
        ...

    def get_sentence_embedding_dimension(self) -> int | None:
        """Return the model's native output dimension, if known."""
        ...


class SentenceTransformerModel:
    """Real sentence-transformers integration, per Requirement 5.1.

    The `sentence_transformers` package (and its model weights, downloaded
    on first use from the configured model hub) is imported and the model
    constructed lazily inside `_ensure_loaded()`, not at module import
    time or at `Embedder.__init__`. This mirrors the same pattern already
    used for Whisper (Task 3.1, `WhisperTranscriptionEngine`): importing
    this module, or even constructing an `Embedder`, never triggers a
    model download -- only calling `embed()` does.

    `revision` (Task 8.3 remediation, Requirement 6.5) pins the exact
    Hugging Face Hub commit loaded, so the model actually used matches the
    `embedding_model_version` provenance value attached to every chunk's
    metadata -- not just a label independent of what was really loaded.

    Truncation of oversized text (Requirement 5.5) is handled entirely by
    sentence-transformers itself: its tokenizer is invoked internally by
    `encode()` with truncation to the model's own `max_seq_length`, so no
    separate custom truncation logic is implemented here (per Task 7.1's
    explicit instruction to use the model/tokenizer's own truncation
    mechanism rather than a redundant custom one).
    """

    def __init__(self, model_name: str, device: str, revision: str | None = None) -> None:
        self._model_name = model_name
        self._device = device
        self._revision = revision
        self._model = None

    def _ensure_loaded(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=self._device, revision=self._revision)
        return self._model

    def encode(
        self,
        texts: Sequence[str],
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> Any:
        model = self._ensure_loaded()
        return model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            convert_to_numpy=convert_to_numpy,
        )

    def get_sentence_embedding_dimension(self) -> int | None:
        model = self._ensure_loaded()
        return model.get_sentence_embedding_dimension()


class Embedder:
    """Generates L2-normalized embedding vectors for a list of texts.

    Model name, device, batch size, and expected dimension are all read
    from `Settings` (never hardcoded), matching this project's established
    pattern (PDFProcessor, VideoProcessor, YouTubeProcessor, Chunker).
    """

    def __init__(self, settings: Settings | None = None, model: EmbeddingModel | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = model or SentenceTransformerModel(
            model_name=self._settings.embedding_model_name,
            device=self._settings.embedding_device,
            revision=self._settings.embedding_model_revision,
        )
        self._dimension_checked = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalized embedding vector per input text, in order.

        Args:
            texts: The texts to embed (typically `Chunk.text` values from
                Task 6.1's Chunker, though this component has no
                dependency on `Chunk` itself -- it only consumes plain
                strings).

        Returns:
            `[]` for empty input (no batch is sent to the model at all).
            Otherwise, a list of length `len(texts)`, where `result[i]`
            is the embedding for `texts[i]` -- ordering and count are
            always preserved, and no input is ever dropped or duplicated.

        Raises:
            EmbeddingDimensionMismatchError: if the loaded model's actual
                output dimension does not match
                `settings.embedding_dimensions`.
        """

        if not texts:
            return []

        self._validate_dimension_once()

        raw_vectors = self._model.encode(
            texts,
            batch_size=self._settings.embedding_batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        # Convert to plain Python floats/lists regardless of whether the
        # model returned a numpy array (the real model) or a list of
        # lists (a test double) -- downstream consumers (Task 8.x) get a
        # uniform, JSON-serializable type either way.
        return [[float(component) for component in vector] for vector in raw_vectors]

    def _validate_dimension_once(self) -> None:
        if self._dimension_checked:
            return

        actual_dimension = self._model.get_sentence_embedding_dimension()
        expected_dimension = self._settings.embedding_dimensions

        if actual_dimension is not None and actual_dimension != expected_dimension:
            raise EmbeddingDimensionMismatchError(
                f"Configured embedding_dimensions={expected_dimension} does not match "
                f"the loaded model's actual dimension={actual_dimension}",
                detail={"expected": expected_dimension, "actual": actual_dimension},
            )

        self._dimension_checked = True
