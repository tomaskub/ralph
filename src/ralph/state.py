"""Local state paths and status primitives."""

from pathlib import Path

DEFAULT_STATE_DIR = Path("~/.local/state/ralph").expanduser()


def state_path(state_dir: Path, repo_name: str, ticket_key: str) -> Path:
    return state_dir / repo_name / f"{ticket_key}.json"

