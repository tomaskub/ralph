from pathlib import Path

from ralph.git import ensure_agent_dir_ignored
from ralph.runner import CommandResult


def test_ensure_agent_dir_ignored_separates_leading_dash_path() -> None:
    runner = FakeRunner()
    worktree_path = Path("/repo")

    ensure_agent_dir_ignored(
        worktree_path,
        agent_files_directory="-ralph-agent",
        runner=runner,
    )

    assert runner.calls == [
        (["git", "check-ignore", "--", "-ralph-agent/test"], worktree_path)
    ]


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []

    def run(self, args: list[str], *, cwd: Path | None = None) -> CommandResult:
        assert cwd is not None
        self.calls.append((args, cwd))
        return CommandResult(args, 0, stdout="-ralph-agent/test\n", stderr="")
