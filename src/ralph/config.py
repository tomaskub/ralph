"""Configuration loading and validation primitives."""

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.config/ralph/config.toml").expanduser()


@dataclass(frozen=True)
class ToolConfig:
    jira: str = "jira"
    gitlab: str = "glab"
    agent: str = "claude"


@dataclass(frozen=True)
class RepoConfig:
    name: str
    repo_path: Path
    worktree_root: Path
    base_ref: str = "origin/main"
    git_remote: str = "origin"
    jira_project: str = ""
    gitlab_project: str = ""


@dataclass(frozen=True)
class RalphConfig:
    default_repo: str
    repos: dict[str, RepoConfig]
    tools: ToolConfig = field(default_factory=ToolConfig)
    branch_kinds: dict[str, str] = field(
        default_factory=lambda: {
            "Task": "feature",
            "Story": "feature",
            "Bug": "bugfix",
        }
    )

