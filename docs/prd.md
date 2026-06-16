# RALPH Loop MVP PRD

## Overview

RALPH is a local operator CLI that automates the repetitive mechanics of AI-agent ticket work while keeping judgment, commits, rebases, merge decisions, and conflict handling under human control.

The MVP supports one explicitly named Jira ticket at a time. It reads ticket context from Jira, creates a fresh Git worktree and branch from trunk, writes narrow agent context files, launches the configured agent command, tracks local run state, and later pushes an already-committed branch to a draft GitLab merge request.

RALPH is not committed into product repositories. It is built as a separate Python CLI, installed with `pipx`, and configured locally for the operator's default product repository.

## Goals

- Provide a repeatable local loop for starting AI-agent work on a Jira ticket.
- Keep each ticket isolated in its own Git worktree and branch.
- Generate precise `.agent/` files for the agent and MR workflow.
- Record enough local state to inspect, finish, and clean up runs.
- Create draft GitLab MRs from local MR title/description files.
- Keep risky operations human-owned: commits, rebases, conflict resolution, review, merge, Jira transitions, and remote branch deletion.

## Non-Goals

- No Jira writes: no status transitions, comments, assignments, labels, or ticket updates.
- No automatic commits.
- No automatic tests in `finish`.
- No automatic rebasing or sync command in MVP.
- No `resume` command in MVP.
- No remote branch deletion.
- No GitLab MR merge automation.
- No epic-level scheduling.
- No parallel ticket execution or ticket batch classification.
- No Jira/GitLab native API clients in MVP.
- No transcript capture or Claude session supervision.
- No special redaction of generated local files.

## Primary User

The MVP is for one local operator working mostly in one configured product repository.

Team use is a future concern. The first version optimizes for simple local configuration, local state, delegated CLI authentication, and predictable behavior from any current working directory.

## Glossary

- **Ticket**: A single Jira issue identified by key, such as `YT-123`.
- **Run**: RALPH's local record of work started for one ticket.
- **Product repo**: The target application repository where ticket work happens.
- **RALPH repo**: The separate tooling repository that contains the RALPH CLI implementation.
- **Base ref**: The configured trunk ref used to create ticket branches, default `origin/main`.
- **Base SHA**: The resolved commit SHA of the base ref at `start` time.
- **Branch kind**: The branch prefix derived from Jira issue type, such as `feature` or `bugfix`.
- **Worktree**: A Git worktree created for a specific ticket branch.
- **Local state**: RALPH-owned metadata under `~/.local/state/ralph`.
- **Agent files**: Generated files under `.agent/` inside the ticket worktree.

## MVP Command Set

The MVP includes:

- `ralph init`
- `ralph doctor`
- `ralph start TICKET`
- `ralph start TICKET --dry-run`
- `ralph status`
- `ralph finish TICKET`
- `ralph cleanup TICKET`

The MVP excludes:

- `ralph sync`
- `ralph resume`
- epic commands
- parallel commands

## Packaging and Runtime

RALPH should be implemented as a Python CLI installed with `pipx`.

Recommended package shape:

```text
ralph-loop/
  README.md
  pyproject.toml
  src/
    ralph/
      __init__.py
      cli.py
      config.py
      models.py
      runner.py
      git.py
      jira.py
      gitlab.py
      state.py
      templates.py
      templates/
        task.md.j2
        context.md.j2
        bootstrap-prompt.md.j2
        status.md.j2
        mr_title.md.j2
        mr_description.md.j2
  tests/
    fixtures/
```

Use:

- `typer` for CLI commands.
- `rich` for readable terminal output.
- `jinja2` for templates.
- `pytest` for tests.
- `ruff` for linting and formatting.
- Standard-library `subprocess` behind an injectable runner abstraction.
- Standard dataclasses plus explicit validation for models.

Do not use Pydantic in MVP.

## Configuration

RALPH reads local configuration from:

```text
~/.config/ralph/config.toml
```

The MVP is configured for one default repo. Commands should work from any directory and must not rely on `cwd`.

Example config:

