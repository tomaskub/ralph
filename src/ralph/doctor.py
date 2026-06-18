"""Read-only readiness checks for the local RALPH environment."""

import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ralph.config import RalphConfig, RepoConfig, derive_gitlab_host
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
    checks.extend(_auth_checks(config, repo=repo, runner=runner, which=which))
    checks.extend(
        _repo_checks(
            repo,
            agent_files_directory=config.agent_files.directory,
            runner=runner,
        )
    )
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
    repo: RepoConfig,
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
        hostname = _configured_gitlab_hostname(repo, runner=runner)
        args = [gitlab, "auth", "status"]
        action = f"Run `{gitlab} auth login`"
        if hostname:
            args.extend(["--hostname", hostname])
            action = f"Run `{gitlab} auth login --hostname {hostname}`"
        checks.append(
            _command_check(
                "GitLab authentication",
                args,
                runner=runner,
                action=action,
            )
        )
    return checks


def _configured_gitlab_hostname(
    repo: RepoConfig,
    *,
    runner: CommandRunner,
) -> str | None:
    repo_path = repo.repo_path.expanduser()
    if not repo_path.exists() or not repo_path.is_dir():
        return None
    return derive_gitlab_host(repo_path, remote=repo.git_remote, runner=runner)


def _repo_checks(
    repo: RepoConfig,
    *,
    agent_files_directory: str,
    runner: CommandRunner,
) -> list[DoctorCheck]:
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
    agent_files_probe = f"{agent_files_directory}/test"
    checks.append(
        _command_check(
            f"{agent_files_directory} ignore rule",
            ["git", "check-ignore", agent_files_probe],
            runner=runner,
            cwd=repo_path,
            action=(
                "Run `ralph setup-ignore` to add the agent files directory "
                "to Git global excludes"
            ),
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
