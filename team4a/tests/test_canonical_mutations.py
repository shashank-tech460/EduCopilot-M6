"""Phase 1 tests -- app.pipeline.canonical_mutations.

A minimal in-memory fake Qdrant client is used (matching the existing
project convention of injectable fakes implementing the same Protocol a
real client does, e.g. Publisher's own `_FakeQdrantAdminClient` pattern in
tests/test_celery_app.py) -- no live Qdrant server required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.pipeline.canonical_mutations import delete_exact_points, delete_older_generations


@dataclass
class _FakePoint:
    id: str
    payload: dict


@dataclass
class _FakeMutationClient:
    """Implements QdrantMutationClientProtocol against an in-memory list of points."""

    points: list[_FakePoint] = field(default_factory=list)
    delete_by_id_calls: list[tuple[str, list[str]]] = field(default_factory=list)
    delete_by_generation_calls: list[tuple[str, str, int]] = field(default_factory=list)

    def delete_points_by_id(self, collection_name, point_ids):
        self.delete_by_id_calls.append((collection_name, list(point_ids)))
        ids = set(point_ids)
        self.points = [p for p in self.points if p.id not in ids]

    def delete_points_by_generation_filter(self, collection_name, document_id, less_than_generation):
        self.delete_by_generation_calls.append((collection_name, document_id, less_than_generation))
        self.points = [
            p
            for p in self.points
            if not (
                p.payload.get("document_id") == document_id
                and p.payload.get("ingestion_generation", 0) < less_than_generation
            )
        ]


@pytest.fixture()
def client():
    return _FakeMutationClient()


def test_delete_exact_points_removes_only_the_named_points(client):
    client.points = [
        _FakePoint(id="p1", payload={"document_id": "doc-A", "ingestion_generation": 5}),
        _FakePoint(id="p2", payload={"document_id": "doc-A", "ingestion_generation": 5}),
        _FakePoint(id="p3", payload={"document_id": "doc-A", "ingestion_generation": 6}),
    ]
    delete_exact_points(client, "educopilot_chunks", ["p1", "p2"])
    remaining_ids = {p.id for p in client.points}
    assert remaining_ids == {"p3"}


def test_delete_exact_points_with_empty_list_is_a_no_op(client):
    client.points = [_FakePoint(id="p1", payload={})]
    delete_exact_points(client, "educopilot_chunks", [])
    assert len(client.points) == 1
    assert client.delete_by_id_calls == []  # never even calls the client for an empty set


def test_monotonic_cleanup_removes_only_strictly_older_generations(client):
    client.points = [
        _FakePoint(id="gen10-a", payload={"document_id": "doc-A", "ingestion_generation": 10}),
        _FakePoint(id="gen10-b", payload={"document_id": "doc-A", "ingestion_generation": 10}),
        _FakePoint(id="gen11", payload={"document_id": "doc-A", "ingestion_generation": 11}),
    ]
    delete_older_generations(client, "educopilot_chunks", "doc-A", current_generation=11)
    remaining = {p.id for p in client.points}
    assert remaining == {"gen11"}


def test_monotonic_cleanup_never_deletes_the_current_or_higher_generation(client):
    """Direct regression guard for the exact defect a `!=` filter would
    reintroduce: chunks at or above the current generation must survive
    regardless of how the cleanup call is invoked."""

    client.points = [
        _FakePoint(id="gen13", payload={"document_id": "doc-A", "ingestion_generation": 13}),
    ]
    # Simulate a stale worker (generation 10) invoking cleanup against a
    # document that is ALREADY at generation 13 -- the monotonic `<`
    # filter must never match generation 13, no matter who calls it or
    # when.
    delete_older_generations(client, "educopilot_chunks", "doc-A", current_generation=10)
    assert {p.id for p in client.points} == {"gen13"}, (
        "a `< 10` filter must never remove a generation-13 point -- this is the exact "
        "stale-delete-deletes-newer-generation defect Rev.4.4 requires this filter to prevent"
    )


def test_cleanup_never_touches_another_document(client):
    client.points = [
        _FakePoint(id="a-old", payload={"document_id": "doc-A", "ingestion_generation": 1}),
        _FakePoint(id="b-old", payload={"document_id": "doc-B", "ingestion_generation": 1}),
    ]
    delete_older_generations(client, "educopilot_chunks", "doc-A", current_generation=2)
    remaining = {p.id for p in client.points}
    assert remaining == {"b-old"}, "cleanup for doc-A must never remove doc-B's points"
