"""Local state paths and status primitives."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ralph.models import RunState, RunStatus, Ticket

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


def list_run_states(
    repo_name: str,
    *,
    state_dir: Path = DEFAULT_STATE_DIR,
) -> list[RunState]:
    repo_state_dir = state_dir / repo_name
    if not repo_state_dir.exists():
        return []
    return [
        read_run_state(path)
        for path in sorted(repo_state_dir.glob("*.json"))
        if path.is_file()
    ]


def read_run_state(path: Path) -> RunState:
    return _run_state_from_json(json.loads(path.read_text()))


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


def _run_state_from_json(data: dict[str, Any]) -> RunState:
    ticket = _ticket_from_json(data["ticket"])
    return RunState(
        ticket_key=str(data["ticket_key"]),
        ticket=ticket,
        repo_name=str(data["repo_name"]),
        repo_path=Path(str(data["repo_path"])),
        worktree_path=Path(str(data["worktree_path"])),
        branch_name=str(data["branch_name"]),
        base_ref=str(data["base_ref"]),
        base_sha=str(data["base_sha"]),
        status=_run_status(str(data["status"])),
        created_at=datetime.fromisoformat(str(data["created_at"])),
        updated_at=datetime.fromisoformat(str(data["updated_at"])),
        command_log=[str(command) for command in data.get("command_log", [])],
        mr_url=data.get("mr_url"),
        error=data.get("error"),
    )


def _ticket_from_json(data: dict[str, Any]) -> Ticket:
    return Ticket(
        key=str(data["key"]),
        summary=str(data["summary"]),
        description=str(data["description"]),
        issue_type=str(data["issue_type"]),
        status=str(data["status"]),
        url=data.get("url"),
        epic=data.get("epic"),
        links=[str(link) for link in data.get("links", [])],
        raw=dict(data.get("raw", {})),
    )


def _run_status(value: str) -> RunStatus:
    if value not in {"started", "needs-attention", "mr-created", "cleaned-up"}:
        raise ValueError(f"Unknown run status: {value}")
    return value  # type: ignore[return-value]
