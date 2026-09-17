"""RetrievalResult -- the minimal piece of Task 1.2's model catalog that
Task 2.1 (VectorStoreManager) structurally depends on for its own return
type.

SCOPE NOTE (historical): at the time this file was written, Task 1.2
("Define Pydantic models and enums") had not yet been implemented --
only Task 1.1 (project structure/config) was approved. The official
design document's `VectorStoreManager.search_similar` signature returns
`list[RetrievalResult]`, and `RetrievalResult` is given as a concrete,
fully-specified dataclass in the design document itself (unlike
`ContextChunk`, which is referenced only by name with no field list
anywhere in the official documents -- see `app/services/vector_store.py`
for how that gap is handled).

Because `RetrievalResult`'s shape is fully and unambiguously specified
already, reproducing it here was not "inventing a contract" -- it was
the one Task 1.2 artifact Task 2.1 could not avoid needing.

UPDATE (Corrective Task 1.2): the remaining Task 1.2 models --
`SearchMode`, `RetrievalConfig`, `QueryRequest`, `SourceAttribution`,
`QueryResponse` -- have since been implemented in
`app/models/query.py`, a separate file, deliberately. `RetrievalResult`
here is an internal component-contract type (VectorStoreManager/
HybridRetriever's own return value shape); the `query.py` models are
API-contract types a later task will build FROM this data. They are
kept in separate files rather than merged, and this dataclass was not
redesigned or replaced as part of that corrective work, per that task's
explicit instruction to preserve already-approved behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RetrievalResult:
    """One retrieved Context_Chunk, as returned by VectorStoreManager /
    (later) HybridRetriever.

    Verbatim shape from the official design document:
        chunk_id: str
        text: str
        relevance_score: float  # 0.0 to 1.0
        metadata: dict
    """

    chunk_id: str
    text: str
    relevance_score: float
    metadata: dict[str, Any]
