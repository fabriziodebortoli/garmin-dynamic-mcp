# garmin-dynamic-mcp — design

Date: 2026-11-10. Supersedes `2026-11-10-garmin-mcp-design.md` (the first, Italian, colleagues-only design). The server built from that design exists and works: this document turns it into a public, community-grade project.

## Intent

Give any MCP client (Claude Desktop, Claude Code, Cursor, VS Code, …) generic, read-only access to the user's own Garmin Connect data through Garmin's **Personal API**, so people can ask whatever they want ("how many km did I run last week?", "chart my sleep vs. HRV for the last 3 months") without the server anticipating the questions.

Fabrizio wants this repository to become **the reference MCP server for Garmin**, with more GitHub stars than the existing alternative, `Mason-Levyy/garmin-personal-mcp` (66 stars, one tool per endpoint, PyPI + MCP Registry + Docker). The two key points that must set it apart are **security** and **dynamism**, plus the easiest installation of any Garmin MCP server.

## What makes it different

1. **Dynamic.** A daily GitHub Action re-extracts Garmin's API specification. When Garmin adds or changes endpoints, a pull request regenerates the endpoint catalog automatically; after a human approves it, a release ships and every running server tells its user that an update is available. Nothing in the server needs code changes for a new endpoint.
2. **Secure.** The key lives in the OS keychain, never in a client config file. The server can only make GET requests to Garmin's API host, only to catalog paths, with validated parameters. Sensitive health data is off by default. Releases are built and published by CI with provenance.
3. **One command to install.** `uvx garmin-dynamic-mcp setup` opens Garmin's key page, picks the key up from the clipboard, verifies it, stores it in the keychain and configures the user's MCP clients.

## Goals

1. A stranger arriving from a Reddit post sees, at the top of the README, one link to Garmin's key page and one command to copy. Five minutes later they ask their first question.
2. A new or changed Garmin endpoint reaches users with no code change: daily detection, auto-generated PR, human approval, automated release, in-chat update notice.
3. The key is never written in plain text in any client config, log, error message or file in the repository.
4. Everything public is in English and the repository looks impeccably maintained (CI on three OSes, badges, security policy, contribution guide, changelog, templates).
5. Discoverable: PyPI, the official MCP Registry, the main "awesome MCP" lists.

## Non-goals (phase 1)

- `.FIT` file download (second-by-second data). It is **phase 2**, to start only after everything in phase 1 is done. The catalog keeps excluding `/download-service/files/activity/{activityId}` until then.
- Docker image or remote HTTP transport. A personal key on a shared or remote server works against the security story. *(Builder's call recorded here: my call, not Fabrizio's.)*
- Any write to Garmin (the Personal API is read-only anyway).
- Per-question tools (`get_weekly_distance`, …). The surface stays generic.
- Fetching Garmin's spec at runtime. The catalog a user runs is always one a human reviewed.

## Anti-goals (failure even if it "works")

- The key ends up in a client config file, a log, an error, a test fixture, a commit, an issue template example.
- The server, or `setup`, talks to any host other than those listed under "Network destinations".
- An update installs itself without the user choosing it.
- `setup` corrupts or silently rewrites a client config the user edited by hand (other servers, comments, formatting they care about).
- A Garmin page change breaks the catalog watcher and nobody notices.
- Installation needs the user to manage Python, virtual environments or dependencies.

## Decisions by Fabrizio

- Stay on Python with `uv`/`uvx` (not a TypeScript rewrite).
- Compete with Mason-Levyy's server rather than contribute to it. Success = more stars, the reference Garmin MCP.
- Install flow: README top shows the Garmin key link and one command; `setup` opens the key page and acquires the key from the clipboard (Garmin has no callback/OAuth flow, so automatic capture without the user copying it is not possible safely).
- Configure **all common MCP clients**, not only Claude.
- Change detection with a GitHub Action, daily (it is a light operation).
- When a newer version exists, the server **notifies and lets the user decide**. No auto-update (no `@latest` in configs).
- Everything in English; repository care must be perfect.
- `.FIT` download after everything else.
- GitHub repository already renamed to `fabriziodebortoli/garmin-dynamic-mcp` (public, empty). PyPI account `fdebortoli` exists. The name `garmin-dynamic-mcp` is free on PyPI.

