<!-- mcp-name: io.github.fabriziodebortoli/garmin-dynamic-mcp -->

# Garmin Dynamic MCP

[![CI](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/garmin-dynamic-mcp)](https://pypi.org/project/garmin-dynamic-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/garmin-dynamic-mcp)](https://pypi.org/project/garmin-dynamic-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/LICENSE)

**The Garmin Connect MCP server that updates itself when Garmin's API changes, and keeps your key in the OS keychain.**

Ask Claude, Cursor or any MCP client about your own Garmin data: activities, steps, sleep, HRV, Body Battery, stress,
weight and more. It runs on your computer, with your own personal key, read-only.

## Quick start

1. **Install [uv](https://docs.astral.sh/uv/)** (it downloads Python and everything else by itself):
   - Windows: `winget install astral-sh.uv`
   - macOS: `brew install uv`
   - Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Run the setup**, in a new terminal:

   ```bash
   uvx garmin-dynamic-mcp setup
   ```

   It opens Garmin's page where you create your key: <https://connect.garmin.com/app/settings/personalApiToken>.
   Create the key, copy it, come back to the terminal and press Enter. The setup reads the key from your
   clipboard (or paste it, hidden), checks it with Garmin, stores it in your system keychain and configures
   your MCP clients.
3. **Restart your MCP client** and ask: *"How many km did I run last week?"*

That's all. To check that everything works at any time: `uvx garmin-dynamic-mcp doctor`.

**Claude Desktop only, prefer clicking?** Download
[`garmin-dynamic-mcp.mcpb`](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/releases/latest/download/garmin-dynamic-mcp.mcpb)
from the latest release and double-click it (or *Settings → Extensions → Advanced settings → Install Extension*). Claude
Desktop asks for your key and stores it securely. It still needs [uv](https://docs.astral.sh/uv/) installed (step 1).

## What you can ask

Claude composes the requests itself and does the maths and the charts, so you are not limited to preset questions:

- "How many km did I run last week?"
- "What is my average cadence over my last ten runs?"
- "Chart the km I ran each day last month."
- "How did my sleep and HRV change over the last 90 days?"
- "Which weeks had the highest training load this year?"

## Supported clients

`setup` finds the clients installed on your machine and configures them. For anything else it prints the snippet to paste.

| Client | Configured by `setup` |
|---|---|
| Claude Desktop | yes (config file) |
| Claude Code | yes (`claude mcp add`, user scope) |
| Cursor | yes (`~/.cursor/mcp.json`) |
| VS Code | yes (user `mcp.json`) |
| Windsurf / Devin Desktop | yes, when its config file exists |
| Gemini CLI | yes, when `~/.gemini/settings.json` exists |
| Codex CLI | yes (`codex mcp add`) |
| Anything else (Zed, ...) | prints the snippet, see [Manual configuration](#manual-configuration) |

`setup` never touches a configuration file it cannot parse as plain JSON (for example one with comments): it prints
the snippet instead. Before its first change to a file it saves a backup next to it.

## How it stays up to date

Garmin's Personal API is new and still growing. This server does not hard-code its endpoints:

1. Every day a GitHub Action downloads Garmin's published OpenAPI specification and compares it with the one the
   catalog was built from.
2. If something changed (new endpoint, new parameter, different limit), the Action regenerates the endpoint catalog
   and opens a pull request that lists exactly what changed.
3. A maintainer reviews and merges it. A release is published automatically.
4. Your server tells you, inside the conversation, that a new version exists. You choose when to update:
   `uvx garmin-dynamic-mcp@latest update`, then restart your client.

The server never downloads a catalog by itself while running: what it can call is always something a human reviewed.
If Garmin changes the page the Action reads, it opens an issue instead of failing silently.

## Security

- **Your key stays in the OS keychain** (Windows Credential Manager, macOS Keychain, Linux Secret Service), not in a
  JSON file. `setup` never writes it into a client configuration.
- **Read-only and locked down.** Only `GET` requests, only to Garmin's API host, only to paths in the catalog, with
  validated parameters. Nothing accepts a free-form URL.
- **Sensitive data is off by default** (nutrition, menstrual cycle): see [Sensitive endpoints](#sensitive-endpoints).
- **No surprise updates.** Client configurations pin an exact version. The server only tells you when a newer one exists.
- **Supply chain.** Releases are built by CI and published to PyPI with trusted publishing (no stored token) and
  attestations; GitHub Actions are pinned by commit.

Details and the threat model: [docs/security.md](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/docs/security.md). To report a vulnerability: [SECURITY.md](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/SECURITY.md).

## Privacy

- The server runs on your computer. The key is sent only to Garmin.
- The only other connection it makes is a daily check of PyPI for a newer version (no data about you is sent).
  Disable it with `GARMIN_MCP_NO_UPDATE_CHECK=1`.
- What you ask Claude for becomes part of your conversation, like any tool result. Consider which questions you ask.
- Garmin's Personal API is for accessing **your own data** with **your own key**. Garmin does not intend it for commercial
  applications serving several users. Read [Garmin's terms](https://developer.garmin.com/gc-developer-program/personal/personal-faq/).

## Updating

When a newer version exists, the answers of the tools include an `update_available` note and Claude will tell you. To update:

```bash
uvx garmin-dynamic-mcp@latest update
```

then restart your MCP client. Prefer not to be told? Set `GARMIN_MCP_NO_UPDATE_CHECK=1` in the server's environment.

## Troubleshooting

Run `uvx garmin-dynamic-mcp doctor` first: it checks the key, the connection to Garmin, your version and every client
configuration, and never prints the key.

- **"expired or was revoked"**: create a new key on Garmin and run `uvx garmin-dynamic-mcp setup` again; it replaces the old one.
  Garmin emails you about a week before a key expires.
- **Claude Desktop does not start the server**: it may not see `uvx` on its PATH. `setup` writes the absolute path of
  `uvx`; if you moved it, run `setup` again. Quit Claude Desktop completely (also from the tray or the menu bar) and reopen it.
- **No system keychain** (some Linux servers): `setup --allow-file-storage` stores the key in an owner-only file instead.
- **A long period returns fewer rows than expected**: responses are capped (below); Claude is told how to narrow the request.

## Manual configuration

If you prefer to edit the configuration yourself, add this to your client's MCP servers (the key is read from the
keychain, so run `setup` once with `--clients none` first):

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": ["garmin-dynamic-mcp==0.2.1"]
    }
  }
}
```

VS Code uses the top-level key `servers` and needs `"type": "stdio"`. For Claude Code:

```bash
claude mcp add garmin --scope user -- uvx garmin-dynamic-mcp==0.2.1
```

If you do not want to use the keychain at all, set `GARMIN_API_KEY` in the server's `env` instead. That puts the key in
a plain-text file, which is why `setup` does not do it.

## What it reads, and its limits

Two generic tools: `list_endpoints` (what exists, with parameters; optional `query`) and `get` (call one endpoint).

- Activities (list, details, workouts), daily summaries, steps, sleep, HRV, stress, Body Battery, heart rate, SpO2, weight,
  hydration, heart-rate zones, fitness age, profile settings. The exact list is in
  [`catalog.json`](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/src/garmin_dynamic_mcp/catalog.json); [docs/garmin-api-findings.md](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/docs/garmin-api-findings.md) says
  which endpoints were verified against a real account.
- The server renews the 24-hour token, fetches activity pages (200 per request, up to 1000 activities per answer, at most
  20 requests), splits long date ranges where Garmin enforces a limit, lets Claude pick fields, and truncates answers at about
  40,000 characters with a note on how to narrow the request.
- It does not download `.FIT` files (second-by-second data) yet, and never writes anything to Garmin or your watch.

## Sensitive endpoints

Nutrition and menstrual-cycle endpoints are in the catalog but **disabled**. To enable them set
`GARMIN_MCP_ENABLE_SENSITIVE=1` in the server's environment. They have not been verified against a real account.

## Development

```bash
uv sync
uv run pytest                 # mocked HTTP, no key needed
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python scripts/fetch_openapi.py build/openapi.json
uv run python scripts/build_catalog.py build/openapi.json
```

See [CONTRIBUTING.md](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/CONTRIBUTING.md). Releases: [docs/releasing.md](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/docs/releasing.md).

## Disclaimer

This is an independent open-source project. It is **not affiliated with, endorsed by or supported by Garmin Ltd.**
"Garmin" and "Garmin Connect" are trademarks of Garmin Ltd. Use of the Personal API is subject to Garmin's terms.

## License

[MIT](https://github.com/fabriziodebortoli/garmin-dynamic-mcp/blob/main/LICENSE)
