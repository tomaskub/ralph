# RALPH Roadmap

## Current Baseline

RALPH is at `0.4.0`.

The current product is a local operator CLI for one ticket run at a time. It
creates an isolated worktree and branch, writes focused files in the configured
agent files directory, tracks local run state, and publishes an already-committed
branch as a draft merge request.

The MVP PRD remains the baseline contract for the first stable loop. This
roadmap describes where Ralph should grow next without weakening the core rule:
Ralph automates repetitive mechanics, while humans keep ownership of judgment,
commits, rebases, conflict resolution, review, merges, and destructive cleanup.

## Product Direction

Ralph is a personal operator tool, not a team workflow platform. It should be
boring glue around well-written tickets, isolated worktrees, focused agent
context files, and the operator's preferred publish command.

The next stages should optimize the two places that cost the most time:

- starting work, especially preparing safe local workspace conventions
- publishing work, especially fitting existing review creation commands

After that, Ralph should expand to common project setups:

- Jira ticket intake for Jira-backed projects
- GitHub Issues ticket intake for GitHub-backed projects
- GitLab merge request publishing through built-in `glab` support or custom
  commands
- GitHub pull request publishing through `gh`
- local state and worktree isolation across all providers

The near-term focus is not parallelism, backlog intelligence, ticket
enrichment, or team automation. Tickets are assumed to be high-quality inputs.
Ralph should make the local execution loop fast and predictable.

## Design Principles

- Keep provider-specific behavior behind narrow adapters.
- Normalize external ticket data into Ralph-owned models before planning a run.
- Keep generated agent context provider-neutral where possible.
- Keep command-line authentication delegated to existing CLIs such as `jira`,
  `glab`, and `gh`.
- Prefer dry-run and read-only checks before adding write behavior.
- Add automation only where Ralph can explain exactly what it will do.
- Prefer operator-level configuration over modifying product repositories.
- Support custom commands where local workflow conventions already exist.

## Roadmap Themes

### 1. Setup Friction and Git Global Excludes

Ralph supports an operator-wide `[agent_files]` directory setting and a
separate `ralph setup-ignore` command that can add that directory to Git global
excludes.

With Git global excludes configured, product repositories do not need
Ralph-specific `.gitignore` entries. `.agent` remains the default agent files
directory. See [Git Global Excludes PRD](prd-git-global-excludes.md) for the
full 0.4.0 feature spec.

### 2. Configurable Review Publishing

Ralph should fit existing publishing workflows before adding more built-in
providers. In particular, some environments already use commands that ingest
title and description files, set assignees, choose reviewers, and apply merge
options.

Target config:

```toml
[review]
title_file = "pr_title.md"
description_file = "pr_description.md"
create_command = "glab-create-mr --title-file {title_file} --description-file {description_file}"
```

The file paths are relative to the configured agent files directory.

Ralph should support two review publishing modes:

- built-in provider mode, such as the current `glab mr create --draft`
- custom command mode, where Ralph validates the files and runs the configured
  command from the worktree

The custom command mode should still preserve Ralph's safety checks:

- state exists and is finishable
- worktree exists and is clean
- branch has commits ahead of the recorded base SHA
- committed diff does not include the configured agent files directory
- title and description files exist and are valid
- existing review request detection runs when Ralph knows how to perform it

Naming direction:

- Use `pr_title.md` and `pr_description.md` as the near-term defaults because
  they match existing operator workflow.
- Treat them as review request files, not GitHub-only files.
- Preserve compatibility with `.agent/mr_title.md` and
  `.agent/mr_description.md` during migration.

### 3. Provider-Neutral Ticket Intake

Ralph currently assumes Jira-shaped tickets. The next major direction is to
introduce an intake abstraction that can normalize tickets from multiple sources.

Target model:

```text
TicketSource
  Jira via configured JSON command
  GitHub Issues via gh
```

Normalized ticket fields should stay close to the MVP model:

- key or number
- display id, such as `YT-123` or `#42`
- title
- description/body
- type or kind, when available
- status/state
- URL
- parent or milestone, when available
- labels
- linked issues or blockers, when available
- raw provider payload in local state

First GitHub Issues slice:

- Add config for `ticket_provider = "jira" | "github"`.
- Add GitHub issue fetch through `gh issue view <number> --json ...`.
- Normalize GitHub issue JSON into Ralph's ticket model.
- Use labels to derive branch kind, for example `bug` to `bugfix` and
  everything else to `feature`.
- Allow GitHub issue state `OPEN` as startable.
- Store raw GitHub JSON in local state, as Jira does today.

Out of scope for the first GitHub slice:

- GitHub issue status writes.
- GitHub project board automation.
- Automatic linked-issue dependency inference beyond clear metadata exposed by
  `gh`.

### 4. Provider-Neutral Built-In Review Publishing

Ralph currently publishes draft GitLab merge requests with `glab`. Projects that
use GitHub Issues often also use GitHub pull requests managed by `gh`.

Target model:

```text
ReviewProvider
  GitLab merge requests via glab
  GitHub pull requests via gh
```

First GitHub PR slice:

- Add config for `review_provider = "gitlab" | "github"`.
- Add `gh pr create --draft` support.
- Reuse `.agent/mr_title.md` and `.agent/mr_description.md` initially, or rename
  them to provider-neutral files in a compatibility-preserving way.
- Detect existing PRs for the current branch with `gh pr list`.
- Record the PR URL in the existing `mr_url` field initially, then consider a
  provider-neutral `review_url` field in a state schema migration.

Important naming decision:

The current docs and code say MR because the MVP targets GitLab. Once GitHub PRs
are supported, Ralph should introduce provider-neutral language:

