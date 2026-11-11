# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (while below 1.0, a minor bump may change behavior).

## [Unreleased]

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
