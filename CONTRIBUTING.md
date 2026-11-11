# Contributing

Thank you for helping. This project aims to be the reference MCP server for Garmin Connect, so quality and security matter more
than speed.

## Setup

You need [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/fabriziodebortoli/garmin-dynamic-mcp
cd garmin-dynamic-mcp
uv sync
```

## Before you open a pull request

```bash
uv run pytest                      # HTTP is mocked: no Garmin key needed
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

All three run in CI on Windows, macOS and Linux.

- **Write the test first.** New behavior and bug fixes come with a test that failed before the change.
- **Never put a real key, token or personal Garmin data** in a test, fixture, issue, log or commit. Tests use fake values such as
  `test-key`. The suite replaces the OS keychain with an in-memory one, so running it never touches yours.
- Keep messages shown to users in English, short, and telling the user what to do next. Never include the key in a message.
- Keep the public surface small: the server has two generic tools on purpose.

## Where things are

| Path | What it is |
|---|---|
| `src/garmin_dynamic_mcp/` | the server and the CLI |
| `src/garmin_dynamic_mcp/catalog.json` | generated endpoint catalog: do not edit by hand |
| `src/garmin_dynamic_mcp/catalog_overrides.json` | measured facts per endpoint (verified, page size, range limits) |
| `scripts/` | catalog pipeline, release helpers, the live probe |
| `docs/garmin-api-findings.md` | what the real API does that its specification does not say |

## The catalog

Never edit `catalog.json`. It is built from Garmin's specification:

```bash
uv run python scripts/fetch_openapi.py build/openapi.json
uv run python scripts/build_catalog.py build/openapi.json --force
```

A fact the specification does not state (an endpoint's real page size or range limit, that it works) goes in
`catalog_overrides.json`. If you have a Garmin key you can measure it with `scripts/live_probe.py`
(`GARMIN_API_KEY=... uv run python scripts/live_probe.py`): it never calls sensitive endpoints and writes only outcomes and field
names. Do not commit its raw report (`build/`).

## Reporting an endpoint that misbehaves

Use the "Endpoint problem" issue form. Include the path, the parameters and the error message. **Never paste your Garmin key** and
trim personal values from any response you include.

## Commits and pull requests

Small, focused commits with a clear message (`fix:`, `feat:`, `docs:`, `ci:`, `chore:`). Describe the why in the pull request.
Releases are described in [docs/releasing.md](docs/releasing.md).

By contributing you agree that your contribution is licensed under the MIT license, and to follow our
[Code of Conduct](CODE_OF_CONDUCT.md). Security problems: see [SECURITY.md](SECURITY.md), not a public issue.
