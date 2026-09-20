"""Phase 5A: controlled cross-script query-transformation evaluation.

EVALUATION ONLY -- reproduces the Phase 2/4A/4D scripts' own safety
discipline:
  - Reads the CANONICAL Qdrant collection (`Settings.canonical_qdrant_collection_name`,
    i.e. `educopilot_chunks`) exclusively through VectorStoreManager's
    read-only methods (`search_similar`, `scroll_all_chunks`). Never
    writes, never creates or deletes a collection, never re-embeds.
  - Uses the REAL production Embedder (all-MiniLM-L6-v2) and the REAL,
    unmodified HybridRetriever -- Phase 5A's MultiQueryRetriever wraps
    it by composition only, adding no new authorization logic.
  - Uses the approved 75-entry ground truth
    (team4b/data/phase2_ground_truth_approved.json) completely
    unmodified -- never edited, never re-ordered, never filtered before
    scoring.
  - Uses a documented, evaluation-only PermissiveGenerationAuthorityClient
    (same rationale as Phase 4B/4C/4D: several of the 75 entries'
    document_ids have no corresponding Mongo `files` record in this dev
    environment, which would make the real fail-closed authority exclude
    them regardless of retrieval-mechanism quality, confounding this
    specifically-retrieval-focused comparison). Never used in production
    code -- generation-authority ENFORCEMENT itself is separately and
    exhaustively covered by tests/test_phase5a_cross_script_retrieval_evaluation.py's
    TestSafetyInheritedFromHybridRetriever class, which does use a real
    fail-closed fake.

Compares, for every one of the 75 entries:
  BASELINE   -- HybridRetriever.retrieve(original_query, ...)
  CANDIDATE  -- MultiQueryRetriever.retrieve(original_query, ...), which
                generates the original query -- always -- plus a
                deterministic Latin->Devanagari transliteration variant
                when it differs, retrieves each independently, and merges.

Two retrieval configurations are measured per approach, matching Phase
4A/4D's own methodology:
  - "pool" config: top_k=100, score_threshold=0.0 -- an unfiltered
    candidate pool, used for Recall@1/3/5/10/100 and MRR (does the
    relevant chunk appear ANYWHERE in a big pool, and how highly ranked).
  - "production" config: top_k=10, score_threshold=Settings.default_score_threshold
    (0.3) -- exactly what a real end-user request would receive today.
    Used for the honest "final retrieval recall" number and the
    hit/miss transition analysis, since Recall@100-in-a-pool and
    Recall@10-under-the-real-threshold can (and, per Phase 4D, often
    do) tell different stories.

This script NEVER fabricates a result: if Qdrant is unreachable, it
raises rather than substituting synthetic data.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

TEAM4B_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TEAM4B_ROOT))

import logging

logging.basicConfig(level=logging.WARNING)

from app.core.config import get_settings
from app.services.bm25_index import BM25Index
from app.services.embedder import Embedder
from app.services.hybrid_retriever import HybridRetriever
from app.services.multi_query_retrieval import MultiQueryRetriever
from app.services.query_transform import generate_query_variants
from app.services.vector_store import VectorStoreManager

GROUND_TRUTH_PATH = TEAM4B_ROOT / "data" / "phase2_ground_truth_approved.json"
OUTPUT_JSON_PATH = TEAM4B_ROOT / "data" / "phase5a_cross_script_retrieval_evaluation_report.json"


class PermissiveGenerationAuthorityClient:
    """Evaluation-only fake -- see module docstring. Never used in
    production code (app/api/dependencies.py, app/services/rag_service.py
    are untouched by Phase 5A)."""

    def get_current_generations(self, document_ids, *, workspace_id):
        return {document_id: 1 for document_id in document_ids}


def rank_of(ranked_ids: list[str], relevant: set[str]) -> int | None:
    for i, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant:
            return i
    return None


def recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked_ids: list[str], relevant: set[str]) -> float:
    rank = rank_of(ranked_ids, relevant)
    return 1.0 / rank if rank is not None else 0.0


RECALL_KS = (1, 3, 5, 10, 100)


def summarize_pool(per_query: list[dict]) -> dict:
    if not per_query:
        return {"query_count": 0, "recall_at_k": {str(k): 0.0 for k in RECALL_KS}, "mrr": 0.0}
    recalls = {k: [] for k in RECALL_KS}
    rrs = []
    for entry in per_query:
        relevant = set(entry["relevant_chunk_ids"])
        ranked = entry["ranked_ids"]
        for k in RECALL_KS:
            recalls[k].append(recall_at_k(ranked, relevant, k))
        rrs.append(reciprocal_rank(ranked, relevant))
    return {
        "query_count": len(per_query),
        "recall_at_k": {str(k): sum(v) / len(v) for k, v in recalls.items()},
        "mrr": sum(rrs) / len(rrs),
    }


def summarize_production_hit_rate(per_query: list[dict]) -> dict:
    if not per_query:
        return {"query_count": 0, "hit_rate_at_production_top_k": 0.0}
    hits = [1.0 if entry["hit"] else 0.0 for entry in per_query]
    return {"query_count": len(per_query), "hit_rate_at_production_top_k": sum(hits) / len(hits)}


def group_key(entry: dict) -> str:
    return f"{entry['query_language']}->{entry['source_language']}"


def main() -> None:
    settings = get_settings()
    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(ground_truth)} approved ground-truth entries (unmodified).")

    vector_store = VectorStoreManager(settings=settings)
    embedder = Embedder(settings=settings)
    bm25_index = BM25Index()
    authority = PermissiveGenerationAuthorityClient()
    retriever = HybridRetriever(
        vector_store=vector_store, bm25_index=bm25_index, embedder=embedder,
        generation_authority=authority, settings=settings, reranker=None,
    )

    t0 = time.perf_counter()
    chunk_count = retriever.refresh_bm25_corpus()
    print(f"BM25 corpus refreshed from canonical collection '{settings.canonical_qdrant_collection_name}': {chunk_count} chunks in {time.perf_counter() - t0:.2f}s (read-only scroll).")

    multi_retriever = MultiQueryRetriever(retriever, variant_generator=generate_query_variants)

    pool_baseline: list[dict] = []
    pool_candidate: list[dict] = []
    prod_baseline: list[dict] = []
    prod_candidate: list[dict] = []
    transitions: list[dict] = []
    latency_records: list[dict] = []

    production_top_k = 10
    production_threshold = settings.default_score_threshold

    total_start = time.perf_counter()
    for i, entry in enumerate(ground_truth, start=1):
        query = entry["query"]
        workspace_id = entry["workspace_id"]
        relevant = set(entry["relevant_chunk_ids"])

        variant_gen_start = time.perf_counter()
        variants = generate_query_variants(query)
        variant_gen_seconds = time.perf_counter() - variant_gen_start
        variant_sources = [v.source for v in variants]

        # -- pool config (top_k=100, threshold=0.0) --
        t = time.perf_counter()
        baseline_pool = retriever.retrieve(query, workspace_id=workspace_id, top_k=100, score_threshold=0.0, search_mode="hybrid")
        baseline_pool_seconds = time.perf_counter() - t

        t = time.perf_counter()
        candidate_pool = multi_retriever.retrieve(query, workspace_id=workspace_id, top_k=100, score_threshold=0.0, search_mode="hybrid", per_variant_pool_size=100)
        candidate_pool_seconds = time.perf_counter() - t

        baseline_pool_ids = [r.chunk_id for r in baseline_pool]
        candidate_pool_ids = [r.chunk_id for r in candidate_pool]
        pool_baseline.append({"relevant_chunk_ids": entry["relevant_chunk_ids"], "ranked_ids": baseline_pool_ids})
        pool_candidate.append({"relevant_chunk_ids": entry["relevant_chunk_ids"], "ranked_ids": candidate_pool_ids})

        # -- production config (top_k=10, threshold=0.3) --
        t = time.perf_counter()
        baseline_prod = retriever.retrieve(query, workspace_id=workspace_id, top_k=production_top_k, score_threshold=production_threshold, search_mode="hybrid")
        baseline_prod_seconds = time.perf_counter() - t

        t = time.perf_counter()
        candidate_prod = multi_retriever.retrieve(query, workspace_id=workspace_id, top_k=production_top_k, score_threshold=production_threshold, search_mode="hybrid", per_variant_pool_size=100)
        candidate_prod_seconds = time.perf_counter() - t

        baseline_prod_ids = [r.chunk_id for r in baseline_prod]
        candidate_prod_ids = [r.chunk_id for r in candidate_prod]
        baseline_hit = bool(set(baseline_prod_ids) & relevant)
        candidate_hit = bool(set(candidate_prod_ids) & relevant)
        prod_baseline.append({"query_id": entry["query_id"], "hit": baseline_hit})
        prod_candidate.append({"query_id": entry["query_id"], "hit": candidate_hit})

        baseline_pool_rank = rank_of(baseline_pool_ids, relevant)
        candidate_pool_rank = rank_of(candidate_pool_ids, relevant)

        if baseline_hit and not candidate_hit:
            transition = "hit_to_miss_regression"
        elif not baseline_hit and candidate_hit:
            transition = "miss_to_hit_improvement"
        elif baseline_hit and candidate_hit:
            transition = "unchanged_hit"
        else:
            transition = "unchanged_miss"

        rank_change = None
        if baseline_pool_rank is not None and candidate_pool_rank is not None:
            rank_change = baseline_pool_rank - candidate_pool_rank  # positive = candidate ranked better (lower number)

        transitions.append({
            "query_id": entry["query_id"],
            "query_language": entry["query_language"],
            "source_language": entry["source_language"],
            "language_pair": group_key(entry),
            "transition_at_production_top10": transition,
            "baseline_pool_rank_top100": baseline_pool_rank,
            "candidate_pool_rank_top100": candidate_pool_rank,
            "rank_change_positive_is_improvement": rank_change,
            "candidate_query_variant_sources_generated": variant_sources,
        })

        latency_records.append({
            "query_id": entry["query_id"],
            "language_pair": group_key(entry),
            "variant_generation_seconds": variant_gen_seconds,
            "num_variants": len(variants),
            "baseline_pool_retrieval_seconds": baseline_pool_seconds,
            "candidate_pool_retrieval_seconds": candidate_pool_seconds,
            "baseline_production_retrieval_seconds": baseline_prod_seconds,
            "candidate_production_retrieval_seconds": candidate_prod_seconds,
        })

        if i % 10 == 0 or i == len(ground_truth):
            print(f"  [{i}/{len(ground_truth)}] {entry['query_id']}: baseline_hit={baseline_hit} candidate_hit={candidate_hit} transition={transition}")

    total_seconds = time.perf_counter() - total_start
    print(f"\nTotal evaluation time: {total_seconds:.2f}s for {len(ground_truth)} queries ({total_seconds / len(ground_truth) * 1000:.1f}ms/query average, both approaches combined).")

    # -- Aggregate: overall pool-based recall/MRR --
    overall_baseline_pool = summarize_pool(pool_baseline)
    overall_candidate_pool = summarize_pool(pool_candidate)

    # -- Aggregate: overall production hit-rate --
    overall_baseline_prod = summarize_production_hit_rate(prod_baseline)
    overall_candidate_prod = summarize_production_hit_rate(prod_candidate)

    # -- By language pair --
    by_pair_baseline_pool: dict[str, list[dict]] = defaultdict(list)
    by_pair_candidate_pool: dict[str, list[dict]] = defaultdict(list)
    by_pair_baseline_prod: dict[str, list[dict]] = defaultdict(list)
    by_pair_candidate_prod: dict[str, list[dict]] = defaultdict(list)
    for entry, pb, pc, prb, prc in zip(ground_truth, pool_baseline, pool_candidate, prod_baseline, prod_candidate):
        key = group_key(entry)
        by_pair_baseline_pool[key].append(pb)
        by_pair_candidate_pool[key].append(pc)
        by_pair_baseline_prod[key].append(prb)
        by_pair_candidate_prod[key].append(prc)

    language_pair_results = {}
    for key in sorted(by_pair_baseline_pool):
        language_pair_results[key] = {
            "query_count": len(by_pair_baseline_pool[key]),
            "baseline_pool": summarize_pool(by_pair_baseline_pool[key]),
            "candidate_pool": summarize_pool(by_pair_candidate_pool[key]),
            "baseline_production_hit_rate": summarize_production_hit_rate(by_pair_baseline_prod[key]),
            "candidate_production_hit_rate": summarize_production_hit_rate(by_pair_candidate_prod[key]),
        }

    # -- By query_type --
    by_type_baseline_pool: dict[str, list[dict]] = defaultdict(list)
    by_type_candidate_pool: dict[str, list[dict]] = defaultdict(list)
    for entry, pb, pc in zip(ground_truth, pool_baseline, pool_candidate):
        by_type_baseline_pool[entry["query_type"]].append(pb)
        by_type_candidate_pool[entry["query_type"]].append(pc)
    query_type_results = {
        qtype: {
            "query_count": len(by_type_baseline_pool[qtype]),
            "baseline_pool": summarize_pool(by_type_baseline_pool[qtype]),
            "candidate_pool": summarize_pool(by_type_candidate_pool[qtype]),
        }
        for qtype in sorted(by_type_baseline_pool)
    }

    transition_counts = Counter(t["transition_at_production_top10"] for t in transitions)
    transition_counts_by_pair: dict[str, Counter] = defaultdict(Counter)
    for t in transitions:
        transition_counts_by_pair[t["language_pair"]][t["transition_at_production_top10"]] += 1

    rank_changes = [t["rank_change_positive_is_improvement"] for t in transitions if t["rank_change_positive_is_improvement"] is not None]
    significant_improvements = [t for t in transitions if (t["rank_change_positive_is_improvement"] or 0) >= 5]
    significant_regressions = [t for t in transitions if (t["rank_change_positive_is_improvement"] or 0) <= -5]

    latency_summary = {
        "mean_variant_generation_seconds": sum(r["variant_generation_seconds"] for r in latency_records) / len(latency_records),
        "mean_baseline_pool_retrieval_seconds": sum(r["baseline_pool_retrieval_seconds"] for r in latency_records) / len(latency_records),
        "mean_candidate_pool_retrieval_seconds": sum(r["candidate_pool_retrieval_seconds"] for r in latency_records) / len(latency_records),
        "mean_baseline_production_retrieval_seconds": sum(r["baseline_production_retrieval_seconds"] for r in latency_records) / len(latency_records),
        "mean_candidate_production_retrieval_seconds": sum(r["candidate_production_retrieval_seconds"] for r in latency_records) / len(latency_records),
        "mean_candidate_overhead_factor_production": (
            sum(r["candidate_production_retrieval_seconds"] for r in latency_records)
            / sum(r["baseline_production_retrieval_seconds"] for r in latency_records)
        ),
        "num_variants_distribution": dict(Counter(r["num_variants"] for r in latency_records)),
    }

    report = {
        "phase": "5A",
        "canonical_collection": settings.canonical_qdrant_collection_name,
        "canonical_point_count_note": "Verified separately before and after this script's run (read-only) -- see the Phase 5A review markdown.",
        "embedding_model": settings.embedding_model_name,
        "reranker_enabled_in_this_run": False,
        "ground_truth_entry_count": len(ground_truth),
        "production_config": {"top_k": production_top_k, "score_threshold": production_threshold},
        "pool_config": {"top_k": 100, "score_threshold": 0.0},
        "overall": {
            "baseline_pool": overall_baseline_pool,
            "candidate_pool": overall_candidate_pool,
            "baseline_production_hit_rate": overall_baseline_prod,
            "candidate_production_hit_rate": overall_candidate_prod,
        },
        "by_language_pair": language_pair_results,
        "by_query_type": query_type_results,
        "transition_analysis_at_production_top10": {
            "counts": dict(transition_counts),
            "counts_by_language_pair": {k: dict(v) for k, v in transition_counts_by_pair.items()},
            "hit_to_miss_regressions": [t for t in transitions if t["transition_at_production_top10"] == "hit_to_miss_regression"],
            "miss_to_hit_improvements": [t for t in transitions if t["transition_at_production_top10"] == "miss_to_hit_improvement"],
        },
        "rank_change_analysis_pool_top100": {
            "mean_rank_change_when_both_hit": (sum(rank_changes) / len(rank_changes)) if rank_changes else None,
            "significant_improvements_rank_change_gte_5": significant_improvements,
            "significant_regressions_rank_change_lte_neg5": significant_regressions,
        },
        "latency": latency_summary,
        "total_evaluation_seconds": total_seconds,
        "per_query_transitions": transitions,
    }

    OUTPUT_JSON_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUTPUT_JSON_PATH}")

    print("\n=== OVERALL (pool top_k=100, threshold=0.0) ===")
    print(f"Baseline  recall@k: {overall_baseline_pool['recall_at_k']}  MRR={overall_baseline_pool['mrr']:.4f}")
    print(f"Candidate recall@k: {overall_candidate_pool['recall_at_k']}  MRR={overall_candidate_pool['mrr']:.4f}")
    print("\n=== OVERALL (production top_k=10, threshold=0.3) hit-rate ===")
    print(f"Baseline:  {overall_baseline_prod['hit_rate_at_production_top_k']:.4f}")
    print(f"Candidate: {overall_candidate_prod['hit_rate_at_production_top_k']:.4f}")
    print("\n=== Transitions at production top_k=10 ===")
    print(dict(transition_counts))


if __name__ == "__main__":
    main()