## Current state (what is reused)

The server built before this design (the colleagues-only version, 97 tests passing). Modules: `errors`, `catalog` (allow-list + validation + path-param regex), `auth` (key → 24 h JWT, cached, expiry warning), `client` (single host, 401 retry, 429/upstream/network mapping), `compact` (`fields`, default activity view, 40 000-char truncation), `fetch` (activity pagination 200/page up to 1000, date-range splitting with `max_range_days`, 20-request cap), `server` (`list_endpoints`, `get`), `scripts/build_catalog.py`, `scripts/live_probe.py`. Facts verified against a live account are in `docs/garmin-api-findings.md`.

All of that stays; phase 1 renames, translates, hardens and extends it.

## Phase 1 — what gets built

### 1. Rename and translate

- Distribution `garmin-dynamic-mcp`, import package `garmin_dynamic_mcp`, console script `garmin-dynamic-mcp`, MCP server name `garmin`.
- All user-facing text in English: tool descriptions, server instructions, error messages, CLI output, README, docs, code comments, docstrings, test names. Garmin's own summaries stay as Garmin wrote them.
- The superseded Italian design and plan leave the tree (they remain in history only if Fabrizio keeps the history; see "Publication").
- `docs/garmin-api-findings.md` is rewritten in English and stripped of anything personal (no history depth of a specific account, no activity counts).

### 2. CLI

`garmin-dynamic-mcp` with no subcommand runs the stdio MCP server (that is what client configs launch). If stdin is a terminal, it first prints one line to stderr: "This is an MCP server. To configure it run: uvx garmin-dynamic-mcp setup", then serves as usual.

Subcommands:

- **`setup`** — interactive, the one command in the README.
  1. Prints the key page URL (`https://connect.garmin.com/app/settings/personalApiToken`) and opens it in the default browser.
  2. Tells the user to create a key and copy it, then press Enter. Input is read with a hidden prompt: if the user pasted the key, that is used; if they just press Enter, the key is read from the clipboard.
  3. Normalizes the key (existing `normalize_key`), verifies it by exchanging it for a token. On failure it explains why (rejected, network) and asks again; nothing is stored.
  4. Stores it in the OS keychain (service `garmin-dynamic-mcp`, account `api-key`). If the clipboard still holds the key, clears it.
  5. Detects installed clients and asks which to configure (all detected ones preselected). Writes each config (see "Client configuration").
  6. Prints what was done per client, the restart instruction, and a first question to try.
  - Non-interactive flags for scripting and tests: `--key-stdin`, `--clients <list>|all|none`, `--yes`.
  - Re-running `setup` replaces the key (that is the documented path when a key expires) and leaves correct client entries unchanged.
- **`doctor`** — reports, without ever printing the key: where the key comes from (env / keychain / file), whether the token exchange works and the token lifetime, installed vs latest version, which clients have a `garmin` entry and which version it pins. Exit code 0 only if everything is fine.
- **`update`** — rewrites the version pin in every client entry that `setup` created to the version currently running. The update notice tells users to run `uvx garmin-dynamic-mcp@latest update`, then restart their client.
- **`forget`** — removes the key from the keychain (and fallback file), and optionally (`--clients`) removes the `garmin` entries from client configs.

### 3. Key storage

- Library `keyring` (Windows Credential Manager, macOS Keychain, Linux Secret Service).
- Lookup order in the server: `GARMIN_API_KEY` environment variable (kept for CI, containers of their own, and the existing manual setup) → keychain → fallback file.
- Fallback file only when no keychain backend is available (typically headless Linux): `setup` explains the risk and asks for explicit confirmation, then writes `~/.config/garmin-dynamic-mcp/api-key` with owner-only permissions (0600 on POSIX; on Windows the keychain always exists). *(My call.)*
- The key is never logged, never part of an exception message, never in client configs written by `setup`.
- Error messages that today mention `GARMIN_API_KEY` now say: run `uvx garmin-dynamic-mcp setup`.

