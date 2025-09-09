# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Daemon handler for EPA Orchestrator."""

import json
import logging
from typing import Dict, List, Optional, Union, cast

from pydantic import ValidationError

from epa_orchestrator.allocations_db import allocations_db
from epa_orchestrator.cpu_pinning import calculate_cpu_pinning, get_isolated_cpus
from epa_orchestrator.hugepages_db import remove_allocation_for_key, upsert_allocation
from epa_orchestrator.memory_manager import get_memory_summary
from epa_orchestrator.schemas import (
    ActionType,
    AllocateCoresRequest,
    AllocateCoresResponse,
    AllocateHugepagesRequest,
    AllocateHugepagesResponse,
    AllocateNumaCoresRequest,
    AllocateNumaCoresResponse,
    ErrorResponse,
    GetMemoryInfoRequest,
    ListAllocationsRequest,
    ListAllocationsResponse,
    MemoryInfoResponse,
    NodeHugepagesInfo,
    SnapAllocation,
)
from epa_orchestrator.utils import (
    _count_cpus_in_ranges,
    get_cpus_in_numa_node,
    get_numa_node_cpus,
)


def handle_allocate_cores(request: AllocateCoresRequest) -> AllocateCoresResponse:
    """Handle allocate cores action (non-NUMA)."""
    if request.numa_node is not None:
        raise ValueError("'numa_node' is not allowed for action allocate_cores")

    isolated = get_isolated_cpus()
    if not isolated:
        raise ValueError("No CPUs available")

    # Get system statistics
    stats = allocations_db.get_system_stats(isolated)

    # Get requested number of cores (default policy when 0)
    num_of_cores = request.num_of_cores or 0

    # Check if we can allocate the requested CPUs when > 0
    if num_of_cores > 0:
        if not allocations_db.can_allocate_cpus(num_of_cores, isolated):
            available_cpus = allocations_db.get_available_cpus(isolated)
            raise ValueError(
                f"Insufficient CPUs available. Requested: {num_of_cores}, Available: {len(available_cpus)}"
            )

    # Calculate CPU allocation
    shared, dedicated = calculate_cpu_pinning(isolated, num_of_cores)

    if not dedicated:
        raise ValueError(f"Failed to allocate {num_of_cores} cores")

    # Store the allocation in the database
    allocations_db.allocate_cores(request.service_name, dedicated)

    # Get updated statistics after allocation
    updated_stats = allocations_db.get_system_stats(isolated)
    cores_allocated = _count_cpus_in_ranges(dedicated)

    return AllocateCoresResponse(
        service_name=request.service_name,
        num_of_cores=num_of_cores,
        cores_allocated=cores_allocated,
        allocated_cores=dedicated,
        shared_cpus=shared,
        total_available_cpus=stats["total_available_cpus"],
        remaining_available_cpus=updated_stats["remaining_available_cpus"],
    )


def handle_allocate_numa_cores(
    request: AllocateNumaCoresRequest,
) -> AllocateNumaCoresResponse:
    """Handle allocate NUMA cores action.

    Supports exact-count allocation and per-node deallocation with num_of_cores = -1.
    """
    # Validate num_of_cores semantics for NUMA
    if request.num_of_cores == 0:
        raise ValueError("num_of_cores=0 is invalid for allocate_numa_cores")

    isolated = get_isolated_cpus()
    stats = allocations_db.get_system_stats(isolated)
    numa_cpus = get_numa_node_cpus()

    if request.numa_node not in numa_cpus:
        raise ValueError(f"NUMA node {request.numa_node} does not exist")

    if request.num_of_cores == -1:
        # Deallocate any existing cores for this service in the specified node
        allocated_cores, _ = allocations_db.allocate_numa_cores(
            request.service_name, request.numa_node, request.num_of_cores
        )
        updated_stats = allocations_db.get_system_stats(isolated)
        return AllocateNumaCoresResponse(
            service_name=request.service_name,
            numa_node=request.numa_node,
            num_of_cores=request.num_of_cores,
            cores_allocated=allocated_cores,
            total_available_cpus=stats["total_available_cpus"],
            remaining_available_cpus=updated_stats["remaining_available_cpus"],
        )

    if not isolated:
        raise ValueError("No Isolated CPUs available for allocation")

    # Allocation path (num_of_cores > 0)
    available_numa_cpus = get_cpus_in_numa_node(request.numa_node, isolated)
    if not available_numa_cpus:
        raise ValueError(f"No isolated CPUs available in NUMA node {request.numa_node}")

    if len(available_numa_cpus) < request.num_of_cores:
        raise ValueError(
            f"NUMA node {request.numa_node} only has {len(available_numa_cpus)} isolated CPUs, "
            f"but {request.num_of_cores} were requested"
        )

    allocated_cores, _ = allocations_db.allocate_numa_cores(
        request.service_name, request.numa_node, request.num_of_cores
    )

    if not allocated_cores:
        raise ValueError(
            f"Failed to allocate cores from NUMA node {request.numa_node}. "
            f"All requested cores may be explicitly allocated to other services."
        )

    updated_stats = allocations_db.get_system_stats(isolated)

    return AllocateNumaCoresResponse(
        service_name=request.service_name,
        numa_node=request.numa_node,
        num_of_cores=request.num_of_cores,
        cores_allocated=allocated_cores,
        total_available_cpus=stats["total_available_cpus"],
        remaining_available_cpus=updated_stats["remaining_available_cpus"],
    )


