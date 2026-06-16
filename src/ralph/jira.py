"""Jira ticket normalization helpers."""

from typing import Any

from ralph.models import Ticket


def normalize_ticket(raw: dict[str, Any]) -> Ticket:
    fields = raw.get("fields", {})
    issue_type = fields.get("issuetype", {})
    status = fields.get("status", {})
    return Ticket(
        key=str(raw.get("key", "")),
        summary=str(fields.get("summary", "")),
        description=str(fields.get("description", "")),
        issue_type=str(issue_type.get("name", "")),
        status=str(status.get("name", "")),
        url=raw.get("self"),
        raw=raw,
    )

