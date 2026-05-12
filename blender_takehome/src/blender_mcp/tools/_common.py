"""Shared utilities for the MCP-side tool wrappers.

The one job here is ``parse_response``: take whatever the addon returned (an
already-validated success dict, a structured ``Failure`` dict, or — in the
worst case — something malformed) and produce a single discriminated-union
instance the tool can return. This is the seam where addon-side bugs become
visible to the agent as ``internal_error`` rather than crashing the server.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import TypeAdapter, ValidationError

from ..models import Failure

T = TypeVar("T")


def parse_response(
    raw: dict[str, Any],
    adapter: TypeAdapter[T],
    command_name: str,
) -> T:
    """Validate ``raw`` against ``adapter`` or wrap into a ``Failure``.

    If the addon returns a malformed payload (missing keys, wrong types, etc.)
    we surface that as a structured failure with ``internal_error`` and embed
    the raw dict in ``details`` so the agent can see what went wrong.

    The cast at the end is safe: every tool's result union includes
    ``Failure`` as a variant, so a ``Failure`` instance is always a valid
    member of ``T``. We pay one wrap+validate to keep types clean.
    """
    try:
        return adapter.validate_python(raw)
    except ValidationError as exc:
        failure = Failure(
            code="internal_error",
            message=f"addon returned malformed response for {command_name!r}: {exc}",
            details={"raw": raw},
        )
        # Re-validate so the returned object is the union variant, not a bare
        # Failure — keeps mypy/pyright happy for the caller.
        return adapter.validate_python(failure.model_dump())
