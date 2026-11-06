"""Small helpers shared by routers."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from afya_mcp.fhir import ref_id

from .errors import ApiError
from .mcp_client import McpUnavailable, ToolFailed, ToolRefused


def now() -> datetime:
    return datetime.now(UTC)


def iso(t: datetime | None) -> str | None:
    return t.isoformat() if t else None


def uuid_or_404(value: str, what: str = "proposal") -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ApiError(404, f"{what} not found") from None


def uuid_or_conflict(value: str) -> str:
    """An id that is not a UUID cannot be a pending proposal: same answer as an unknown one (409, api.md)."""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ApiError(409, "proposal is not pending") from None


def tool_error(e: Exception, forbidden: str = "not allowed") -> ApiError:
    """Translate afya-mcp failures into the error body of docs/api.md."""
    if isinstance(e, ToolRefused):
        return ApiError(403, forbidden)
    if isinstance(e, McpUnavailable):
        return ApiError(503, "the data service is not reachable")
    text = e.text if isinstance(e, ToolFailed) else str(e)
    if "HTTP 404" in text:
        return ApiError(404, "record not found")
    return ApiError(503, "the data service failed; try again")


def bare(ref: Any) -> str:
    return ref_id(str(ref))
