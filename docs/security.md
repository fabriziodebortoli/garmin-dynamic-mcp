# Security model

## What we protect

1. **Your Garmin key.** A Personal API key gives read access to your Garmin data until it expires (30 days to a year) or you
   revoke it.
2. **Your Garmin data**, which can include health information.
3. **Your machine and your MCP client configuration**, which `setup` modifies.

## Trust boundaries

- **The model is untrusted input.** It chooses an endpoint path and parameters. The server accepts a path only if it is in the
  catalog, validates every parameter against the catalog (unknown parameters are rejected, dates must be real `YYYY-MM-DD` dates,
  path values may contain only letters, digits, `-` and `_`), and builds the URL itself. There is no tool that accepts a URL.
- **Garmin's responses are data.** They are returned to the model as data, truncated and optionally reduced to chosen fields.
- **The catalog is reviewed by a human.** It is generated from Garmin's published specification by a script, but a change only
  reaches users through a pull request that a maintainer approves and a release that CI publishes. The running server never
  fetches a catalog or a specification.
- **Your MCP client is trusted** with the tool results, like with any other tool.

## Network destinations

| Who | Host | Why |
|---|---|---|
| server | `personal.connectapi.garmin.com` | token exchange (`POST`) and data (`GET` only) |
| server | `pypi.org` | once per run, check for a newer version (opt out: `GARMIN_MCP_NO_UPDATE_CHECK=1`) |
| `setup` | `personal.connectapi.garmin.com` | verify the key |
| `setup` | your browser opens `connect.garmin.com` | you create the key there |
| CI | `developer.garmin.com` | the daily catalog watcher |

Nothing else. In particular there is no telemetry.

## The key

- Stored with the OS keychain by default (Windows Credential Manager, macOS Keychain, Linux Secret Service).
- Lookup order in the server: environment variable `GARMIN_API_KEY` → keychain → owner-only file
  (`~/.config/garmin-dynamic-mcp/api-key`, only if you ran `setup --allow-file-storage` because no keychain exists).
- `setup` never writes the key into a client configuration file, and `doctor` never prints it.
- The access token (valid 24 hours) lives in memory only.
- The key is never logged and never part of an error message. Unexpected errors are reported by exception type only.
- `setup` clears the clipboard afterwards if it still holds the key you copied.
- **If a key leaks**, revoke it on Garmin Connect and run `setup` again. `uvx garmin-dynamic-mcp forget` removes the stored copy.

## What `setup` changes on your machine

It writes one `garmin` entry in the configuration of each client you confirm. It only edits files that parse as strict JSON
with the expected shape, backs a file up before its first change, writes atomically, changes nothing but the `garmin` entry
and asks before replacing a `garmin` entry it did not create. Claude Code and Codex CLI are configured through their own
commands. The entry runs `uvx garmin-dynamic-mcp==<version>`: pinned, so nothing changes under you.

## Updates and the supply chain

- Client entries pin an exact version. The server tells you when a newer one exists; you decide (`update`).
  We do not recommend `@latest` in a client configuration: a compromised release would reach everyone silently.
- Releases are built and published by GitHub Actions to PyPI with **trusted publishing** (OIDC, no stored token) and
  attestations, from the `pypi` environment.
- Third-party GitHub Actions are pinned by commit SHA; workflows use least-privilege `permissions`; Dependabot proposes
  updates with a seven-day cooldown.
- The catalog watcher can open a pull request but cannot merge or release. A human review of the endpoint diff is the gate.

## Known limits

- A model with access to your data can summarise it for the conversation provider; that is inherent to using a model on your data.
- On a machine without a keychain, the file fallback protects only against other users, not against processes running as you.
- The Personal API is read-only, but it can still expose sensitive data (health, nutrition, cycle tracking). The last two are
  off by default.

Report vulnerabilities as described in [SECURITY.md](../SECURITY.md).
