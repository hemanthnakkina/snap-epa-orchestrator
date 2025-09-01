# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Concise unit tests for epa_orchestrator.utils."""

import builtins
import os
from unittest.mock import patch

import pytest

from epa_orchestrator.utils import get_numa_node_cpus, to_ranges


class TestToRanges:
    """Unit tests for to_ranges utility function."""

    def test_consecutive(self):
        """Test to_ranges with consecutive numbers."""
        assert to_ranges([0, 1, 2, 3]) == "0-3"

    def test_disjoint(self):
        """Test to_ranges with disjoint numbers."""
        assert to_ranges([0, 2, 4, 6]) == "0,2,4,6"

    def test_empty(self):
        """Test to_ranges with empty list."""
        assert to_ranges([]) == ""


def test_get_numa_node_cpus_from_cpulist(tmp_path, monkeypatch):
    """NUMA mapping is parsed from node*/cpulist into a node->CPU set mapping."""
    base = tmp_path / "sys" / "devices" / "system" / "node"
    (base / "node0").mkdir(parents=True)
    (base / "node1").mkdir(parents=True)
    (base / "node0" / "cpulist").write_text("0-3\n", encoding="utf-8")
    (base / "node1" / "cpulist").write_text("4-7\n", encoding="utf-8")

    sys_base = "/sys/devices/system/node"

    def fake_exists(p: str) -> bool:
        if p == sys_base:
            return True
        if p == os.path.join(sys_base, "node0", "cpulist"):
            return True
        if p == os.path.join(sys_base, "node1", "cpulist"):
            return True
        return False

    def fake_listdir(p: str):
        if p == sys_base:
            return ["node0", "node1"]
        return []

    original_open = builtins.open

    def _open(path, mode="r", *args, **kwargs):
        p = str(path)
        if p == os.path.join(sys_base, "node0", "cpulist"):
            return original_open(base / "node0" / "cpulist", mode, *args, **kwargs)
        if p == os.path.join(sys_base, "node1", "cpulist"):
            return original_open(base / "node1" / "cpulist", mode, *args, **kwargs)
        raise FileNotFoundError

    monkeypatch.setattr("epa_orchestrator.utils.os.path.exists", fake_exists)
    monkeypatch.setattr("epa_orchestrator.utils.os.listdir", fake_listdir)

    with patch("builtins.open", _open):
        result = get_numa_node_cpus()
        assert result == {0: {0, 1, 2, 3}, 1: {4, 5, 6, 7}}


def test_get_numa_node_cpus_raises_on_missing(tmp_path, monkeypatch):
    """If no nodes/cpulists are available, the utility raises a ValueError."""
    sys_base = "/sys/devices/system/node"

    def fake_exists(p: str) -> bool:
        return p == sys_base

    def fake_listdir(p: str):
        if p == sys_base:
            return []
        return []

    monkeypatch.setattr("epa_orchestrator.utils.os.path.exists", fake_exists)
    monkeypatch.setattr("epa_orchestrator.utils.os.listdir", fake_listdir)

    with pytest.raises(ValueError) as ei:
        _ = get_numa_node_cpus()
    assert "NUMA topology not available" in str(ei.value)