### 4. Client configuration

`setup` writes a stdio server entry named `garmin`:

- `command`: absolute path of `uvx` (found with `shutil.which`; GUI apps like Claude Desktop often don't inherit the user's PATH). If `uvx` is not found, `setup` explains how to install `uv` and stops.
- `args`: `["garmin-dynamic-mcp==<running version>"]` — pinned, so updates only happen through `update`.
- no `env` block (the key comes from the keychain).

Supported clients (paths and formats in the appendix, verified from official docs):

- Claude Desktop, Cursor, VS Code, Windsurf/Devin Desktop, Gemini CLI: JSON file, merged in place.
- Claude Code and Codex CLI: through their own CLIs (`claude mcp add`, `codex mcp add`) when they are on PATH. This avoids editing `~/.claude.json` and avoids a TOML-writing dependency.
- Any other client (Zed, Antigravity, …): `setup` prints the generic snippet to paste.
- A client counts as "detected" when its config file or its config directory exists, or its CLI is on PATH.

Rules for touching a config file:

- Read it; if it does not parse as strict JSON (VS Code allows comments) or has an unexpected shape, **do not write**: print the snippet and the file path instead.
- Back it up next to itself (`<name>.bak-garmin-<timestamp>`) before the first change.
- Change only the `garmin` entry; keep everything else as it was (other servers, key order). Formatting: 2-space indent.
- Write atomically (temp file + rename).
- If a `garmin` entry already exists and was not created by us (different command), ask before replacing it.

### 5. Dynamic catalog pipeline

