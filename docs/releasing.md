# Releasing

There is one release path. A release happens when a **version bump and a CHANGELOG entry reach `main`** and the version in
`pyproject.toml` has no tag yet. `.github/workflows/release.yml` then tests, builds, publishes to PyPI, creates the tag
`vX.Y.Z` and the GitHub release (notes = the CHANGELOG section), and publishes `server.json` to the MCP Registry.

## Two ways to reach `main`

1. **Garmin changed its API.** The daily `catalog-watch` workflow opens a pull request on the branch `catalog-update` with the
   regenerated catalog, a version bump (minor if endpoints were added or removed, patch otherwise), the CHANGELOG entry and
   `uv.lock`. Review the endpoint diff in the pull request body, in particular:
   - new endpoints are unverified and become callable by every user once released;
   - anything health-related under a new service name should be classified as sensitive (see `SENSITIVE_PREFIXES` in
     `scripts/build_catalog.py`).

   Merging the pull request releases it.
2. **A code change.** Open a pull request that also bumps `version` in `pyproject.toml` and `server.json` (both `version` fields)
   and adds a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md`. Tests check that the three agree.

## One-time repository setup

On GitHub (Settings):

- **Actions → General → Workflow permissions:** allow GitHub Actions to create and approve pull requests (the catalog watcher
  needs it).
- **Environments:** create the environment `pypi` and set **Deployment branches** to `main` only. Add yourself as a required
  reviewer for a manual gate. PyPI trusted publishing binds the repository, the workflow file and the environment name but
  **not the branch**, so the environment's branch rule (plus the `github.ref == 'refs/heads/main'` guard in `release.yml`) is
  what stops a manual run on another branch from publishing.
- **Code security:** enable private vulnerability reporting, secret scanning with push protection, Dependabot alerts.
- **Branches:** protect `main`: require pull requests, **Require review from Code Owners** (otherwise `CODEOWNERS` does
  nothing), and the checks `lint`, `test (ubuntu-latest, 3.10)` and the other `test (...)`
  and `build` jobs of `ci.yml`.
- **Pages:** source "GitHub Actions" (for the landing page).

On PyPI, add a *pending trusted publisher* for the project `garmin-dynamic-mcp` (account → Publishing): owner
`fabriziodebortoli`, repository `garmin-dynamic-mcp`, workflow `release.yml`, environment `pypi`. **Do this before the first push
to `main`**: that push starts the first release.

The MCP Registry publication uses GitHub OIDC and needs no secret. The registry checks that the PyPI package description
contains `mcp-name: io.github.fabriziodebortoli/garmin-dynamic-mcp` (the README has it as an HTML comment).

## If a release fails half way

The jobs run in order (test → build → PyPI → GitHub release → MCP Registry). If a late job fails, use **Re-run failed jobs**
on that run: it repeats only the failed ones with the earlier results. Do not start a new run: PyPI already has the version, so
a fresh run would stop at the duplicate upload.

## If the catalog watcher breaks

It opens an issue labelled `catalog-watch-broken` when it cannot read Garmin's specification (usually because Garmin changed the
Swagger page). Fix `scripts/fetch_openapi.py` (`tests/fixtures` show what it expects), merge, and the next run closes the issue.

## Claude Desktop extension (MCPB) — status: verified in Claude Desktop, attached to every release

Verified by the maintainer in Claude Desktop with the 0.2.1 bundle. `release.yml` builds it in the read-only `mcpb` job (after
PyPI has the version) and `github-release` attaches `garmin-dynamic-mcp.mcpb` to every release; the README links the stable
`releases/latest/download/garmin-dynamic-mcp.mcpb` URL. The rest of this section is the original background.

### Background (before it was verified)

`mcpb/` holds a one-click Claude Desktop extension (`server.type: "uv"`, the key is a `sensitive` user setting that Claude
Desktop stores securely and passes as `GARMIN_API_KEY`). `uv run python scripts/build_mcpb.py X.Y.Z` validates and packs it
with the official MCPB CLI into `build/garmin-dynamic-mcp.mcpb`.

It is **not attached to releases yet**, because it has not been confirmed that current Claude Desktop runs `uv`-type bundles
(Anthropic's own documentation recommends Node and does not mention `uv`). To decide:

1. After the first PyPI release, build the bundle for that version and install it in Claude Desktop (double-click the file,
   enter a key, ask a question).
2. If it works: add a build step to `release.yml` (before `github-release`, upload `build/garmin-dynamic-mcp.mcpb` and attach
   it with `gh release create ... dist/* garmin-dynamic-mcp.mcpb`), and add a "One-click install for Claude Desktop" line to
   the README.
3. If it does not: delete `mcpb/`, `scripts/build_mcpb.py` and `tests/test_build_mcpb.py`, and record why here.
