"""Command-line entry point for RALPH."""

import json
import re
import shlex
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ralph import __version__
from ralph.config import (
    DEFAULT_BASE_REF,
    DEFAULT_CONFIG_PATH,
    DEFAULT_STATE_DIR,
    ConfigError,
    build_single_repo_config,
    derive_gitlab_project,
    load_config,
    validate_init_inputs,
    write_config,
)
from ralph.doctor import DoctorCheck, run_doctor_checks
from ralph.git import (
    GitPlanError,
    add_worktree,
    branch_name_for_ticket,
    commits_ahead_count,
    committed_paths,
    current_branch,
    delete_local_branch,
    ensure_agent_dir_ignored,
    fetch_remote,
    local_branch_exists,
    push_branch,
    remote_branch_exists,
    remove_worktree,
    resolve_ref_sha,
    upstream_divergence,
    upstream_name,
    worktree_path_for_branch,
    worktree_state,
)
from ralph.jira import (
    JiraFetchError,
    branch_kind_for_ticket,
    fetch_ticket_json,
    normalize_ticket,
    validate_ticket,
)
from ralph.models import RunState, RunStatus, Ticket
from ralph.runner import CommandResult, CommandRunner
from ralph.state import (
    list_run_states,
    read_run_state,
    state_path,
    write_run_state,
)
from ralph.templates import render_template

app = typer.Typer(
    help="Local operator CLI for AI-agent ticket work loops.",
    invoke_without_command=True,
    no_args_is_help=True,
)
console = Console(width=160)
PACKAGE_NAME = "ralph-loop"
DEFAULT_INSTALL_REPO_URL = "https://github.com/tomaskub/ralph.git"
GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/tomaskub/ralph/releases/latest"
)
SEMVER_TAG_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class NotImplementedCommand(RuntimeError):
    """Raised when an MVP command surface exists before implementation."""


def fail_unimplemented(command: str) -> None:
    console.print(
        f"[bold red]ralph {command} is not implemented yet.[/bold red]\n"
        "This command is part of the MVP surface, but this slice only scaffolds "
        "the installable CLI foundation."
    )
    raise typer.Exit(code=2)


