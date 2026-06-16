"""Jira ticket fetching, normalization, and validation helpers."""

import json
import shlex
from dataclasses import dataclass, field
from typing import Any

from ralph.config import RepoConfig
from ralph.models import Ticket
from ralph.runner import CommandRunner


def normalize_ticket(raw: dict[str, Any]) -> Ticket:
    fields = raw.get("fields", {})
    issue_type = fields.get("issuetype", {})
    status = fields.get("status", {})
    return Ticket(
        key=str(raw.get("key", "")),
        summary=str(fields.get("summary", "")),
        description=_field_to_text(fields.get("description")),
        issue_type=str(issue_type.get("name", "")),
        status=str(status.get("name", "")),
        url=raw.get("self"),
        epic=_epic_key(fields),
        links=_link_keys(fields),
        raw=raw,
    )


@dataclass(frozen=True)
class JiraFetchError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class Blocker:
    key: str
    status: str


@dataclass(frozen=True)
class DependencyDecision:
    unresolved_blockers: list[Blocker] = field(default_factory=list)
    requires_confirmation: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class TicketValidationResult:
    errors: list[str] = field(default_factory=list)
    dependency: DependencyDecision = field(default_factory=DependencyDecision)

    @property
    def ok(self) -> bool:
        return (
            not self.errors
            and not self.dependency.unresolved_blockers
            and not self.dependency.requires_confirmation
        )


def fetch_ticket_json(
    ticket_key: str,
    *,
    issue_json_command: str,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Fetch raw Jira JSON through the configured command."""
    runner = runner or CommandRunner()
    args = shlex.split(issue_json_command.format(ticket=ticket_key))
    if not args:
        raise JiraFetchError("Configured Jira issue JSON command is empty")

    result = runner.run(args)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise JiraFetchError(f"Jira issue JSON command failed{detail}")

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise JiraFetchError(
            "Jira issue JSON command did not return valid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise JiraFetchError("Jira issue JSON command must return a JSON object")
    return raw


def validate_ticket(
    ticket: Ticket,
    *,
    repo: RepoConfig,
    branch_kinds: dict[str, str],
) -> TicketValidationResult:
    errors: list[str] = []
    expected_prefix = f"{repo.jira_project}-"
    if repo.jira_project and not ticket.key.startswith(expected_prefix):
        errors.append(
            f"Ticket {ticket.key or '<empty>'} is outside Jira project "
            f"{repo.jira_project}"
        )
    if not ticket.summary.strip():
        errors.append("Ticket summary is empty")
    if not ticket.description.strip():
        errors.append("Ticket description is empty")
    if ticket.status != "To Do":
        errors.append(f"Ticket status must be To Do, got {ticket.status or '<empty>'}")
    if ticket.issue_type not in branch_kinds:
        errors.append(f"Unmapped Jira issue type: {ticket.issue_type or '<empty>'}")

    return TicketValidationResult(
        errors=errors,
        dependency=dependency_decision(ticket.raw),
    )


def branch_kind_for_ticket(ticket: Ticket, branch_kinds: dict[str, str]) -> str:
    try:
        return branch_kinds[ticket.issue_type]
    except KeyError as exc:
        raise KeyError(f"Unmapped Jira issue type: {ticket.issue_type}") from exc


def dependency_decision(raw: dict[str, Any]) -> DependencyDecision:
    fields = raw.get("fields")
    if not isinstance(fields, dict) or "issuelinks" not in fields:
        return DependencyDecision(
            requires_confirmation=True,
            reason="Jira dependency information is unavailable",
        )

    links = fields.get("issuelinks")
    if not isinstance(links, list):
        return DependencyDecision(
            requires_confirmation=True,
            reason="Jira dependency information is ambiguous",
        )

    blockers: list[Blocker] = []
    for link in links:
        if not isinstance(link, dict):
            return DependencyDecision(
                requires_confirmation=True,
                reason="Jira dependency information is ambiguous",
            )
        blocker = _unresolved_blocker_from_link(link)
        if blocker is not None:
            blockers.append(blocker)

    return DependencyDecision(unresolved_blockers=blockers)


def _unresolved_blocker_from_link(link: dict[str, Any]) -> Blocker | None:
    link_type = link.get("type", {})
    inward_label = str(_nested(link_type, "inward") or "").lower()
    inward_issue = link.get("inwardIssue")
    if "block" not in inward_label or not isinstance(inward_issue, dict):
        return None

    status = str(_nested(inward_issue, "fields", "status", "name") or "")
    status_category = str(
        _nested(inward_issue, "fields", "status", "statusCategory", "key") or ""
    ).lower()
    if status_category == "done" or status.lower() in {"done", "closed", "resolved"}:
        return None
    return Blocker(key=str(inward_issue.get("key", "")), status=status)


def _field_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            return "\n".join(filter(None, (_field_to_text(item) for item in content)))
        text = value.get("text")
        if isinstance(text, str):
            return text
    if isinstance(value, list):
        return "\n".join(filter(None, (_field_to_text(item) for item in value)))
    return str(value)


def _epic_key(fields: dict[str, Any]) -> str | None:
    for key in ("epic", "parent", "customfield_10014"):
        value = fields.get(key)
        if isinstance(value, dict) and value.get("key"):
            return str(value["key"])
        if isinstance(value, str) and value:
            return value
    return None


def _link_keys(fields: dict[str, Any]) -> list[str]:
    links = fields.get("issuelinks")
    if not isinstance(links, list):
        return []

    keys: list[str] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        for issue_key in ("inwardIssue", "outwardIssue"):
            issue = link.get(issue_key)
            if isinstance(issue, dict) and issue.get("key"):
                keys.append(str(issue["key"]))
    return keys


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
