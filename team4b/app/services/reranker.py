"""Team 4B Phase 4B -- generalized, domain-agnostic post-RRF reranking layer.

APPROVED ARCHITECTURE (Phase 4B):

    HybridRetriever's existing semantic+BM25+RRF pipeline (UNCHANGED)
        -> expanded candidate pool (Settings.reranker_candidate_pool_size)
        -> Reranker.rerank(query, candidates, top_k)      <-- THIS MODULE
        -> existing generation/citation pipeline (UNCHANGED)

SCOPE: this module implements ONLY the reranking abstraction and its one
real cross-encoder implementation. It does not implement query rewriting,
query expansion, decomposition, adaptive retrieval, or any embedding
change -- those remain explicitly out of scope (Phase 4B instructions).

DOMAIN-AGNOSTIC BY CONSTRUCTION: `rerank()` operates on `(query,
candidate.text)` string pairs and passes `metadata` straight through
unread and unmodified -- nothing here branches on subject, language,
workspace, or document identity. It is exercised in this codebase's own
tests only against synthetic, subject-agnostic fixtures, never against
the OS/DBMS evaluation benchmark's specific questions.

NEVER FABRICATES EVIDENCE (Phase 4B Task 5): `rerank()` returns a
re-ordered, possibly-truncated SUBSET of exactly the `candidates` it was
given. It can never add a candidate that wasn't passed in, and it never
touches `chunk_id`, `text`, or `metadata` -- only `relevance_score` is
replaced (with the cross-encoder's own sigmoid-normalized score, keeping
the field's existing [0.0, 1.0] contract). Citation identity is
therefore structurally impossible to alter here.

FAILURE SAFETY (Phase 4B Task 9): this module raises a real exception
(`RerankerUnavailableError`) rather than silently returning an empty or
unranked list -- the same "fail loudly, let the caller decide" contract
already established by `VectorStoreUnavailableError` and
`GenerationAuthorityUnavailableError` elsewhere in this codebase. This
module itself has no fallback opinion; `HybridRetriever` (the caller)
decides the degrade-to-pre-rerank-order policy, keeping the two concerns
separate (Task 7: ranking vs. evidence selection are different layers).

MODEL SELECTION (Task 3) -- evaluated locally in this environment before
choosing:

  - `cross-encoder/ms-marco-MiniLM-L-6-v2` (~91MB, 6-layer MiniLM):
    downloads and loads in seconds, predicts in ~35ms for a handful of
    pairs. English-only training data (MS MARCO). Correctly separated a
    relevant vs. irrelevant English pair in a smoke test (this module's
    own manual verification, not a unit test fixture). REJECTED as the
    default: this project's own Phase 3/4A work identified Hindi-source
    retrieval as the single largest known weakness, and an English-only
    reranker would provide zero benefit for exactly that case, working
    against the "domain/language-agnostic" product requirement.
  - `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (~470MB, 12-layer
    MiniLM, CHOSEN AS DEFAULT): trained on mMARCO, which covers Hindi
    among ~14 languages. Manually verified in this environment against
    both an English and a Hindi (Devanagari) query/pair: it correctly
    ranked the relevant passage above the irrelevant one in BOTH
    languages (English: scores +8.63 vs. -5.51; Hindi: -1.79 vs. -4.98).
    DOCUMENTED LIMITATION: absolute score magnitude/confidence is
    markedly weaker for Hindi than English in this manual check (-1.79
    is a much smaller margin above its irrelevant counterpart than
    English's +8.63 vs. -5.51) -- the model still discriminates
    correctly but with less confidence on Devanagari text. First model
    load takes ~130s in this environment (one-time cost per process,
    not per query) -- acceptable for a long-lived service process, not
    for a cold-start-per-request deployment.

Neither candidate was rejected for unavailability -- both downloaded and
ran successfully in this environment (huggingface.co was reachable).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Protocol, Sequence

from app.core.config import Settings, get_settings
from app.models.retrieval import RetrievalResult

logger = logging.getLogger(__name__)


class RerankerUnavailableError(Exception):
    """Raised when the reranker cannot score candidates at all (model
    failed to load, or the underlying `predict()` call raised for any
    reason). Mirrors `VectorStoreUnavailableError`'s and
    `GenerationAuthorityUnavailableError`'s own "fail loudly, caller
    decides the fallback" convention -- this class never silently
    degrades a result itself.
    """


class RerankerProtocol(Protocol):
    """The minimal interface `HybridRetriever` needs from a reranker --
    matches this module's own `CrossEncoderReranker`, injectable for
    tests without loading a real model.
    """

    def rerank(self, query: str, candidates: Sequence[RetrievalResult], top_k: int) -> list[RetrievalResult]: ...


class CrossEncoderModelProtocol(Protocol):
    """The minimal interface `CrossEncoderReranker` needs from a
    sentence-transformers `CrossEncoder` (or a test fake standing in for
    one).
    """

    def predict(self, sentence_pairs: Sequence[tuple[str, str]]) -> Any: ...


class RealCrossEncoderModel:
    """Real sentence-transformers `CrossEncoder` integration.

    Constructed lazily inside `_ensure_model()`, matching this project's
    established convention (`RealEmbeddingModel`, `RealQdrantClient`):
    constructing a `CrossEncoderReranker` never loads model weights;
    only an actual `predict()` call does.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)
        return self._model

    def predict(self, sentence_pairs: Sequence[tuple[str, str]]) -> Any:
        return self._ensure_model().predict(list(sentence_pairs))