# Hugepages/memory handlers restored from main


def handle_get_memory_info(
    request: GetMemoryInfoRequest,
) -> Union[MemoryInfoResponse, ErrorResponse]:
    """Handle get memory info action."""
    try:
        memory_summary = get_memory_summary()
        if "error" in memory_summary:
            err = str(memory_summary.get("error", "Unknown error"))
            logging.error(f"Failed to get memory information: {err}")
            return ErrorResponse(error=f"Failed to get memory information: {err}")
        numa_map = cast(Dict[str, NodeHugepagesInfo], memory_summary.get("numa_hugepages", {}))
        return MemoryInfoResponse(
            service_name=request.service_name,
            numa_hugepages=numa_map,
        )
    except Exception as e:
        logging.error(f"Failed to get memory information: {e}")
        return ErrorResponse(error=f"Failed to get memory information: {e}")


def handle_allocate_hugepages(
    request: AllocateHugepagesRequest,
) -> Union[AllocateHugepagesResponse, ErrorResponse]:
    """Handle allocate hugepages action (tracking only)."""
    try:
        # Validation for 0 is handled by schema; treat -1 as deallocation
        if request.hugepages_requested == -1:
            removed = remove_allocation_for_key(
                request.service_name, request.node_id, request.size_kb
            )
            message = (
                "Removed recorded hugepage allocation"
                if removed
                else "No existing record to remove"
            )
            return AllocateHugepagesResponse(
                service_name=request.service_name,
                hugepages_requested=request.hugepages_requested,
                allocation_successful=True,
                message=message,
                node_id=request.node_id,
                size_kb=request.size_kb,
            )

        # Capacity validation for positive requests
        if request.hugepages_requested > 0:
            summary = get_memory_summary()
            if "error" in summary:
                err = str(summary.get("error", "Unknown error"))
                logging.error(f"Failed to get memory information: {err}")
                return ErrorResponse(error=f"Failed to get memory information: {err}")

            numa_hugepages = cast(Dict[str, Dict[str, object]], summary.get("numa_hugepages", {}))
            node_key = f"node{request.node_id}"
            node_info = numa_hugepages.get(node_key)
            if not node_info:
                return ErrorResponse(error=f"NUMA node {request.node_id} not found")

            capacity_list = cast(List[Dict[str, int]], node_info.get("capacity", []))
            size_entry: Optional[Dict[str, int]] = next(
                (e for e in capacity_list if int(e.get("size", -1)) == request.size_kb),
                None,
            )
            if not size_entry:
                return ErrorResponse(
                    error=f"Hugepage size {request.size_kb} KB not found on node {request.node_id}"
                )

            free = int(size_entry.get("free", 0))
            if free < request.hugepages_requested:
                return ErrorResponse(
                    error=(
                        f"NUMA node {request.node_id} size {request.size_kb} KB only has {free} "
                        f"free hugepages, requested {request.hugepages_requested}"
                    )
                )

        # Record (replace) the allocation request for this key
        upsert_allocation(
            request.service_name, request.node_id, request.size_kb, request.hugepages_requested
        )

        message = f"Successfully set allocation request to {request.hugepages_requested} hugepages"

        return AllocateHugepagesResponse(
            service_name=request.service_name,
            hugepages_requested=request.hugepages_requested,
            allocation_successful=True,
            message=message,
            node_id=request.node_id,
            size_kb=request.size_kb,
        )
    except Exception as e:
        logging.error(f"Failed to record hugepage allocation: {e}")
        return ErrorResponse(error=f"Failed to record hugepage allocation: {e}")


