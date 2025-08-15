# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Daemon handler for EPA Orchestrator."""

import json
import logging
from typing import Dict, Union, cast

from pydantic import TypeAdapter, ValidationError

from epa_orchestrator.allocations_db import allocations_db
from epa_orchestrator.cpu_pinning import calculate_cpu_pinning, get_isolated_cpus
from epa_orchestrator.hugepages_db import record_allocation
from epa_orchestrator.memory_manager import get_memory_summary
from epa_orchestrator.schemas import (
    AllocateCoresRequest,
    AllocateCoresResponse,
    AllocateHugepagesRequest,
    AllocateHugepagesResponse,
    EpaRequest,
    ErrorResponse,
    GetMemoryInfoRequest,
    ListAllocationsRequest,
    ListAllocationsResponse,
    MemoryInfoResponse,
    NodeHugepagesInfo,
    SnapAllocation,
)
from epa_orchestrator.utils import _count_cpus_in_ranges

logging.basicConfig(level=logging.INFO)


def handle_allocate_cores(request: AllocateCoresRequest) -> AllocateCoresResponse:
    """Handle allocate cores action.

    Args:
        request: The EPA request

    Returns:
        AllocateCoresResponse with detailed allocation information
    """
    try:
        isolated = get_isolated_cpus()
    except RuntimeError as e:
        raise ValueError("No Isolated CPUs configured") from e
    if not isolated:
        raise ValueError("No CPUs available")

    # Get system statistics
    stats = allocations_db.get_system_stats(isolated)

    # Get cores requested (default to 0 if None)
    cores_requested = request.cores_requested or 0

    # Check if we can allocate the requested CPUs
    if cores_requested > 0:
        if not allocations_db.can_allocate_cpus(cores_requested, isolated):
            available_cpus = allocations_db.get_available_cpus(isolated)
            raise ValueError(
                f"Insufficient CPUs available. Requested: {cores_requested}, Available: {len(available_cpus)}"
            )

    # Calculate CPU allocation
    shared, dedicated = calculate_cpu_pinning(isolated, cores_requested)

    if not dedicated:
        raise ValueError(f"Failed to allocate {cores_requested} cores")

    # Store the allocation in the database
    allocations_db.allocate_cores(request.service_name, dedicated)

    # Get updated statistics after allocation
    updated_stats = allocations_db.get_system_stats(isolated)
    cores_allocated = _count_cpus_in_ranges(dedicated)

    return AllocateCoresResponse(
        service_name=request.service_name,
        cores_requested=cores_requested,
        cores_allocated=cores_allocated,
        allocated_cores=dedicated,
        shared_cpus=shared,
        total_available_cpus=stats["total_available_cpus"],
        remaining_available_cpus=updated_stats["remaining_available_cpus"],
    )


def handle_list_allocations(request: ListAllocationsRequest) -> ListAllocationsResponse:
    """Handle list allocations action.

    Returns:
        ListAllocationsResponse with detailed allocation information
    """
    try:
        isolated = get_isolated_cpus()
    except RuntimeError:
        # Return empty response when no isolated CPUs are configured
        return ListAllocationsResponse(
            total_allocations=0,
            total_allocated_cpus=0,
            total_available_cpus=0,
            remaining_available_cpus=0,
            allocations=[],
        )
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
        allocations.append(
            SnapAllocation(
                service_name=service_name, allocated_cores=allocated_cores, cores_count=cores_count
            )
        )

    return ListAllocationsResponse(
        total_allocations=stats["total_allocations"],
        total_allocated_cpus=stats["total_allocated_cpus"],
        total_available_cpus=stats["total_available_cpus"],
        remaining_available_cpus=stats["remaining_available_cpus"],
        allocations=allocations,
    )


def handle_get_memory_info(request: GetMemoryInfoRequest) -> MemoryInfoResponse:
    """Handle get memory info action."""
    try:
        memory_summary = get_memory_summary()
        numa_map = cast(Dict[str, NodeHugepagesInfo], memory_summary.get("numa_hugepages", {}))
        return MemoryInfoResponse(
            service_name=request.service_name,
            numa_hugepages=numa_map,
        )
    except Exception as e:
        logging.error(f"Failed to get memory information: {e}")
        return MemoryInfoResponse(
            service_name=request.service_name,
            numa_hugepages={},
        )


def handle_allocate_hugepages(request: AllocateHugepagesRequest) -> AllocateHugepagesResponse:
    """Handle allocate hugepages action (tracking only)."""
    try:
        record_allocation(
            request.service_name, request.node_id, request.size_kb, request.hugepages_requested
        )

        message = (
            f"Successfully recorded allocation request for {request.hugepages_requested} hugepages"
        )

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
        return AllocateHugepagesResponse(
            service_name=request.service_name,
            hugepages_requested=request.hugepages_requested,
            allocation_successful=False,
            message=f"Failed to record hugepage allocation: {e}",
            node_id=request.node_id,
            size_kb=request.size_kb,
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
        request: Union[
            AllocateCoresRequest,
            ListAllocationsRequest,
            GetMemoryInfoRequest,
            AllocateHugepagesRequest,
        ] = TypeAdapter(EpaRequest).validate_python(request_data)
        response: Union[
            AllocateCoresResponse,
            ListAllocationsResponse,
            MemoryInfoResponse,
            AllocateHugepagesResponse,
            ErrorResponse,
        ]
        if isinstance(request, AllocateCoresRequest):
            response = handle_allocate_cores(request)
        elif isinstance(request, ListAllocationsRequest):
            response = handle_list_allocations(request)
        elif isinstance(request, GetMemoryInfoRequest):
            response = handle_get_memory_info(request)
        elif isinstance(request, AllocateHugepagesRequest):
            response = handle_allocate_hugepages(request)
        else:
            response = ErrorResponse(
                error=f"Unknown action: {getattr(request, 'action', None)}",
                version="1.0",
            )
        return response.model_dump_json().encode()
    except (ValidationError, json.JSONDecodeError) as e:
        error_response = ErrorResponse(
            error=str(e),
            version="1.0",
        )
        return error_response.model_dump_json().encode()
    except ValueError as e:
        error_response = ErrorResponse(
            error=str(e),
            version="1.0",
        )
        return error_response.model_dump_json().encode()
    except Exception as e:
        error_response = ErrorResponse(
            error=str(e),
            version="1.0",
        )
        return error_response.model_dump_json().encode()
