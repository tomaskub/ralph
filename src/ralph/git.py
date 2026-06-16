"""Git-related planning and validation helpers."""

from pathlib import Path


def worktree_path_for_branch(worktree_root: Path, branch_name: str) -> Path:
    return worktree_root / branch_name.replace("/", "__")

