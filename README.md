# EPA Orchestrator Snap

This repository contains the source for the EPA Orchestrator snap.

**EPA Orchestrator** is designed to provide secure, policy-driven resource orchestration for snaps and workloads on Linux systems. Its vision is to enable fine-grained, dynamic allocation and management of system resources—starting with CPU pinning and memory management, with plans to expand to other resource types and orchestration policies. The orchestrator exposes a secure Unix socket API for resource allocation and introspection, making it easy for other snaps (such as openstack-hypervisor) and workloads to request and manage dedicated or shared resources in a controlled manner.

## Features

- **CPU Pinning and Allocation**: Allocate isolated and shared CPU sets to snaps and workloads, supporting both dedicated and shared CPU usage models with basic system-size heuristics.
- **Memory Management and Hugepage Tracking**: Introspect NUMA hugepages and track hugepage allocations across NUMA nodes with per-service allocation tracking.
- **Resource Introspection**: Query current allocations and available resources via a secure API.
- **Secure Unix Socket API**: All orchestration actions are performed via a secure, local Unix socket with JSON-based requests and responses.
- **Basic Allocation Heuristics**: Automatic allocation based on system size (small vs large systems) when no specific core count is requested.

### CPU Allocation Policy: Small vs. Large Systems

When a client requests core allocation with `cores_requested: 0`, EPA Orchestrator applies a policy based on the total number of CPUs detected:

- **Small systems (≤100 CPUs):**
  - By default, 80% of the available CPUs are allocated to the requesting snap or workload.
  - The remaining 20% are left unallocated (shared).
- **Large systems (>100 CPUs):**
  - By default, 16 CPUs are always reserved (left unallocated/shared).
  - All other CPUs are allocated to the requesting snap or workload.

This policy ensures that on large servers, a fixed number of CPUs are always available for system or shared use, while on smaller systems, a proportional allocation is used.

### Planned Features

- **Hugepage Introspection and Tracking**: ✅ **Implemented** - NUMA hugepage introspection and tracking via `get_memory_info` and `allocate_hugepages` actions.

## Getting Started

To get started with the EPA Orchestrator, install the snap using snapd:

```bash
sudo snap install epa-orchestrator --dangerous --devmode
```

The snap runs a daemon that listens on a Unix domain socket and provides a JSON API for CPU allocation and hugepage introspection/tracking.

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
  "cores_requested": 2
}
```

- `cores_requested`: Number of cores to allocate (0 = 80% of total CPUs)

#### Response Example (Success)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "cores_requested": 2,
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

#### 2. List Allocations (`list_allocations`)

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
      "cores_count": 2
    },
    {
      "service_name": "another-service",
      "allocated_cores": "2-3",
      "cores_count": 2
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

Get NUMA hugepage information (with EPA-tracked overlay), keyed by node name with usage lists:

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
      "usage": [
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

- `hugepages_requested`: Number of hugepages to record
- `node_id`: NUMA node ID for per-node tracking
- `size_kb`: Hugepage size in KB (e.g., 2048 for 2MB, 1048576 for 1GB)

#### Response Example (Success)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "hugepages_requested": 2,
  "allocation_successful": true,
  "message": "Successfully recorded allocation request for 2 hugepages",
  "node_id": 0,
  "size_kb": 2048
}
```

#### Response Example (Error)

```json
{
  "version": "1.0",
  "service_name": "my-service",
  "hugepages_requested": 2,
  "allocation_successful": false,
  "message": "Failed to record hugepage allocation: internal error",
  "node_id": 0,
  "size_kb": 2048
}
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
