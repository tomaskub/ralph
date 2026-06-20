from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "unblock-ready-issues"
SPEC = importlib.util.spec_from_loader(
    "unblock_ready_issues",
    SourceFileLoader("unblock_ready_issues", str(SCRIPT_PATH)),
)
assert SPEC is not None
unblock_ready_issues = importlib.util.module_from_spec(SPEC)
sys.modules["unblock_ready_issues"] = unblock_ready_issues
assert SPEC.loader is not None
SPEC.loader.exec_module(unblock_ready_issues)


Issue = unblock_ready_issues.Issue
ProjectItem = unblock_ready_issues.ProjectItem
blocked_by_issue_numbers = unblock_ready_issues.blocked_by_issue_numbers
ready_candidates = unblock_ready_issues.ready_candidates


def test_blocked_by_issue_numbers_parses_hash_and_url_references() -> None:
    body = """## What to build

Something useful.

## Blocked by

- #32
- https://github.com/tomaskub/ralph/issues/36

## Acceptance criteria

- [ ] Done
"""

    assert blocked_by_issue_numbers(body) == {32, 36}


def test_blocked_by_issue_numbers_treats_none_as_unblocked_metadata() -> None:
    body = """## What to build

Something useful.

## Blocked by

None - can start immediately
"""

    assert blocked_by_issue_numbers(body) == set()


def test_ready_candidates_requires_backlog_and_closed_blockers() -> None:
    open_issues = {
        37: Issue(
            number=37,
            title="Document setup",
            body="## Blocked by\n\n- #33\n- #36\n",
            state="OPEN",
            labels=frozenset(),
        ),
        45: Issue(
            number=45,
            title="Update fails",
            body="No dependency section",
            state="OPEN",
            labels=frozenset(),
        ),
        46: Issue(
            number=46,
            title="Already running",
            body="## Blocked by\n\n- #33\n",
            state="OPEN",
            labels=frozenset({"ready-for-agent"}),
        ),
    }
    project_items = {
        37: ProjectItem(issue_number=37, item_id="item-37", status="Backlog"),
        45: ProjectItem(issue_number=45, item_id="item-45", status="Backlog"),
        46: ProjectItem(issue_number=46, item_id="item-46", status="In review"),
    }

    assert ready_candidates(
        open_issues=open_issues,
        closed_issue_numbers={33, 36},
        project_items=project_items,
        backlog_status="Backlog",
    ) == [open_issues[37]]


def test_ready_candidates_keeps_issue_blocked_when_any_blocker_is_open() -> None:
    open_issues = {
        37: Issue(
            number=37,
            title="Document setup",
            body="## Blocked by\n\n- #33\n- #36\n",
            state="OPEN",
            labels=frozenset(),
        ),
    }
    project_items = {
        37: ProjectItem(issue_number=37, item_id="item-37", status="Backlog"),
    }

    assert (
        ready_candidates(
            open_issues=open_issues,
            closed_issue_numbers={33},
            project_items=project_items,
            backlog_status="Backlog",
        )
        == []
    )