@app.callback()
def callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the installed RALPH version and exit.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Run RALPH."""
    if version:
        console.print(f"ralph {__version__}")
        raise typer.Exit()


@app.command()
def update(
    repo_url: Annotated[
        str,
        typer.Option(
            "--repo-url",
            help="Git repository URL to install RALPH from.",
        ),
    ] = DEFAULT_INSTALL_REPO_URL,
    tag: Annotated[
        str | None,
        typer.Option(
            "--tag",
            help="Install this exact Git tag instead of discovering the latest tag.",
        ),
    ] = None,
) -> None:
    """Update the installed RALPH CLI from the latest GitHub release tag."""
    runner = CommandRunner()
    selected_tag = tag or _discover_latest_install_tag(runner, repo_url)
    if selected_tag is None:
        console.print("[red]RALPH update failed.[/red]")
        console.print(
            "Could not find a stable semver GitHub release or tag, "
            "for example 0.1.0."
        )
        console.print(
            f"Install manually once a tag exists: pipx install --force "
            f"{shlex.quote(f'git+{repo_url}@<tag>')}"
        )
        raise typer.Exit(code=1)

    install_source = f"git+{repo_url}@{selected_tag}"
    args = ("pipx", "install", "--force", install_source)
    console.print(f"Updating RALPH with: {shlex.join(args)}")
    result = runner.run(args)
    if result.returncode != 0:
        console.print("[red]RALPH update failed.[/red]")
        output = result.stderr.strip() or result.stdout.strip()
        if output:
            console.print(output)
        console.print(f"Run manually: {shlex.join(args)}")
        raise typer.Exit(code=result.returncode)

    output = result.stdout.strip()
    if output:
        console.print(output)
    console.print(f"[green]RALPH is up to date at {selected_tag}.[/green]")


def _discover_latest_install_tag(
    runner: CommandRunner,
    repo_url: str,
) -> str | None:
    release_tag = _latest_github_release_tag()
    if release_tag and _semver_key(release_tag):
        return release_tag

    result = runner.run(("git", "ls-remote", "--tags", repo_url))
    if result.returncode != 0:
        output = result.stderr.strip() or result.stdout.strip()
        if output:
            console.print(output)
        return None

    return _latest_semver_tag(_tags_from_ls_remote(result.stdout))


def _latest_github_release_tag() -> str | None:
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": PACKAGE_NAME,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None

    tag_name = payload.get("tag_name")
    if isinstance(tag_name, str):
        return tag_name
    return None


def _tags_from_ls_remote(output: str) -> list[str]:
    tags: list[str] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
            continue
        tag = parts[1].removeprefix("refs/tags/").removesuffix("^{}")
        if tag not in tags:
            tags.append(tag)
    return tags


def _latest_semver_tag(tags: list[str]) -> str | None:
    semver_tags = [(key, tag) for tag in tags if (key := _semver_key(tag))]
    if not semver_tags:
        return None
    return max(semver_tags)[1]


def _semver_key(tag: str) -> tuple[int, int, int] | None:
    match = SEMVER_TAG_PATTERN.match(tag)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


@app.command()
def init() -> None:
    """Create local RALPH configuration."""
    repo_path = Path(
        typer.prompt("Product repo path", default=str(Path.cwd()))
    ).expanduser()
    worktree_root = Path(typer.prompt("Worktree root")).expanduser()
    base_ref = typer.prompt("Base ref", default=DEFAULT_BASE_REF)
    jira_project = typer.prompt("Jira project key").strip().upper()

    errors = validate_init_inputs(
        repo_path=repo_path,
        worktree_root=worktree_root,
        base_ref=base_ref,
    )
    if errors:
        for error in errors:
            console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1)

    gitlab_project = derive_gitlab_project(repo_path)
    if gitlab_project is None:
        gitlab_project = typer.prompt("GitLab project path").strip()

    if not worktree_root.exists():
        console.print(f"Worktree root will be created: {worktree_root}")
        if not typer.confirm("Create worktree root?", default=True):
            raise typer.Exit(code=1)
        worktree_root.mkdir(parents=True, exist_ok=True)

    DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    config = build_single_repo_config(
        repo_path=repo_path,
        worktree_root=worktree_root,
        base_ref=base_ref,
        jira_project=jira_project,
        gitlab_project=gitlab_project,
    )
    write_config(config, DEFAULT_CONFIG_PATH)
    console.print(f"[green]Wrote config:[/green] {DEFAULT_CONFIG_PATH}")


@app.command()
def doctor() -> None:
    """Validate local tools, configuration, and repository setup."""
    try:
        config = load_config(DEFAULT_CONFIG_PATH)
    except ConfigError as exc:
        console.print(f"[red]Config error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    checks = run_doctor_checks(config)
    _render_doctor_checks(checks)
    if any(not check.ok for check in checks):
        raise typer.Exit(code=1)


@app.command()
def start(
    ticket: Annotated[str, typer.Argument(help="Jira ticket key to start.")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Plan the run without writing anything."),
    ] = False,
    confirm_ambiguous_dependencies: Annotated[
        bool,
        typer.Option(
            "--confirm-ambiguous-dependencies",
            help=(
                "Proceed when Jira dependency information is unavailable "
                "or ambiguous."
            ),
        ),
    ] = False,
    allow_blocked: Annotated[
        bool,
        typer.Option(
            "--allow-blocked",
            help="Proceed even when Jira reports unresolved blockers.",
        ),
    ] = False,
) -> None:
    """Start an isolated ticket worktree and launch the configured agent."""
    config = load_config(DEFAULT_CONFIG_PATH)
    repo = config.repos[config.default_repo]
    if repo.jira_project and not ticket.startswith(f"{repo.jira_project}-"):
        console.print(
            f"[red]Ticket {ticket} is outside Jira project {repo.jira_project}[/red]"
        )
        raise typer.Exit(code=1)

    try:
        raw = fetch_ticket_json(
            ticket,
            issue_json_command=config.jira.issue_json_command,
        )
    except JiraFetchError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    normalized_ticket = normalize_ticket(raw)
    result = validate_ticket(
        normalized_ticket,
        repo=repo,
        branch_kinds=config.branch_kinds,
    )
    for error in result.errors:
        console.print(f"[red]{error}[/red]")

    if result.dependency.unresolved_blockers and not allow_blocked:
        blockers = ", ".join(
            f"{blocker.key} ({blocker.status or 'unknown status'})"
            for blocker in result.dependency.unresolved_blockers
        )
        console.print(f"[red]Ticket has unresolved blockers: {blockers}[/red]")

    if result.dependency.requires_confirmation and not confirm_ambiguous_dependencies:
        console.print(
            "[yellow]Dependency information requires manual confirmation: "
            f"{result.dependency.reason}[/yellow]"
        )

    dependency_blocked = (
        bool(result.dependency.unresolved_blockers) and not allow_blocked
    )
    dependency_blocked = dependency_blocked or (
        result.dependency.requires_confirmation
        and not confirm_ambiguous_dependencies
    )
    if result.errors or dependency_blocked:
        raise typer.Exit(code=1)

    branch_kind = branch_kind_for_ticket(normalized_ticket, config.branch_kinds)
    branch_name = branch_name_for_ticket(normalized_ticket, branch_kind)
    worktree_path = worktree_path_for_branch(repo.worktree_root, branch_name)

    if dry_run:
        try:
            base_sha = resolve_ref_sha(repo.repo_path, repo.base_ref)
            _check_start_availability(
                repo_path=repo.repo_path,
                worktree_path=worktree_path,
                remote=repo.git_remote,
                branch_name=branch_name,
            )
        except GitPlanError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        _render_start_dry_run(
            ticket=normalized_ticket,
            branch_name=branch_name,
            worktree_path=worktree_path,
            base_ref=repo.base_ref,
            base_sha=base_sha,
            jira_command=config.jira.issue_json_command.format(ticket=ticket),
            agent_command=config.tools.agent,
        )
        return

    try:
        fetch_remote(repo.repo_path, repo.git_remote)
        base_sha = resolve_ref_sha(repo.repo_path, repo.base_ref)
        _check_start_availability(
            repo_path=repo.repo_path,
            worktree_path=worktree_path,
            remote=repo.git_remote,
            branch_name=branch_name,
        )
        _start_real_run(
            ticket=normalized_ticket,
            repo_name=repo.name,
            repo_path=repo.repo_path,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=repo.base_ref,
            base_sha=base_sha,
            git_remote=repo.git_remote,
            agent_command=config.tools.agent,
        )
    except GitPlanError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command()
def status(
    include_cleaned_up: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Include cleaned-up runs.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Include base SHA and other verbose fields.",
        ),
    ] = False,
) -> None:
    """Show local RALPH runs."""
    try:
        config = load_config(DEFAULT_CONFIG_PATH)
    except ConfigError as exc:
        console.print(f"[red]Config error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    repo = config.repos[config.default_repo]
    runs = list_run_states(repo.name, state_dir=DEFAULT_STATE_DIR)
    if not include_cleaned_up:
        runs = [run for run in runs if run.status != "cleaned-up"]

    _render_status(runs, verbose=verbose)


@app.command()
def finish(ticket: Annotated[str, typer.Argument(help="Jira ticket key.")]) -> None:
    """Publish an already-committed branch as a draft GitLab MR."""
    try:
        config = load_config(DEFAULT_CONFIG_PATH)
    except ConfigError as exc:
        console.print(f"[red]Config error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    repo = config.repos[config.default_repo]
    path = state_path(DEFAULT_STATE_DIR, repo.name, ticket)
    if not path.exists():
        console.print(f"[red]No local state exists for {ticket}[/red]")
        raise typer.Exit(code=1)

    state = read_run_state(path)
    try:
        mr_url = _finish_run(state=state, gitlab_command=config.tools.gitlab)
    except GitPlanError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    updated = replace(
        state,
        status="mr-created",
        mr_url=mr_url,
        updated_at=_now(),
        command_log=[
            *state.command_log,
            f"git push {state.branch_name}",
            f"{config.tools.gitlab} mr create --draft",
        ],
        error=None,
    )
    state_file = write_run_state(updated, state_dir=DEFAULT_STATE_DIR)
    console.print("[green]Created draft GitLab MR.[/green]")
    console.print(f"MR: {mr_url}")
    console.print(f"State: {state_file}")


@app.command()
def cleanup(
    ticket: Annotated[str, typer.Argument(help="Jira ticket key.")],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Allow cleanup before an MR URL is recorded.",
        ),
    ] = False,
) -> None:
    """Remove local ticket work after MR creation or explicit force."""
    try:
        config = load_config(DEFAULT_CONFIG_PATH)
    except ConfigError as exc:
        console.print(f"[red]Config error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    repo = config.repos[config.default_repo]
    path = state_path(DEFAULT_STATE_DIR, repo.name, ticket)
    if not path.exists():
        console.print(f"[red]No local state exists for {ticket}[/red]")
        raise typer.Exit(code=1)

    state = read_run_state(path)
    try:
        _check_cleanup_eligibility(state, force=force)
    except GitPlanError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"Worktree: {state.worktree_path}")
    console.print(f"Local branch: {state.branch_name}")
    if not typer.confirm("Remove local worktree and delete local branch?"):
        console.print("[yellow]Cleanup cancelled.[/yellow]")
        raise typer.Exit(code=1)

    try:
        _cleanup_run(state)
    except GitPlanError as exc:
        updated = replace(
            state,
            status="needs-attention",
            updated_at=_now(),
            command_log=[
                *state.command_log,
                f"git worktree remove {state.worktree_path}",
                f"git branch -d {state.branch_name}",
            ],
            error=str(exc),
        )
        state_file = write_run_state(updated, state_dir=DEFAULT_STATE_DIR)
        console.print("[red]Cleanup needs manual attention.[/red]")
        console.print(f"[red]{exc}[/red]")
        console.print(f"State: {state_file}")
        raise typer.Exit(code=1) from exc

    updated = replace(
        state,
        status="cleaned-up",
        updated_at=_now(),
        command_log=[
            *state.command_log,
            f"git worktree remove {state.worktree_path}",
            f"git branch -d {state.branch_name}",
        ],
        error=None,
    )
    state_file = write_run_state(updated, state_dir=DEFAULT_STATE_DIR)
    console.print("[green]Cleaned up local ticket work.[/green]")
    console.print(f"State: {state_file}")


def main() -> None:
    app()


def _render_doctor_checks(checks: list[DoctorCheck]) -> None:
    table = Table(title="RALPH doctor")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Detail")
    table.add_column("Action")

    for check in checks:
        table.add_row(
            check.name,
            "[green]OK[/green]" if check.ok else "[red]FAIL[/red]",
            check.detail,
            check.action or "",
        )
    console.print(table)


def _render_status(runs: list[RunState], *, verbose: bool) -> None:
    if not runs:
        console.print("No local RALPH runs found.")
        return

    table = Table(title="RALPH runs", min_width=140)
    table.add_column("Ticket", no_wrap=True)
    table.add_column("Title", max_width=28, overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Branch", max_width=32, overflow="fold")
    table.add_column("Worktree", max_width=36, overflow="fold")
    table.add_column("MR", max_width=28, overflow="fold")
    table.add_column("Worktree state", no_wrap=True)
    if verbose:
        table.add_column("Base SHA", no_wrap=True)

    for run in runs:
        row = [
            run.ticket_key,
            run.ticket.summary,
            run.status,
            run.branch_name,
            str(run.worktree_path),
            run.mr_url or "",
            _format_worktree_state(worktree_state(run.worktree_path)),
        ]
        if verbose:
            row.append(run.base_sha)
        table.add_row(*row)
    console.print(table)


def _format_worktree_state(state: str) -> str:
    if state == "clean":
        return "[green]clean[/green]"
    if state == "dirty":
        return "[yellow]dirty[/yellow]"
    return "[red]missing[/red]"


def _check_start_availability(
    *,
    repo_path: Path,
    worktree_path: Path,
    remote: str,
    branch_name: str,
) -> None:
    if worktree_path.exists():
        raise GitPlanError(f"Worktree path already exists: {worktree_path}")
    if local_branch_exists(repo_path, branch_name):
        raise GitPlanError(f"Local branch already exists: {branch_name}")
    if remote_branch_exists(repo_path, remote, branch_name):
        raise GitPlanError(f"Remote branch already exists: {remote}/{branch_name}")


def _render_start_dry_run(
    *,
    ticket: Ticket,
    branch_name: str,
    worktree_path: Path,
    base_ref: str,
    base_sha: str,
    jira_command: str,
    agent_command: str,
) -> None:
    console.print("[bold]Dry run[/bold]")
    console.print(f"Ticket: {ticket.key}")
    console.print(f"Summary: {ticket.summary}")
    console.print(f"Issue type: {ticket.issue_type}")
    console.print(f"Status: {ticket.status}")
    console.print("Dependency/status decision: allowed")
    console.print(f"Planned branch: {branch_name}")
    console.print(f"Planned worktree path: {worktree_path}")
    console.print(f"Resolved base ref: {base_ref}")
    console.print(f"Resolved base SHA: {base_sha}")
    console.print("Planned commands:")
    console.print(f"  {jira_command}")
    console.print(
        f"  git worktree add --no-track -b {branch_name} {worktree_path} {base_ref}"
    )
    console.print(f"  {agent_command}")
    console.print("Generated file previews:")
    for path, content in _agent_file_previews(
        ticket=ticket,
        branch_name=branch_name,
    ):
        console.print(f"[bold]{path}[/bold]")
        console.print(content.rstrip())
    console.print(
        "[green]No branches, worktrees, state files, or .agent/ files were "
        "written.[/green]"
    )


def _agent_file_previews(
    *,
    ticket: Ticket,
    branch_name: str,
) -> list[tuple[str, str]]:
    context = {"ticket": ticket, "branch_name": branch_name}
    return [
        (".agent/task.md", render_template("task.md.j2", **context)),
        (".agent/context.md", render_template("context.md.j2", **context)),
        (
            ".agent/bootstrap-prompt.md",
            render_template("bootstrap-prompt.md.j2", **context),
        ),
        (".agent/status.md", render_template("status.md.j2", **context)),
        (".agent/mr_title.md", render_template("mr_title.md.j2", **context)),
        (
            ".agent/mr_description.md",
            render_template("mr_description.md.j2", **context),
        ),
    ]


def _start_real_run(
    *,
    ticket: Ticket,
    repo_name: str,
    repo_path: Path,
    worktree_path: Path,
    branch_name: str,
    base_ref: str,
    base_sha: str,
    git_remote: str,
    agent_command: str,
) -> None:
    command_log = [
        f"git fetch {git_remote}",
        f"git worktree add --no-track -b {branch_name} {worktree_path} {base_ref}",
        agent_command,
    ]
    started_at = _now()
    add_worktree(
        repo_path=repo_path,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
    )

    try:
        ensure_agent_dir_ignored(worktree_path)
        _write_agent_files(ticket=ticket, branch_name=branch_name, root=worktree_path)
        state = _run_state(
            ticket=ticket,
            repo_name=repo_name,
            repo_path=repo_path,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
            base_sha=base_sha,
            status="started",
            created_at=started_at,
            command_log=command_log,
        )
        state_path = write_run_state(state, state_dir=DEFAULT_STATE_DIR)
        _run_agent_command(agent_command, cwd=worktree_path)
    except Exception as exc:
        state = _run_state(
            ticket=ticket,
            repo_name=repo_name,
            repo_path=repo_path,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
            base_sha=base_sha,
            status="needs-attention",
            created_at=started_at,
            command_log=command_log,
            error=str(exc),
        )
        state_path = write_run_state(state, state_dir=DEFAULT_STATE_DIR)
        console.print(
            "[red]Start needs manual attention. Git state was left in place.[/red]"
        )
        console.print(f"State: {state_path}")
        raise typer.Exit(code=1) from exc

    console.print("[green]Started ticket run.[/green]")
    console.print(f"Worktree: {worktree_path}")
    console.print(f"Branch: {branch_name}")
    console.print(f"State: {state_path}")


def _write_agent_files(*, ticket: Ticket, branch_name: str, root: Path) -> None:
    agent_dir = root / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=False)
    for relative_path, content in _agent_file_previews(
        ticket=ticket,
        branch_name=branch_name,
    ):
        (root / relative_path).write_text(content)


def _run_agent_command(command: str, *, cwd: Path) -> CommandResult:
    args = shlex.split(command)
    if not args:
        raise GitPlanError("Configured agent command is empty")

    result = CommandRunner().run(args, cwd=cwd)
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Agent command failed{suffix}")
    return result


def _finish_run(*, state: RunState, gitlab_command: str) -> str:
    if state.status == "mr-created":
        if state.mr_url:
            raise GitPlanError(
                f"MR already recorded for {state.ticket_key}: {state.mr_url}"
            )
        raise GitPlanError(f"MR is already marked created for {state.ticket_key}")
    if state.status == "cleaned-up":
        raise GitPlanError(f"Run is already cleaned up for {state.ticket_key}")
    if not state.worktree_path.exists():
        raise GitPlanError(f"Worktree does not exist: {state.worktree_path}")
    if current_branch(state.worktree_path) != state.branch_name:
        raise GitPlanError(f"Worktree is not on expected branch: {state.branch_name}")
    if worktree_state(state.worktree_path) != "clean":
        raise GitPlanError("Worktree must be clean before finish")

    upstream = upstream_name(state.worktree_path)
    if upstream:
        behind, _ahead = upstream_divergence(state.worktree_path, upstream)
        if behind:
            raise GitPlanError(
                f"Branch is behind or diverged from upstream {upstream}; "
                "reconcile manually before finish"
            )

    if commits_ahead_count(state.worktree_path, state.base_sha) == 0:
        raise GitPlanError(
            f"Branch has no commits ahead of recorded base SHA {state.base_sha}"
        )
    agent_paths = [
        path for path in committed_paths(state.worktree_path, state.base_sha)
        if path == ".agent" or path.startswith(".agent/")
    ]
    if agent_paths:
        raise GitPlanError(
            "Committed diff includes .agent/ files: " + ", ".join(agent_paths)
        )

    title = _read_mr_title(state.worktree_path)
    description = _read_mr_description(state.worktree_path)
    existing_url = _find_existing_mr(
        state=state,
        gitlab_command=gitlab_command,
    )
    if existing_url:
        updated = replace(
            state,
            status="mr-created",
            mr_url=existing_url,
            updated_at=_now(),
            error=None,
        )
        write_run_state(updated, state_dir=DEFAULT_STATE_DIR)
        raise GitPlanError(f"MR already exists for {state.branch_name}: {existing_url}")

    push_branch(
        state.worktree_path,
        "origin",
        state.branch_name,
        has_upstream=upstream is not None,
    )
    return _create_draft_mr(
        state=state,
        gitlab_command=gitlab_command,
        title=title,
        description=description,
    )


def _check_cleanup_eligibility(state: RunState, *, force: bool) -> None:
    if state.status == "cleaned-up":
        raise GitPlanError(f"Run is already cleaned up for {state.ticket_key}")
    if not force and state.status != "mr-created":
        raise GitPlanError(
            f"Run must have an MR before cleanup; use --force to override for "
            f"{state.ticket_key}"
        )
    if not force and not state.mr_url:
        raise GitPlanError(
            f"Run must have an MR URL before cleanup; use --force to override for "
            f"{state.ticket_key}"
        )
    if not state.worktree_path.exists():
        raise GitPlanError(f"Worktree does not exist: {state.worktree_path}")
    if worktree_state(state.worktree_path) != "clean":
        raise GitPlanError("Worktree must be clean before cleanup")


def _cleanup_run(state: RunState) -> None:
    remove_worktree(state.repo_path, state.worktree_path)
    delete_local_branch(state.repo_path, state.branch_name)


def _read_mr_title(worktree_path: Path) -> str:
    path = worktree_path / ".agent" / "mr_title.md"
    if not path.exists():
        raise GitPlanError("Missing .agent/mr_title.md")
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) != 1:
        raise GitPlanError(".agent/mr_title.md must contain exactly one non-empty line")
    if _has_todo_marker(lines[0]):
        raise GitPlanError(".agent/mr_title.md contains TODO text")
    return lines[0]


def _read_mr_description(worktree_path: Path) -> str:
    path = worktree_path / ".agent" / "mr_description.md"
    if not path.exists():
        raise GitPlanError("Missing .agent/mr_description.md")
    description = path.read_text().strip()
    if not description:
        raise GitPlanError(".agent/mr_description.md must not be empty")
    if _has_todo_marker(description):
        raise GitPlanError(".agent/mr_description.md contains TODO text")
    return description


def _has_todo_marker(value: str) -> bool:
    return re.search(r"\b(?:TODO|TBD)\b", value, flags=re.IGNORECASE) is not None


def _find_existing_mr(*, state: RunState, gitlab_command: str) -> str | None:
    args = [
        *shlex.split(gitlab_command),
        "mr",
        "list",
        "--source-branch",
        state.branch_name,
        "--state",
        "opened",
        "--output",
        "json",
    ]
    result = CommandRunner().run(args, cwd=state.worktree_path)
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict):
        return None
    url = first.get("web_url") or first.get("url")
    return str(url) if url else None


def _create_draft_mr(
    *,
    state: RunState,
    gitlab_command: str,
    title: str,
    description: str,
) -> str:
    args = [
        *shlex.split(gitlab_command),
        "mr",
        "create",
        "--draft",
        "--title",
        title,
        "--description",
        description,
        "--source-branch",
        state.branch_name,
    ]
    result = CommandRunner().run(args, cwd=state.worktree_path)
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise GitPlanError(f"Could not create draft GitLab MR{suffix}")
    match = re.search(r"https?://\S+", result.stdout)
    if not match:
        raise GitPlanError("GitLab MR was created but no MR URL was reported")
    return match.group(0).rstrip(")")


def _run_state(
    *,
    ticket: Ticket,
    repo_name: str,
    repo_path: Path,
    worktree_path: Path,
    branch_name: str,
    base_ref: str,
    base_sha: str,
    status: RunStatus,
    created_at: datetime,
    command_log: list[str],
    error: str | None = None,
) -> RunState:
    return RunState(
        ticket_key=ticket.key,
        ticket=ticket,
        repo_name=repo_name,
        repo_path=repo_path,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
        base_sha=base_sha,
        status=status,
        created_at=created_at,
        updated_at=_now(),
        command_log=command_log,
        error=error,
    )


def _now() -> datetime:
    return datetime.now(UTC)
