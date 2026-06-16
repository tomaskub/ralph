# RALPH

RALPH is a local operator CLI for repeatable AI-agent ticket work loops.

This repository currently contains the installable CLI foundation. Product
behavior is being added incrementally from the MVP PRD in `docs/prd.md`.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
```

