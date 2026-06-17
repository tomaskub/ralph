import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from ralph import __version__
from ralph.cli import app
from ralph.config import (
    JiraConfig,
    RalphConfig,
    ToolConfig,
    build_single_repo_config,
    load_config,
    write_config,
)
from ralph.doctor import DoctorCheck
from ralph.git import local_branch_exists
from ralph.models import RunState, Ticket
from ralph.state import write_run_state
from tests.test_config import make_git_repo, run_git

runner = CliRunner()


def test_version_option_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"ralph {__version__}" in result.output


def test_mvp_commands_are_registered() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ["init", "doctor", "start", "status", "finish", "cleanup"]:
        assert command in result.output


def test_status_reports_no_local_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=tmp_path / "product",
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", tmp_path / "state")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "No local RALPH runs found." in result.output


def test_doctor_renders_checks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=tmp_path / "product",
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "ralph.cli.run_doctor_checks",
        lambda config: [
            DoctorCheck(
                name="git installed",
                ok=True,
                detail="/usr/bin/git",
                action=None,
            )
        ],
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "RALPH doctor" in result.output
    assert "git installed" in result.output


def test_start_rejects_ticket_outside_configured_jira_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=tmp_path / "product",
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)

    result = runner.invoke(app, ["start", "OTHER-123", "--dry-run"])

    assert result.exit_code == 1
    assert "Ticket OTHER-123 is outside Jira project YT" in result.output


