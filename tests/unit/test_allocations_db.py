# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Concise unit tests for epa_orchestrator.allocations_db."""


class TestAllocationsDB:
    """Unit tests for AllocationsDB class."""

    def test_allocate_and_get_allocation(self, fresh_allocations_db):
        """Test allocation and retrieval of CPU cores."""
        fresh_allocations_db.allocate_cores("snap1", "0-1")
        assert fresh_allocations_db.get_allocation("snap1") == "0-1"
        assert fresh_allocations_db._allocated_cpus == {0, 1}

    def test_remove_allocation(self, fresh_allocations_db):
        """Test removal of a CPU allocation."""
        fresh_allocations_db.allocate_cores("snap1", "0-1")
        assert fresh_allocations_db.remove_allocation("snap1") is True
        assert fresh_allocations_db.get_allocation("snap1") is None
        assert fresh_allocations_db._allocated_cpus == set()

    def test_get_system_stats(self, fresh_allocations_db):
        """Test retrieval of system statistics."""
        fresh_allocations_db.allocate_cores("snap1", "0-1")
        stats = fresh_allocations_db.get_system_stats("0-3")
        assert stats["total_available_cpus"] == 4
        assert stats["total_allocated_cpus"] == 2
        assert stats["remaining_available_cpus"] == 2
        assert stats["total_allocations"] == 1

    def test_can_allocate_cpus(self, fresh_allocations_db):
        """Test checking if CPUs can be allocated."""
        assert fresh_allocations_db.can_allocate_cpus(2, "0-3") is True
        fresh_allocations_db.allocate_cores("snap1", "0-3")
        assert fresh_allocations_db.can_allocate_cpus(1, "0-3") is False

    def test_get_available_cpus_for_service_includes_own_allocation(self, fresh_allocations_db):
        """Re-allocation pool must include service's existing cores."""
        isolated = "96-127,224-255,352-383,480-511"  # 128 cores
        fresh_allocations_db.allocate_cores(
            "openstack-hypervisor", "96-127,224-255,352-383,480-495"
        )
        # Old get_available_cpus: excludes own allocation, so only 496-511 (16 CPUs)
        old_available = fresh_allocations_db.get_available_cpus(isolated)
        assert len(old_available) == 16
        # New get_available_cpus_for_service: includes own allocation
        new_available = fresh_allocations_db.get_available_cpus_for_service(
            "openstack-hypervisor", isolated
        )
        assert len(new_available) == 128
