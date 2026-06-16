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
    validate_init_inputs,
    write_config,
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
) -> None:
    """Start an isolated ticket worktree and launch the configured agent."""
    suffix = f" {ticket}"
    if dry_run:
        suffix += " --dry-run"
    fail_unimplemented(f"start{suffix}")


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