```toml
default_repo = "yt-smzr"

[repos.yt-smzr]
repo_path = "~/workspace/yt-smzr"
worktree_root = "~/workspace/yt-smzr-worktrees"
base_ref = "origin/main"
git_remote = "origin"
jira_project = "YT"
gitlab_project = "group/yt-smzr"

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

The exact Jira JSON command is configurable because Jira CLIs vary. RALPH must depend on JSON output and normalize it into its own ticket model.

## `ralph init`

`init` creates minimal local configuration.

It should ask only for essentials:

- product repo path
- worktree root
- base ref, default `origin/main`
- Jira project key

It should derive the Git remote as `origin` by default and derive the GitLab project path from the Git remote when possible. If derivation fails, ask for the GitLab project path.

`init` should validate before writing config:

- repo path exists
- repo path is a Git repository
- configured base ref can resolve after read-only Git checks
- worktree root can be created

`init` may create:

- `~/.config/ralph`
- `~/.local/state/ralph`
- the configured worktree root, after showing the path and asking confirmation

`init` must not:

- modify product repo files
- modify global git excludes
- write Jira/GitLab state

## `ralph doctor`

`doctor` validates the local machine and configuration. It should perform live read-only checks where possible.

Required checks:

- `git` is installed.
- configured Jira CLI exists and can make a read-only authenticated call.
- `glab` exists and can make a read-only authenticated call.
- configured agent command exists.
- configured repo path exists and is a Git repository.
- configured base ref can be fetched/resolved.
- worktree root exists or appears creatable.
- `.agent/` is ignored in the configured repo, verified with `git check-ignore .agent/test`.

`doctor` should not modify the filesystem by default. It reports actionable failures.

## Ticket Model

RALPH normalizes Jira JSON into:

- `key`
- `summary`
- `description`
- `issue_type`
- `status`
- `url`
- `epic`
- `links`

The raw Jira JSON should be stored in local state for debugging. It should not be written into `.agent/`.

RALPH should validate:

- ticket key belongs to configured Jira project
- summary is non-empty
- description is non-empty
- status is exactly `To Do`
- issue type exists in configured branch kind mapping
- no clear unresolved blocking dependency exists

If dependency information is unavailable or ambiguous, `start` should require manual confirmation before proceeding. Clear unresolved blockers should refuse by default with an explicit override.

The MVP does not require separate acceptance criteria extraction.

## Branch Naming

Branch names are derived from Jira issue type and summary.

Default mapping:

- Jira `Task` -> `feature`
- Jira `Story` -> `feature`
- Jira `Bug` -> `bugfix`

Format:

```text
{branch_kind}/{ticket}-{ticket-summary-kebab-cased}
```

Example:

```text
feature/YT-123-add-video-summary-cache
bugfix/YT-124-handle-transcript-errors
```

Slug rules:

- source is Jira summary
- lowercase
- ASCII-normalized
- non-alphanumeric runs collapse to hyphens
- strip leading/trailing hyphens
- max full branch length is 80 characters
- truncate only the slug
- strip trailing hyphens after truncation

If the issue type is unmapped, `start` refuses. No per-command branch kind override in MVP.

## Worktree Naming

The default worktree path is based on the branch name, transformed for filesystem readability:

```text
{worktree_root}/{branch-name-with-slash-replaced-by-__}
```

Example:

```text
~/workspace/yt-smzr-worktrees/feature__YT-123-add-video-summary-cache
```

No ticket alias symlink in MVP.

## Local State

RALPH state is stored outside the product repo:

```text
~/.local/state/ralph/{repo-name}/{ticket}.json
```

State should include:

- ticket key
- normalized ticket fields
- raw Jira JSON or path to it
- repo path
- worktree path
- branch name
- base ref
- base SHA resolved at `start`
- status
- MR URL, if created
- timestamps
- short command log

Supported statuses:

- `started`
- `needs-attention`
- `mr-created`
- `cleaned-up`

`planned` may exist only as dry-run output and is not persisted.

The short command log should include command plans and command results for non-interactive commands: command, timestamp, exit code, and brief stdout/stderr snippets on failure. It should not capture full interactive agent transcripts.

## Agent Files

On real `start`, RALPH creates `.agent/` files inside the ticket worktree after `git worktree add` succeeds and `git check-ignore .agent/test` passes inside that worktree.

Generated files:

```text
.agent/task.md
.agent/context.md
.agent/bootstrap-prompt.md
.agent/status.md
.agent/mr_title.md
.agent/mr_description.md
```

`task.md` should contain the normalized Jira ticket brief:

- ticket
- title
- URL
- epic
- status
- description
- links/dependencies

`context.md` should contain RALPH context:

- repo path
- worktree path
- branch
- base ref
- base SHA
- important constraints
- reminder that `.agent/` is local-only ignored context

`bootstrap-prompt.md` should tell the agent:

- read `AGENTS.md` if present
- read `.agent/task.md` and `.agent/context.md`
- inspect relevant code before editing
- implement only the ticket scope
- do not rebase or merge
- do not commit
- run relevant tests when appropriate
- document test results or inability to test
- update `.agent/status.md`
- update `.agent/mr_title.md`
- update `.agent/mr_description.md`

`status.md` should be a lightweight progress/status template.

`mr_title.md` should contain a single-line draft title derived from the ticket.

`mr_description.md` should contain Markdown sections:

```text
Ticket:
Summary:
Verification:
Risks:
```

No raw Jira JSON should be written into `.agent/`.

## `ralph start TICKET`

`start` performs the conservative ticket launch.

Required flow:

1. Load local config.
2. Validate ticket key belongs to configured Jira project.
3. Fetch Jira issue JSON through configured Jira command.
4. Normalize ticket fields.
5. Validate summary, description, issue type, status, and blockers.
6. Fetch configured Git remote.
7. Resolve configured base ref to `base_sha`.
8. Generate branch name.
9. Generate worktree path.
10. Refuse if worktree path already exists.
11. Refuse if branch already exists locally or remotely.
12. Run one `git worktree add -b <branch> <path> <base-ref>` command.
13. Inside the new worktree, verify `.agent/` ignore behavior with `git check-ignore .agent/test`.
14. Write `.agent/` files.
15. Persist local state as `started`.
16. Launch the configured agent command in the worktree.

`start` should launch the configured agent command automatically. There is no `--no-launch` flag in MVP.

Ralph treats agent launch as a handoff. It does not supervise the session or wait for a structured result. If the interactive agent command blocks the terminal, that is acceptable.

If `git worktree add` succeeds but later steps fail, RALPH should persist state as `needs-attention` with branch/worktree details and failure information. It should not auto-clean partially created Git state.

`start` does not require the main checkout to be clean.

## `ralph start TICKET --dry-run`

Dry-run is required for MVP.

It may perform read-only external reads:

- Jira JSON fetch
- Git fetch/resolve checks
- branch/path existence checks

It must not:

- create branches
- create worktrees
- write files
- write local state
- launch the agent

Dry-run should print:

- normalized ticket summary
- dependency/status decision
- planned branch
- planned worktree path
- resolved base SHA
- planned commands
- generated file previews

Dry-run prints only; it writes no temporary preview files.

## `ralph status`

`status` reads local state and performs lightweight Git checks for existing worktrees.

Default output should be a concise `rich` table with:

- ticket
- title
- status
- branch
- worktree path
- MR URL if any
- dirty/clean/missing worktree state

It should not call Jira by default.

By default, hide `cleaned-up` runs. A future or optional `--all` can show them. Base SHA should be hidden by default and available in verbose output.

## `ralph finish TICKET`

`finish` publishes an already-committed branch and creates a draft GitLab MR.

It assumes the human has reviewed and committed changes. It must not create commits.

Required preflight:

- local state exists
- status is compatible with finishing
- worktree exists
- current branch matches state
- worktree is clean
- branch has at least one commit ahead of recorded base SHA or configured base
- committed diff does not include any `.agent/` files
- upstream state is not behind or diverged
- no existing MR is already recorded or detected for the branch
- `.agent/mr_title.md` exists and is non-empty
- `.agent/mr_title.md` contains exactly one non-empty line after trimming
- `.agent/mr_description.md` exists and is non-empty
- MR title or description does not contain obvious `TODO`

`finish` should not run tests. The agent or human should document verification in `.agent/status.md` and `.agent/mr_description.md`.

Required behavior:

1. Push the branch.
2. Use `git push -u origin <branch>` when no upstream exists.
3. Use `git push` when upstream exists.
4. Never force-push.
5. Create a draft GitLab MR with `glab`.
6. Use `.agent/mr_title.md` for title and `.agent/mr_description.md` for description.
7. Prefer file-based `glab` arguments for MR description where supported.
8. Fall back to safe shell input/cat-style invocation only if file-based arguments are unavailable.
9. Verify exact stable `glab` flags during implementation.
10. Store MR URL and mark state `mr-created`.

If an MR already exists, `finish` should refuse to create a duplicate, print the existing MR URL, and update state if appropriate.

## `ralph cleanup TICKET`

`cleanup` removes local ticket work after MR creation or explicit force.

Eligibility:

- state exists
- worktree exists
- worktree is clean
- MR URL exists or `--force` is passed
- user confirms destructive cleanup

`--force` bypasses only the MR-created eligibility check. It must not bypass final confirmation.

Behavior:

1. Remove the worktree.
2. Delete the local branch with Git safe branch deletion behavior, equivalent to `git branch -d <branch>`.
3. Never use forced branch deletion in MVP.
4. Never delete the remote branch.
5. Mark state as `cleaned-up` after cleanup succeeds.

If worktree removal succeeds but safe branch deletion fails, report the failure and mark state `needs-attention`. The worktree can be regenerated if needed.

Do not archive `.agent/` before removing the worktree.

## Terminal Output

Use `rich` for readable operator output:

- tables
- command previews
- warnings
- errors
- concise next steps

RALPH should print exact Git/Jira/GitLab/agent commands before running them, redacting secrets if secret-bearing config is ever supported.

Errors must be actionable and should explain the next command or manual action.

## Testing Requirements

MVP should include focused automated tests for:

- config loading and validation
- `init` config generation behavior
- Jira ticket normalization
- Jira project key validation
- status validation
- dependency/blocker detection
- branch kind mapping
- branch slug generation and 80-character truncation
- worktree path generation
- template rendering
- local state transitions
- command runner behavior
- `finish` preflight checks
- `.agent/` committed-file refusal
- cleanup eligibility checks

Use mocked command runners for subprocess-heavy behavior.

Include an integration-style dry-run test using:

- fixture Jira JSON
- temporary Git repo
- simulated `origin/main`
- `ralph start TICKET --dry-run`

The test should assert the expected plan and verify that no branches, worktrees, state files, or `.agent/` files are created.

## Acceptance Criteria

The MVP is complete when:

- `ralph init` creates valid local config for one default repo.
- `ralph doctor` validates tools, auth, repo, base ref, worktree root, and `.agent/` ignore behavior.
- `ralph start TICKET --dry-run` prints a complete non-mutating plan from Jira JSON and Git state.
- `ralph start TICKET` creates a fresh worktree branch from `origin/main`, writes `.agent/` files, records local state, and launches the configured agent command.
- `ralph status` shows local runs from state plus Git worktree cleanliness.
- `ralph finish TICKET` refuses unsafe states, pushes an already-committed branch, creates a draft GitLab MR from `.agent/mr_title.md` and `.agent/mr_description.md`, and records the MR URL.
- `ralph cleanup TICKET` removes local worktree state safely, never deletes remote branches, and retains cleaned-up local state.
- Automated tests cover core planning, validation, naming, templating, state transitions, and dry-run behavior.

## Future Scope

Future versions may add:

- `ralph sync TICKET` for human-gated fetch/rebase flows.
- `ralph resume TICKET` to validate state and relaunch the agent in an existing worktree.
- limited parallel scheduling for clearly independent tickets.
- richer Jira MCP workflows.
- Jira status transitions and comments.
- configurable redaction.
- MR update flows.
- team-shared configuration.
- epic-level planning.
- issue slicing.
- CI/check status inspection.
