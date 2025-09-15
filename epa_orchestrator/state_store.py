# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Persistent state storage for EPA Orchestrator.

Provides a simple JSON-backed store with:
- Exclusive file locking (fcntl) to serialize access across processes
- Atomic writes (write to temp file then replace) to avoid torn writes
- Sectioned updates (so independent modules can update their own section)

The state file lives under $SNAP_DATA/data/state.json when SNAP_DATA is set.
Outside snap, it falls back to ~/.local/share/epa-orchestrator/data/state.json.
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional


class StateCorruptionError(Exception):
    """Raised when the persisted state file is detected as corrupt/invalid JSON."""


def _default_base_dir() -> str:
    snap_data = os.environ.get("SNAP_DATA")
    if snap_data:
        return snap_data
    # Fallback for non-snap environments (tests/dev)
    return os.path.join(os.path.expanduser("~"), ".local", "share", "epa-orchestrator")


class StateStore:
    """JSON-backed state store with file locking and atomic writes.

    The state is a JSON object with structure like:
    {
        "version": 1,
        "updated_at": "...",
        "allocations_db": { ... },
        "hugepages_db": { ... }
    }
    """

    def __init__(self, *, filename: str = "state.json", subdir: str = "data") -> None:
        """Initialize the store paths and ensure the base directory exists."""
        base_dir = _default_base_dir()
        self._dir_path = os.path.join(base_dir, subdir)
        self._file_path = os.path.join(self._dir_path, filename)
        self._lock_path = f"{self._file_path}.lock"
        # Enable persistence by default in all environments.
        self._disabled = False
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        try:
            os.makedirs(self._dir_path, exist_ok=True)
        except Exception as e:
            logging.error(f"Failed to ensure state directory {self._dir_path}: {e}")
            raise

    @contextmanager
    def _locked(self) -> Generator[None, None, None]:
        fd: Optional[int] = None
        try:
            fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
            except Exception:
                # Best-effort unlock/close
                pass

    def _read_unlocked(self) -> Dict[str, Any]:
        if not os.path.exists(self._file_path):
            return {}
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                obj: object = json.load(f)
                return obj if isinstance(obj, dict) else {}
        except Exception as e:
            # Treat invalid JSON as fatal corruption: raise to crash the daemon
            raise StateCorruptionError(
                f"State file is corrupt or invalid JSON: {self._file_path}"
            ) from e

    def _atomic_write_unlocked(self, data: Dict[str, Any]) -> None:
        temp_fd = None
        temp_path = None
        try:
            # Write to a temp file in the same directory for atomic replace
            temp_fd, temp_path = tempfile.mkstemp(
                dir=self._dir_path, prefix=".state.", suffix=".tmp"
            )
            with os.fdopen(temp_fd, "w", encoding="utf-8") as tmp_fp:
                temp_fd = None  # fd owned by tmp_fp now
                json.dump(data, tmp_fp, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                tmp_fp.flush()
                os.fsync(tmp_fp.fileno())
            os.replace(temp_path, self._file_path)
            # fsync directory to persist rename on crash
            dir_fd = os.open(self._dir_path, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception as e:
            logging.error(f"Failed to atomically write state file {self._file_path}: {e}")
            raise
        finally:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except Exception:
                    pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        logging.debug(f"Cleanup temp file failed: {temp_path}: {e}")

    def read_all(self) -> Dict[str, Any]:
        """Read the entire state under an exclusive lock."""
        with self._locked():
            return self._read_unlocked()

    def write_all(self, data: Dict[str, Any]) -> None:
        """Write the entire state under an exclusive lock."""
        data = dict(data or {})
        data.setdefault("version", 1)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self._locked():
            self._atomic_write_unlocked(data)

    def read_section(self, section: str) -> Dict[str, Any]:
        """Read a single top-level section dictionary from the state file."""
        with self._locked():
            state = self._read_unlocked()
            sec = state.get(section)
            return dict(sec) if isinstance(sec, dict) else {}

    def update_section(self, section: str, content: Dict[str, Any]) -> None:
        """Atomically update a single top-level section, preserving others."""
        with self._locked():
            state = self._read_unlocked()
            state[section] = dict(content or {})
            state.setdefault("version", 1)
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._atomic_write_unlocked(state)
