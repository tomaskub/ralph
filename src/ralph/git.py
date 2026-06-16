"""Git-related planning and validation helpers."""

import re
from pathlib import Path

from ralph.models import Ticket

MAX_BRANCH_LENGTH = 80


def worktree_path_for_branch(worktree_root: Path, branch_name: str) -> Path:
    return worktree_root / branch_name.replace("/", "__")


def branch_name_for_ticket(ticket: Ticket, branch_kind: str) -> str:
    slug = _slugify(ticket.summary)
    branch = f"{branch_kind}/{ticket.key}-{slug}"
    return branch[:MAX_BRANCH_LENGTH].rstrip("-")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "ticket"
