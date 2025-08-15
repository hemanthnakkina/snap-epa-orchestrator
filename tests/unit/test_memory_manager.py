# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for epa_orchestrator.memory_manager."""

from epa_orchestrator.memory_manager import (
    get_memory_summary,
)


class TestMemorySummaryOnly:
    """Unit tests focused on get_memory_summary structure."""

    def test_get_memory_summary_success(self):
        """Test successful memory summary retrieval."""
        summary = get_memory_summary()
        assert isinstance(summary, dict)
        assert "numa_hugepages" in summary
        assert isinstance(summary["numa_hugepages"], dict)

    def test_get_memory_summary_error_handling(self, monkeypatch):
        """Test memory summary error handling path."""
        from epa_orchestrator import memory_manager as mm

        def boom():
            raise RuntimeError("Test error")

        monkeypatch.setattr(mm, "get_numa_hugepages_info", lambda: boom())

        summary = get_memory_summary()
        assert isinstance(summary, dict)
        assert summary.get("numa_hugepages") == {}
        assert summary.get("error") == "Test error"
