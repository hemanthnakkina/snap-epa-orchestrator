# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for NUMA-aware hugepages info assembly."""

import os
from unittest.mock import patch

from epa_orchestrator.memory_manager import get_numa_hugepages_info


def _make_node_tree(tmpdir, node_id: int, sizes: dict):
    node_dir = os.path.join(tmpdir, f"node{node_id}")
    huge_dir = os.path.join(node_dir, "hugepages")
    os.makedirs(huge_dir, exist_ok=True)
    for size_kb, values in sizes.items():
        entry = os.path.join(huge_dir, f"hugepages-{size_kb}kB")
        os.makedirs(entry, exist_ok=True)
        with open(os.path.join(entry, "nr_hugepages"), "w", encoding="utf-8") as f:
            f.write(str(values.get("total", 0)))
        with open(os.path.join(entry, "free_hugepages"), "w", encoding="utf-8") as f:
            f.write(str(values.get("free", 0)))
        with open(os.path.join(entry, "surplus_hugepages"), "w", encoding="utf-8") as f:
            f.write(str(values.get("surplus", 0)))


def test_numa_info_structured(tmp_path):
    """Test structured NUMA hugepage information assembly."""
    with patch("epa_orchestrator.memory_manager.NODES_BASE_PATH", str(tmp_path)):
        _make_node_tree(str(tmp_path), 0, {2048: {"total": 100, "free": 60, "surplus": 0}})
        _make_node_tree(str(tmp_path), 1, {1048576: {"total": 2, "free": 1, "surplus": 0}})

        info = get_numa_hugepages_info()
        assert set(info.keys()) == {"node0", "node1"}
        node0 = info["node0"]
        entry_2m = [u for u in node0["usage"] if u["size"] == 2048][0]
        assert entry_2m["total"] == 100
        assert entry_2m["free"] == 60
        assert node0["allocations"] == {}


def test_numa_info_empty_nodes(tmp_path):
    """Test NUMA hugepage information for empty nodes."""
    with patch("epa_orchestrator.memory_manager.NODES_BASE_PATH", str(tmp_path)):
        os.makedirs(str(tmp_path), exist_ok=True)
        os.makedirs(os.path.join(str(tmp_path), "node0"), exist_ok=True)
        info = get_numa_hugepages_info()
        assert info == {"node0": {"usage": [], "allocations": {}}}