def _sigmoid(x: float) -> float:
    """Numerically stable logistic sigmoid, mapping an unbounded
    cross-encoder logit to (0.0, 1.0) -- keeps `relevance_score`'s
    existing [0.0, 1.0] contract (Property 7) intact for reranked
    results, exactly as `_normalize_cosine_similarity`/
    `_normalize_bm25_score` already do for the pre-rerank legs in
    `hybrid_retriever.py`.
    """

    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


class CrossEncoderReranker:
    """Generalized, domain-agnostic reranker (Phase 4B Task 2): scores
    each candidate's `text` directly against `query` with a
    cross-encoder, and returns candidates sorted by that score,
    truncated to `top_k`.

    Deliberately narrow: no workspace/document/generation-authority
    logic lives here (Task 2 -- "preserve existing retrieval contracts";
    those checks already happened upstream in `HybridRetriever` before
    any candidate ever reaches this class). This class only ever sees
    candidates that have ALREADY passed every filter -- it cannot
    un-filter them, since it never adds to the list it's given.
    """

    def __init__(self, settings: Settings | None = None, model: CrossEncoderModelProtocol | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = model or RealCrossEncoderModel(self._settings.reranker_model_name)

    def rerank(self, query: str, candidates: Sequence[RetrievalResult], top_k: int) -> list[RetrievalResult]:
        """Re-score and re-order `candidates` against `query`, returning
        at most `top_k` of them (fewer if `len(candidates) < top_k`;
        empty in, empty out).

        Raises `RerankerUnavailableError` (never returns a degraded
        result itself) if the underlying model cannot be loaded or
        `predict()` raises for any reason -- see module docstring's
        "FAILURE SAFETY" section for why that decision belongs to the
        caller, not here.
        """

        if not candidates:
            return []

        pairs = [(query, candidate.text) for candidate in candidates]

        start = time.perf_counter()
        try:
            raw_scores = self._model.predict(pairs)
        except Exception as exc:  # noqa: BLE001
            raise RerankerUnavailableError(
                f"Reranker model {self._settings.reranker_model_name!r} failed to score "
                f"{len(candidates)} candidate(s): {exc}"
            ) from exc
        elapsed = time.perf_counter() - start

        scored = [(candidate, _sigmoid(float(score))) for candidate, score in zip(candidates, raw_scores)]
        # Stable, deterministic tie-break by chunk_id ascending -- same
        # discipline as `reciprocal_rank_fusion`'s own tie-break, so equal
        # rerank scores never depend on incoming list order.
        scored.sort(key=lambda pair: (-pair[1], pair[0].chunk_id))
        selected = scored[:top_k]

        logger.info(
            "Reranking applied",
            extra={
                "candidate_count": len(candidates),
                "final_evidence_count": len(selected),
                "reranking_seconds": elapsed,
                "model_name": self._settings.reranker_model_name,
            },
        )

        return [
            RetrievalResult(
                chunk_id=candidate.chunk_id,
                text=candidate.text,
                relevance_score=score,
                metadata=candidate.metadata,
            )
            for candidate, score in selected
        ]
