"""Optional third-party dependency detection for the test suite.

Why this exists
---------------
The README claims the deterministic core can be verified with no packages
installed. That claim was false at the test boundary: five test modules
imported ``fastapi`` or ``sqlalchemy`` at module scope, so a reviewer running
``python3 -m unittest discover`` on a bare interpreter saw five import errors
and a red ``FAILED`` line before reading a word of the architecture.

An import error is not a test failure, but it looks exactly like one. These
flags let the HTTP and SQL suites *skip* cleanly when their dependencies are
absent, so a bare run reports ``OK (skipped=N)`` and a full run in CI executes
everything.

CI installs ``backend/requirements.txt``, so nothing is silently skipped where
it matters.
"""

from __future__ import annotations

import importlib.util


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


HAS_FASTAPI = _installed("fastapi")
HAS_SQLALCHEMY = _installed("sqlalchemy")

REQUIRES_FASTAPI = (
    "fastapi is not installed; HTTP contract tests need "
    "`pip install -r requirements.txt`"
)
REQUIRES_SQLALCHEMY = (
    "sqlalchemy is not installed; SQL persistence tests need "
    "`pip install -r requirements.txt`"
)

__all__ = [
    "HAS_FASTAPI",
    "HAS_SQLALCHEMY",
    "REQUIRES_FASTAPI",
    "REQUIRES_SQLALCHEMY",
]