def test_start_dry_run_fetches_and_validates_jira_ticket(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=tmp_path / "product",
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.resolve_ref_sha", lambda repo_path, ref: "abc123")
    monkeypatch.setattr("ralph.cli._check_start_availability", lambda **kwargs: None)
    monkeypatch.setattr(
        "ralph.cli.fetch_ticket_json",
        lambda ticket, *, issue_json_command: {
            "key": ticket,
            "fields": {
                "summary": "Add cache",
                "description": "Cache the summary.",
                "issuetype": {"name": "Task"},
                "status": {"name": "To Do"},
                "issuelinks": [],
            },
        },
    )

    result = runner.invoke(app, ["start", "YT-123", "--dry-run"])

    assert result.exit_code == 0
    assert "Summary: Add cache" in result.output
    assert "Planned branch: feature/YT-123-add-cache" in result.output
    assert "No branches, worktrees, state files, or .agent/ files were written." in (
        result.output
    )


def test_start_dry_run_integration_does_not_mutate_repo_or_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = make_git_repo(tmp_path)
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(repo, "remote", "set-url", "origin", str(origin))
    run_git(repo, "push", "-u", "origin", "main")
    head_before = run_git_stdout(repo, "rev-parse", "HEAD")
    branches_before = run_git_stdout(repo, "branch", "--format=%(refname:short)")
    worktrees_before = run_git_stdout(repo, "worktree", "list", "--porcelain")

    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state" / "ralph"
    worktree_root = tmp_path / "worktrees"
    fixture = tmp_path / "jira-ticket.json"
    fixture.write_text(
        json.dumps(
            {
                "key": "YT-123",
                "self": "https://jira.example/browse/YT-123",
                "fields": {
                    "summary": "Plan café dry run",
                    "description": "Preview the work without mutations.",
                    "issuetype": {"name": "Task"},
                    "status": {"name": "To Do"},
                    "issuelinks": [],
                },
            }
        )
    )
    printer = tmp_path / "print_jira.py"
    printer.write_text(
        "import pathlib, sys\n"
        f"print(pathlib.Path({str(fixture)!r}).read_text())\n"
    )
    config = build_single_repo_config(
        repo_path=repo,
        worktree_root=worktree_root,
        base_ref="origin/main",
        jira_project="YT",
        gitlab_project="group/product",
        repo_name="product",
    )
    write_config(
        RalphConfig(
            default_repo=config.default_repo,
            repos=config.repos,
            tools=config.tools,
            jira=JiraConfig(
                issue_json_command=f"{sys.executable} {printer} {{ticket}}"
            ),
            branch_kinds=config.branch_kinds,
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["start", "YT-123", "--dry-run"])

    assert result.exit_code == 0
    assert "Planned branch: feature/YT-123-plan-cafe-dry-run" in result.output
    assert "Resolved base SHA:" in result.output
    assert ".agent/task.md" in result.output
    assert ".agent/mr_description.md" in result.output
    assert "No branches, worktrees, state files, or .agent/ files were written." in (
        result.output
    )
    assert run_git_stdout(repo, "rev-parse", "HEAD") == head_before
    assert run_git_stdout(repo, "branch", "--format=%(refname:short)") == (
        branches_before
    )
    assert run_git_stdout(repo, "worktree", "list", "--porcelain") == worktrees_before
    assert not worktree_root.exists()
    assert not state_dir.exists()
    assert not (repo / ".agent").exists()


def test_start_creates_worktree_agent_files_state_and_launches_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = make_git_repo(tmp_path)
    (repo / ".gitignore").write_text(".agent/\n")
    run_git(repo, "add", ".gitignore")
    run_git(repo, "commit", "-m", "Ignore agent files")
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(repo, "remote", "set-url", "origin", str(origin))
    run_git(repo, "push", "-u", "origin", "main")

    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state" / "ralph"
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    fixture = tmp_path / "jira-ticket.json"
    fixture.write_text(json.dumps(jira_ticket_json()))
    printer = tmp_path / "print_jira.py"
    printer.write_text(
        "import pathlib\n"
        f"print(pathlib.Path({str(fixture)!r}).read_text())\n"
    )
    agent = tmp_path / "agent.py"
    agent.write_text(
        "import pathlib\n"
        "pathlib.Path('agent-ran.txt').write_text('yes')\n"
    )
    config = build_single_repo_config(
        repo_path=repo,
        worktree_root=worktree_root,
        base_ref="origin/main",
        jira_project="YT",
        gitlab_project="group/product",
        repo_name="product",
    )
    write_config(
        RalphConfig(
            default_repo=config.default_repo,
            repos=config.repos,
            tools=ToolConfig(agent=f"{sys.executable} {agent}"),
            jira=JiraConfig(
                issue_json_command=f"{sys.executable} {printer} {{ticket}}"
            ),
            branch_kinds=config.branch_kinds,
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["start", "YT-123"])

    assert result.exit_code == 0
    branch = "feature/YT-123-add-cache"
    worktree = worktree_root / "feature__YT-123-add-cache"
    state_path = state_dir / "product" / "YT-123.json"
    state = json.loads(state_path.read_text())
    assert "Started ticket run" in result.output
    assert run_git_stdout(repo, "show-ref", "--verify", f"refs/heads/{branch}")
    assert worktree.exists()
    assert (worktree / ".agent" / "task.md").read_text() == "# YT-123\n\nAdd cache\n\n"
    assert (worktree / ".agent" / "context.md").read_text() == (
        "# RALPH Context\n\nBranch: feature/YT-123-add-cache\n\n"
    )
    assert (worktree / "agent-ran.txt").read_text() == "yes"
    assert state["ticket_key"] == "YT-123"
    assert state["repo_name"] == "product"
    assert state["status"] == "started"
    assert state["branch_name"] == branch
    assert state["base_ref"] == "origin/main"
    assert state["base_sha"]
    assert state["command_log"][-1] == f"{sys.executable} {agent}"
    assert "raw" in state["ticket"]


def test_start_persists_needs_attention_after_worktree_creation_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = make_git_repo(tmp_path)
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(repo, "remote", "set-url", "origin", str(origin))
    run_git(repo, "push", "-u", "origin", "main")

    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state" / "ralph"
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    fixture = tmp_path / "jira-ticket.json"
    fixture.write_text(json.dumps(jira_ticket_json()))
    printer = tmp_path / "print_jira.py"
    printer.write_text(
        "import pathlib\n"
        f"print(pathlib.Path({str(fixture)!r}).read_text())\n"
    )
    config = build_single_repo_config(
        repo_path=repo,
        worktree_root=worktree_root,
        base_ref="origin/main",
        jira_project="YT",
        gitlab_project="group/product",
        repo_name="product",
    )
    write_config(
        RalphConfig(
            default_repo=config.default_repo,
            repos=config.repos,
            tools=ToolConfig(agent=f"{sys.executable} -c pass"),
            jira=JiraConfig(
                issue_json_command=f"{sys.executable} {printer} {{ticket}}"
            ),
            branch_kinds=config.branch_kinds,
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["start", "YT-123"])

    branch = "feature/YT-123-add-cache"
    worktree = worktree_root / "feature__YT-123-add-cache"
    state = json.loads((state_dir / "product" / "YT-123.json").read_text())
    assert result.exit_code == 1
    assert "Start needs manual attention" in result.output
    assert run_git_stdout(repo, "show-ref", "--verify", f"refs/heads/{branch}")
    assert worktree.exists()
    assert state["status"] == "needs-attention"
    assert ".agent/ is not ignored by Git" in state["error"]


def test_status_renders_state_and_worktree_states(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clean_repo = make_git_repo(tmp_path)
    dirty_repo = tmp_path / "dirty"
    dirty_repo.mkdir()
    run_git(dirty_repo, "init", "-b", "main")
    run_git(dirty_repo, "config", "user.name", "Test User")
    run_git(dirty_repo, "config", "user.email", "test@example.com")
    (dirty_repo / "README.md").write_text("# Dirty\n")
    run_git(dirty_repo, "add", "README.md")
    run_git(dirty_repo, "commit", "-m", "Initial commit")
    (dirty_repo / "notes.txt").write_text("untracked\n")
    missing_worktree = tmp_path / "missing"

    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state" / "ralph"
    write_config(
        build_single_repo_config(
            repo_path=clean_repo,
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)
    for state in [
        run_state("YT-123", "Add cache", clean_repo, "started"),
        run_state("YT-124", "Fix dirty run", dirty_repo, "needs-attention"),
        run_state("YT-125", "Recover missing worktree", missing_worktree, "started"),
        run_state("YT-126", "Already cleaned", tmp_path / "cleaned", "cleaned-up"),
    ]:
        write_run_state(state, state_dir=state_dir)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "RALPH runs" in result.output
    assert "YT-123" in result.output
    assert "Add cache" in result.output
    assert "started" in result.output
    assert "clean" in result.output
    assert "YT-124" in result.output
    assert "dirty" in result.output
    assert "YT-125" in result.output
    assert "missing" in result.output
    assert "abc123" not in result.output
    assert "YT-126" not in result.output

    verbose = runner.invoke(app, ["status", "--all", "--verbose"])

    assert verbose.exit_code == 0
    assert "YT-126" in verbose.output
    assert "cleaned-up" in verbose.output
    assert "abc123" in verbose.output


def test_finish_pushes_branch_creates_draft_mr_and_updates_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, worktree, origin, base_sha = make_finish_worktree(tmp_path)
    state_dir = tmp_path / "state" / "ralph"
    config_path = tmp_path / "config.toml"
    glab = fake_glab(tmp_path, list_json="[]", create_output="https://gitlab.example/mr/1\n")
    write_config(
        RalphConfig(
            default_repo="product",
            repos={
                "product": build_single_repo_config(
                    repo_path=repo,
                    worktree_root=tmp_path / "worktrees",
                    base_ref="origin/main",
                    jira_project="YT",
                    gitlab_project="group/product",
                    repo_name="product",
                ).repos["product"]
            },
            tools=ToolConfig(gitlab=f"{sys.executable} {glab}"),
        ),
        config_path,
    )
    write_run_state(
        run_state("YT-123", "Add cache", worktree, "started", base_sha=base_sha),
        state_dir=state_dir,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["finish", "YT-123"])

    assert result.exit_code == 0
    assert "Created draft GitLab MR" in result.output
    assert "https://gitlab.example/mr/1" in result.output
    assert run_git_stdout(
        origin, "show-ref", "--verify", "refs/heads/feature/YT-123-add-cache"
    )
    state = json.loads((state_dir / "product" / "YT-123.json").read_text())
    assert state["status"] == "mr-created"
    assert state["mr_url"] == "https://gitlab.example/mr/1"


def test_finish_refuses_committed_agent_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, worktree, _origin, base_sha = make_finish_worktree(tmp_path)
    run_git(worktree, "add", "-f", ".agent/mr_title.md")
    run_git(worktree, "commit", "-m", "Commit agent file")
    state_dir = tmp_path / "state" / "ralph"
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=repo,
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    write_run_state(
        run_state("YT-123", "Add cache", worktree, "started", base_sha=base_sha),
        state_dir=state_dir,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["finish", "YT-123"])

    assert result.exit_code == 1
    assert "Committed diff includes .agent/ files" in result.output


def test_finish_records_existing_mr_and_refuses_duplicate_creation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, worktree, _origin, base_sha = make_finish_worktree(tmp_path)
    state_dir = tmp_path / "state" / "ralph"
    config_path = tmp_path / "config.toml"
    glab = fake_glab(
        tmp_path,
        list_json='[{"web_url": "https://gitlab.example/mr/existing"}]',
        create_output="should-not-create\n",
    )
    write_config(
        RalphConfig(
            default_repo="product",
            repos={
                "product": build_single_repo_config(
                    repo_path=repo,
                    worktree_root=tmp_path / "worktrees",
                    base_ref="origin/main",
                    jira_project="YT",
                    gitlab_project="group/product",
                    repo_name="product",
                ).repos["product"]
            },
            tools=ToolConfig(gitlab=f"{sys.executable} {glab}"),
        ),
        config_path,
    )
    write_run_state(
        run_state("YT-123", "Add cache", worktree, "started", base_sha=base_sha),
        state_dir=state_dir,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["finish", "YT-123"])

    assert result.exit_code == 1
    assert "MR already exists" in result.output
    assert not (tmp_path / "glab-created").exists()
    state = json.loads((state_dir / "product" / "YT-123.json").read_text())
    assert state["status"] == "mr-created"
    assert state["mr_url"] == "https://gitlab.example/mr/existing"


def test_cleanup_requires_mr_unless_forced(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, worktree, _origin = make_cleanup_worktree(tmp_path)
    state_dir = tmp_path / "state" / "ralph"
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=repo,
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    write_run_state(
        run_state(
            "YT-123",
            "Add cache",
            worktree,
            "started",
            repo_path=repo,
        ),
        state_dir=state_dir,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    refused = runner.invoke(app, ["cleanup", "YT-123"])

    assert refused.exit_code == 1
    assert "Run must have an MR before cleanup" in refused.output
    assert worktree.exists()
    assert local_branch_exists(repo, "feature/YT-123-add-cache")

    forced = runner.invoke(app, ["cleanup", "YT-123", "--force"], input="y\n")

    assert forced.exit_code == 0
    assert "Cleaned up local ticket work" in forced.output
    assert not worktree.exists()
    assert not local_branch_exists(repo, "feature/YT-123-add-cache")


def test_cleanup_requires_confirmation_before_deleting_local_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, worktree, _origin = make_cleanup_worktree(tmp_path)
    state_dir = tmp_path / "state" / "ralph"
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=repo,
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    write_run_state(
        run_state(
            "YT-123",
            "Add cache",
            worktree,
            "mr-created",
            repo_path=repo,
            mr_url="https://gitlab.example/mr/1",
        ),
        state_dir=state_dir,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["cleanup", "YT-123"], input="n\n")

    assert result.exit_code == 1
    assert "Cleanup cancelled" in result.output
    assert worktree.exists()
    assert local_branch_exists(repo, "feature/YT-123-add-cache")
    state = json.loads((state_dir / "product" / "YT-123.json").read_text())
    assert state["status"] == "mr-created"


def test_cleanup_removes_worktree_deletes_local_branch_and_retains_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, worktree, origin = make_cleanup_worktree(tmp_path)
    run_git(repo, "push", "-u", "origin", "feature/YT-123-add-cache")
    state_dir = tmp_path / "state" / "ralph"
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=repo,
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    write_run_state(
        run_state(
            "YT-123",
            "Add cache",
            worktree,
            "mr-created",
            repo_path=repo,
            mr_url="https://gitlab.example/mr/1",
        ),
        state_dir=state_dir,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["cleanup", "YT-123"], input="y\n")

    assert result.exit_code == 0
    assert "Cleaned up local ticket work" in result.output
    assert not worktree.exists()
    assert not local_branch_exists(repo, "feature/YT-123-add-cache")
    assert run_git_stdout(
        origin, "show-ref", "--verify", "refs/heads/feature/YT-123-add-cache"
    )
    state_path = state_dir / "product" / "YT-123.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["status"] == "cleaned-up"
    assert state["mr_url"] == "https://gitlab.example/mr/1"
    assert state["command_log"][-2:] == [
        f"git worktree remove {worktree}",
        "git branch -d feature/YT-123-add-cache",
    ]


def test_cleanup_marks_needs_attention_when_safe_branch_delete_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, worktree, _origin = make_cleanup_worktree(tmp_path)
    (worktree / "code.txt").write_text("implemented\n")
    run_git(worktree, "add", "code.txt")
    run_git(worktree, "commit", "-m", "Implement YT-123")
    state_dir = tmp_path / "state" / "ralph"
    config_path = tmp_path / "config.toml"
    write_config(
        build_single_repo_config(
            repo_path=repo,
            worktree_root=tmp_path / "worktrees",
            base_ref="origin/main",
            jira_project="YT",
            gitlab_project="group/product",
            repo_name="product",
        ),
        config_path,
    )
    write_run_state(
        run_state(
            "YT-123",
            "Add cache",
            worktree,
            "mr-created",
            repo_path=repo,
            mr_url="https://gitlab.example/mr/1",
        ),
        state_dir=state_dir,
    )
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(app, ["cleanup", "YT-123"], input="y\n")

    assert result.exit_code == 1
    assert "Cleanup needs manual attention" in result.output
    assert "Could not delete local branch feature/YT-123-add-cache" in result.output
    assert not worktree.exists()
    assert local_branch_exists(repo, "feature/YT-123-add-cache")
    state = json.loads((state_dir / "product" / "YT-123.json").read_text())
    assert state["status"] == "needs-attention"
    assert "Could not delete local branch" in state["error"]


def test_init_writes_config_without_modifying_product_repo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = make_git_repo(tmp_path)
    worktree_root = tmp_path / "product-worktrees"
    config_path = tmp_path / "config" / "ralph" / "config.toml"
    state_dir = tmp_path / "state" / "ralph"
    head_before = (repo / ".git" / "refs" / "heads" / "main").read_text()
    monkeypatch.setattr("ralph.cli.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("ralph.cli.DEFAULT_STATE_DIR", state_dir)

    result = runner.invoke(
        app,
        ["init"],
        input=f"{repo}\n{worktree_root}\n\nYT\ny\n",
    )

    assert result.exit_code == 0
    assert config_path.exists()
    assert state_dir.exists()
    assert worktree_root.exists()
    assert (repo / ".git" / "refs" / "heads" / "main").read_text() == head_before

    config = load_config(config_path)
    repo_config = config.repos["product"]
    assert repo_config.repo_path == repo
    assert repo_config.worktree_root == worktree_root
    assert repo_config.base_ref == "origin/main"
    assert repo_config.git_remote == "origin"
    assert repo_config.jira_project == "YT"
    assert repo_config.gitlab_project == "group/product"


def run_state(
    ticket_key: str,
    summary: str,
    worktree_path: Path,
    status: str,
    *,
    base_sha: str = "abc123",
    repo_path: Path = Path("/workspace/product"),
    mr_url: str | None = None,
) -> RunState:
    ticket = Ticket(
        key=ticket_key,
        summary=summary,
        description=f"{summary}.",
        issue_type="Task",
        status="To Do",
    )
    return RunState(
        ticket_key=ticket.key,
        ticket=ticket,
        repo_name="product",
        repo_path=repo_path,
        worktree_path=worktree_path,
        branch_name=f"feature/{ticket.key}-{summary.lower().replace(' ', '-')}",
        base_ref="origin/main",
        base_sha=base_sha,
        status=status,
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 3, 5, 6, tzinfo=UTC),
        mr_url=mr_url,
    )


def make_finish_worktree(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = make_git_repo(tmp_path)
    (repo / ".gitignore").write_text(".agent/\n")
    run_git(repo, "add", ".gitignore")
    run_git(repo, "commit", "-m", "Ignore agent files")
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(repo, "remote", "set-url", "origin", str(origin))
    run_git(repo, "push", "-u", "origin", "main")
    base_sha = run_git_stdout(repo, "rev-parse", "HEAD").strip()
    worktree = tmp_path / "worktrees" / "feature__YT-123-add-cache"
    worktree.parent.mkdir()
    run_git(
        repo,
        "worktree",
        "add",
        "-b",
        "feature/YT-123-add-cache",
        str(worktree),
        "main",
    )
    (worktree / "code.txt").write_text("implemented\n")
    run_git(worktree, "add", "code.txt")
    run_git(worktree, "commit", "-m", "Implement YT-123")
    agent_dir = worktree / ".agent"
    agent_dir.mkdir()
    (agent_dir / "mr_title.md").write_text("YT-123: Add cache\n")
    (agent_dir / "mr_description.md").write_text(
        "Ticket: YT-123\n\nVerification: pytest\n"
    )
    return repo, worktree, origin, base_sha


def make_cleanup_worktree(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = make_git_repo(tmp_path)
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(repo, "remote", "set-url", "origin", str(origin))
    run_git(repo, "push", "-u", "origin", "main")
    worktree = tmp_path / "worktrees" / "feature__YT-123-add-cache"
    worktree.parent.mkdir()
    run_git(
        repo,
        "worktree",
        "add",
        "-b",
        "feature/YT-123-add-cache",
        str(worktree),
        "main",
    )
    return repo, worktree, origin


def fake_glab(tmp_path: Path, *, list_json: str, create_output: str) -> Path:
    script = tmp_path / "fake_glab.py"
    script.write_text(
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['mr', 'list']:\n"
        f"    print({list_json!r})\n"
        "elif args[:2] == ['mr', 'create']:\n"
        f"    pathlib.Path({str(tmp_path / 'glab-created')!r}).write_text('yes')\n"
        f"    print({create_output!r}, end='')\n"
        "else:\n"
        "    raise SystemExit(2)\n"
    )
    return script


def run_git_stdout(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def jira_ticket_json() -> dict:
    return {
        "key": "YT-123",
        "self": "https://jira.example/browse/YT-123",
        "fields": {
            "summary": "Add cache",
            "description": "Cache the summary.",
            "issuetype": {"name": "Task"},
            "status": {"name": "To Do"},
            "issuelinks": [],
        },
    }
