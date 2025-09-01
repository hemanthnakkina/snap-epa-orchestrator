# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for memory management functionality."""

import json
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import parse_obj_as

from epa_orchestrator.daemon_handler import handle_daemon_request
from epa_orchestrator.schemas import (
    ActionType,
    AllocateHugepagesRequest,
    AllocateHugepagesResponse,
    GetMemoryInfoRequest,
    MemoryInfoResponse,
)


class TestMemoryIntegration:
    """Integration tests for memory management functionality."""

    @pytest.fixture
    def socket_path(self, tmp_path):
        """Create a temporary socket path."""
        socket_dir = tmp_path / "data"
        socket_dir.mkdir()
        return str(socket_dir / "epa.sock")

    @pytest.fixture
    def memory_socket_daemon(self, socket_path, monkeypatch):
        """Start a socket-based daemon server with memory functionality."""
        monkeypatch.setenv("SNAP_DATA", str(Path(socket_path).parent.parent))

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(socket_path)
        server_sock.listen(5)

        def server_handler():
            """Handle daemon requests."""
            for _ in range(10):
                try:
                    conn, _ = server_sock.accept()
                except OSError:
                    break
                with conn:
                    data = conn.recv(1024)
                    if data:
                        response_bytes = handle_daemon_request(data)
                        conn.sendall(response_bytes)

        server_thread = threading.Thread(target=server_handler, daemon=True)
        server_thread.start()

        time.sleep(0.1)

        yield server_sock

        server_sock.close()
        if Path(socket_path).exists():
            Path(socket_path).unlink()

    def test_get_memory_info_via_socket(self, memory_socket_daemon, socket_path):
        """Test getting memory information through socket communication."""
        request = GetMemoryInfoRequest(
            service_name="test-service", action=ActionType.GET_MEMORY_INFO
        )

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(socket_path)
            client.sendall(json.dumps(request.dict()).encode())
            response_data = client.recv(4096)

        response = parse_obj_as(MemoryInfoResponse, json.loads(response_data.decode()))
        assert response.service_name == "test-service"
        assert isinstance(response.numa_hugepages, dict)

    @patch("epa_orchestrator.daemon_handler.get_memory_summary")
    def test_allocate_hugepages_via_socket(self, mock_summary, memory_socket_daemon, socket_path):
        """Test hugepage allocation through socket communication."""
        # Provide capacity so the allocation passes under capacity checks
        mock_summary.return_value = {
            "numa_hugepages": {
                "node0": {"capacity": [{"total": 10, "free": 10, "size": 2048}], "allocations": {}}
            }
        }
        request = AllocateHugepagesRequest(
            service_name="test-service",
            action=ActionType.ALLOCATE_HUGEPAGES,
            hugepages_requested=2,
            node_id=0,
            size_kb=2048,
        )

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(socket_path)
            client.sendall(json.dumps(request.dict()).encode())
            response_data = client.recv(4096)

        response = parse_obj_as(AllocateHugepagesResponse, json.loads(response_data.decode()))
        assert response.service_name == "test-service"
        assert response.allocation_successful is True
        assert response.hugepages_requested == 2
        assert response.node_id == 0
        assert response.size_kb == 2048

    def test_memory_info_response_structure(self, memory_socket_daemon, socket_path):
        """Test that memory info response has correct structure."""
        request = GetMemoryInfoRequest(
            service_name="test-service", action=ActionType.GET_MEMORY_INFO
        )

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(socket_path)
            client.sendall(json.dumps(request.dict()).encode())
            response_data = client.recv(4096)

        response = parse_obj_as(MemoryInfoResponse, json.loads(response_data.decode()))

        assert hasattr(response, "version")
        assert hasattr(response, "service_name")
        assert hasattr(response, "numa_hugepages")
        assert response.version == "1.0"
        assert response.service_name == "test-service"
        assert isinstance(response.numa_hugepages, dict)
