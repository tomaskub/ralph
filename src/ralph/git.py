"""Git-related planning and validation helpers."""

import re
import unicodedata
from pathlib import Path
from typing import Literal

from ralph.models import Ticket
from ralph.runner import CommandRunner

MAX_BRANCH_LENGTH = 80
WorktreeState = Literal["missing", "clean", "dirty"]


def worktree_path_for_branch(worktree_root: Path, branch_name: str) -> Path:
    return worktree_root / branch_name.replace("/", "__")


def branch_name_for_ticket(ticket: Ticket, branch_kind: str) -> str:
    slug = _slugify(ticket.summary)
    branch = f"{branch_kind}/{ticket.key}-{slug}"
    return branch[:MAX_BRANCH_LENGTH].rstrip("-")


def resolve_ref_sha(
    repo_path: Path,
    ref: str,
    *,
    runner: CommandRunner | None = None,
) -> str:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo_path,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Base ref does not resolve to a commit: {ref}{suffix}")
    return result.stdout.strip()


def fetch_remote(
    repo_path: Path,
    remote: str,
    *,
    runner: CommandRunner | None = None,
) -> None:
    runner = runner or CommandRunner()
    result = runner.run(["git", "fetch", remote], cwd=repo_path)
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not fetch {remote}{suffix}")


def add_worktree(
    repo_path: Path,
    worktree_path: Path,
    branch_name: str,
    base_ref: str,
    *,
    runner: CommandRunner | None = None,
) -> None:
    runner = runner or CommandRunner()
    result = runner.run(
        [
            "git",
            "worktree",
            "add",
            "--no-track",
            "-b",
            branch_name,
            str(worktree_path),
            base_ref,
        ],
        cwd=repo_path,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not create worktree {worktree_path}{suffix}")


def ensure_agent_dir_ignored(
    worktree_path: Path,
    agent_files_directory: str = ".agent",
    *,
    runner: CommandRunner | None = None,
) -> None:
    runner = runner or CommandRunner()
    ignored_path = f"{agent_files_directory}/test"
    result = runner.run(["git", "check-ignore", ignored_path], cwd=worktree_path)
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"{agent_files_directory}/ is not ignored by Git" + suffix)


def worktree_state(
    worktree_path: Path,
    *,
    runner: CommandRunner | None = None,
) -> WorktreeState:
    if not worktree_path.exists():
        return "missing"

    runner = runner or CommandRunner()
    result = runner.run(["git", "status", "--porcelain"], cwd=worktree_path)
    if result.returncode != 0:
        return "dirty"
    return "dirty" if result.stdout.strip() else "clean"


def local_branch_exists(
    repo_path: Path,
    branch_name: str,
    *,
    runner: CommandRunner | None = None,
) -> bool:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=repo_path,
    )
    return result.returncode == 0


def remote_branch_exists(
    repo_path: Path,
    remote: str,
    branch_name: str,
    *,
    runner: CommandRunner | None = None,
) -> bool:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "ls-remote", "--exit-code", remote, f"refs/heads/{branch_name}"],
        cwd=repo_path,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 2:
        return False
    detail = result.stderr.strip()
    suffix = f": {detail}" if detail else ""
    raise GitPlanError(
        f"Could not check remote branch {remote}/{branch_name}{suffix}"
    )


def current_branch(
    worktree_path: Path,
    *,
    runner: CommandRunner | None = None,
) -> str:
    runner = runner or CommandRunner()
    result = runner.run(["git", "branch", "--show-current"], cwd=worktree_path)
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not determine current branch{suffix}")
    return result.stdout.strip()


def commits_ahead_count(
    worktree_path: Path,
    base_ref: str,
    *,
    runner: CommandRunner | None = None,
) -> int:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "rev-list", "--count", f"{base_ref}..HEAD"],
        cwd=worktree_path,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not count commits ahead of {base_ref}{suffix}")
    return int(result.stdout.strip())


def committed_paths(
    worktree_path: Path,
    base_ref: str,
    *,
    runner: CommandRunner | None = None,
) -> list[str]:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "diff", "--name-only", f"{base_ref}..HEAD"],
        cwd=worktree_path,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not inspect committed diff{suffix}")
    return [line for line in result.stdout.splitlines() if line]


def upstream_name(
    worktree_path: Path,
    *,
    runner: CommandRunner | None = None,
) -> str | None:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=worktree_path,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def upstream_divergence(
    worktree_path: Path,
    upstream: str,
    *,
    runner: CommandRunner | None = None,
) -> tuple[int, int]:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "rev-list", "--left-right", "--count", f"{upstream}...HEAD"],
        cwd=worktree_path,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not compare upstream {upstream}{suffix}")
    behind, ahead = result.stdout.strip().split()
    return int(behind), int(ahead)


def push_branch(
    worktree_path: Path,
    remote: str,
    branch_name: str,
    *,
    has_upstream: bool,
    runner: CommandRunner | None = None,
) -> None:
    runner = runner or CommandRunner()
    args = (
        ["git", "push"]
        if has_upstream
        else ["git", "push", "-u", remote, branch_name]
    )
    result = runner.run(args, cwd=worktree_path)
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not push branch {branch_name}{suffix}")


def remove_worktree(
    repo_path: Path,
    worktree_path: Path,
    *,
    runner: CommandRunner | None = None,
) -> None:
    runner = runner or CommandRunner()
    result = runner.run(
        ["git", "worktree", "remove", str(worktree_path)],
        cwd=repo_path,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not remove worktree {worktree_path}{suffix}")


def delete_local_branch(
    repo_path: Path,
    branch_name: str,
    *,
    runner: CommandRunner | None = None,
) -> None:
    runner = runner or CommandRunner()
    result = runner.run(["git", "branch", "-d", branch_name], cwd=repo_path)
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not delete local branch {branch_name}{suffix}")


class GitPlanError(RuntimeError):
    """Raised when read-only Git planning checks fail."""


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "ticket"
