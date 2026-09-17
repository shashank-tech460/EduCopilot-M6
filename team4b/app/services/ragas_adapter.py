"""Team 4B real RAGAS adapter (Task 9.1, remediated).

Implements `RagasEvaluatorProtocol` (from `app/services/evaluation.py`)
against the ACTUAL installed `ragas==0.4.3` API, verified by direct
inspection in this environment (`ragas.evaluate`, `ragas.SingleTurnSample`,
`ragas.EvaluationDataset`, `ragas.RunConfig`, `ragas.metrics.Faithfulness`
/`AnswerRelevancy`/`ContextPrecision`) -- not assumed from memory or an
older RAGAS version's API shape.

==========================================================================
REMEDIATION NOTICE (read this before the rest of the docstring)
==========================================================================

An earlier version of this adapter computed `context_recall` by passing
`reference=item.response` (the generated answer itself) into RAGAS's
legacy `ContextRecall` metric. A follow-up audit (see project history)
proved, by reading `ragas.metrics._context_recall.LLMContextRecall._ascore()`
directly, that this produces a semantically invalid, circular result --
`context_recall` is documented by RAGAS itself as measuring "TP and FN
using **annotated answer** and retrieved context" (an independent,
externally-verified ground truth), not the system's own generated
answer. RAGAS 0.4.3 ships NO reference-free variant of `context_recall`
(confirmed: `ragas.metrics.collections` contains only `ContextRecall`
and `ContextEntityRecall`, both still requiring `reference`).

THIS VERSION THEREFORE:
  - NEVER constructs, requests, or fabricates a value for `context_recall`
    from RAGAS. The `ContextRecall` metric class is not imported, not
    instantiated, and not included in the metrics list passed to
    `evaluate()` anywhere in this file.
  - Represents `context_recall` as STRUCTURALLY UNAVAILABLE for every
    item, unconditionally: `EvaluationMetrics.context_recall = None`,
    with `errors["context_recall"] = CONTEXT_RECALL_UNAVAILABLE_REASON`
    (a fixed, constant string -- never a per-execution error message).
    This is a deliberate architectural fact of the official Team 4B
    evaluation contract (`query`, `response`, `contexts` only, no
    independent reference field), not a bug, not a transient failure,
    and not something a retry or a different RAGAS call would fix.
  - Still preserves `faithfulness`, `answer_relevancy`, and
    `context_precision` as genuinely computed metrics.

CONTEXT_PRECISION -- WHY IT STILL USES `reference=item.response`:
RAGAS 0.4.3 does publish a genuine reference-free formulation,
`ragas.metrics.collections.ContextPrecisionWithoutReference`, whose
`ascore(user_input, response, retrieved_contexts)` needs no `reference`
argument at all -- verified by reading its source directly. It was
NOT adopted here because it requires a fundamentally different LLM
integration: its `llm` parameter is a modern
`InstructorBaseRagasLLM`-family object with an `agenerate(prompt: str,
response_model: Type[BaseModel]) -> BaseModel` structured-output method
(typically built via `ragas.llms.llm_factory(model, client=<an
OpenAI-compatible client>)`), which is a completely different protocol
from this adapter's existing `_OllamaRagasLLM` (the LEGACY
`generate_text`/`agenerate_text` duck-typed interface the rest of this
adapter, and `Faithfulness`/`AnswerRelevancy`, already depend on).
Building and maintaining a second, parallel LLM wrapper for one metric
alone was judged disproportionate scope for this remediation (a
"tightly scoped" fix, per the remediation instructions) -- flagged here
as a considered-and-rejected option, not an oversight.

Instead, `context_precision` continues to use the LEGACY
`ragas.metrics.ContextPrecision` class, which structurally requires
`sample.reference` to be set (confirmed via `_required_columns`). The
value supplied, `item.response`, is NOT presented or claimed anywhere in
this codebase as an independent ground-truth reference. It is used
because, verified by direct side-by-side source comparison:

    Legacy `LLMContextPrecisionWithReference._ascore()`:
        QAC(question=user_input, context=context, answer=reference)

    Official reference-free `ContextPrecisionWithoutReference.ascore()`:
        ContextPrecisionInput(question=user_input, context=context, answer=response)

these are the SAME prompt/scoring structure, with `response` in the
identical slot. Supplying `reference=item.response` to the legacy class
therefore reproduces RAGAS's own official reference-free
`context_precision` computation field-for-field -- it is documented here
as "the reference-free formulation, computed via the legacy API's
required field," never as "an independently-verified ground truth."

OTHER NOTES (unchanged from the original implementation):

1. NOT LIVE-TESTED. This sandbox has no reachable Ollama instance
   (confirmed unreachable in Task 6.1's report: `curl localhost:11434`
   -> connection refused). This adapter has therefore never actually
   been exercised against a real LLM or embedding model.
   `tests/test_ragas_adapter.py` verifies: the `_OllamaRagasLLM`/
   `_ProjectRagasEmbeddings` wrapper classes in isolation against fake
   clients; the pure, network-free `_build_samples()`/`_build_metrics()`
   helpers (proving no `ContextRecall` instance is ever created and
   every sample's `reference` is documented, not fabricated as
   ground truth). None of this exercises `ragas.evaluate()` itself,
   which requires the full RAGAS/LLM/embeddings machinery this
   environment cannot run.

2. Deprecation warnings: `ragas.metrics.Faithfulness`/`AnswerRelevancy`/
   `ContextPrecision` emit a `DeprecationWarning` in this version
   pointing at `ragas.metrics.collections` as the future replacement.
   The legacy classes are still fully functional in `ragas==0.4.3` (not
   yet removed) and are used here deliberately, to keep every
   RAGAS-computed metric on one consistent, well-understood API rather
   than mixing legacy and `collections`-style classes (whose method/
   constructor conventions differ) within a single adapter.

3. DEPENDENCY NOTE: `ragas==0.4.3` fails to import against the latest
   `langchain-community` (0.4.2) in this environment
   (`ModuleNotFoundError: langchain_community.chat_models.vertexai`) --
   a genuine upstream incompatibility, not a mistake in this project's
   own code. Resolved by pinning `langchain-community<0.4` (resolved to
   0.3.31) in `requirements.txt`, unchanged by this remediation per the
   explicit instruction not to touch already-verified dependency
   versions unless required.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.core.config import Settings, get_settings
from app.models.evaluation import EvaluationItem, EvaluationMetrics
from app.services.embedder import Embedder
from app.services.llm_generator import LLMClientProtocol, RealOllamaClient

#: Metrics genuinely computed via RAGAS in this adapter. `context_recall`
#: is deliberately absent -- see module docstring.
_RAGAS_COMPUTED_METRIC_NAMES: tuple[str, ...] = ("faithfulness", "answer_relevancy", "context_precision")

#: Fixed, constant explanation used for EVERY item, every time -- never a
#: per-execution error message. Signals "structurally unavailable under
#: the official contract" as distinct from "RAGAS attempted this metric
#: and it failed" (see `app/services/evaluation.py`'s module docstring
#: for the corresponding "partial failure vs. structural unavailability"
#: distinction at the pipeline level).
CONTEXT_RECALL_UNAVAILABLE_REASON = (
    "context_recall requires an independently-verified reference answer, which the "
    "official Team 4B evaluation contract (query, response, contexts) does not provide. "
    "This metric is structurally unavailable under the current contract; it was never "
    "attempted, and no value has been fabricated."
)


class _OllamaRagasLLM:
    """Wraps the project's own `LLMClientProtocol` (Task 6.1) so RAGAS's
    LLM-based metrics call Ollama through the exact same configured
    endpoint/model this project already established, without modifying
    `LLMGenerator`/`RealOllamaClient` themselves.

    Constructed as a plain object satisfying `ragas.llms.base.BaseRagasLLM`'s
    interface at the attribute/method level, rather than subclassing that
    (dataclass-based, ABC) class directly -- avoids fighting dataclass
    field initialization order for a wrapper this thin, while still
    providing every method RAGAS's evaluation loop actually calls.

    Injectable `client` for testing this wrapper's own logic without a
    live Ollama server; see `tests/test_ragas_adapter.py`.
    """

    def __init__(self, settings: Settings, client: LLMClientProtocol | None = None) -> None:
        from ragas.run_config import RunConfig

        self._settings = settings
        self._client = client or RealOllamaClient(settings.ollama_url)
        self.run_config = RunConfig(timeout=int(settings.evaluation_batch_timeout_seconds))
        self.multiple_completion_supported = False
        self.cache = None

    def set_run_config(self, run_config: Any) -> None:
        self.run_config = run_config

    def get_temperature(self, n: int) -> float:
        return 0.3 if n > 1 else 0.01

    def is_finished(self, response: Any) -> bool:
        return True

    def generate_text(
        self, prompt: Any, n: int = 1, temperature: float = 0.01, stop: Any = None, callbacks: Any = None
    ) -> Any:
        from langchain_core.outputs import Generation, LLMResult

        text = self._client.generate(
            model=self._settings.ollama_model_name,
            prompt=prompt.to_string(),
            timeout=self._settings.evaluation_batch_timeout_seconds,
        )
        return LLMResult(generations=[[Generation(text=text)]])

    async def agenerate_text(
        self, prompt: Any, n: int = 1, temperature: float | None = 0.01, stop: Any = None, callbacks: Any = None
    ) -> Any:
        return self.generate_text(prompt, n, temperature or 0.01, stop, callbacks)


class _ProjectRagasEmbeddings:
    """Wraps the project's own `Embedder` (Task 3.1) so RAGAS's
    embedding-based scoring (used internally by `answer_relevancy`) uses
    the exact same configured embedding model this project already
    established, without modifying `Embedder` itself.

    Injectable `embedder` for testing without a live/downloadable model.
    """

    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self._embedder = embedder or Embedder(settings=settings)
        self.run_config = None
        self.cache = None

    def embed_query(self, text: str) -> list[float]:
        return self._embedder.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_queries(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def set_run_config(self, run_config: Any) -> None:
        self.run_config = run_config


def _build_samples(items: Sequence[EvaluationItem]) -> list[Any]:
    """Build RAGAS `SingleTurnSample` objects from our official
    `EvaluationItem` triples.

    Pure and network-free (Pydantic model construction only) -- callable
    and testable without any live LLM/embeddings/RAGAS execution.

    `reference` is set to `item.response` for every sample. This is NOT
    an independent ground-truth answer -- see this module's docstring's
    "CONTEXT_PRECISION" section for exactly why it's still required and
    why that's safe specifically for `context_precision`. It is never
    read by anything computing `context_recall`, because no
    `context_recall` metric is ever included in `_build_metrics()`'s
    output.
    """

    from ragas import SingleTurnSample

    return [
        SingleTurnSample(
            user_input=item.query,
            response=item.response,
            retrieved_contexts=list(item.contexts),
            reference=item.response,
        )
        for item in items
    ]


def _build_metrics(llm: Any, embeddings: Any) -> list[Any]:
    """Build the RAGAS metric objects this adapter actually computes:
    `Faithfulness`, `AnswerRelevancy`, `ContextPrecision`. Deliberately
    does NOT include `ContextRecall` -- see module docstring.

    Pure (dataclass construction only, no network calls) -- testable
    without live RAGAS execution.
    """

    from ragas.metrics import AnswerRelevancy, ContextPrecision, Faithfulness

    return [
        Faithfulness(llm=llm),
        AnswerRelevancy(llm=llm, embeddings=embeddings),
        ContextPrecision(llm=llm),
    ]


class RagasEvaluationAdapter:
    """Real RAGAS-backed implementation of `RagasEvaluatorProtocol`.

    See this module's docstring for: why this is not live-tested here,
    and why `context_recall` is always represented as structurally
    unavailable rather than computed (it is never requested from RAGAS
    at all, under any circumstances).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def evaluate_batch(
        self, items: Sequence[EvaluationItem]
    ) -> list[tuple[EvaluationMetrics, dict[str, str]]]:
        import pandas as pd  # type: ignore[import-untyped]  # no stub package installed for pandas in this environment
        from ragas import EvaluationDataset, RunConfig, evaluate

        llm = _OllamaRagasLLM(self._settings)
        embeddings = _ProjectRagasEmbeddings(self._settings)

        samples = _build_samples(items)
        dataset = EvaluationDataset(samples=samples)
        metrics = _build_metrics(llm, embeddings)
        run_config = RunConfig(timeout=int(self._settings.evaluation_batch_timeout_seconds))

        # `llm`/`embeddings` are duck-typed wrappers satisfying RAGAS's
        # BaseRagasLLM/BaseRagasEmbeddings interfaces at the
        # attribute/method level (see class docstrings for why they
        # don't subclass those dataclass-based ABCs directly) --
        # deliberately not the exact static types `evaluate()` declares,
        # hence the two ignores below.
        result: Any = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,  # type: ignore[arg-type]
            embeddings=embeddings,  # type: ignore[arg-type]
            run_config=run_config,
            raise_exceptions=False,
            show_progress=False,
        )

        scores_frame = result.to_pandas()

        parsed: list[tuple[EvaluationMetrics, dict[str, str]]] = []
        for row_index in range(len(items)):
            row = scores_frame.iloc[row_index]
            metric_values: dict[str, float | None] = {}
            errors: dict[str, str] = {}
            for metric_name in _RAGAS_COMPUTED_METRIC_NAMES:
                raw_value = row.get(metric_name)
                if raw_value is None or pd.isna(raw_value):
                    metric_values[metric_name] = None
                    errors[metric_name] = "RAGAS did not return a value for this metric (see adapter logs)."
                else:
                    metric_values[metric_name] = float(raw_value)

            # context_recall: ALWAYS structurally unavailable under the
            # official contract -- never requested from RAGAS above,
            # never fabricated. Unconditional, identical for every item.
            metric_values["context_recall"] = None
            errors["context_recall"] = CONTEXT_RECALL_UNAVAILABLE_REASON

            parsed.append((EvaluationMetrics(**metric_values), errors))

        return parsed
