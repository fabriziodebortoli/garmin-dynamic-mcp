# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (while below 1.0, a minor bump may change behavior).

## [Unreleased]

## [0.2.2] - 2026-11-11

### Fixed

- A key that Garmin no longer knows (deleted, or replaced by a newer one) makes the token exchange answer HTTP 404
  ("Personal API Key ... does not exist"). It used to be reported as a generic Garmin error; it now says the key has
  expired or was revoked and tells the user to create a new one and run `setup`.

## [0.2.1] - 2026-11-11

### Fixed

- `setup`: the key prompt now says that pressing Enter reads the key from the clipboard, shows `*` for each character
  and how many characters were received, and accepts Ctrl+V on Windows (pasting into the hidden prompt used to produce
  a key that Garmin rejected as expired). Control characters left by a paste are dropped.
- `setup`: a key that Garmin rejects now reports its length and suggests the clipboard route.
- `setup`, `doctor` and `update`: Claude Code and Codex are checked with `mcp get garmin` instead of `mcp list`, which
  health-checks every registered server and took about 18 seconds with 60 servers (now about 3 seconds).
- `setup`, `doctor` and `update` show what they are doing (a spinner on a terminal) while a client is configured.

## [0.2.0] - 2026-11-10

First public release.

### Added

- Two generic, read-only MCP tools, `list_endpoints` and `get`, over Garmin's Personal API.
- `garmin-dynamic-mcp setup`: opens Garmin's key page, reads the key from the clipboard, verifies it,
  stores it in the OS keychain and configures Claude Desktop, Claude Code, Cursor, VS Code, Windsurf,
  Gemini CLI and Codex CLI. `doctor`, `update` and `forget` commands.
- Endpoint catalog generated from Garmin's OpenAPI specification, with provenance (source, hash, date),
  date-range limits read from the specification, and a daily GitHub Action that opens a pull request
  when Garmin changes its API.
- Update notice (`update_available`) when a newer release exists; opt out with `GARMIN_MCP_NO_UPDATE_CHECK=1`.
- Automatic token exchange, activity pagination, splitting of long date ranges, field selection and
  response truncation.

### Security

- The key is kept in the OS keychain, never in client configuration files.
- Only GET requests to Garmin's API host, only catalog paths, with validated parameters.
- Nutrition and menstrual-cycle endpoints are disabled unless `GARMIN_MCP_ENABLE_SENSITIVE=1`.
