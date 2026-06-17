from pathlib import Path

from ralph.config import RalphConfig, ToolConfig, build_single_repo_config
from ralph.doctor import run_doctor_checks
from ralph.runner import CommandResult


def test_doctor_accepts_configured_tools_repo_and_ignore_rule(tmp_path: Path) -> None:
    repo = tmp_path / "product"
    repo.mkdir()
    worktree_root = tmp_path / "worktrees"
    config = config_for(repo, worktree_root)
    runner = FakeRunner(
        {
            ("jira", "me"): CommandResult(("jira", "me"), 0, "you@example.com\n", ""),
            ("glab", "auth", "status"): CommandResult(
                ("glab", "auth", "status"),
                0,
                "Logged in\n",
                "",
            ),
            ("git", "rev-parse", "--git-dir"): CommandResult(
                ("git", "rev-parse", "--git-dir"),
                0,
                ".git\n",
                "",
            ),
            ("git", "rev-parse", "--verify", "origin/main^{commit}"): CommandResult(
                ("git", "rev-parse", "--verify", "origin/main^{commit}"),
                0,
                "abc123\n",
                "",
            ),
            ("git", "check-ignore", ".agent/test"): CommandResult(
                ("git", "check-ignore", ".agent/test"),
                0,
                ".agent/test\n",
                "",
            ),
        }
    )

    checks = run_doctor_checks(
        config,
        runner=runner,
        which=lambda command: f"/usr/bin/{command}",
    )

    assert all(check.ok for check in checks)
    assert [check.name for check in checks] == [
        "git installed",
        "Jira CLI installed",
        "GitLab CLI installed",
        "agent command installed",
        "Jira authentication",
        "GitLab authentication",
        "repo path",
        "Git repository",
        "base ref",
        "worktree root",
        ".agent ignore rule",
    ]
    assert runner.cwd_by_args[("git", "check-ignore", ".agent/test")] == repo


def test_doctor_reports_actionable_failures(tmp_path: Path) -> None:
    repo = tmp_path / "product"
    repo.mkdir()
    config = config_for(repo, tmp_path / "missing" / "worktrees")
    runner = FakeRunner(
        {
            ("glab", "auth", "status"): CommandResult(
                ("glab", "auth", "status"),
                1,
                "",
                "not logged in\n",
            ),
            ("git", "rev-parse", "--git-dir"): CommandResult(
                ("git", "rev-parse", "--git-dir"),
                0,
                ".git\n",
                "",
            ),
            ("git", "rev-parse", "--verify", "origin/main^{commit}"): CommandResult(
                ("git", "rev-parse", "--verify", "origin/main^{commit}"),
                1,
                "",
                "unknown revision\n",
            ),
            ("git", "check-ignore", ".agent/test"): CommandResult(
                ("git", "check-ignore", ".agent/test"),
                1,
                "",
                "",
            ),
        }
    )

    checks = run_doctor_checks(
        config,
        runner=runner,
        which=lambda command: None if command in {"jira", "claude"} else command,
    )

    failed = {check.name: check for check in checks if not check.ok}
    assert failed["Jira CLI installed"].action == "Install jira or update config"
    assert failed["agent command installed"].action == "Install claude or update config"
    assert failed["GitLab authentication"].action == "Run `glab auth login`"
    assert failed["base ref"].action == (
        "Fetch or configure a valid base_ref, currently origin/main"
    )
    assert failed["worktree root"].action == (
        f"Create {tmp_path / 'missing'} or update worktree_root in config"
    )
    assert failed[".agent ignore rule"].action == (
        "Add `.agent/` to the product repo ignore rules"
    )


def config_for(repo: Path, worktree_root: Path) -> RalphConfig:
    config = build_single_repo_config(
        repo_path=repo,
        worktree_root=worktree_root,
        base_ref="origin/main",
        jira_project="YT",
        gitlab_project="group/product",
        repo_name="product",
    )
    return RalphConfig(
        default_repo=config.default_repo,
        repos=config.repos,
        tools=ToolConfig(jira="jira", gitlab="glab", agent="claude"),
        jira=config.jira,
        branch_kinds=config.branch_kinds,
    )


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], CommandResult]) -> None:
        self.results = results
        self.cwd_by_args: dict[tuple[str, ...], Path | None] = {}

    def run(self, args, cwd=None) -> CommandResult:
        key = tuple(args)
        self.cwd_by_args[key] = cwd
        return self.results[key]
