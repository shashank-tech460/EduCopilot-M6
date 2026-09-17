"""MVP M4 -- independent tests for GenerationAuthorityClient.

Uses `mongomock` (already an available dependency in this environment,
matching Team 4A's own established Phase 1 testing convention -- a real
`pymongo`-compatible interface, not a hand-rolled stub) so these tests
exercise the actual query shape (`$in`, `workspaceId` match, projection)
against something that behaves like real MongoDB, not merely a mock that
always agrees with whatever the code under test asks of it.
"""

from __future__ import annotations

import mongomock
import pytest
from bson import ObjectId

from app.services.generation_authority import (
    GenerationAuthorityClient,
    GenerationAuthorityUnavailableError,
)

WORKSPACE_A = ObjectId()
WORKSPACE_B = ObjectId()
FILE_1 = ObjectId()
FILE_2 = ObjectId()


def _client_with_files(*files: dict) -> GenerationAuthorityClient:
    mongo_client = mongomock.MongoClient()
    collection = mongo_client["test_db"]["files"]
    if files:
        collection.insert_many(files)
    return GenerationAuthorityClient(mongo_client=mongo_client, database_name="test_db", collection_name="files")


class TestBasicLookup:
    def test_returns_current_generation_for_a_real_file_in_the_workspace(self):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 1})

        result = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))

        assert result == {str(FILE_1): 1}

    def test_multiple_candidates_resolved_in_one_batched_call(self):
        client = _client_with_files(
            {"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 2},
            {"_id": FILE_2, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 5},
        )

        result = client.get_current_generations({str(FILE_1), str(FILE_2)}, workspace_id=str(WORKSPACE_A))

        assert result == {str(FILE_1): 2, str(FILE_2): 5}

    def test_empty_candidate_set_returns_empty_without_querying(self):
        client = _client_with_files()
        result = client.get_current_generations(set(), workspace_id=str(WORKSPACE_A))
        assert result == {}


class TestFailClosed:
    def test_file_not_found_excludes_that_candidate(self):
        client = _client_with_files()  # no files at all
        result = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))
        assert result == {}

    def test_file_belongs_to_a_different_workspace_excludes_it(self):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_B, "currentIngestionGeneration": 1})
        result = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))
        assert result == {}

    def test_missing_currentIngestionGeneration_excludes_that_candidate(self):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A})
        result = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))
        assert result == {}

    def test_null_currentIngestionGeneration_excludes_that_candidate(self):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": None})
        result = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))
        assert result == {}

    @pytest.mark.parametrize("malformed_value", ["1", 1.5, [1], {"n": 1}, True, False])
    def test_malformed_currentIngestionGeneration_excludes_that_candidate(self, malformed_value):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": malformed_value})
        result = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))
        assert result == {}

    def test_malformed_document_id_excludes_only_that_candidate_not_the_whole_batch(self):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 1})

        result = client.get_current_generations(
            {str(FILE_1), "not-a-valid-object-id"}, workspace_id=str(WORKSPACE_A)
        )

        assert result == {str(FILE_1): 1}
        assert "not-a-valid-object-id" not in result

    def test_malformed_workspace_id_excludes_every_candidate(self):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 1})
        result = client.get_current_generations({str(FILE_1)}, workspace_id="not-a-valid-object-id")
        assert result == {}

    def test_mixed_good_and_malformed_document_ids_only_malformed_ones_are_excluded(self):
        """TEST 12: a malformed document_id cannot cause arbitrary Mongo
        lookup behavior -- it is filtered BEFORE the query, and cannot
        affect the outcome for other, well-formed candidates."""

        client = _client_with_files(
            {"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 1},
            {"_id": FILE_2, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 2},
        )
        malformed_candidates = {"'; DROP TABLE files; --", "../../etc/passwd", "", "x" * 500}

        result = client.get_current_generations(
            {str(FILE_1), str(FILE_2)} | malformed_candidates, workspace_id=str(WORKSPACE_A)
        )

        assert result == {str(FILE_1): 1, str(FILE_2): 2}

    def test_mongo_total_failure_raises_generation_authority_unavailable(self):
        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 1})

        class ExplodingCollection:
            def find(self, *args, **kwargs):
                from pymongo.errors import PyMongoError

                raise PyMongoError("connection refused")

        client._collection = ExplodingCollection()

        with pytest.raises(GenerationAuthorityUnavailableError):
            client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))

    def test_unavailable_error_message_never_leaks_connection_details(self):
        error = GenerationAuthorityUnavailableError()
        message = str(error)
        assert "mongodb://" not in message
        assert "password" not in message.lower()


class TestReingestionScenario:
    def test_current_generation_reflects_the_latest_reingestion(self):
        """Generation 1 -> Generation 2 re-ingestion: Mongo's
        currentIngestionGeneration is the ONLY thing that determines
        what's current -- this test simulates the Mongo-side state after
        Team 4A's re-ingestion has completed."""

        client = _client_with_files({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 2})
        result = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))
        assert result == {str(FILE_1): 2}


class TestFreshnessAndConsistency:
    def test_no_caching_a_changed_mongo_value_is_reflected_on_the_next_call(self):
        mongo_client = mongomock.MongoClient()
        collection = mongo_client["test_db"]["files"]
        collection.insert_one({"_id": FILE_1, "workspaceId": WORKSPACE_A, "currentIngestionGeneration": 1})
        client = GenerationAuthorityClient(mongo_client=mongo_client, database_name="test_db", collection_name="files")

        first = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))
        collection.update_one({"_id": FILE_1}, {"$set": {"currentIngestionGeneration": 2}})
        second = client.get_current_generations({str(FILE_1)}, workspace_id=str(WORKSPACE_A))

        assert first == {str(FILE_1): 1}
        assert second == {str(FILE_1): 2}

    def test_client_never_overrides_read_preference_to_a_non_primary_value(self):
        """The approved architecture requires PRIMARY/strong consistency.
        pymongo's own default IS PRIMARY -- this test proves this module
        never overrides it to something weaker anywhere in its own
        query construction (the class's docstring discusses this design
        choice in prose, which legitimately mentions these terms; this
        check targets actual CODE usage, not documentation text)."""

        import ast
        import inspect
        import textwrap

        source = inspect.getsource(GenerationAuthorityClient)
        tree = ast.parse(textwrap.dedent(source))

        offending_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "read_preference":
                offending_calls.append(node)
            if isinstance(node, ast.Attribute) and node.attr in ("secondary", "secondary_preferred", "nearest"):
                offending_calls.append(node)

        assert offending_calls == []
