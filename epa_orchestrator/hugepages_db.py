# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""In-memory tracking of hugepage allocation requests per service."""

import logging
from typing import Dict, List, Optional, Union

from epa_orchestrator.schemas import (
    HugepageAllocationEntry,
    NodeHugepageAllocation,
    ServiceHugepageAllocations,
)

# Structure: service_name -> list of allocations
# allocation: {"node_id": int, "size_kb": int, "count": int}
_allocations: Dict[str, List[Dict[str, int]]] = {}


def upsert_allocation(service_name: str, node_id: int, size_kb: int, count: int) -> None:
    """Replace existing record for service+node+size with a new count.

    If a prior record exists for the same key, remove it before adding the new one.
    """
    if service_name not in _allocations:
        _allocations[service_name] = []
    before = len(_allocations[service_name])
    _allocations[service_name] = [
        e
        for e in _allocations[service_name]
        if not (int(e.get("node_id", -1)) == node_id and int(e.get("size_kb", -1)) == size_kb)
    ]
    # Validate and normalize the entry using the schema
    entry = HugepageAllocationEntry(node_id=node_id, size_kb=size_kb, count=count)
    _allocations[service_name].append(
        {"node_id": entry.node_id, "size_kb": entry.size_kb, "count": entry.count}
    )
    action = "Replaced" if len(_allocations[service_name]) < before + 1 else "Set"
    logging.info(
        f"{action} hugepage allocation for {service_name} node {node_id} size {size_kb}KB -> {count}"
    )


def list_allocations() -> Dict[str, List[Dict[str, int]]]:
    """Return all hugepage allocation records by service."""
    result: Dict[str, List[Dict[str, int]]] = {}
    for service, entries in _allocations.items():
        validated = ServiceHugepageAllocations(
            service_name=service,
            allocations=[HugepageAllocationEntry(**e) for e in entries],
        )
        result[service] = [
            {"node_id": e.node_id, "size_kb": e.size_kb, "count": e.count}
            for e in validated.allocations
        ]
    return result


def list_allocations_for_node(node_id: int) -> List[Dict[str, Union[str, int]]]:
    """Return flattened list of allocations for a specific node."""
    results: List[Dict[str, Union[str, int]]] = []
    for service, entries in _allocations.items():
        for entry in entries:
            if entry.get("node_id") == node_id:
                validated = NodeHugepageAllocation(
                    service_name=service,
                    size_kb=int(entry.get("size_kb", 0)),
                    count=int(entry.get("count", 0)),
                )
                results.append(
                    {
                        "service_name": validated.service_name,
                        "size_kb": validated.size_kb,
                        "count": validated.count,
                    }
                )
    return results


def get_allocation(service_name: str) -> Optional[List[Dict[str, int]]]:
    """Get the allocated hugepages for a specific service."""
    return _allocations.get(service_name)


def clear_all_allocations() -> None:
    """Clear all allocations."""
    _allocations.clear()
    logging.info("Cleared all hugepage allocations")


def remove_allocation_for_key(service_name: str, node_id: int, size_kb: int) -> bool:
    """Remove any allocation record for a specific service+node+size.

    Returns True if at least one matching record was removed, False otherwise.
    """
    if service_name not in _allocations:
        return False
    original_len = len(_allocations[service_name])
    _allocations[service_name] = [
        e
        for e in _allocations.get(service_name, [])
        if not (int(e.get("node_id", -1)) == node_id and int(e.get("size_kb", -1)) == size_kb)
    ]
    if not _allocations[service_name]:
        # Clean up empty service entry
        del _allocations[service_name]
    removed = len(_allocations.get(service_name, [])) != original_len
    if removed:
        logging.info(
            f"Removed hugepage allocation records for {service_name} node {node_id} size {size_kb}KB"
        )
    return removed
