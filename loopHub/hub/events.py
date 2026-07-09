"""Parse and filter Taiga webhook payloads into hub events.

Only `action=change, type=userstory` with a status transition we care about
becomes an event. The diff carries status *display names*; mapping to roles
uses the configured names (resolved to ids at startup for API write-backs).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StatusChange:
    story_id: int
    story_ref: int
    project_id: int
    subject: str
    description: str
    version: int
    from_status: str            # display name
    to_status: str              # display name
    custom_attributes: dict[str, Any]
    raw: dict[str, Any]


def parse(payload: dict[str, Any]) -> StatusChange | None:
    """Return a StatusChange for userstory status moves, else None."""
    if payload.get("action") != "change" or payload.get("type") != "userstory":
        return None
    diff = (payload.get("change") or {}).get("diff") or {}
    status = diff.get("status")
    if not status or "from" not in status or "to" not in status:
        return None
    data = payload.get("data") or {}
    return StatusChange(
        story_id=int(data["id"]),
        story_ref=int(data.get("ref") or 0),
        project_id=int((data.get("project") or {}).get("id") or 0),
        subject=data.get("subject") or "",
        description=data.get("description") or "",
        version=int(data.get("version") or 0),
        from_status=status["from"],
        to_status=status["to"],
        custom_attributes=data.get("custom_attributes_values") or {},
        raw=payload,
    )
