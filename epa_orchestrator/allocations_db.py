# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Database for tracking snap CPU allocations."""

import logging
from typing import Dict, Optional, Set, Tuple

from .cpu_pinning import get_isolated_cpus, get_thread_siblings_map
from .schemas import SnapAllocation
from .state_store import StateStore
from .utils import (
    get_cpus_in_numa_node,
    parse_cpu_ranges,
    to_ranges,
)


class AllocationsDB:
    """In-memory database for tracking snap CPU allocations."""

    def __init__(self) -> None:
        """Initialize the allocations database."""
        self._allocations: Dict[str, str] = {}
        self._allocated_cpus: Set[int] = set()
        self._explicit_allocations: Dict[str, str] = {}
        self._explicitly_allocated_cpus: Set[int] = set()
        logging.info("Allocations database initialized")
        self._state_store: StateStore = StateStore()
        self._load_from_store()

    def _parse_cpu_ranges(self, cpu_ranges: str) -> set[int]:
        """Parse CPU range string into a set of CPU numbers."""
        return set(parse_cpu_ranges(cpu_ranges))

    def _remove_service_allocation(self, service_name: str) -> set[int]:
        """Remove any allocation for a service and return removed CPU set."""
        removed: set[int] = set()
        if service_name in self._allocations:
            old_cores = self._allocations.pop(service_name)
            removed = self._parse_cpu_ranges(old_cores)
            self._allocated_cpus -= removed
        if service_name in self._explicit_allocations:
            old_explicit = self._parse_cpu_ranges(self._explicit_allocations.pop(service_name))
            self._explicitly_allocated_cpus -= old_explicit
        return removed

    def _snapshot(self) -> Dict[str, object]:
        """Return a JSON-serializable snapshot of current state."""
        return {
            "allocations": dict(self._allocations),
            "explicit_allocations": dict(self._explicit_allocations),
        }

    def _persist(self) -> None:
        try:
            self._state_store.update_section("allocations_db", self._snapshot())
        except Exception as e:
            logging.error(f"Failed to persist allocations state: {e}")

    def _load_from_store(self) -> None:

        data = self._state_store.read_section("allocations_db")

        allocations = data.get("allocations")
        explicit_allocations = data.get("explicit_allocations")

        if isinstance(allocations, dict):
            self._allocations = {str(k): str(v) for k, v in allocations.items()}
        else:
            self._allocations = {}
        if isinstance(explicit_allocations, dict):
            self._explicit_allocations = {str(k): str(v) for k, v in explicit_allocations.items()}
        else:
            self._explicit_allocations = {}

        self._allocated_cpus = set()
        self._explicitly_allocated_cpus = set()
        for cores_str in self._allocations.values():
            self._allocated_cpus.update(self._parse_cpu_ranges(cores_str))
        for cores_str in self._explicit_allocations.values():
            self._explicitly_allocated_cpus.update(self._parse_cpu_ranges(cores_str))

    def _apply_allocation(self, service_name: str, cpu_set: set[int], explicit: bool) -> None:
        """Apply an allocation to a service, updating all tracking structures."""
        if not cpu_set:
            return
        cores_str = to_ranges(sorted(cpu_set))
        self._allocations[service_name] = cores_str
        self._allocated_cpus.update(cpu_set)
        if explicit:
            self._explicit_allocations[service_name] = cores_str
            self._explicitly_allocated_cpus.update(cpu_set)
        elif service_name in self._explicit_allocations:
            del self._explicit_allocations[service_name]

    def _subtract_cpus_from_service(self, service_name: str, cpus_to_remove: set[int]) -> None:
        """Subtract given CPUs from a service allocation, remove entry if empty."""
        if service_name not in self._allocations:
            return
        current_set = self._parse_cpu_ranges(self._allocations[service_name])
        if not (current_set & cpus_to_remove):
            return
        remaining = current_set - cpus_to_remove
        # Update global allocated CPUs
        self._allocated_cpus -= current_set & cpus_to_remove
        # Handle explicit tracking if needed
        if service_name in self._explicit_allocations:
            explicit_set = self._parse_cpu_ranges(self._explicit_allocations[service_name])
            explicit_remaining = explicit_set - cpus_to_remove
            self._explicitly_allocated_cpus -= explicit_set & cpus_to_remove
            if explicit_remaining:
                self._explicit_allocations[service_name] = to_ranges(sorted(explicit_remaining))
            else:
                del self._explicit_allocations[service_name]
        if remaining:
            self._allocations[service_name] = to_ranges(sorted(remaining))
        else:
            del self._allocations[service_name]

    def get_available_cpus(self, total_cpus: str) -> list[int]:
        """Get list of available CPUs that haven't been allocated.

        Args:
            total_cpus: Comma-separated list of all available CPU ranges

        Returns:
            List of available CPU numbers
        """
        self._load_from_store()
        all_cpus = self._parse_cpu_ranges(total_cpus)
        available_cpus = sorted(list(all_cpus - self._allocated_cpus))
        return available_cpus

    def get_available_cpus_for_service(self, service_name: str, total_cpus: str) -> list[int]:
        """Get CPUs available for (re-)allocation to a specific service.

        When a service requests allocation, it may already hold cores. Those cores
        should be in the pool since they will be freed and re-assigned. Excludes
        only allocations of *other* services.

        Args:
            service_name: Service requesting allocation
            total_cpus: Comma-separated list of all available CPU ranges (e.g. isolated)

        Returns:
            List of CPU numbers the service may be allocated from
        """
        self._load_from_store()
        all_cpus = self._parse_cpu_ranges(total_cpus)
        this_service_cpus = self._parse_cpu_ranges(
            self._allocations.get(service_name, "")
        ) | self._parse_cpu_ranges(self._explicit_allocations.get(service_name, ""))
        other_allocated = self._allocated_cpus - this_service_cpus
        return sorted(list(all_cpus - other_allocated))

    def can_allocate_cpus(self, requested_count: int, total_cpus: str) -> bool:
        """Check if requested number of CPUs can be allocated.

        Args:
            requested_count: Number of CPUs requested
            total_cpus: Comma-separated list of all available CPU ranges

        Returns:
            True if allocation is possible, False otherwise
        """
        self._load_from_store()
        available_cpus = self.get_available_cpus(total_cpus)
        return len(available_cpus) >= requested_count

    def allocate_cores(self, service_name: str, allocated_cores: str) -> None:
        """Allocate cores to a service.

        Args:
            service_name: Name of the service
            allocated_cores: Comma-separated list of CPU ranges allocated to the service
        """
        self._load_from_store()
        if not allocated_cores:
            logging.warning(f"No cores allocated to service {service_name}")
            return
        # Remove previous allocation for this service first
        self._remove_service_allocation(service_name)
        new_cpu_set = self._parse_cpu_ranges(allocated_cores)
        # Enforce exclusivity: reject overlap with CPUs already allocated to other services
        overlap = new_cpu_set & self._allocated_cpus
        if overlap:
            raise ValueError(
                f"Requested CPUs {to_ranges(sorted(list(overlap)))} are already allocated to other services"
            )
        self._apply_allocation(service_name, new_cpu_set, explicit=False)
        logging.info(f"Allocated cores {allocated_cores} to service {service_name}")
        self._persist()

    def _get_allocatable_numa_cpus(
        self, service_name: str, numa_node: int, isolated_cpus_str: str
    ) -> Tuple[Set[int], Set[int]]:
        """Get allocatable and rejected CPUs for NUMA allocation.

        Args:
            service_name: Name of the service requesting cores
            numa_node: NUMA node to allocate cores from
            isolated_cpus_str: String of isolated CPUs

        Returns:
            Tuple of (allocatable_cpus, rejected_cpus)
        """
        numa_cpus = get_cpus_in_numa_node(numa_node, isolated_cpus_str)
        if not numa_cpus:
            return set(), set()

        rejected_cpus = set()
        allocatable_cpus = set()

        for cpu in numa_cpus:
            if cpu in self._explicitly_allocated_cpus:
                for other_service, other_cores in self._explicit_allocations.items():
                    if other_service != service_name:
                        other_cpu_set = self._parse_cpu_ranges(other_cores)
                        if cpu in other_cpu_set:
                            rejected_cpus.add(cpu)
                            break
                else:
                    allocatable_cpus.add(cpu)
            else:
                allocatable_cpus.add(cpu)

        return allocatable_cpus, rejected_cpus

    def _get_service_allocation_set(self, service_name: str) -> set[int]:
        """Return current allocation set for a service (empty if none)."""
        return self._parse_cpu_ranges(self._allocations.get(service_name, ""))

    def _get_service_explicit_set(self, service_name: str) -> set[int]:
        """Return current explicit allocation set for a service (empty if none)."""
        return self._parse_cpu_ranges(self._explicit_allocations.get(service_name, ""))

    def _apply_numa_explicit_allocation(
        self,
        service_name: str,
        numa_node: int,
        new_cores_in_node: Set[int],
    ) -> None:
        """Apply explicit allocation for a specific NUMA node.

        This overrides prior cores for this service within the same NUMA node,
        and appends allocations from other NUMA nodes.
        """
        current_allocation_set = self._get_service_allocation_set(service_name)
        current_allocation_str = to_ranges(sorted(current_allocation_set))
        existing_in_node = get_cpus_in_numa_node(numa_node, current_allocation_str)
        if existing_in_node:
            self._subtract_cpus_from_service(service_name, set(existing_in_node))

        remaining_allocation = self._get_service_allocation_set(service_name)

        for other_service, other_cores_str in list(self._allocations.items()):
            if other_service == service_name:
                continue
            other_set = self._parse_cpu_ranges(other_cores_str)
            overlap = other_set & new_cores_in_node
            if overlap:
                self._subtract_cpus_from_service(other_service, overlap)

        updated_allocation = remaining_allocation | new_cores_in_node
        self._allocations[service_name] = to_ranges(sorted(updated_allocation))
        self._allocated_cpus.update(new_cores_in_node)

        remaining_explicit = self._get_service_explicit_set(service_name)
        updated_explicit = remaining_explicit | new_cores_in_node
        self._explicit_allocations[service_name] = to_ranges(sorted(updated_explicit))
        self._explicitly_allocated_cpus.update(new_cores_in_node)

    def allocate_numa_cores(
        self, service_name: str, numa_node: int, num_of_cores: int
    ) -> Tuple[str, str]:
        """Allocate or deallocate cores from a NUMA node.

        - num_of_cores > 0: allocate exactly that many cores from the node
        - num_of_cores == -1: deallocate existing cores for this service in the node
        - num_of_cores == 0: invalid; returns no-op ("", "")
        """
        self._load_from_store()
        isolated_cpus = get_isolated_cpus()

        if num_of_cores == 0:
            return "", ""

        if num_of_cores == -1:
            prev_alloc_str = self._allocations.get(service_name, "")
            in_node = get_cpus_in_numa_node(numa_node, prev_alloc_str)
            if in_node:
                self._subtract_cpus_from_service(service_name, set(in_node))
            prev_explicit_str = self._explicit_allocations.get(service_name, "")
            in_node_explicit = get_cpus_in_numa_node(numa_node, prev_explicit_str)
            if in_node_explicit:
                self._subtract_cpus_from_service(service_name, set(in_node_explicit))
            self._persist()
            return "", ""

        allocatable_cpus, rejected_cpus = self._get_allocatable_numa_cpus(
            service_name, numa_node, isolated_cpus
        )

        if len(allocatable_cpus) < num_of_cores:
            return "", to_ranges(sorted(rejected_cpus))

        cores_to_allocate = self._select_numa_cpus_smt_aware(allocatable_cpus, num_of_cores)

        prev_alloc_str = self._allocations.get(service_name, "")
        prev_in_node = get_cpus_in_numa_node(numa_node, prev_alloc_str)

        for other_service, other_cores_str in list(self._allocations.items()):
            if other_service == service_name:
                continue
            other_set = self._parse_cpu_ranges(other_cores_str)
            overlap = other_set & cores_to_allocate
            if overlap:
                self._subtract_cpus_from_service(other_service, overlap)

        self._apply_numa_explicit_allocation(service_name, numa_node, cores_to_allocate)

        allocated_cores_str = to_ranges(sorted(cores_to_allocate))
        if prev_in_node:
            logging.info(
                f"Overrode NUMA node {numa_node} allocation for service {service_name}: {allocated_cores_str}"
            )
        else:
            logging.info(
                f"Appended NUMA node {numa_node} allocation for service {service_name}: {allocated_cores_str}"
            )
        self._persist()
        return allocated_cores_str, ""

    def _select_numa_cpus_smt_aware(self, candidate_cpus: Set[int], num_of_cores: int) -> set[int]:
        """Select exactly num_of_cores from candidates, preferring pairs then singles."""
        groups = self._group_candidates_by_siblings(candidate_cpus)
        selected_list = self._select_from_groups_pairs_then_singles(groups, num_of_cores)
        return set(sorted(selected_list))

    def _group_candidates_by_siblings(self, candidate_cpus: Set[int]) -> list[list[int]]:
        """Group candidate CPUs by their thread sibling sets.

        Returns a list of groups, each a sorted list of CPUs, ordered by the group's lowest CPU id.
        Only CPUs present in candidate_cpus are included in groups.
        """
        if not candidate_cpus:
            return []
        mapping = get_thread_siblings_map(set(candidate_cpus))
        group_to_members: dict[tuple[int, ...], list[int]] = {}
        for cpu in sorted(candidate_cpus):
            group_tuple = tuple(sorted(mapping.get(cpu, {cpu})))
            if group_tuple not in group_to_members:
                members = [m for m in group_tuple if m in candidate_cpus]
                group_to_members[group_tuple] = sorted(members)
        ordered_groups = [
            group_to_members[k]
            for k in sorted(group_to_members.keys(), key=lambda g: g[0] if g else -1)
        ]
        return ordered_groups

    def _select_from_groups_pairs_then_singles(
        self, groups: list[list[int]], count: int
    ) -> list[int]:
        """Pick CPUs by taking pairs from groups first, then singles.

        Mutates the input groups (consumes members) to keep the logic simple.
        """
        selected: list[int] = []
        remaining = count

        pair_taken = self._take_pairs_from_groups(groups, remaining)
        selected.extend(pair_taken)
        remaining -= len(pair_taken)

        if remaining > 0:
            single_taken = self._take_singles_from_groups(groups, remaining)
            selected.extend(single_taken)
            remaining -= len(single_taken)

        if remaining > 0:
            leftovers = self._collect_leftovers(groups)
            selected.extend(leftovers[:remaining])

        return selected[:count]

    def _take_pairs_from_groups(self, groups: list[list[int]], budget: int) -> list[int]:
        """Consume up to budget CPUs in pairs (2 per group) from groups."""
        taken: list[int] = []
        if budget < 2:
            return taken
        remaining = budget
        for members in groups:
            if remaining < 2:
                break
            if len(members) >= 2:
                taken.extend(members[:2])
                del members[:2]
                remaining -= 2
        return taken

    def _take_singles_from_groups(self, groups: list[list[int]], budget: int) -> list[int]:
        """Consume up to budget CPUs one-by-one across groups."""
        taken: list[int] = []
        if budget <= 0:
            return taken
        remaining = budget
        for members in groups:
            if remaining == 0:
                break
            if members:
                taken.append(members.pop(0))
                remaining -= 1
        return taken

    def _collect_leftovers(self, groups: list[list[int]]) -> list[int]:
        """Flatten remaining members across all groups in order."""
        leftovers: list[int] = []
        for members in groups:
            leftovers.extend(members)
        return leftovers

    def get_allocation(self, service_name: str) -> Optional[str]:
        """Get the allocated cores for a specific service.

        Args:
            service_name: Name of the service

        Returns:
            Comma-separated list of CPU ranges allocated to the service, or None if not found
        """
        self._load_from_store()
        return self._allocations.get(service_name)

    def is_explicit_allocation(self, service_name: str) -> bool:
        """Check if a service has an explicit allocation.

        Args:
            service_name: Name of the service

        Returns:
            True if the service has an explicit allocation, False otherwise
        """
        self._load_from_store()
        return service_name in self._explicit_allocations

    def get_all_allocations(self) -> list[SnapAllocation]:
        """Get all service allocations.

        Returns:
            List of SnapAllocation objects
        """
        self._load_from_store()
        return [
            SnapAllocation(
                service_name=service_name,
                allocated_cores=cores,
                cores_count=len(self._parse_cpu_ranges(cores)),
                is_explicit=service_name in self._explicit_allocations,
            )
            for service_name, cores in self._allocations.items()
        ]

    def remove_allocation(self, service_name: str) -> bool:
        """Remove allocation for a specific service.

        Args:
            service_name: Name of the service

        Returns:
            True if allocation was removed, False if not found
        """
        self._load_from_store()
        if service_name in self._allocations or service_name in self._explicit_allocations:
            self._remove_service_allocation(service_name)
            logging.info(f"Removed allocation for service {service_name}")
            self._persist()
            return True
        return False

    def clear_all_allocations(self) -> None:
        """Clear all allocations."""
        self._load_from_store()
        self._allocations.clear()
        self._allocated_cpus.clear()
        self._explicit_allocations.clear()
        self._explicitly_allocated_cpus.clear()
        logging.info("Cleared all allocations")
        self._persist()

    def get_total_allocated_count(self) -> int:
        """Get the total number of allocated CPUs.

        Returns:
            Number of allocated CPUs
        """
        self._load_from_store()
        return len(self._allocated_cpus)

    def get_snap_allocation_count(self, service_name: str) -> int:
        """Get the number of CPUs allocated to a specific service.

        Args:
            service_name: Name of the service

        Returns:
            Number of CPUs allocated to the service, or 0 if not found
        """
        self._load_from_store()
        allocation = self._allocations.get(service_name)
        if allocation:
            return len(self._parse_cpu_ranges(allocation))
        return 0

    def get_system_stats(self, total_cpus: str) -> dict[str, int]:
        """Get system statistics for CPU allocation.

        Args:
            total_cpus: Comma-separated list of all available CPU ranges

        Returns:
            Dictionary with system statistics
        """
        self._load_from_store()
        total_available = len(self._parse_cpu_ranges(total_cpus))
        total_allocated = len(self._allocated_cpus)
        remaining_available = total_available - total_allocated

        return {
            "total_available_cpus": total_available,
            "total_allocated_cpus": total_allocated,
            "remaining_available_cpus": remaining_available,
            "total_allocations": len(self._allocations),
        }


allocations_db: AllocationsDB = AllocationsDB()
