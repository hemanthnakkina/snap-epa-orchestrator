# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Functional tests for EPA Orchestrator socket API: testing with real daemon.

This suite exercises live socket interactions.
"""

import json
import socket


def test_allocate_cores_via_socket_api(socket_path):
    """Test that allocate_cores works with real daemon."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)

    request = {
        "version": "1.0",
        "service_name": "test-service",
        "action": "allocate_cores",
        "num_of_cores": 2,
    }

    sock.sendall(json.dumps(request).encode())
    response = sock.recv(4096).decode()
    result = json.loads(response)

    if "error" in result:
        # Acceptable if no isolated CPUs are configured
        assert "No CPUs available" in result["error"]
    else:
        assert result["version"] == "1.0"
        assert result["service_name"] == "test-service"
        assert result["num_of_cores"] == 2

        # Check for successful allocation (no error)
        assert not result.get("error"), f"Unexpected error in response: {result.get('error')}"

        # Check that cores were actually allocated
        assert result["cores_allocated"] == 2
        assert result["allocated_cores"] != ""
        assert result["total_available_cpus"] > 0
        assert "shared_cpus" in result

    sock.close()


def test_list_allocations_via_socket_api(socket_path):
    """Test that list_allocations works with real daemon."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)

    request = {
        "version": "1.0",
        "service_name": "any-service",
        "action": "list_allocations",
    }

    sock.sendall(json.dumps(request).encode())
    response = sock.recv(4096).decode()
    result = json.loads(response)

    assert result["version"] == "1.0"

    # Check for successful response (no error)
    assert not result.get("error"), f"Unexpected error in response: {result.get('error')}"

    # Accept both cases: no isolated CPUs (0) or isolated CPUs (>0)
    assert result["total_available_cpus"] >= 0
    assert result["total_allocations"] >= 0
    assert result["total_allocated_cpus"] >= 0
    assert result["remaining_available_cpus"] >= 0
    assert "allocations" in result
    assert isinstance(result["allocations"], list)

    for allocation in result["allocations"]:
        assert "is_explicit" in allocation
        assert isinstance(allocation["is_explicit"], bool)

    sock.close()
