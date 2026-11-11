# Security policy

## Supported versions

Only the latest release receives security fixes. Run `uvx garmin-dynamic-mcp doctor` to see whether you are up to date.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.** Use GitHub's private reporting:
<https://github.com/fabriziodebortoli/garmin-dynamic-mcp/security/advisories/new>

Include what you found, how to reproduce it and what you think the impact is. You will get an answer within a few days;
this is a volunteer project, so please be patient. We will agree with you on a fix and on when to disclose it.

**Never include your Garmin key or a token in a report.** If you think a key was exposed, revoke it right away on
<https://connect.garmin.com/app/settings/personalApiToken> and create a new one.

## What is in scope

- Anything that lets the server call a host other than Garmin's API host, or send anything other than `GET` requests
  (apart from the token exchange).
- Anything that lets a model or a crafted parameter reach a path outside the endpoint catalog.
- The key, or a token, ending up in a log, an error message, a client configuration or a file.
- Weaknesses in the setup command's handling of client configuration files (corruption, unexpected overwrites).
- Problems in the release or catalog-update workflows that could let someone publish an unreviewed release.

## What is out of scope

- Vulnerabilities in Garmin's own services (report those to Garmin).
- Anything that needs an attacker who already controls your computer or your MCP client.
- Garmin data appearing in your conversation with a model: that is how the tool works. Choose your questions with care.

The threat model and the design choices behind these rules are in [docs/security.md](docs/security.md).
