from pathlib import Path

from ralph.config import RepoConfig
from ralph.git import branch_name_for_ticket, worktree_path_for_branch
from ralph.jira import (
    branch_kind_for_ticket,
    dependency_decision,
    fetch_ticket_json,
    normalize_ticket,
    validate_ticket,
)
from ralph.runner import CommandResult
from ralph.state import state_path
from ralph.templates import render_template


def test_worktree_path_replaces_branch_separator() -> None:
    assert worktree_path_for_branch(
        Path("/tmp/worktrees"),
        "feature/YT-123-add-cache",
    ) == Path("/tmp/worktrees/feature__YT-123-add-cache")


def test_branch_name_uses_branch_kind_ticket_key_and_summary_slug() -> None:
    ticket = normalize_ticket(jira_json())

    assert branch_name_for_ticket(ticket, "feature") == "feature/YT-123-add-cache"


def test_state_path_uses_repo_and_ticket() -> None:
    assert state_path(Path("/tmp/state"), "yt-smzr", "YT-123") == Path(
        "/tmp/state/yt-smzr/YT-123.json"
    )


def test_normalize_ticket_extracts_core_fields() -> None:
    ticket = normalize_ticket(
        jira_json(
            fields={
                "parent": {"key": "YT-1"},
                "issuelinks": [
                    {"outwardIssue": {"key": "YT-99"}},
                    {"inwardIssue": {"key": "YT-42"}},
                ],
            }
        )
    )

    assert ticket.key == "YT-123"
    assert ticket.summary == "Add cache"
    assert ticket.description == "Cache the summary."
    assert ticket.issue_type == "Task"
    assert ticket.status == "To Do"
    assert ticket.url == "https://jira.example/browse/YT-123"
    assert ticket.epic == "YT-1"
    assert ticket.links == ["YT-99", "YT-42"]


def test_fetch_ticket_json_uses_configured_command_through_runner() -> None:
    runner = FakeRunner(stdout='{"key": "YT-123", "fields": {}}')

    raw = fetch_ticket_json(
        "YT-123",
        issue_json_command="jira issue view {ticket} --format json",
        runner=runner,
    )

    assert raw["key"] == "YT-123"
    assert runner.args == ("jira", "issue", "view", "YT-123", "--format", "json")


def test_validate_ticket_rejects_wrong_project_status_description_and_type() -> None:
    ticket = normalize_ticket(
        jira_json(
            key="OTHER-1",
            fields={
                "description": "",
                "issuetype": {"name": "Spike"},
                "status": {"name": "In Progress"},
                "issuelinks": [],
            },
        )
    )

    result = validate_ticket(
        ticket,
        repo=repo_config(),
        branch_kinds={"Task": "feature"},
    )

    assert result.errors == [
        "Ticket OTHER-1 is outside Jira project YT",
        "Ticket description is empty",
        "Ticket status must be To Do, got In Progress",
        "Unmapped Jira issue type: Spike",
    ]


def test_validate_ticket_requires_confirmation_when_dependencies_are_missing() -> None:
    ticket = normalize_ticket(jira_json())

    result = validate_ticket(
        ticket,
        repo=repo_config(),
        branch_kinds={"Task": "feature"},
    )

    assert result.errors == []
    assert result.dependency.requires_confirmation is True
    assert result.dependency.reason == "Jira dependency information is unavailable"


def test_dependency_decision_detects_unresolved_blockers() -> None:
    decision = dependency_decision(
        jira_json(
            fields={
                "issuelinks": [
                    {
                        "type": {"inward": "is blocked by"},
                        "inwardIssue": {
                            "key": "YT-99",
                            "fields": {"status": {"name": "In Progress"}},
                        },
                    },
                    {
                        "type": {"inward": "is blocked by"},
                        "inwardIssue": {
                            "key": "YT-100",
                            "fields": {
                                "status": {
                                    "name": "Done",
                                    "statusCategory": {"key": "done"},
                                }
                            },
                        },
                    },
                ]
            }
        )
    )

    blockers = [
        (blocker.key, blocker.status)
        for blocker in decision.unresolved_blockers
    ]
    assert blockers == [("YT-99", "In Progress")]


def test_branch_kind_mapping_uses_configured_issue_type_mapping() -> None:
    ticket = normalize_ticket(jira_json(fields={"issuetype": {"name": "Bug"}}))

    assert branch_kind_for_ticket(ticket, {"Bug": "bugfix"}) == "bugfix"


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


def repo_config() -> RepoConfig:
    return RepoConfig(
        name="product",
        repo_path=Path("/workspace/product"),
        worktree_root=Path("/workspace/product-worktrees"),
        jira_project="YT",
        gitlab_project="group/product",
    )


def jira_json(
    *,
    key: str = "YT-123",
    fields: dict | None = None,
) -> dict:
    base_fields = {
        "summary": "Add cache",
        "description": "Cache the summary.",
        "issuetype": {"name": "Task"},
        "status": {"name": "To Do"},
    }
    if fields:
        base_fields.update(fields)
    return {
        "key": key,
        "self": "https://jira.example/browse/YT-123",
        "fields": base_fields,
    }


class FakeRunner:
    def __init__(self, *, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.args: tuple[str, ...] | None = None

    def run(self, args, cwd=None) -> CommandResult:
        self.args = tuple(args)
        return CommandResult(
            args=tuple(args),
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )
