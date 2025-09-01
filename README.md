# EPA Orchestrator Snap

This repository contains the source for the EPA Orchestrator snap.

**EPA Orchestrator** is designed to provide secure, policy-driven resource orchestration for snaps and workloads on Linux systems. Its vision is to enable fine-grained, dynamic allocation and management of system resources—starting with CPU pinning and memory management, with plans to expand to other resource types and orchestration policies. The orchestrator exposes a secure Unix socket API for resource allocation and introspection, making it easy for other snaps (such as openstack-hypervisor) and workloads to request and manage dedicated or shared resources in a controlled manner.

## Features

- **CPU Pinning and Allocation**: Allocate isolated and shared CPU sets to snaps and workloads, supporting both dedicated and shared CPU usage models with basic system-size heuristics.
- **Memory Management and Hugepage Tracking**: Introspect NUMA hugepages and track hugepage allocations across NUMA nodes with per-service allocation tracking.
- **NUMA-Aware Core Allocation**: Request a specific number of cores from a particular NUMA node with override/append semantics and exact-count guarantees.
- **Resource Introspection**: Query current allocations and available resources via a secure API.
- **Secure Unix Socket API**: All orchestration actions are performed via a secure, local Unix socket with JSON-based requests and responses.
- **Basic Allocation Heuristics**: Automatic allocation based on system size (small vs large systems) when no specific core count is requested.

### CPU Allocation Policy: Small vs. Large Systems

When a client requests core allocation with `num_of_cores: 0`, EPA Orchestrator applies a policy based on the total number of CPUs detected:

- **Small systems (≤100 CPUs):**
  - By default, 80% of the available CPUs are allocated to the requesting snap or workload.
  - The remaining 20% are left unallocated (shared).
- **Large systems (>100 CPUs):**
  - By default, 16 CPUs are always reserved (left unallocated/shared).
  - All other CPUs are allocated to the requesting snap or workload.

This policy ensures that on large servers, a fixed number of CPUs are always available for system or shared use, while on smaller systems, a proportional allocation is used.

### NUMA-Aware Core Allocation Policy

The NUMA-aware allocation action allows services to request a specific number of cores from a particular NUMA node:

- **NUMA Locality**: Cores are allocated from the specified NUMA node to ensure optimal memory access patterns.
- **Force Reallocation**: NUMA allocation will override any existing non-explicit allocations to other services, even if they span multiple NUMA nodes.
- **Atomic Exact-Count**: If fewer than the requested number of cores are available in the NUMA node, the request fails with an error; no partial allocation occurs.
- **Priority System**: NUMA allocations take precedence over automatic allocations and cannot be overridden by other services.
- **Per-NUMA override/append semantics**: If the same service requests the same NUMA node again, it overrides previous cores from that node. If it requests a different NUMA node, the new cores are appended so the service may hold allocations across multiple NUMA nodes.
- **Per-NUMA deallocation**: Sending `num_of_cores = -1` for a node deallocates any existing cores for that service in that node. `num_of_cores = 0` is invalid for NUMA.

### Planned Features

- **Hugepage Introspection and Tracking**: ✅ **Implemented** - NUMA hugepage introspection and tracking via `get_memory_info` and `allocate_hugepages` actions.

## Getting Started

To get started with the EPA Orchestrator, install the snap using snapd:

```bash
sudo snap install epa-orchestrator --dangerous --devmode
```

The snap runs a daemon that listens on a Unix domain socket and provides a JSON API for CPU allocation and introspection.

## Configuration Reference

The EPA Orchestrator snap does not require complex configuration for basic operation. However, it can be integrated with other snaps (e.g., openstack-hypervisor) via the slot/plug mechanism for EPA information sharing.

### API Usage

The daemon listens on:

```
$SNAP_DATA/data/epa.sock
```

Clients can connect to this socket and send JSON requests. The supported actions are:

#### 1. Allocate Cores (`allocate_cores`)

Request CPU allocation for a specific service:

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "action": "allocate_cores",
  "num_of_cores": 2
}
```

- `num_of_cores`: Number of cores to allocate. `0` (80% of total CPUs).
- `numa_node` is not allowed for this action and will be rejected.

#### Response Example (Success)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "num_of_cores": 2,
  "cores_allocated": 2,
  "allocated_cores": "0-1",
  "shared_cpus": "2-19",
  "total_available_cpus": 20,
  "remaining_available_cpus": 18
}
```

#### Response Example (Error)

```json
{
  "version": "1.0",
  "error": "Insufficient CPUs available. Requested: 100, Available: 20"
}
```

