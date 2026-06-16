from pathlib import Path

from typer.testing import CliRunner

from ralph import __version__
from ralph.cli import app
from ralph.config import build_single_repo_config, load_config, write_config
from ralph.doctor import DoctorCheck
from tests.test_config import make_git_repo

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
    assert "No files were written." in result.output


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