- **Review request** as the generic concept.
- **Merge request** for GitLab.
- **Pull request** for GitHub.
- `review_url` as the long-term state field.

### 5. Resume and Run Recovery

Ralph should help operators recover from interrupted starts and return to an
existing ticket run without reconstructing paths manually.

Candidate commands:

```text
ralph resume TICKET
ralph open TICKET
ralph repair TICKET
```

Recommended first slice:

- Add `ralph resume TICKET`.
- Load local state.
- Verify the worktree exists.
- Verify the expected branch is checked out.
- Print the task, context path, status path, branch, and worktree.
- Launch the configured agent command from the worktree.

Do not add automatic repair first. Ralph should initially report precise
recovery instructions for `needs-attention` runs.

### 6. Sync and Base Drift Awareness

The MVP intentionally avoided automatic rebasing. That should remain true, but
Ralph can still make base drift visible.

Candidate command:

```text
ralph sync TICKET
```

First slice:

- Fetch the configured remote.
- Compare the run's recorded base SHA with the current base ref.
- Report whether the ticket branch is behind, ahead, or diverged from upstream.
- Print exact manual commands the operator may choose to run.
- Do not rebase automatically.

Later optional slice:

- `ralph sync TICKET --rebase` behind explicit confirmation.
- This should stay separate from `finish`.

### 7. Pre-Finish Verification

`finish` should remain strict and focused on publishing. A separate verification
command can become richer without making publish behavior surprising.

Candidate command:

```text
ralph check TICKET
```

Checks:

- State exists and is finishable.
- Worktree exists and is on the expected branch.
- Worktree is clean.
- Branch has commits ahead of the recorded base SHA.
- Committed diff does not include `.agent/`.
- Review title and description files are valid.
- `.agent/status.md` has been updated from the initial template.
- Optional configured verification commands pass.

Config sketch:

```toml
[verify]
commands = [
  "uv run ruff check .",
  "uv run pytest",
]
```

### 8. Configuration Evolution

Provider support will require configuration growth. Keep the default simple, but
allow projects to declare their intake and review providers explicitly.

Possible future config:

```toml
default_repo = "product"

[repos.product]
repo_path = "~/workspace/product"
worktree_root = "~/workspace/product-worktrees"
base_ref = "origin/main"
git_remote = "origin"
ticket_provider = "github"
review_provider = "github"

[agent_files]
directory = ".agent"

[review]
title_file = "pr_title.md"
description_file = "pr_description.md"

[providers.jira]
project = "YT"
issue_json_command = "jira issue view {ticket} --format json"

[providers.github]
repo = "owner/product"

[tools]
jira = "jira"
gitlab = "glab"
github = "gh"
agent = "claude"

[branch_kinds.github_labels]
bug = "bugfix"
feature = "feature"
enhancement = "feature"
```

Migration rule:

Existing Jira/GitLab configs should continue to load. Ralph can infer:

- `ticket_provider = "jira"` when `jira_project` is present.
- `review_provider = "gitlab"` when `gitlab_project` is present.

### 9. Multi-Project Usability

The MVP is optimized for one default repo. After provider-neutral support lands,
multi-project use should become easier.

Candidate features:

- `ralph status --repo NAME`
- `ralph status --all-repos`
- `ralph start --repo NAME TICKET`
- `ralph doctor --repo NAME`
- better `ralph init` support for adding a second repo

Keep this after provider-neutral intake. Multi-repo support is more valuable
once Ralph can support both GitLab/Jira and GitHub/Issues projects.

## Suggested Milestones

### 0.4.0: Setup Friction

- Add configurable agent files directory.
- Add `ralph setup-ignore`.
- Update `doctor` to check the configured agent files directory.
- Keep `.agent/` as the default.
- Avoid requiring product repo `.gitignore` changes.

### 0.5.0: Configurable Publishing

- Add configurable review title and description filenames.
- Add custom review create command support.
- Support `pr_title.md` and `pr_description.md` as first-class defaults.
- Preserve compatibility with existing MR title and description files.
- Keep built-in GitLab MR publishing working.

### 0.6.0: GitHub Issues and PRs

- Add provider-neutral ticket normalization.
- Support `gh issue view` for GitHub Issues.
- Add provider-neutral review publishing.
- Support `gh pr create --draft`.
- Preserve Jira and GitLab behavior.

### 0.7.0: Resume and Check

- Add `ralph resume TICKET`.
- Add `ralph check TICKET`.
- Improve state command logs.
- Improve diagnostics for `needs-attention` runs.

### 0.8.0: Sync Awareness

- Add advisory `ralph sync TICKET`.
- Report base drift and upstream divergence.
- Print manual commands instead of rebasing automatically.

### 0.9.0: Multi-Repo Operator Workflow

- Add explicit `--repo` support.
- Add all-repo status.
- Improve `init` for adding and validating multiple repos.

## Open Questions

- Should Ralph rename `.agent/mr_title.md` and `.agent/mr_description.md` to
  `pr_title.md` and `pr_description.md`, or only make the filenames
  configurable?
- Should GitHub issue numbers be accepted as `42`, `#42`, or only a configured
  display form?
- How should branch kinds be derived for GitHub Issues when labels are missing?
- Should `finish` become `publish` in a future major version, with `finish`
  retained as an alias?
- Should state schema migrations be explicit, or should Ralph tolerate old state
  records opportunistically?

## Recommended Immediate Next Issues

1. Add configurable agent files directory.
2. Add `ralph setup-ignore` for Git global excludes.
3. Add configurable review title and description filenames.
4. Add custom review create command support.
5. Design provider-neutral ticket and review interfaces for GitHub support.