#### 2. Allocate NUMA Cores (`allocate_numa_cores`)

Request a specific number of cores from a particular NUMA node:

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "action": "allocate_numa_cores",
  "numa_node": 1,
  "num_of_cores": 5
}
```

- `numa_node`: NUMA node ID to allocate cores from (0-based)
- `num_of_cores`: Number of cores to allocate from the specified NUMA node
  - `> 0` allocates exactly that many cores
  - `-1` deallocates any existing cores for that service in that node
  - `0` is invalid

#### Response Example (Success)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "numa_node": 1,
  "num_of_cores": 5,
  "cores_allocated": "4-8",
  "total_available_cpus": 20,
  "remaining_available_cpus": 15
}
```

#### Response Example (Insufficient Cores Error)

```json
{
  "version": "1.0",
  "error": "NUMA node 1 only has 3 isolated CPUs, but 5 were requested"
}
```

#### Response Example (Per-NUMA Deallocation)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "numa_node": 1,
  "num_of_cores": -1,
  "cores_allocated": "",
  "total_available_cpus": 20,
  "remaining_available_cpus": 20
}
```

#### 3. List Allocations (`list_allocations`)

Get all current service allocations:

```json
{
  "version": "1.0",
  "service_name": "any-service",
  "action": "list_allocations"
}
```

#### Response Example (Success)

```json
{
  "version": "1.0",
  "total_allocations": 2,
  "total_allocated_cpus": 4,
  "total_available_cpus": 20,
  "remaining_available_cpus": 16,
  "allocations": [
    {
      "service_name": "my-service",
      "allocated_cores": "0-1",
      "cores_count": 2,
      "is_explicit": false
    },
    {
      "service_name": "another-service",
      "allocated_cores": "2-3",
      "cores_count": 2,
      "is_explicit": true
    }
  ]
}
```

#### Response Example (No Isolated CPUs)

```json
{
  "version": "1.0",
  "total_allocations": 0,
  "total_allocated_cpus": 0,
  "total_available_cpus": 0,
  "remaining_available_cpus": 0,
  "allocations": []
}
```

#### 3. Get Memory Info (`get_memory_info`)

Get NUMA hugepage information (with EPA-tracked overlay), keyed by node name with capacity lists:

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "action": "get_memory_info"
}
```

#### Response Example (Success)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "numa_hugepages": {
    "node0": {
      "capacity": [
        { "total": 100, "free": 60, "size": 2048 },
        { "total": 4, "free": 1, "size": 1048576 }
      ],
      "allocations": {
        "openstack-hypervisor": { "2048": 20, "1048576": 2 },
        "database-service": { "2048": 15, "1048576": 1 },
        "my-service": { "2048": 5 }
      }
    }
  }
}
```

#### Response Example (No Hugepages)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "numa_hugepages": {}
}
```

#### 4. Allocate Hugepages (`allocate_hugepages`)

Record hugepage allocation request (tracking-only) for a specific NUMA node and size:

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "action": "allocate_hugepages",
  "hugepages_requested": 2,
  "node_id": 0,
  "size_kb": 2048
}
```

- `hugepages_requested`: Number of hugepages to record (>0), use `-1` to deallocate, `0` is invalid
- `node_id`: NUMA node ID for per-node tracking
- `size_kb`: Hugepage size in KB (e.g., 2048 for 2MB, 1048576 for 1GB)

#### Response Example (Success)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "hugepages_requested": 2,
  "allocation_successful": true,
  "message": "Successfully set allocation request to 2 hugepages",
  "node_id": 0,
  "size_kb": 2048
}
```

#### Response Example (Deallocate)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "hugepages_requested": -1,
  "allocation_successful": true,
  "message": "Removed recorded hugepage allocation",
  "node_id": 0,
  "size_kb": 2048
}
```

#### Response Examples (Errors)

```json
{ "version": "1.0", "error": "NUMA node 3 not found" }
```
```json
{ "version": "1.0", "error": "Hugepage size 1048576 KB not found on node 0" }
```
```json
{ "version": "1.0", "error": "NUMA node 0 size 2048 KB only has 5 free hugepages, requested 10" }
```

## Build

To build and test the snap, see CONTRIBUTING.md for full details. Typical steps:

```bash
# Build the snap
snapcraft --use-lxd

# Install the snap
sudo snap install --dangerous epa-orchestrator_*.snap
```

## Testing

The project includes unit, integration, and functional tests.

```bash
tox -e unit
tox -e integration
tox -e functional
tox -e lint
tox -e fmt
tox -e mypy
```

**Note:** Functional tests require sudo privileges for snap installation and management.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to contribute to this project.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
