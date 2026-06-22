"""Configuration loading, writing, and validation primitives."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ralph.runner import CommandRunner

DEFAULT_CONFIG_PATH = Path("~/.config/ralph/config.toml").expanduser()
DEFAULT_STATE_DIR = Path("~/.local/state/ralph").expanduser()
DEFAULT_BASE_REF = "origin/main"
DEFAULT_GIT_REMOTE = "origin"
DEFAULT_AGENT_FILES_DIRECTORY = ".agent"


@dataclass(frozen=True)
class ToolConfig:
    jira: str = "jira"
    gitlab: str = "glab"
    agent: str = "claude"


@dataclass(frozen=True)
class JiraConfig:
    issue_json_command: str = "jira issue view {ticket} --raw"


@dataclass(frozen=True)
class AgentFilesConfig:
    directory: str = DEFAULT_AGENT_FILES_DIRECTORY

    def __post_init__(self) -> None:
        validate_agent_files_directory(self.directory)


@dataclass(frozen=True)
class RepoConfig:
    name: str
    repo_path: Path
    worktree_root: Path
    base_ref: str = DEFAULT_BASE_REF
    git_remote: str = DEFAULT_GIT_REMOTE
    jira_project: str = ""
    gitlab_project: str = ""


@dataclass(frozen=True)
class RalphConfig:
    default_repo: str
    repos: dict[str, RepoConfig]
    agent_files: AgentFilesConfig = field(default_factory=AgentFilesConfig)
    tools: ToolConfig = field(default_factory=ToolConfig)
    jira: JiraConfig = field(default_factory=JiraConfig)
    branch_kinds: dict[str, str] = field(
        default_factory=lambda: {
            "Task": "feature",
            "Story": "feature",
            "Bug": "bugfix",
        }
    )


class ConfigError(ValueError):
    """Raised when local configuration is missing or invalid."""


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> RalphConfig:
    if not path.exists():
        raise ConfigError(f"Config file does not exist: {path}")

    data = tomllib.loads(path.read_text())
    try:
        default_repo = data["default_repo"]
        repos_data = data["repos"]
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {exc.args[0]}") from exc

    repos = {
        name: _repo_config_from_toml(name, repo_data)
        for name, repo_data in repos_data.items()
    }
    if default_repo not in repos:
        raise ConfigError(f"default_repo {default_repo!r} is not configured")

    tools_data = data.get("tools", {})
    tools = ToolConfig(
        jira=tools_data.get("jira", ToolConfig.jira),
        gitlab=tools_data.get("gitlab", ToolConfig.gitlab),
        agent=tools_data.get("agent", ToolConfig.agent),
    )
    jira_data = data.get("jira", {})
    jira = JiraConfig(
        issue_json_command=str(
            jira_data.get("issue_json_command", JiraConfig.issue_json_command)
        )
    )
    agent_files_data = data.get("agent_files", {})
    agent_files = AgentFilesConfig(
        directory=str(
            agent_files_data.get("directory", DEFAULT_AGENT_FILES_DIRECTORY)
        )
    )

    return RalphConfig(
        default_repo=default_repo,
        repos=repos,
        agent_files=agent_files,
        tools=tools,
        jira=jira,
        branch_kinds=data.get(
            "branch_kinds",
            {
                "Task": "feature",
                "Story": "feature",
                "Bug": "bugfix",
            },
        ),
    )


def write_config(config: RalphConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_to_toml(config))


def config_to_toml(config: RalphConfig) -> str:
    lines = [
        f'default_repo = "{_toml_escape(config.default_repo)}"',
        "",
    ]
    for name, repo in config.repos.items():
        lines.extend(
            [
                f"[repos.{_toml_key(name)}]",
                f'repo_path = "{_toml_escape(_path_to_config_value(repo.repo_path))}"',
                (
                    'worktree_root = '
                    f'"{_toml_escape(_path_to_config_value(repo.worktree_root))}"'
                ),
                f'base_ref = "{_toml_escape(repo.base_ref)}"',
                f'git_remote = "{_toml_escape(repo.git_remote)}"',
                f'jira_project = "{_toml_escape(repo.jira_project)}"',
                f'gitlab_project = "{_toml_escape(repo.gitlab_project)}"',
                "",
            ]
        )

    lines.extend(
        [
            "[agent_files]",
            f'directory = "{_toml_escape(config.agent_files.directory)}"',
            "",
            "[tools]",
            f'jira = "{_toml_escape(config.tools.jira)}"',
            f'gitlab = "{_toml_escape(config.tools.gitlab)}"',
            f'agent = "{_toml_escape(config.tools.agent)}"',
            "",
            "[jira]",
            (
                'issue_json_command = '
                f'"{_toml_escape(config.jira.issue_json_command)}"'
            ),
            "",
            "[branch_kinds]",
        ]
    )
    for issue_type, branch_kind in config.branch_kinds.items():
        lines.append(f'{_toml_key(issue_type)} = "{_toml_escape(branch_kind)}"')
    lines.append("")
    return "\n".join(lines)


def build_single_repo_config(
    *,
    repo_path: Path,
    worktree_root: Path,
    base_ref: str,
    jira_project: str,
    gitlab_project: str,
    repo_name: str | None = None,
) -> RalphConfig:
    repo_path = _normalize_config_path(repo_path)
    worktree_root = _normalize_config_path(worktree_root)
    name = repo_name or repo_path.name
    repo = RepoConfig(
        name=name,
        repo_path=repo_path,
        worktree_root=worktree_root,
        base_ref=base_ref or DEFAULT_BASE_REF,
        git_remote=DEFAULT_GIT_REMOTE,
        jira_project=jira_project,
        gitlab_project=gitlab_project,
    )
    return RalphConfig(default_repo=name, repos={name: repo})


def validate_agent_files_directory(directory: str) -> None:
    if directory == "":
        raise ConfigError("agent_files.directory must not be empty")
    path = Path(directory)
    if path.is_absolute():
        raise ConfigError("agent_files.directory must be a relative directory name")
    if (
        path.name != directory
        or "\\" in directory
        or any(part == ".." for part in path.parts)
    ):
        raise ConfigError(
            "agent_files.directory must be one relative directory name without "
            "path separators or parent-directory traversal"
        )


def validate_init_inputs(
    *,
    repo_path: Path,
    worktree_root: Path,
    base_ref: str,
    runner: CommandRunner | None = None,
) -> list[str]:
    runner = runner or CommandRunner()
    errors: list[str] = []
    repo_path = _normalize_config_path(repo_path)
    worktree_root = _normalize_config_path(worktree_root)

    if not base_ref:
        errors.append("Base ref is required")
    if not str(worktree_root):
        errors.append("Worktree root is required")

    if not repo_path.exists():
        errors.append(f"Repo path does not exist: {repo_path}")
        return errors
    if not repo_path.is_dir():
        errors.append(f"Repo path is not a directory: {repo_path}")
        return errors

    git_dir = runner.run(["git", "rev-parse", "--git-dir"], cwd=repo_path)
    if git_dir.returncode != 0:
        errors.append(f"Repo path is not a Git repository: {repo_path}")
        return errors

    if base_ref:
        resolved_base = runner.run(
            ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
            cwd=repo_path,
        )
        if resolved_base.returncode != 0:
            errors.append(f"Base ref does not resolve to a commit: {base_ref}")

    if worktree_root.exists() and not worktree_root.is_dir():
        errors.append(f"Worktree root exists but is not a directory: {worktree_root}")
    else:
        parent = worktree_root if worktree_root.exists() else worktree_root.parent
        if not parent.exists():
            errors.append(f"Worktree root parent does not exist: {parent}")
        elif not parent.is_dir():
            errors.append(f"Worktree root parent is not a directory: {parent}")

    return errors


def derive_gitlab_project(
    repo_path: Path,
    *,
    remote: str = DEFAULT_GIT_REMOTE,
    runner: CommandRunner | None = None,
) -> str | None:
    runner = runner or CommandRunner()
    result = runner.run(["git", "remote", "get-url", remote], cwd=repo_path)
    if result.returncode != 0:
        return None
    return gitlab_project_from_remote_url(result.stdout.strip())


def derive_gitlab_host(
    repo_path: Path,
    *,
    remote: str = DEFAULT_GIT_REMOTE,
    runner: CommandRunner | None = None,
) -> str | None:
    runner = runner or CommandRunner()
    result = runner.run(["git", "remote", "get-url", remote], cwd=repo_path)
    if result.returncode != 0:
        return None
    return gitlab_host_from_remote_url(result.stdout.strip())


def gitlab_project_from_remote_url(remote_url: str) -> str | None:
    if not remote_url:
        return None

    scp_like = re.match(r"^[^@]+@[^:]+:(?P<path>.+)$", remote_url)
    if scp_like:
        return _clean_git_remote_path(scp_like.group("path"))

    protocol = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/]+/(?P<path>.+)$", remote_url)
    if protocol:
        return _clean_git_remote_path(protocol.group("path"))

    return None


def gitlab_host_from_remote_url(remote_url: str) -> str | None:
    if not remote_url:
        return None

    scp_like = re.match(r"^[^@]+@(?P<host>[^:]+):.+$", remote_url)
    if scp_like:
        return scp_like.group("host")

    protocol = re.match(
        r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/.+$",
        remote_url,
    )
    if protocol:
        return protocol.group("host")

    return None


def _repo_config_from_toml(name: str, data: dict[str, object]) -> RepoConfig:
    required = ["repo_path", "worktree_root"]
    for key in required:
        if key not in data:
            raise ConfigError(f"Missing required repo key for {name}: {key}")

    return RepoConfig(
        name=name,
        repo_path=_normalize_config_path(Path(str(data["repo_path"]))),
        worktree_root=_normalize_config_path(Path(str(data["worktree_root"]))),
        base_ref=str(data.get("base_ref", DEFAULT_BASE_REF)),
        git_remote=str(data.get("git_remote", DEFAULT_GIT_REMOTE)),
        jira_project=str(data.get("jira_project", "")),
        gitlab_project=str(data.get("gitlab_project", "")),
    )


def _normalize_config_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _path_to_config_value(path: Path) -> str:
    return str(path)


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_key(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return f'"{_toml_escape(value)}"'


def _clean_git_remote_path(path: str) -> str | None:
    cleaned = path.removesuffix(".git").strip("/")
    return cleaned or None
