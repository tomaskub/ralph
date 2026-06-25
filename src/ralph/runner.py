"""Subprocess runner abstraction."""

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Thin wrapper around subprocess for later dependency injection in tests."""

    def run(
        self,
        args: Sequence[str],
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        input: str | None = None,
    ) -> CommandResult:
        subprocess_env = None if env is None else {**os.environ, **env}
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            env=subprocess_env,
            input=input,
            check=False,
            capture_output=True,
            text=True,
        )
        return CommandResult(
            args=tuple(args),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
