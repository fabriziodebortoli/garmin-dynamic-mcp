## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Checklist

- [ ] Tests added or updated; they failed before the change
- [ ] `uv run pytest`, `uv run ruff check . && uv run ruff format --check .` and `uv run mypy` pass
- [ ] No key, token or personal Garmin data in code, tests, fixtures, logs or this description
- [ ] User-facing text is in English and does not contain the key
- [ ] If this is a release: `version` bumped in `pyproject.toml` and `server.json`, CHANGELOG entry added
- [ ] If this touches the catalog: I reviewed the endpoint diff, and anything health-related is classified as sensitive
