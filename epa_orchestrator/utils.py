# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Utility functions for CPU range operations."""

import os
from typing import Dict, Set


def parse_cpu_ranges(cpu_ranges: str) -> Set[int]:
    """Convert CPU range string to a set of CPU numbers.

    Args:
        cpu_ranges: Comma-separated string of CPU ranges (e.g., "0-3,6,8-10")

    Returns:
        Set of CPU integers

    Examples:
        >>> parse_cpu_ranges("0-3,6,8-10")
        {0, 1, 2, 3, 6, 8, 9, 10}
        >>> parse_cpu_ranges("1,3,5")
        {1, 3, 5}
        >>> parse_cpu_ranges("0-2")
        {0, 1, 2}
    """
    if not cpu_ranges or not cpu_ranges.strip():
        return set()

    cpus: Set[int] = set()
    for part in cpu_ranges.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = map(int, part.split("-"))
            if start > end:
                raise ValueError(f"Invalid CPU range: {part} (start > end)")
            cpus.update(range(start, end + 1))
        else:
            cpus.add(int(part))
    return cpus


def to_ranges(cpu_list: list[int]) -> str:
    """Convert CPU cores list to CPU range in string format.

    Args:
        cpu_list: List of CPU core numbers

    Returns:
        Comma-separated string of CPU ranges

    Examples:
        >>> to_ranges([0, 1, 2, 4, 6, 7, 8])
        "0-2,4,6-8"
        >>> to_ranges([1, 3, 5])
        "1,3,5"
        >>> to_ranges([])
        ""
    """
    if not cpu_list:
        return ""

    sorted_cpus = sorted(cpu_list)
    ranges = []
    start = sorted_cpus[0]
    prev = start

    for cpu in sorted_cpus[1:]:
        if cpu != prev + 1:
            if start == prev:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{prev}")
            start = cpu
        prev = cpu

    if start == prev:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{prev}")

    return ",".join(ranges)


def get_numa_node_cpus() -> Dict[int, Set[int]]:
    """Get mapping of NUMA nodes to their associated CPU cores.

    Returns:
        Dictionary mapping NUMA node ID to set of CPU core numbers

    Raises:
        ValueError: If NUMA topology is not available
    """
    base = "/sys/devices/system/node"
    if not os.path.exists(base):
        raise ValueError("NUMA topology not available")

    try:
        node_dirs = [d for d in os.listdir(base) if d.startswith("node") and d[4:].isdigit()]
    except Exception:
        node_dirs = []

    numa_cpus: Dict[int, Set[int]] = {}
    for node_dir in sorted(node_dirs, key=lambda n: int(n[4:])):
        cpulist_path = os.path.join(base, node_dir, "cpulist")
        try:
            with open(cpulist_path, "r") as f:
                cpulist_str = f.read().strip()
        except Exception:
            cpulist_str = ""
        cpus = parse_cpu_ranges(cpulist_str)
        if cpus:
            numa_cpus[int(node_dir[4:])] = cpus

    if not numa_cpus:
        raise ValueError("NUMA topology not available")
    return numa_cpus


def get_cpus_in_numa_node(numa_node: int, cpus_str: str) -> Set[int]:
    """Get CPUs from a given string that belong to a specific NUMA node.

    Args:
        numa_node: The NUMA node ID.
        cpus_str: Comma-separated string of CPU ranges (e.g., "0-3,6,8-10").

    Returns:
        A set of CPU integers that are in the specified NUMA node and in cpus_str.
    """
    all_cpus_in_numa = get_numa_node_cpus().get(numa_node, set())
    requested_cpus = parse_cpu_ranges(cpus_str)
    return all_cpus_in_numa.intersection(requested_cpus)


def _count_cpus_in_ranges(cpu_ranges: str) -> int:
    """Count the number of CPUs in a comma-separated range string.

    Args:
        cpu_ranges: Comma-separated list of CPU ranges (e.g., "0-2,4,6-8")

    Returns:
        Number of CPUs in the ranges
    """
    return len(parse_cpu_ranges(cpu_ranges))
