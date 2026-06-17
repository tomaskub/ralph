"""Local state paths and status primitives."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ralph.models import RunState, Ticket

DEFAULT_STATE_DIR = Path("~/.local/state/ralph").expanduser()


def state_path(state_dir: Path, repo_name: str, ticket_key: str) -> Path:
    return state_dir / repo_name / f"{ticket_key}.json"


def write_run_state(
    state: RunState,
    *,
    state_dir: Path = DEFAULT_STATE_DIR,
) -> Path:
    path = state_path(state_dir, state.repo_name, state.ticket_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_run_state_to_json(state), indent=2, sort_keys=True))
    return path


def _run_state_to_json(state: RunState) -> dict[str, Any]:
    data = asdict(state)
    data["repo_path"] = str(state.repo_path)
    data["worktree_path"] = str(state.worktree_path)
    data["created_at"] = _datetime_to_json(state.created_at)
    data["updated_at"] = _datetime_to_json(state.updated_at)
    data["ticket"] = _ticket_to_json(state.ticket)
    return data


def _ticket_to_json(ticket: Ticket) -> dict[str, Any]:
    return {
        "key": ticket.key,
        "summary": ticket.summary,
        "description": ticket.description,
        "issue_type": ticket.issue_type,
        "status": ticket.status,
        "url": ticket.url,
        "epic": ticket.epic,
        "links": ticket.links,
        "raw": ticket.raw,
    }


def _datetime_to_json(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
