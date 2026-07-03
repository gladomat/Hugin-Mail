"""Logging configuration. Library modules use `logging.getLogger(__name__)`; the
CLI calls `configure()` once from its top-level callback. No `print` in library
code — progress is a side channel (logging + optional callbacks)."""

from __future__ import annotations

import logging
import sys


def configure(verbosity: int = 0, quiet: bool = False) -> None:
    """verbosity: 0=INFO, 1+=DEBUG. quiet forces WARNING."""
    level = logging.WARNING if quiet else (logging.DEBUG if verbosity else logging.INFO)
    root = logging.getLogger("huginmail")
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
