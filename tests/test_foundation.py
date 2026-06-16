from pathlib import Path

from ralph.git import worktree_path_for_branch
from ralph.jira import normalize_ticket
from ralph.state import state_path
from ralph.templates import render_template


def test_worktree_path_replaces_branch_separator() -> None:
    assert worktree_path_for_branch(
        Path("/tmp/worktrees"),
        "feature/YT-123-add-cache",
    ) == Path("/tmp/worktrees/feature__YT-123-add-cache")


def test_state_path_uses_repo_and_ticket() -> None:
    assert state_path(Path("/tmp/state"), "yt-smzr", "YT-123") == Path(
        "/tmp/state/yt-smzr/YT-123.json"
    )


def test_normalize_ticket_extracts_core_fields() -> None:
    ticket = normalize_ticket(
        {
            "key": "YT-123",
            "self": "https://jira.example/browse/YT-123",
            "fields": {
                "summary": "Add cache",
                "description": "Cache the summary.",
                "issuetype": {"name": "Task"},
                "status": {"name": "To Do"},
            },
        }
    )

    assert ticket.key == "YT-123"
    assert ticket.summary == "Add cache"
    assert ticket.issue_type == "Task"
    assert ticket.status == "To Do"
    assert ticket.url == "https://jira.example/browse/YT-123"


def test_template_rendering_uses_package_templates() -> None:
    ticket = normalize_ticket(
        {
            "key": "YT-123",
            "fields": {
                "summary": "Add cache",
                "description": "Cache the summary.",
                "issuetype": {"name": "Task"},
                "status": {"name": "To Do"},
            },
        }
    )

    rendered = render_template("mr_title.md.j2", ticket=ticket)

    assert rendered == "YT-123: Add cache\n"

