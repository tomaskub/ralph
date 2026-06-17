import json
import sys
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


def test_unimplemented_commands_fail_clearly() -> None:
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 2
    assert "ralph status is not implemented yet" in result.output


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
