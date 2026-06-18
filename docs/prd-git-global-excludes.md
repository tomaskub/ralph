# Git Global Excludes PRD

## Overview

Ralph should reduce setup friction by letting the operator configure one
operator-wide agent files directory and add that directory to Git global
excludes. Product repositories should not need Ralph-specific `.gitignore`
entries just to keep local agent context out of commits.

This is the 0.4.0 setup-friction feature. It changes where Ralph writes agent
files, not which files Ralph generates.

## Goals

- Add a top-level `[agent_files]` configuration section.
- Keep `.agent` as the default agent files directory.
- Let operators choose one alternate agent files directory when `.agent/`
  already has product meaning.
- Add `ralph setup-ignore` to append the configured directory pattern to Git
  global excludes.
- Update `doctor`, `start`, generated output, and `finish` safety checks to use
  the configured agent files directory.
- Avoid requiring product repo `.gitignore` changes.

## Non-Goals

- No per-repo agent files directory override.
- No generated filename changes.
- No provider-neutral review filename migration.
- No automatic Git global excludes writes during `ralph init`.
- No cleanup or normalization of existing Git global excludes entries.

## Configuration

Target config:

```toml
[agent_files]
directory = ".agent"
```

The `[agent_files]` section is top-level operator configuration. `ralph init`
should write it with the default `.agent` value, and existing config files that
omit the section should continue to behave as if `.agent` were configured.

The configured directory must be a single relative directory name. Reject empty
values, absolute paths, path separators, and parent-directory traversal. Treat
invalid values as configuration load errors.

If `.agent/` already means something in a product repo, the operator can choose
one alternate global directory:

```toml
[agent_files]
directory = ".ralph-agent"
```

## Agent Files

Default generated files remain:

```text
.agent/task.md
.agent/context.md
.agent/bootstrap-prompt.md
.agent/status.md
.agent/mr_title.md
.agent/mr_description.md
```

When the directory is changed, every generated path moves under the configured
directory, for example:

```text
.ralph-agent/task.md
.ralph-agent/context.md
.ralph-agent/bootstrap-prompt.md
.ralph-agent/status.md
.ralph-agent/mr_title.md
.ralph-agent/mr_description.md
```

User-facing output, errors, and generated bootstrap prompt text should use the
configured directory dynamically. Hardcoded `.agent/` language should remain
only where Ralph explicitly mentions legacy migration behavior.

Provider-neutral review filenames remain part of the later configurable
publishing work.

## Command

Add:

```text
ralph setup-ignore
ralph setup-ignore --yes
ralph setup-ignore --dry-run
```

Keep this as a separate explicit command. `ralph init` may surface
`ralph setup-ignore` as a next step, but it must not modify Git global excludes
inline.

`ralph setup-ignore` should:

- Read the configured agent files directory.
- Not require a valid configured product repo; this command configures
  operator-level Git ignore behavior, while `doctor` verifies product repo
  behavior.
- Resolve Git global excludes from
  `git config --global --path core.excludesfile`.
- If unset, use the standard default path `~/.config/git/ignore`.
- Show the exact Git global excludes path and ignore pattern.
- Create the parent directory if needed.
- Never remove or rewrite unrelated ignore entries.

## Pattern Append Rules

Append a short Ralph provenance comment and the unanchored
`<agent-directory>/` pattern only when the pattern is absent.

Use this provenance comment:

```text
# Ralph agent files
```

Example append for the default directory:

```text
# Ralph agent files
.agent/
```

Treat the pattern as present only when a non-comment line exactly matches after
trimming whitespace. Do not infer equivalence from broader Git ignore patterns
such as `.agent`, `**/.agent/`, or `/.agent/`.

If the exact pattern already exists, exit successfully without prompting or
writing. Do not add or backfill the comment.

Preserve existing file content and append safely. If the existing file does not
end with a newline, insert one before adding Ralph's comment and pattern, then
leave the file newline-terminated.

## Confirmation and Dry Run

Before writing, the command should show:

- Git global excludes path
- ignore pattern
- whether the file exists
- whether parent directories will be created

Then ask for confirmation.

`--yes` skips only the confirmation prompt.

`--dry-run` should print the resolved Git global excludes path, Ralph comment,
pattern, and whether parent directories would be created. It must not prompt or
write.

If the exact pattern is already present, the command should exit successfully
without prompting or writing, even without `--yes`.

## Doctor Behavior

`doctor` should check that the configured agent files directory is ignored in
the product repo with:

```text
git check-ignore <agent-directory>/test
```

Accept ignore coverage from repo `.gitignore`, `.git/info/exclude`, Git global
excludes, or any other Git ignore mechanism. If missing, suggest
`ralph setup-ignore`.

## Start Behavior

Preserve the current fail-fast safety gate. After creating the worktree and
before writing agent files, Ralph must verify that the configured agent files
directory is ignored.

If the check fails:

- mark the run `needs-attention`
- do not write agent files
- leave Git state in place for manual recovery, matching the current start
  failure behavior

## Finish Behavior

`finish` should reject committed files under the configured agent files
directory.

During migration, `finish` should also reject committed files under legacy
`.agent/` when the configured directory is different.

## Acceptance Criteria

- Existing configs without `[agent_files]` continue to behave as `.agent`.
- New configs written by `ralph init` include `[agent_files]`.
- Invalid `agent_files.directory` values fail during config load.
- `ralph setup-ignore --dry-run` reports intended changes without writing.
- `ralph setup-ignore` appends `# Ralph agent files` and the configured
  unanchored pattern only when the exact pattern is absent.
- `ralph setup-ignore --yes` performs the same write without prompting.
- Running `ralph setup-ignore` twice is idempotent and does not duplicate the
  comment or pattern.
- `doctor` checks `git check-ignore <agent-directory>/test` and suggests
  `ralph setup-ignore` when missing.
- `start` fails before writing agent files when the configured directory is not
  ignored.
- Generated agent files and bootstrap prompt text use the configured directory.
- `finish` rejects committed files under the configured directory and legacy
  `.agent/` during migration.
