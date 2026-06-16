# Agent Instructions

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `tomaskub/ralph`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five-label triage vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain-doc layout. See `docs/agents/domain.md`.

## Testing

Use `uv run ruff check .` for linting.
Use `uv run pytest` for the test suite.
