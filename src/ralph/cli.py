"""Command-line entry point for RALPH."""

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
    branch_name_for_ticket,
    local_branch_exists,
    remote_branch_exists,
    resolve_ref_sha,
    worktree_path_for_branch,
)
from ralph.jira import (
    JiraFetchError,
    branch_kind_for_ticket,
    fetch_ticket_json,
    normalize_ticket,
    validate_ticket,
)
from ralph.models import Ticket
from ralph.templates import render_template

app = typer.Typer(
    help="Local operator CLI for AI-agent ticket work loops.",
    invoke_without_command=True,
    no_args_is_help=True,
)
console = Console()


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

    fail_unimplemented(f"start {ticket}")


@app.command()
def status() -> None:
    """Show local RALPH runs."""
    fail_unimplemented("status")


@app.command()
def finish(ticket: Annotated[str, typer.Argument(help="Jira ticket key.")]) -> None:
    """Publish an already-committed branch as a draft GitLab MR."""
    fail_unimplemented(f"finish {ticket}")


@app.command()
def cleanup(ticket: Annotated[str, typer.Argument(help="Jira ticket key.")]) -> None:
    """Remove local ticket work after MR creation or explicit force."""
    fail_unimplemented(f"cleanup {ticket}")


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
    console.print(f"  git worktree add {worktree_path} {branch_name}")
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
