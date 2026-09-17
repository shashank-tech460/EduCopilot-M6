"""Focused validation tests for the Phase 3 generalized, domain-agnostic
ground truth CANDIDATE dataset:

    team4b/data/phase3_generalized_ground_truth_candidate.json

Scope: pure data validation -- schema shape, uniqueness, allowed value
sets, and cross-checks against the real canonical corpus structure. This
suite never approves/rejects a relevance judgment (that remains a human
review decision) and never writes to Qdrant/MongoDB/Redis -- the one test
that talks to Qdrant (`TestRelevantChunkIdsExistInCanonicalCorpus`) only
ever calls `get_collections()`/`scroll()`, and skips (rather than fails)
if Qdrant is unreachable in the environment running the tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "phase3_generalized_ground_truth_candidate.json"
PHASE2_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "phase2_ground_truth_candidate.json"

VALID_QUERY_LANGUAGES = {"english", "hindi", "hinglish"}
VALID_SOURCE_LANGUAGES = {"english", "hindi", "hinglish", "mixed"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_STATUSES = {"CANDIDATE_NOT_VALIDATED"}

# Optional `review_flag` values introduced in the Phase 3.1 reconciliation
# pass -- set on entries that were specifically re-examined against their
# COMPLETE chunk text (not just the stored excerpt).
VALID_REVIEW_FLAGS = {"NEEDS_ADJACENT_CHUNK_VERIFICATION", "RE_VERIFIED_SUFFICIENT"}

# Real workspace_ids / document_ids the corpus actually contained at the
# time this dataset was built (confirmed by direct, read-only inspection --
# see phase3_generalized_ground_truth_review.md's corpus inspection
# summary). Used to catch a typo'd or invented ID, independent of whether
# Qdrant is reachable when these tests run.
KNOWN_REAL_WORKSPACE_IDS = {
    "6a912a1883f46878932e0eec",
    "6a8de2d7e43679cbe2ee243d",
}
KNOWN_REAL_DOCUMENT_IDS = {
    "6aa90e314ac03b89c7624ccb",
    "6aa72e4416cbab6b27d5f50b",
    "6aa846698a7bd709c53a5f4e",
    "6aa72dae16cbab6b27d5f508",
    "6aa90d9f4ac03b89c7624cc8",
    "6aa8457c8a7bd709c53a5f46",
    "6aaa7e8c81e2b76728b76bb6",
}

REQUIRED_STRING_FIELDS = [
    "query_id",
    "workspace_id",
    "query",
    "query_language",
    "source_language",
    "domain",
    "subject",
    "source_type",
    "query_type",
    "difficulty",
    "status",
    "rationale",
]


@pytest.fixture(scope="module")
def dataset() -> dict:
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "top-level JSON must be an object (with _notice + entries), not a bare array"
    return raw


@pytest.fixture(scope="module")
def entries(dataset: dict) -> list[dict]:
    return dataset["entries"]


class TestSchemaValidity:
    def test_file_has_notice_and_entries(self, dataset: dict):
        assert "_notice" in dataset
        assert "CANDIDATE" in dataset["_notice"]
        assert "entries" in dataset
        assert isinstance(dataset["entries"], list)
        assert len(dataset["entries"]) > 0

    def test_every_entry_has_required_string_fields(self, entries: list[dict]):
        for entry in entries:
            for field in REQUIRED_STRING_FIELDS:
                assert field in entry, f"{entry.get('query_id')!r} missing field {field!r}"
                assert isinstance(entry[field], str) and entry[field].strip(), (
                    f"{entry.get('query_id')!r}.{field} must be a non-empty string"
                )

    def test_relevant_chunk_ids_is_a_nonempty_list_of_strings(self, entries: list[dict]):
        for entry in entries:
            chunk_ids = entry["relevant_chunk_ids"]
            assert isinstance(chunk_ids, list) and len(chunk_ids) > 0, entry["query_id"]
            assert all(isinstance(cid, str) and cid for cid in chunk_ids), entry["query_id"]

    def test_document_id_is_a_string_or_explicitly_null(self, entries: list[dict]):
        for entry in entries:
            assert entry["document_id"] is None or isinstance(entry["document_id"], str), entry["query_id"]

    def test_document_id_is_null_only_for_genuinely_workspace_wide_entries(self, entries: list[dict]):
        for entry in entries:
            if entry["document_id"] is None:
                assert entry["query_type"] == "workspace_wide", entry["query_id"]
                assert "document_ids" in entry, entry["query_id"]

    def test_optional_document_ids_field_is_a_multi_entry_list_of_strings(self, entries: list[dict]):
        for entry in entries:
            if "document_ids" in entry:
                document_ids = entry["document_ids"]
                assert isinstance(document_ids, list) and len(document_ids) >= 2, entry["query_id"]
                assert all(isinstance(doc_id, str) and doc_id for doc_id in document_ids), entry["query_id"]


class TestUniqueQueryIds:
    def test_no_duplicate_query_ids(self, entries: list[dict]):
        query_ids = [entry["query_id"] for entry in entries]
        duplicates = {qid for qid in query_ids if query_ids.count(qid) > 1}
        assert not duplicates, f"duplicate query_id values: {duplicates}"


class TestAllowedValues:
    def test_query_language_is_allowed(self, entries: list[dict]):
        for entry in entries:
            assert entry["query_language"] in VALID_QUERY_LANGUAGES, entry["query_id"]

    def test_source_language_is_allowed(self, entries: list[dict]):
        for entry in entries:
            assert entry["source_language"] in VALID_SOURCE_LANGUAGES, entry["query_id"]

    def test_difficulty_is_allowed(self, entries: list[dict]):
        for entry in entries:
            assert entry["difficulty"] in VALID_DIFFICULTIES, entry["query_id"]

    def test_status_is_a_known_unvalidated_status(self, entries: list[dict]):
        """No entry may claim a validated/approved status -- this dataset
        is a candidate only, and no code path in its construction ever
        writes anything other than CANDIDATE_NOT_VALIDATED."""

        for entry in entries:
            assert entry["status"] in VALID_STATUSES, entry["query_id"]

    def test_mixed_source_language_is_used_only_with_multiple_relevant_chunks(self, entries: list[dict]):
        """`source_language: "mixed"` is reserved for the deliberate
        multi-document/cross-language hard cases -- it must never appear
        on an entry backed by only one chunk (that would just be a
        mislabeled single-language entry)."""

        for entry in entries:
            if entry["source_language"] == "mixed":
                assert len(entry["relevant_chunk_ids"]) > 1, entry["query_id"]


class TestWorkspaceAndDocumentIdsAreReal:
    """Cross-checks against a fixed snapshot of the real workspace_ids and
    document_ids present in the corpus when this dataset was built. This
    catches a typo'd or invented ID even when Qdrant is not reachable --
    see TestRelevantChunkIdsExistInCanonicalCorpus below for the live,
    read-only check against Qdrant itself."""

    def test_every_workspace_id_is_a_known_real_workspace(self, entries: list[dict]):
        for entry in entries:
            assert entry["workspace_id"] in KNOWN_REAL_WORKSPACE_IDS, entry["query_id"]

    def test_every_document_id_is_a_known_real_document_or_null(self, entries: list[dict]):
        for entry in entries:
            if entry["document_id"] is not None:
                assert entry["document_id"] in KNOWN_REAL_DOCUMENT_IDS, entry["query_id"]

    def test_every_entry_in_document_ids_is_a_known_real_document(self, entries: list[dict]):
        for entry in entries:
            for document_id in entry.get("document_ids", []):
                assert document_id in KNOWN_REAL_DOCUMENT_IDS, (entry["query_id"], document_id)


class TestRelevantChunkIdsExistInCanonicalCorpus:
    """The only test class in this file that talks to Qdrant -- read-only
    (`get_collections`/`scroll`), never writes, never modifies
    `educopilot_chunks`. Skips (does not fail the suite) if Qdrant is
    unreachable, since every other validation in this file is independent
    of live service availability."""

    @pytest.fixture(scope="class")
    @classmethod
    def real_chunk_ids(cls) -> set[str]:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.core.config import get_settings
        from qdrant_client import QdrantClient

        settings = get_settings()
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, check_compatibility=False)

        try:
            client.get_collections()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Qdrant not reachable in this environment: {exc}")

        chunk_ids: set[str] = set()
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=settings.canonical_qdrant_collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                chunk_id = (point.payload or {}).get("chunk_id")
                if chunk_id:
                    chunk_ids.add(chunk_id)
            if offset is None:
                break
        return chunk_ids

    def test_every_relevant_chunk_id_exists_in_the_canonical_collection(
        self, entries: list[dict], real_chunk_ids: set[str]
    ):
        missing = [
            (entry["query_id"], chunk_id)
            for entry in entries
            for chunk_id in entry["relevant_chunk_ids"]
            if chunk_id not in real_chunk_ids
        ]
        assert missing == [], f"chunk_ids referenced by candidate ground truth but not found in the canonical corpus: {missing}"


class TestPhase31Reconciliation:
    """Guards for the Phase 3.1 reconciliation pass -- catches a regression
    of any of that pass's specific corrections."""

    def test_review_flag_when_present_is_a_known_value(self, entries: list[dict]):
        for entry in entries:
            if "review_flag" in entry:
                assert entry["review_flag"] in VALID_REVIEW_FLAGS, entry["query_id"]

    def test_needs_adjacent_chunk_verification_entries_have_a_verification_note(self, entries: list[dict]):
        for entry in entries:
            if entry.get("review_flag") == "NEEDS_ADJACENT_CHUNK_VERIFICATION":
                assert isinstance(entry.get("verification_note"), str) and entry["verification_note"].strip(), (
                    entry["query_id"]
                )

    def test_a_needs_adjacent_chunk_verification_entry_must_not_also_claim_re_verified_sufficient(
        self, entries: list[dict]
    ):
        # Sanity: the two flags are mutually exclusive by construction.
        for entry in entries:
            assert not (
                entry.get("review_flag") == "NEEDS_ADJACENT_CHUNK_VERIFICATION"
                and entry.get("review_flag") == "RE_VERIFIED_SUFFICIENT"
            )

    def test_c_mft_mvt_query_type_is_comparison_not_advantage_disadvantage(self, entries: list[dict]):
        mft_entries = [e for e in entries if e["query_id"].startswith("c_mft_mvt__")]
        assert len(mft_entries) == 3
        for entry in mft_entries:
            assert entry["query_type"] == "comparison", entry["query_id"]

    def test_c_sjf_difficulty_query_does_not_claim_absolute_impossibility(self, entries: list[dict]):
        sjf_entries = [e for e in entries if e["query_id"].startswith("c_sjf_difficulty__")]
        assert len(sjf_entries) == 3
        english_entry = next(e for e in sjf_entries if e["query_language"] == "english")
        assert "can't be implemented" not in english_entry["query"].lower()
        assert "difficult" in english_entry["query"].lower()

    def test_c_memory_hierarchy_locality_was_resolved_with_a_real_continuation_chunk(self, entries: list[dict]):
        """Final live-Qdrant correction: the original chunk alone was
        confirmed insufficient (cut off before explaining the concept), and
        its real, live-verified continuation chunk was added -- never a
        silently invented chunk_id, and never the unrelated same-timestamp
        chunk (`29d10e3f-...`) that was inspected and rejected."""

        mem_entries = [e for e in entries if e["query_id"].startswith("c_memory_hierarchy_locality__")]
        assert len(mem_entries) == 3
        for entry in mem_entries:
            assert entry.get("review_flag") == "RE_VERIFIED_SUFFICIENT", entry["query_id"]
            assert entry["relevant_chunk_ids"] == [
                "2c1abf3a-9337-5167-8b7c-e6fb816f20cc",
                "1e2576b8-b408-5ded-9144-2d977076f961",
            ], entry["query_id"]
            assert "29d10e3f-8811-5937-999e-db01f7019a02" not in entry["relevant_chunk_ids"], entry["query_id"]

    def test_c_workspace_wide_scheduling_algorithms_query_does_not_overclaim_cpu_only(self, entries: list[dict]):
        entry = next(e for e in entries if e["query_id"] == "c_workspace_wide_scheduling_algorithms__q_english")
        assert "cpu scheduling" not in entry["query"].lower()
        assert entry["subject"] == "scheduling"
        # Still workspace-wide and multi-document, unchanged by the wording fix.
        assert entry["document_id"] is None
        assert len(entry["document_ids"]) == 3
        assert len(entry["relevant_chunk_ids"]) == 4

    def test_entry_count_unchanged_by_reconciliation(self, entries: list[dict]):
        assert len(entries) == 75


class TestPreviousPhase2DatasetIsPreserved:
    """Regression guard: this Phase 3 revision must never delete or
    truncate the earlier phase2_ground_truth_candidate.json."""

    def test_phase2_candidate_file_still_exists_and_is_valid(self):
        assert PHASE2_DATA_PATH.exists(), "phase2_ground_truth_candidate.json must not be deleted"
        raw = json.loads(PHASE2_DATA_PATH.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert len(raw["entries"]) == 36, "phase2 candidate dataset entry count changed unexpectedly"
