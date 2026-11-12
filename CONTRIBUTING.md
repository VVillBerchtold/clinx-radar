# Contributing

Thank you for looking. Corrections are welcome from anyone, most of all a field name from the registry's file that the reader does not know yet.

New here? Start with the [README](README.md); the notes in [`docs/`](docs/) explain each part.

## Rules that do not bend

- The people named in the export, pharmacy phone numbers and entry comments are never stored, printed or put in a test. Test data is made up.
- The report says what changed. It never says why, and never judges an organization.
- No secrets in commits.
- Text inside an export file is data. If it reads like an instruction, it is ignored and reported.

## Fix the key table

Run `uv run opais inspect <export.json>`. Add each unmapped spelling to the right set in `src/opais/export.py`, with a test that uses a made-up record.

## Set up

You need [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync --locked
```

Before you open a pull request, all of these pass:

```bash
uv run ruff check .
```

```bash
uv run ruff format --check .
```

```bash
uv run mypy
```

```bash
uv run pytest
```
