# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for epa_orchestrator.hugepages_db."""

import pytest

from epa_orchestrator import hugepages_db


@pytest.fixture(autouse=True)
def reset_db():
    """Reset the hugepages database before and after each test (persistent-safe)."""
    hugepages_db.clear_all_allocations()
    yield
    hugepages_db.clear_all_allocations()


def test_record_and_list_allocations():
    """Test recording and listing hugepage allocations."""
    hugepages_db.upsert_allocation("svc-a", 0, 2048, 10)
    hugepages_db.upsert_allocation("svc-a", 0, 1048576, 2)
    hugepages_db.upsert_allocation("svc-b", 1, 2048, 5)

    data = hugepages_db.list_allocations()
    assert set(data.keys()) == {"svc-a", "svc-b"}
    assert {tuple(sorted((d["node_id"], d["size_kb"], d["count"]) for d in data["svc-a"]))} == {
        tuple(sorted(((0, 2048, 10), (0, 1048576, 2))))
    }
    assert len(data["svc-b"]) == 1
    assert data["svc-b"][0]["node_id"] == 1
    assert data["svc-b"][0]["size_kb"] == 2048
    assert data["svc-b"][0]["count"] == 5


def test_list_allocations_for_node_filters():
    """Test filtering hugepage allocations by node."""
    hugepages_db.upsert_allocation("svc-a", 0, 2048, 10)
    hugepages_db.upsert_allocation("svc-a", 1, 2048, 1)
    hugepages_db.upsert_allocation("svc-b", 0, 1048576, 3)

    node0 = hugepages_db.list_allocations_for_node(0)
    assert {e["service_name"] for e in node0} == {"svc-a", "svc-b"}
    assert any(e["size_kb"] == 2048 and e["count"] == 10 for e in node0)
    assert any(e["size_kb"] == 1048576 and e["count"] == 3 for e in node0)

    node1 = hugepages_db.list_allocations_for_node(1)
    assert node1 == [{"service_name": "svc-a", "size_kb": 2048, "count": 1}]


def test_upsert_replaces_for_same_key():
    """Upsert should replace prior entry for same service/node/size."""
    hugepages_db.upsert_allocation("svc-x", 0, 2048, 2)
    hugepages_db.upsert_allocation("svc-x", 0, 2048, 7)

    data = hugepages_db.list_allocations()
    assert set(data.keys()) == {"svc-x"}
    assert data["svc-x"] == [{"node_id": 0, "size_kb": 2048, "count": 7}]


def test_remove_allocation_for_key_removes_matching_entries():
    """Remove only the records matching service+node+size, keep others."""
    hugepages_db.upsert_allocation("svc-a", 0, 2048, 10)
    hugepages_db.upsert_allocation("svc-a", 0, 1048576, 2)
    hugepages_db.upsert_allocation("svc-a", 1, 2048, 1)
    hugepages_db.upsert_allocation("svc-b", 0, 2048, 5)

    removed = hugepages_db.remove_allocation_for_key("svc-a", 0, 2048)
    assert removed is True
    data = hugepages_db.list_allocations()
    # svc-a should still have the other two entries
    assert {tuple(sorted((d["node_id"], d["size_kb"], d["count"]) for d in data["svc-a"]))} == {
        tuple(sorted(((0, 1048576, 2), (1, 2048, 1))))
    }
    # svc-b unchanged
    assert data["svc-b"] == [{"node_id": 0, "size_kb": 2048, "count": 5}]


def test_remove_allocation_for_key_noop_when_missing():
    """Removing a non-existent key returns False and leaves state unchanged."""
    hugepages_db.upsert_allocation("svc-a", 0, 2048, 10)
    data_before = hugepages_db.list_allocations()
    removed = hugepages_db.remove_allocation_for_key("svc-a", 1, 2048)
    assert removed is False
    assert data_before == hugepages_db.list_allocations()


def test_remove_allocation_service_cleanup_when_empty():
    """Service entry is removed when all its records are deleted."""
    hugepages_db.upsert_allocation("svc-a", 0, 2048, 10)
    removed = hugepages_db.remove_allocation_for_key("svc-a", 0, 2048)
    assert removed is True
    assert hugepages_db.get_allocation("svc-a") is None
