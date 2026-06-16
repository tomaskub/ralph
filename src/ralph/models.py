"""Domain models for tickets, runs, and generated plans."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

RunStatus = Literal["started", "needs-attention", "mr-created", "cleaned-up"]


@dataclass(frozen=True)
class Ticket:
    key: str
    summary: str
    description: str
    issue_type: str
    status: str
    url: str | None = None
    epic: str | None = None
    links: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunState:
    ticket_key: str
    ticket: Ticket
    repo_path: Path
    worktree_path: Path
    branch_name: str
    base_ref: str
    base_sha: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    mr_url: str | None = None