- `scripts/fetch_openapi.py` (new, from the extraction script used during development): downloads `https://developer.garmin.com/gc-developer-program/personal/swagger-docs/`, finds the page bundle whose name contains `swagger-docs`, extracts the embedded `JSON.parse('{"openapi":…}')` string, unescapes and parses it. Verified on 2026-11-10: the result is identical to the spec used to build the current catalog. Fails loudly (non-zero exit, clear message) if the page, the bundle or the marker is missing, or if the result is not OpenAPI 3.x with at least one path.
- `scripts/build_catalog.py` gains:
  - range limits parsed from Garmin's descriptions ("maximum of 31 days", "maximum of 28 days", "maximum of 1 year" → 366), so new endpoints arrive with their limits without a live probe. Values in `catalog_overrides.json` (measured) still win.
  - provenance in `catalog.json`: `source_url`, `spec_sha256` (of the canonical JSON), `generated_at`. *(The full OpenAPI document is no longer committed: only the derived catalog. This avoids redistributing Garmin's spec wholesale; diffs are computed on the catalog. My call.)*
  - new endpoints get `verified: false`; sensitive classification by path prefix as today.
- `scripts/diff_catalog.py`: Markdown summary of two catalogs — endpoints added/removed, parameters added/removed/changed, limit changes, summary changes.
- Workflow `catalog-watch.yml`: daily cron and manual trigger. Fetch → build → if `spec_sha256` changed: run tests, open or update a single PR (branch `catalog-update`) with the diff summary as body and a label. If fetching fails: open (or comment on an existing) issue labelled `catalog-watch-broken`. Light: one page and one ~2.5 MB bundle per day.
- The auto-PR also bumps the version in `pyproject.toml` (minor when endpoints are added or removed, patch otherwise; we are in 0.x) and adds a CHANGELOG entry generated from the diff. Merging it is the human approval; the release follows automatically (see "Distribution and release").
- CI on the auto-PR: PRs created with the default `GITHUB_TOKEN` do not trigger other workflows, but `workflow_dispatch` is the documented exception. The watcher therefore dispatches `ci.yml` on the `catalog-update` branch (`actions: write`), so the required checks run on the PR head commit. No PAT or GitHub App secret is needed. *(My call; if required checks do not attach this way, fall back to not requiring checks for that branch and say so in the docs.)*

### 6. Update notice

- On the first tool call of each server process, a background check asks `https://pypi.org/pypi/garmin-dynamic-mcp/json` for the latest version (timeout 3 s). Failure is silent and never delays or breaks a tool call.
- If a newer version exists, every `get` and `list_endpoints` response includes `update_available: {"current", "latest", "how_to_update": "uvx garmin-dynamic-mcp@latest update, then restart your MCP client", "release_notes": "<GitHub release URL>"}`. Tool descriptions tell the model to tell the user once.
- Opt out with `GARMIN_MCP_NO_UPDATE_CHECK=1`.

### 7. Tool surface

Unchanged shape: `list_endpoints` and `get(path, params, fields)`. *(My call, departing from `docs/project_spec.md`, which asked for one `garmin_api` tool addressed by `operationId`: Garmin's spec has no operationIds (0 of 26), so the path is the natural stable identifier, and the two-tool shape is already built, tested and simple for models to use.)*

- `list_endpoints` gains an optional `query` (case-insensitive substring over path and summary) so the list stays usable when Garmin adds many endpoints.
- Both tools get MCP annotations: `readOnlyHint: true`, `openWorldHint: true`, plus a title.
- `get` responses keep `data`, `partial`, `notes`, `key_warning`, and add `update_available` when relevant.

### 8. Hardening (from the earlier review and from the competitor's open issues)

- Regexes with `fullmatch` and ASCII semantics; non-ASCII characters and BOM in the key handled by `normalize_key`.
- `max_range_days` 366 for `/usersummary-service/v2/dailysummaries` (documented "1 year").
- Activity search: negative or non-integer `limit`/`start` rejected; a non-list response raised as an upstream error.
- Notes when `fields` selects names that are null in every item ("no item has field X — check the name with list_endpoints") and when a range returns days with no data at all (the competitor's "sleep all-null" issue).
- 3xx responses treated as upstream errors, not as empty bodies; non-JSON bodies reported as upstream errors, never as "unreachable".
- A mid-run error during range splitting keeps the chunks already read and returns them as a partial result with a note.
- Token refresh tolerant to small clock skew.
- Test gaps flagged by the earlier review closed.

### 9. Distribution and release

- One release path for everything: a version bump plus CHANGELOG entry merged into `main` (by the catalog auto-PR or by a hand-written release PR). `release.yml` runs on push to `main` (and manually); if the version in `pyproject.toml` has no tag yet, it builds, tests, publishes to PyPI via **Trusted Publishing** (environment `pypi`, `id-token: write`, attestations on), creates the tag `vX.Y.Z` and a GitHub Release with the CHANGELOG section as notes. Doing it all in one workflow avoids the "tags pushed by `GITHUB_TOKEN` don't trigger workflows" trap. *(My call.)*
- Same workflow publishes `server.json` to the official MCP Registry (namespace `io.github.fabriziodebortoli/garmin-dynamic-mcp`, GitHub OIDC). The README carries the `mcp-name:` marker the registry uses to verify PyPI ownership.
- Version starts at `0.2.0` (0.1.0 was the colleagues-only build; never published).
- Claude Desktop one-click extension (`.mcpb`): built and attached to each GitHub Release if MCPB can run a uv-based Python server without the user installing Python; otherwise left out. See appendix.
- Submissions to "awesome MCP" lists and the launch post are Fabrizio's to send; the builder prepares the text.

### 10. Repository care

- `README.md`: badges (CI, PyPI version, Python versions, license), one-sentence pitch, **Quick start** (link to the key page, one line to install `uv` per OS, `uvx garmin-dynamic-mcp setup`, restart, a first question), example questions, supported clients table, how dynamism works, security model, privacy, updating, troubleshooting (`doctor`), manual configuration, sensitive endpoints, development, disclaimer, license.
- `SECURITY.md` (private reporting via GitHub Security Advisories, scope, threat model summary), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `CHANGELOG.md` (Keep a Changelog), issue templates (bug, feature, endpoint problem) with a "never paste your key" warning, PR template, `CODEOWNERS`, `dependabot.yml` (pip and actions).
- `docs/security.md`: threat model, network destinations, what the key can do, where it is stored.
- CI (`ci.yml`): ruff (lint + format), mypy, pytest with coverage on Ubuntu, macOS, Windows × Python 3.10 and 3.13; build check (`uv build`, `twine check`). All third-party actions pinned by commit SHA; least-privilege `permissions`.
- Disclaimer: not affiliated with or endorsed by Garmin; "Garmin" is a trademark of Garmin Ltd.
- MIT license, copyright Fabrizio De Bortoli.
- A one-page GitHub Pages landing (static, English, built from the README content: pitch, quick start, supported clients, security), deployed by a workflow. Last item of phase 1. *(My call: `docs/project_spec.md` asked for it and it fits "reference for the community".)*
- `docs/project_spec.md` (Fabrizio's Italian working notes) stays out of the repository: it is superseded by this design and everything public is in English.

### 11. Acceptance (phase 1 is done when)

- All CI checks green on the three OSes; `uv build` and `twine check` pass.
- From a clean machine state (no cache), `uvx garmin-dynamic-mcp setup` with a real key configures Claude Desktop on Windows and Claude Code, and a first question is answered. Fabrizio runs this once; the builder prepares the checklist.
- The README quick start is followed by someone other than the builder (Fabrizio or a colleague) without help.
- The catalog watcher has run once manually and produced either "no change" or a correct PR.
- `doctor` reports green on Fabrizio's machine.
- No secret in the repository or its history (scan with a secret scanner before the first push).

## Network destinations

| Who | Host | Why |
|---|---|---|
| server | `personal.connectapi.garmin.com` | token exchange and data (GET only) |
| server | `pypi.org` | daily update check (opt-out) |
| `setup` | `personal.connectapi.garmin.com` | verify the key |
| `setup` | browser opens `connect.garmin.com` | the user creates the key |
| CI | `developer.garmin.com` | catalog watcher |

## Security model (summary)

- Trust boundary: the model is untrusted input. It can only pick a catalog path and parameters; the server validates both and builds the URL itself.
- What a stolen key gives: read access to that user's Garmin data until the key expires or is revoked. Hence: keychain, no plain-text configs, short-lived tokens in memory only.
- Supply chain: pinned versions in client configs, no auto-update, Trusted Publishing with attestations, SHA-pinned actions, Dependabot.
- Catalog changes are reviewed by a human before release; the server never loads a catalog from the network.

## Testing

- TDD for all new code, HTTP mocked with respx; no real key in the repo.
- `setup`/`doctor`/`update`/`forget` tested with a temporary home directory, an in-memory keyring backend, fake clipboard and fake browser.
- Config writers tested per client: new file, existing file with other servers, existing `garmin` entry, comments/invalid JSON (must not write), backup and atomic write.
- Catalog pipeline tested on fixtures (a saved bundle excerpt, specs with added/removed endpoints); the daily workflow is exercised once with a manual run.
- Live test (`-m live`) still skipped without a key.

## Publication (Fabrizio's steps, with the builder's help)

1. Revoke the development key on Garmin Connect (it was pasted in a chat).
2. Decide on git history: existing commits are in Italian and carry a work e-mail address. Options are to publish as is or to start the public repository from one clean commit authored with a GitHub no-reply address. The builder asks before pushing.
3. On PyPI, add a pending Trusted Publisher for `garmin-dynamic-mcp` (owner `fabriziodebortoli`, repo `garmin-dynamic-mcp`, workflow `release.yml`, environment `pypi`).
4. On GitHub: enable private vulnerability reporting, secret scanning and push protection, Dependabot alerts, branch protection on `main`; create the `pypi` environment.
5. Authorize the first push and the first tag.

Nothing is pushed, tagged or published without Fabrizio's explicit go-ahead for that step.

## Left to the builder

- Module layout for the CLI and config writers; whether to use `argparse` or a small dependency.
- Clipboard access without heavy dependencies (PowerShell `Get-Clipboard`/`Set-Clipboard` on Windows, `pbpaste`/`pbcopy` on macOS, `wl-paste`/`xclip`/`xsel` on Linux, hidden prompt as fallback).
- Exact wording of messages, README and community files.
- Coverage threshold, mypy strictness.

## Phase 2 (after phase 1 is complete)

`.FIT` download: an endpoint to fetch an activity's original file and a way to give Claude usable data from it (for example a parsed, down-sampled summary), with a strict output directory. Separate design when phase 1 is done.

## Appendix — client config facts (checked 2026-11-10)

| Client | Where | Shape | Source |
|---|---|---|---|
| Claude Desktop | Windows `%APPDATA%\Claude\claude_desktop_config.json`; macOS `~/Library/Application Support/Claude/claude_desktop_config.json`; Linux `~/.config/Claude/claude_desktop_config.json` (only if it exists; Linux support unofficial) | `{"mcpServers": {"garmin": {"command", "args"}}}` | modelcontextprotocol.io/docs/develop/connect-local-servers |
| Claude Code | CLI: `claude mcp add --scope user --transport stdio garmin -- <uvx> garmin-dynamic-mcp==X.Y.Z`; replace with `claude mcp remove garmin --scope user` first | stored by Claude Code in `~/.claude.json` | code.claude.com/docs/en/mcp |
| Cursor | `~/.cursor/mcp.json` | `{"mcpServers": {"garmin": {"type": "stdio", "command", "args"}}}` | cursor.com/docs/context/mcp |
| VS Code | user `mcp.json`: Windows `%APPDATA%\Code\User\mcp.json`, macOS `~/Library/Application Support/Code/User/mcp.json`, Linux `~/.config/Code/User/mcp.json` (per-OS paths not in the official docs; standard user-settings folder) | `{"servers": {"garmin": {"type": "stdio", "command", "args"}}}`; file may contain comments → snippet only | code.visualstudio.com/docs/copilot/reference/mcp-configuration |
| Windsurf / Devin Desktop | official pages disagree: `~/.codeium/windsurf/mcp_config.json` (legacy), `~/.codeium/mcp_config.json`, `~/.config/devin/mcp_config.json`; write each one that already exists | `{"mcpServers": {...}}` | docs.devin.ai/desktop/cascade/mcp |
| Gemini CLI | `~/.gemini/settings.json` (only if it exists; Gemini CLI was retired for consumer plans in June 2026) | `{"mcpServers": {...}}` among other settings | geminicli.com/docs/tools/mcp-server |
| Codex CLI | CLI: `codex mcp add garmin -- <uvx> garmin-dynamic-mcp==X.Y.Z` | stored in `~/.codex/config.toml` | learn.chatgpt.com/docs/extend/mcp |
| Zed, Antigravity, others | snippet printed | Zed: `context_servers` | zed.dev/docs/ai/mcp |

**MCPB (Claude Desktop one-click).** The MCPB spec defines `server.type: "uv"` (manifest 0.4) where the host installs dependencies with uv and the user needs no Python; secrets declared in `user_config` with `sensitive: true` are stored by Claude Desktop in the OS keychain and passed as an environment variable (the server already honors `GARMIN_API_KEY`). Anthropic's own MCPB page does not mention uv and recommends Node, so support in current Claude Desktop is unconfirmed. Plan: build the bundle as the last phase-1 item, have Fabrizio install it once in Claude Desktop; ship it with releases only if that works.

**MCP Registry.** `server.json` (schema `2025-12-11`), `name: io.github.fabriziodebortoli/garmin-dynamic-mcp`, package `{registryType: "pypi", identifier: "garmin-dynamic-mcp", transport: {type: "stdio"}}`, optional secret env var `GARMIN_API_KEY`. README contains `<!-- mcp-name: io.github.fabriziodebortoli/garmin-dynamic-mcp -->`. Published from Actions with `mcp-publisher login github-oidc` after the PyPI upload.

**PyPI Trusted Publishing.** Pending publisher created from the account's "Publishing" page; it does not reserve the name until the first upload. `pypa/gh-action-pypi-publish` with job-level `id-token: write` and environment `pypi`; PEP 740 attestations are on by default.

**keyring.** 25.x; Windows Credential Locker, macOS Keychain, Linux Secret Service/KWallet. Without a backend, `get_password` raises `keyring.errors.NoKeyringError` → fallback file path described in "Key storage".
