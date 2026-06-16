"""Command-line entry point for RALPH."""

from typing import Annotated

import typer
from rich.console import Console

from ralph import __version__

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
    fail_unimplemented("init")


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
