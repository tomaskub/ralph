import subprocess
from pathlib import Path

from ralph.config import (
    DEFAULT_BASE_REF,
    build_single_repo_config,
    config_to_toml,
    derive_gitlab_project,
    gitlab_project_from_remote_url,
    load_config,
    validate_init_inputs,
    write_config,
)


def test_load_config_reads_single_default_repo(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = build_single_repo_config(
        repo_path=Path("~/workspace/product"),
        worktree_root=Path("~/workspace/product-worktrees"),
        base_ref=DEFAULT_BASE_REF,
        jira_project="YT",
        gitlab_project="group/product",
        repo_name="product",
    )

    write_config(config, config_path)

    loaded = load_config(config_path)
    repo = loaded.repos["product"]
    assert loaded.default_repo == "product"
    assert repo.repo_path == Path("~/workspace/product").expanduser()
    assert repo.worktree_root == Path("~/workspace/product-worktrees").expanduser()
    assert repo.base_ref == "origin/main"
    assert repo.git_remote == "origin"
    assert repo.jira_project == "YT"
    assert repo.gitlab_project == "group/product"
    assert loaded.jira.issue_json_command == "jira issue view {ticket} --format json"


def test_config_to_toml_contains_expected_single_repo_shape() -> None:
    config = build_single_repo_config(
        repo_path=Path("/workspace/product"),
        worktree_root=Path("/workspace/product-worktrees"),
        base_ref="origin/main",
        jira_project="YT",
        gitlab_project="group/product",
        repo_name="product",
    )

    rendered = config_to_toml(config)

    assert 'default_repo = "product"' in rendered
    assert "[repos.product]" in rendered
    assert 'repo_path = "/workspace/product"' in rendered
    assert 'worktree_root = "/workspace/product-worktrees"' in rendered
    assert 'git_remote = "origin"' in rendered
    assert "[tools]" in rendered
    assert "[jira]" in rendered
    assert 'issue_json_command = "jira issue view {ticket} --format json"' in rendered
    assert "[branch_kinds]" in rendered


def test_validate_init_inputs_accepts_git_repo_base_ref_and_creatable_worktree(
    tmp_path: Path,
) -> None:
    repo = make_git_repo(tmp_path)
    worktree_root = tmp_path / "product-worktrees"

    errors = validate_init_inputs(
        repo_path=repo,
        worktree_root=worktree_root,
        base_ref="origin/main",
    )

    assert errors == []


def test_validate_init_inputs_rejects_missing_base_ref(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)

    errors = validate_init_inputs(
        repo_path=repo,
        worktree_root=tmp_path / "product-worktrees",
        base_ref="origin/missing",
    )

    assert errors == ["Base ref does not resolve to a commit: origin/missing"]


def test_derive_gitlab_project_from_origin_remote(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)

    assert derive_gitlab_project(repo) == "group/product"


def test_gitlab_project_from_remote_url_supports_common_url_forms() -> None:
    assert (
        gitlab_project_from_remote_url("git@gitlab.com:group/product.git")
        == "group/product"
    )
    assert (
        gitlab_project_from_remote_url("https://gitlab.com/group/product.git")
        == "group/product"
    )


def make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "product"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.name", "Test User")
    run_git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("# Product\n")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "Initial commit")
    run_git(repo, "remote", "add", "origin", "git@gitlab.com:group/product.git")
    run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
