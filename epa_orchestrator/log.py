# SPDX-FileCopyrightText: 2024 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

"""Logging configuration for the EPA orchestrator daemon."""

import logging
import sys


def setup_logging() -> None:
    """Configure logging."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.DEBUG)
