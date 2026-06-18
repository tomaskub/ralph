# RALPH

RALPH is a local operator CLI for repeatable AI-agent ticket work loops.

It automates the local mechanics around one Jira ticket at a time: read ticket
context, create an isolated Git worktree and branch, write focused `.agent/`
files for an AI agent, track local run state, and publish an already-committed
branch as a draft GitLab merge request.

RALPH keeps judgment-heavy operations under human control. It does not commit
changes, rebase, resolve conflicts, merge MRs, transition Jira tickets, or delete
remote branches.

## Installation

RALPH is packaged as the `ralph-loop` Python project and exposes the `ralph`
console command. It requires Python 3.12 or newer.

Install the published package with `pipx`:

```bash
pipx install "git+https://github.com/tomaskub/ralph.git@0.1.0"
```

To install RALPH directly from this repository:

```bash
python -m pip install "ralph-loop @ git+ssh://git@github.com/tomaskub/ralph.git"
ralph --version
```

For local development, clone this repository and install the development
dependencies:

```bash
git clone git@github.com:tomaskub/ralph.git
cd ralph
uv sync --extra dev
uv run ralph --version
```

For an editable development install with `pip`:

```bash
python -m pip install -e ".[dev]"
ralph --version
```

RALPH shells out to local tools, so the operator machine also needs:

- `git`
- a Jira CLI that can return issue JSON
- `glab` for GitLab merge request creation
- the configured agent command, default `claude`

## Usage

Initialize local configuration:

```bash
ralph init
```

`init` writes `~/.config/ralph/config.toml` and creates local state under
`~/.local/state/ralph`. It prompts for the product repo path, worktree root,
base ref, and Jira project key. RALPH uses `origin/main` as the default base ref
and `origin` as the default Git remote.

Before starting work, verify the local setup:

```bash
ralph doctor
```

`doctor` checks tool availability, Jira and GitLab authentication, the configured
Git repo, base ref, worktree root, and whether `.agent/` is ignored by the
product repo.

Preview a ticket run without writing branches, worktrees, state, or `.agent/`
files:

```bash
ralph start YT-123 --dry-run
```

Start a real ticket run:

```bash
ralph start YT-123
```

This command fetches the configured remote, validates the Jira ticket, creates a
ticket branch from the configured base ref, creates a dedicated worktree, writes
the `.agent/` files, records local run state, and launches the configured agent.

Inspect local runs:

```bash
ralph status
ralph status --all --verbose
```

After the human or agent has made and committed product changes in the worktree,
publish the branch as a draft GitLab MR:

```bash
ralph finish YT-123
```

`finish` requires a clean worktree, at least one commit ahead of the recorded
base SHA, valid `.agent/mr_title.md` and `.agent/mr_description.md` files, and no
committed `.agent/` files. It pushes the branch and creates a draft MR with
`glab`.

After the MR exists, remove local ticket work:

```bash
ralph cleanup YT-123
```

`cleanup` removes the local worktree and local branch, then marks the retained
state record as cleaned up. It does not delete the remote branch. Use
`--force` only when you intentionally want to clean up before an MR URL is
recorded.

Update an existing `pipx` installation:

```bash
ralph update
```

This finds the latest stable GitHub release/tag and reinstalls that exact ref
with pipx, equivalent to:

```bash
pipx install --force "git+https://github.com/tomaskub/ralph.git@<latest-tag>"
```

To install a specific tag manually:

```bash
ralph update --tag 0.1.0
```

For development dogfooding against the latest `main`, install that branch
explicitly:

```bash
pipx install "git+https://github.com/tomaskub/ralph.git@main"
```

### Configuration

The default config path is `~/.config/ralph/config.toml`.

```toml
default_repo = "product"

[repos.product]
repo_path = "~/workspace/product"
worktree_root = "~/workspace/product-worktrees"
base_ref = "origin/main"
git_remote = "origin"
jira_project = "YT"
gitlab_project = "group/product"

[tools]
jira = "jira"
gitlab = "glab"
agent = "claude"

[jira]
issue_json_command = "jira issue view {ticket} --format json"

[branch_kinds]
Task = "feature"
Story = "feature"
Bug = "bugfix"
```

## Development

Install development dependencies:

```bash
uv sync --extra dev
```

Run linting:

```bash
uv run ruff check .
```

Run tests:

```bash
uv run pytest
```

The main CLI entry point is `src/ralph/cli.py`. Command behavior is covered by
the tests in `tests/test_cli.py`, with configuration, doctor checks, and
foundation behavior covered by the rest of the test suite.

The MVP product requirements are documented in `docs/prd.md`.
The post-MVP direction and planned next stages are documented in
`docs/roadmap.md`.

To run the CLI directly from the checkout:

```bash
uv run ralph --help
```

### Pull Request Checks

GitHub Actions runs the repository quality gates on pull requests and pushes to
`main`:

```bash
uv run ruff check .
uv run pytest
uv build
```

### Main Branch Protection

Configure branch protection for `main` in GitHub repository settings:

- require a pull request before merging
- do not require approving reviews
- require status checks before merging
- require the `ci` status check to pass before merging
- require branches to be up to date before merging
- include administrators so maintainers cannot bypass the required CI check
- block direct pushes by allowing merges only through pull requests

### Releases

Create a release from an up-to-date, clean checkout:

```bash
make release
```

The release command infers the version from `pyproject.toml` and
`src/ralph/__init__.py`, requires both sources to match, validates that
`<version>` does not already exist locally or on `origin`, then runs linting,
tests, and a package build before creating the tag and GitHub release with
generated notes.
