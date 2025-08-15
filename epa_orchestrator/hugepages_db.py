# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""In-memory tracking of hugepage allocation requests per service."""

import logging
from typing import Dict, List, Optional, Union

# Structure: service_name -> list of allocations
# allocation: {"node_id": int, "size_kb": int, "count": int}
_allocations: Dict[str, List[Dict[str, int]]] = {}


def record_allocation(service_name: str, node_id: int, size_kb: int, count: int) -> None:
    """Record a hugepage allocation request for a service."""
    if service_name not in _allocations:
        _allocations[service_name] = []
    _allocations[service_name].append({"node_id": node_id, "size_kb": size_kb, "count": count})
    logging.info(
        f"Recorded hugepage allocation: {count}x{size_kb}KB to {service_name} on node {node_id}"
    )


def list_allocations() -> Dict[str, List[Dict[str, int]]]:
    """Return all hugepage allocation records by service."""
    return {k: list(v) for k, v in _allocations.items()}


def list_allocations_for_node(node_id: int) -> List[Dict[str, Union[str, int]]]:
    """Return flattened list of allocations for a specific node."""
    results: List[Dict[str, Union[str, int]]] = []
    for service, entries in _allocations.items():
        for entry in entries:
            if entry.get("node_id") == node_id:
                results.append(
                    {
                        "service_name": service,
                        "size_kb": entry.get("size_kb", 0),
                        "count": entry.get("count", 0),
                    }
                )
    return results


def get_allocation(service_name: str) -> Optional[List[Dict[str, int]]]:
    """Get the allocated hugepages for a specific service."""
    return _allocations.get(service_name)


def remove_allocation(service_name: str) -> bool:
    """Remove allocation for a specific service."""
    if service_name in _allocations:
        del _allocations[service_name]
        logging.info(f"Removed hugepage allocation for service {service_name}")
        return True
    return False


def clear_all_allocations() -> None:
    """Clear all allocations."""
    _allocations.clear()
    logging.info("Cleared all hugepage allocations")


def get_total_allocated_count() -> int:
    """Get the total number of allocated hugepages across all services."""
    total = 0
    for entries in _allocations.values():
        for entry in entries:
            total += entry.get("count", 0)
    return total


def get_service_allocation_count(service_name: str) -> int:
    """Get the number of hugepages allocated to a specific service."""
    if service_name not in _allocations:
        return 0
    total = 0
    for entry in _allocations[service_name]:
        total += entry.get("count", 0)
    return total


def get_system_stats() -> Dict[str, int]:
    """Get system statistics for hugepage allocation."""
    total_allocated = get_total_allocated_count()
    total_allocations = len(_allocations)

    return {
        "total_allocated_hugepages": total_allocated,
        "total_allocations": total_allocations,
    }
