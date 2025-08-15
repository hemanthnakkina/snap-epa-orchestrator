# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0
"""Pydantic schemas for socket communication."""
from enum import Enum
from typing import Annotated, Dict, List, Literal, Union

from pydantic import BaseModel, Field

API_VERSION: Literal["1.0"] = "1.0"


class ActionType(str, Enum):
    """Enum for different action types."""

    ALLOCATE_CORES = "allocate_cores"
    LIST_ALLOCATIONS = "list_allocations"
    GET_MEMORY_INFO = "get_memory_info"
    ALLOCATE_HUGEPAGES = "allocate_hugepages"


class AllocateCoresRequest(BaseModel):
    """Request model for allocating cores."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    action: Literal[ActionType.ALLOCATE_CORES]
    service_name: str = Field(description="Name of the requesting service")
    cores_requested: int = Field(
        default=0,
        ge=0,
        description="Number of dedicated cores requested (0 means default allocation)",
    )


class ListAllocationsRequest(BaseModel):
    """Request model for listing allocations."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    action: Literal[ActionType.LIST_ALLOCATIONS]
    service_name: str = Field(description="Name of the requesting service")


class GetMemoryInfoRequest(BaseModel):
    """Request model for getting memory information."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    action: Literal[ActionType.GET_MEMORY_INFO]
    service_name: str = Field(description="Name of the requesting service")


class AllocateHugepagesRequest(BaseModel):
    """Request model for allocating hugepages for a specific NUMA node and size."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    action: Literal[ActionType.ALLOCATE_HUGEPAGES]
    service_name: str = Field(description="Name of the requesting service")
    hugepages_requested: int = Field(
        ge=0,
        description="Number of hugepages to allocate",
    )
    node_id: int = Field(
        ge=0,
        description="NUMA node id for per-node allocation",
    )
    size_kb: int = Field(
        gt=0,
        description="Hugepage size in KB (e.g., 2048)",
    )


EpaRequest = Annotated[
    Union[
        AllocateCoresRequest,
        ListAllocationsRequest,
        GetMemoryInfoRequest,
        AllocateHugepagesRequest,
    ],
    Field(discriminator="action"),
]


class AllocateCoresResponse(BaseModel):
    """Pydantic model for allocate cores response."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    service_name: str = Field(description="Name of the service that was allocated cores")
    cores_requested: int = Field(description="Number of cores that were requested")
    cores_allocated: int = Field(description="Number of cores that were actually allocated")
    allocated_cores: str = Field(description="Comma-separated list of allocated CPU ranges")
    shared_cpus: str = Field(description="Comma-separated list of shared CPU ranges")
    total_available_cpus: int = Field(description="Total number of CPUs available in the system")
    remaining_available_cpus: int = Field(
        description="Number of CPUs still available for allocation"
    )


class SnapAllocation(BaseModel):
    """Model for service allocation information."""

    service_name: str = Field(description="Name of the service")
    allocated_cores: str = Field(description="Comma-separated list of allocated CPU ranges")
    cores_count: int = Field(description="Number of cores allocated to this service")


class ListAllocationsResponse(BaseModel):
    """Pydantic model for list allocations response."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    total_allocations: int = Field(description="Total number of service allocations")
    total_allocated_cpus: int = Field(
        description="Total number of CPUs allocated across all services"
    )
    total_available_cpus: int = Field(description="Total number of CPUs available in the system")
    remaining_available_cpus: int = Field(
        description="Number of CPUs still available for allocation"
    )
    allocations: List[SnapAllocation] = Field(description="List of all service allocations")


class UsageEntry(BaseModel):
    """Usage entry for a specific hugepage size on a node."""

    total: int
    free: int
    size: int


class NodeHugepagesInfo(BaseModel):
    """Per-node hugepages info with usage list and allocations."""

    usage: List[UsageEntry]
    allocations: Dict[str, Dict[str, int]]


class MemoryInfoResponse(BaseModel):
    """Pydantic model for NUMA hugepages information response."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    service_name: str = Field(description="Name of the requesting service")
    numa_hugepages: Dict[str, NodeHugepagesInfo] = Field(
        default_factory=dict, description="Per-NUMA hugepages info keyed by node name"
    )


class AllocateHugepagesResponse(BaseModel):
    """Pydantic model for hugepage allocation response."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    service_name: str = Field(description="Name of the requesting service")
    hugepages_requested: int = Field(description="Number of hugepages requested")
    allocation_successful: bool = Field(description="Whether allocation was successful")
    message: str = Field(description="Allocation result message")
    node_id: int = Field(description="NUMA node targeted")
    size_kb: int = Field(description="Hugepage size targeted in KB")


class ErrorResponse(BaseModel):
    """Pydantic model for error responses."""

    version: Literal["1.0"] = Field(default=API_VERSION)
    error: str
