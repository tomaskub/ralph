"""Read-only readiness checks for the local RALPH environment."""

import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ralph.config import RalphConfig, RepoConfig
from ralph.runner import CommandRunner


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    action: str | None = None


def run_doctor_checks(
    config: RalphConfig,
    *,
    runner: CommandRunner | None = None,
    which: Callable[[str], str | None] | None = None,
) -> list[DoctorCheck]:
    """Run read-only checks for configured tools and the default repo."""
    runner = runner or CommandRunner()
    which = which or shutil.which
    repo = config.repos[config.default_repo]

    checks: list[DoctorCheck] = []
    checks.extend(_tool_checks(config, which=which))
    checks.extend(_auth_checks(config, runner=runner, which=which))
    checks.extend(_repo_checks(repo, runner=runner))
    return checks


def _tool_checks(
    config: RalphConfig,
    *,
    which: Callable[[str], str | None],
) -> list[DoctorCheck]:
    tools = {
        "git": "git",
        "Jira CLI": config.tools.jira,
        "GitLab CLI": config.tools.gitlab,
        "agent command": config.tools.agent,
    }
    checks: list[DoctorCheck] = []
    for label, command in tools.items():
        executable = _executable_name(command)
        path = which(executable) if executable else None
        checks.append(
            DoctorCheck(
                name=f"{label} installed",
                ok=path is not None,
                detail=path or f"{executable or command} not found on PATH",
                action=(
                    None
                    if path
                    else f"Install {executable or command} or update config"
                ),
            )
        )
    return checks


def _auth_checks(
    config: RalphConfig,
    *,
    runner: CommandRunner,
    which: Callable[[str], str | None],
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    jira = _executable_name(config.tools.jira)
    if jira and which(jira):
        checks.append(
            _command_check(
                "Jira authentication",
                [jira, "me"],
                runner=runner,
                action=f"Run `{jira} login` or check Jira CLI authentication",
            )
        )

    gitlab = _executable_name(config.tools.gitlab)
    if gitlab and which(gitlab):
        checks.append(
            _command_check(
                "GitLab authentication",
                [gitlab, "auth", "status"],
                runner=runner,
                action=f"Run `{gitlab} auth login`",
            )
        )
    return checks


def _repo_checks(repo: RepoConfig, *, runner: CommandRunner) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    repo_path = repo.repo_path.expanduser()
    worktree_root = repo.worktree_root.expanduser()

    if not repo_path.exists():
        return [
            DoctorCheck(
                name="repo path",
                ok=False,
                detail=f"{repo_path} does not exist",
                action="Update repo_path in ~/.config/ralph/config.toml",
            )
        ]
    if not repo_path.is_dir():
        return [
            DoctorCheck(
                name="repo path",
                ok=False,
                detail=f"{repo_path} is not a directory",
                action="Update repo_path in ~/.config/ralph/config.toml",
            )
        ]

    checks.append(
        DoctorCheck(name="repo path", ok=True, detail=str(repo_path), action=None)
    )
    checks.append(
        _command_check(
            "Git repository",
            ["git", "rev-parse", "--git-dir"],
            runner=runner,
            cwd=repo_path,
            action=f"Initialize a Git repository at {repo_path} or update config",
        )
    )
    checks.append(
        _command_check(
            "base ref",
            ["git", "rev-parse", "--verify", f"{repo.base_ref}^{{commit}}"],
            runner=runner,
            cwd=repo_path,
            action=f"Fetch or configure a valid base_ref, currently {repo.base_ref}",
        )
    )
    checks.append(_worktree_root_check(worktree_root))
    checks.append(
        _command_check(
            ".agent ignore rule",
            ["git", "check-ignore", ".agent/test"],
            runner=runner,
            cwd=repo_path,
            action="Add `.agent/` to the product repo ignore rules",
        )
    )
    return checks


def _worktree_root_check(worktree_root: Path) -> DoctorCheck:
    if worktree_root.exists():
        if worktree_root.is_dir():
            return DoctorCheck(
                name="worktree root",
                ok=True,
                detail=str(worktree_root),
                action=None,
            )
        return DoctorCheck(
            name="worktree root",
            ok=False,
            detail=f"{worktree_root} exists but is not a directory",
            action="Update worktree_root in ~/.config/ralph/config.toml",
        )

    parent = worktree_root.parent
    if parent.exists() and parent.is_dir():
        return DoctorCheck(
            name="worktree root",
            ok=True,
            detail=f"{worktree_root} can be created",
            action=None,
        )
    return DoctorCheck(
        name="worktree root",
        ok=False,
        detail=f"parent does not exist: {parent}",
        action=f"Create {parent} or update worktree_root in config",
    )


def _command_check(
    name: str,
    args: list[str],
    *,
    runner: CommandRunner,
    cwd: Path | None = None,
    action: str,
) -> DoctorCheck:
    result = runner.run(args, cwd=cwd)
    detail = (result.stdout or result.stderr).strip().splitlines()
    return DoctorCheck(
        name=name,
        ok=result.returncode == 0,
        detail=detail[0] if detail else ("ok" if result.returncode == 0 else "failed"),
        action=None if result.returncode == 0 else action,
    )


def _executable_name(command: str) -> str:
    parts = shlex.split(command)
    return parts[0] if parts else ""
