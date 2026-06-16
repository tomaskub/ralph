from typer.testing import CliRunner

from ralph import __version__
from ralph.cli import app

runner = CliRunner()


def test_version_option_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"ralph {__version__}" in result.output


def test_mvp_commands_are_registered() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ["init", "doctor", "start", "status", "finish", "cleanup"]:
        assert command in result.output


def test_unimplemented_commands_fail_clearly() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 2
    assert "ralph doctor is not implemented yet" in result.output


def test_start_accepts_ticket_and_dry_run_flag() -> None:
    result = runner.invoke(app, ["start", "YT-123", "--dry-run"])

    assert result.exit_code == 2
    assert "ralph start YT-123 --dry-run is not implemented yet" in result.output