def handle_list_allocations(request: ListAllocationsRequest) -> ListAllocationsResponse:
    """Handle list allocations action.

    Returns:
        ListAllocationsResponse with detailed allocation information
    """
    isolated = get_isolated_cpus()
    if not isolated:
        # Return empty response when no isolated CPUs are available
        return ListAllocationsResponse(
            total_allocations=0,
            total_allocated_cpus=0,
            total_available_cpus=0,
            remaining_available_cpus=0,
            allocations=[],
        )

    # Get system statistics
    stats = allocations_db.get_system_stats(isolated)

    # Build detailed allocation list
    allocations = []
    for service_name, allocated_cores in allocations_db._allocations.items():
        cores_count = allocations_db.get_snap_allocation_count(service_name)
        is_explicit = allocations_db.is_explicit_allocation(service_name)
        allocations.append(
            SnapAllocation(
                service_name=service_name,
                allocated_cores=allocated_cores,
                cores_count=cores_count,
                is_explicit=is_explicit,
            )
        )

    return ListAllocationsResponse(
        total_allocations=stats["total_allocations"],
        total_allocated_cpus=stats["total_allocated_cpus"],
        total_available_cpus=stats["total_available_cpus"],
        remaining_available_cpus=stats["remaining_available_cpus"],
        allocations=allocations,
    )


def handle_daemon_request(data: bytes) -> bytes:
    """Handle daemon request.

    Args:
        data: The request data

    Returns:
        The response data
    """
    try:
        request_data = json.loads(data.decode())
        action_value = request_data.get("action")

        response: Union[
            AllocateCoresResponse,
            AllocateNumaCoresResponse,
            ListAllocationsResponse,
            MemoryInfoResponse,
            AllocateHugepagesResponse,
            ErrorResponse,
        ]

        if action_value in (
            ActionType.ALLOCATE_CORES,
            ActionType.ALLOCATE_CORES.value,
            "allocate_cores",
        ):
            ac_req: AllocateCoresRequest = AllocateCoresRequest.parse_obj(request_data)
            response = handle_allocate_cores(ac_req)
        elif action_value in (
            ActionType.ALLOCATE_NUMA_CORES,
            ActionType.ALLOCATE_NUMA_CORES.value,
            "allocate_numa_cores",
        ):
            numa_req: AllocateNumaCoresRequest = AllocateNumaCoresRequest.parse_obj(request_data)
            response = handle_allocate_numa_cores(numa_req)
        elif action_value in (
            ActionType.LIST_ALLOCATIONS,
            ActionType.LIST_ALLOCATIONS.value,
            "list_allocations",
        ):
            la_req: ListAllocationsRequest = ListAllocationsRequest.parse_obj(request_data)
            response = handle_list_allocations(la_req)
        elif action_value in (
            ActionType.GET_MEMORY_INFO,
            ActionType.GET_MEMORY_INFO.value,
            "get_memory_info",
        ):
            mem_req: GetMemoryInfoRequest = GetMemoryInfoRequest.parse_obj(request_data)
            response = handle_get_memory_info(mem_req)
        elif action_value in (
            ActionType.ALLOCATE_HUGEPAGES,
            ActionType.ALLOCATE_HUGEPAGES.value,
            "allocate_hugepages",
        ):
            hp_req: AllocateHugepagesRequest = AllocateHugepagesRequest.parse_obj(request_data)
            response = handle_allocate_hugepages(hp_req)
        else:
            response = ErrorResponse(
                error=f"Unknown action: {action_value}",
                version="1.0",
            )

        return response.json().encode()
    except (ValidationError, json.JSONDecodeError) as e:
        error_response = ErrorResponse(
            error=str(e),
            version="1.0",
        )
        return error_response.json().encode()
    except ValueError as e:
        error_response = ErrorResponse(
            error=str(e),
            version="1.0",
        )
        return error_response.json().encode()
    except Exception as e:
        error_response = ErrorResponse(
            error=str(e),
            version="1.0",
        )
        return error_response.json().encode()
