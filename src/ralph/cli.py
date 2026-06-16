"""Command-line entry point for RALPH."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ralph import __version__
from ralph.config import (
    DEFAULT_BASE_REF,
    DEFAULT_CONFIG_PATH,
    DEFAULT_STATE_DIR,
    build_single_repo_config,
    derive_gitlab_project,
    load_config,
    validate_init_inputs,
    write_config,
)
from ralph.git import branch_name_for_ticket, worktree_path_for_branch
from ralph.jira import (
    JiraFetchError,
    branch_kind_for_ticket,
    fetch_ticket_json,
    normalize_ticket,
    validate_ticket,
)

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
    fail_unimplemented("doctor")


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
        console.print("[bold]Dry run[/bold]")
        console.print(f"Ticket: {normalized_ticket.key}")
        console.print(f"Summary: {normalized_ticket.summary}")
        console.print("Dependency/status decision: allowed")
        console.print(f"Planned branch: {branch_name}")
        console.print(f"Planned worktree path: {worktree_path}")
        console.print(f"Planned Jira command: {config.jira.issue_json_command}")
        console.print("[green]No files were written.[/green]")
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
