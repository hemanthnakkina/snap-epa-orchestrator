# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for epa_orchestrator.hugepages_db."""

import pytest

from epa_orchestrator import hugepages_db


@pytest.fixture(autouse=True)
def reset_db():
    """Reset the hugepages database before and after each test."""
    hugepages_db._allocations.clear()
    yield
    hugepages_db._allocations.clear()


def test_record_and_list_allocations():
    """Test recording and listing hugepage allocations."""
    hugepages_db.record_allocation("svc-a", 0, 2048, 10)
    hugepages_db.record_allocation("svc-a", 0, 1048576, 2)
    hugepages_db.record_allocation("svc-b", 1, 2048, 5)

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
    hugepages_db.record_allocation("svc-a", 0, 2048, 10)
    hugepages_db.record_allocation("svc-a", 1, 2048, 1)
    hugepages_db.record_allocation("svc-b", 0, 1048576, 3)

    node0 = hugepages_db.list_allocations_for_node(0)
    assert {e["service_name"] for e in node0} == {"svc-a", "svc-b"}
    assert any(e["size_kb"] == 2048 and e["count"] == 10 for e in node0)
    assert any(e["size_kb"] == 1048576 and e["count"] == 3 for e in node0)

    node1 = hugepages_db.list_allocations_for_node(1)
    assert node1 == [{"service_name": "svc-a", "size_kb": 2048, "count": 1}]
