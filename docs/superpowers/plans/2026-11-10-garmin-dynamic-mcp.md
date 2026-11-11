# garmin-dynamic-mcp Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the working colleagues-only `garmin-mcp` server into the public, English, keychain-secured, self-updating-catalog `garmin-dynamic-mcp`, with a one-command `setup` for all common MCP clients and a community-grade repository.

**Architecture:** The existing core (catalog allow-list, token manager, client, fetcher, compaction, two MCP tools) is renamed and translated, then extended with four new modules: `keystore` (OS keychain), `clients` (config writers), `clipboard`, `updates` (PyPI check), and a `cli` front end (`serve` default, `setup`, `doctor`, `update`, `forget`). Repository scripts and GitHub workflows implement the daily catalog watcher and a single "merge to main → release" path.

**Tech Stack:** Python ≥3.10, uv/uvx, `mcp>=2,<3` (`MCPServer`), httpx, keyring, pytest + pytest-asyncio + respx + pytest-cov, ruff, mypy, hatchling, GitHub Actions, PyPI Trusted Publishing, MCP Registry `mcp-publisher`.

**Spec:** `docs/superpowers/specs/2026-11-10-garmin-dynamic-mcp-design.md`

## Global Constraints

- Distribution `garmin-dynamic-mcp`, import package `garmin_dynamic_mcp`, console script `garmin-dynamic-mcp`, MCP server name `garmin`, version `0.2.0`.
- All user-facing text, comments, docstrings, test names and docs in English. Garmin's own summaries stay verbatim.
- The API key is never logged, printed, put in an exception message, written to a client config, or committed. Tests use only fake keys such as `"test-key"`.
- Network destinations: server → `personal.connectapi.garmin.com` (GET + token POST) and `pypi.org` (update check, opt-out `GARMIN_MCP_NO_UPDATE_CHECK=1`); `setup` → `personal.connectapi.garmin.com` and the browser to `connect.garmin.com`; CI → `developer.garmin.com`. Nothing else.
- Keychain: `keyring`, service `garmin-dynamic-mcp`, account `api-key`. Key lookup order: env `GARMIN_API_KEY` → keychain → fallback file `~/.config/garmin-dynamic-mcp/api-key` (0600).
- Client entries written by `setup`: name `garmin`, `command` = absolute path of `uvx`, `args` = `["garmin-dynamic-mcp==<running version>"]`, no `env`.
- Sensitive endpoints stay gated by `GARMIN_MCP_ENABLE_SENSITIVE=1`. `/download-service/files/activity/{activityId}` stays excluded (phase 2).
- Existing limits unchanged: 200 activities/page, 1000 activities and 20 requests per call, 40 000-char responses.
- Every third-party GitHub Action pinned by full commit SHA with the tag in a trailing comment; workflow `permissions` least-privilege, default `contents: read`.
- Nothing is pushed, tagged or published without Fabrizio's explicit go-ahead for that step.

## Review Focus

- A client config file that exists but is empty (0 bytes) or whitespace → treated as `{}` and written; a file containing comments or invalid JSON → never written, snippet printed. (Task 7)
- A key copied with surrounding whitespace, newline, quotes or a UTF-8 BOM (clipboard on Windows) → normalized before verification and storage. (Task 3)
- `uvx` living under a path with spaces (`C:\Users\Name Surname\...`) → stored as one JSON string and passed to `claude`/`codex` as a single argv element, never through a shell. (Task 7)
- Keychain present but locked or access denied (a `KeyringError` that is not `NoKeyringError`) when the server starts → clear "run `uvx garmin-dynamic-mcp doctor`" error from the tool, no crash, no traceback with secrets. (Task 3)
- PyPI unreachable, slow, returning HTML, or a pre-release as latest → no `update_available`, no delay beyond 3 s, no error in the tool call. (Task 5)

---

### Task 1: Rename, translate, version 0.2.0, lint and type baseline

**Files:**
- Move: `src/garmin_mcp/` → `src/garmin_dynamic_mcp/` (all modules, `catalog.json`, `catalog_overrides.json`)
- Modify: every module in `src/garmin_dynamic_mcp/`, `scripts/build_catalog.py`, `scripts/live_probe.py`, all `tests/*.py`, `pyproject.toml`, `.gitignore`
- Delete: `docs/superpowers/specs/2026-11-10-garmin-mcp-design.md`, `docs/superpowers/plans/2026-11-10-garmin-mcp.md`

**Interfaces:**
- Produces: package `garmin_dynamic_mcp` with the same public names as before (`GarminError`, `Catalog`, `load_catalog`, `TokenManager`, `normalize_key`, `GarminClient`, `Fetcher`, `compact`, `truncate`, `build_server`). `load_catalog` reads `resources.files("garmin_dynamic_mcp")`.

- [ ] **Step 1:** `git mv src/garmin_mcp src/garmin_dynamic_mcp`; replace `garmin_mcp` imports everywhere (src, scripts, tests).
- [ ] **Step 2:** Translate every user-facing string to English, keeping meaning. Tests that assert on message text are updated to the English wording (assert on stable fragments such as `"expired or revoked"`, `"Unknown path"`, `"YYYY-MM-DD"`). Translate comments, docstrings, test names, CLI output of scripts.
- [ ] **Step 3:** `pyproject.toml`: `name = "garmin-dynamic-mcp"`, `version = "0.2.0"`, English description ("Dynamic, secure, read-only MCP server for the Garmin Connect Personal API"), `license = "MIT"`, `authors`, `keywords`, `classifiers` (Python 3.10–3.13, OS Independent, Typing :: Typed), `[project.urls]` (Homepage, Repository, Issues, Changelog → `https://github.com/fabriziodebortoli/garmin-dynamic-mcp…`), dependency `keyring>=25`, dev group adds `pytest-cov>=5`, `ruff>=0.6`, `mypy>=1.11`; wheel packages `["src/garmin_dynamic_mcp"]`; marker text in English. Temporarily keep script `garmin-dynamic-mcp = "garmin_dynamic_mcp.server:main"` (Task 9 switches it to the CLI). Add `py.typed`.
- [ ] **Step 4:** Add `[tool.ruff]` (`line-length = 110`, `target-version = "py310"`, lint `select = ["E","F","W","I","B","UP","S","SIM","RUF"]`, tests ignore `S101`) and `[tool.mypy]` (`python_version = "3.10"`, `strict = true`, `files = ["src"]`). Fix findings until clean.
- [ ] **Step 5:** Delete the two superseded Italian docs.
- [ ] **Step 6: Verify**

Run: `uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: no lint/type errors; `97 passed, 1 skipped`; `grep -rn "garmin_mcp" src scripts tests` returns nothing.

- [ ] **Step 7: Commit** — `refactor: rename to garmin-dynamic-mcp, English everywhere, lint and type baseline`

---

### Task 2: Core hardening

**Files:**
- Modify: `src/garmin_dynamic_mcp/{auth,catalog,client,fetch,compact}.py`, `src/garmin_dynamic_mcp/catalog_overrides.json`, regenerate `catalog.json`
- Test: `tests/test_auth.py`, `tests/test_catalog.py`, `tests/test_client.py`, `tests/test_fetch.py`, `tests/test_compact.py`

**Interfaces:**
- Produces: `normalize_key(raw: str | None) -> str` (now also strips `\ufeff` and rejects internal whitespace/non-ASCII with `GarminError("key_missing", …)` whose message never contains the key); `compact(path, data, fields) -> tuple[Any, list[str]]` (**signature change**: returns notes too); `FetchResult` unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_normalize_key_strips_bom_quotes_and_newlines():
    assert normalize_key('\ufeff "abc-123"\r\n') == "abc-123"


def test_normalize_key_rejects_inner_whitespace_without_echoing_it():
    with pytest.raises(GarminError) as e:
        normalize_key("abc 123")
    assert "abc" not in e.value.message


@pytest.mark.parametrize("value", ["2026-11-01\n", "12\n", "١٢٣"])  # trailing newline, Arabic-Indic digits
def test_validation_uses_full_ascii_match(catalog, value): ...  # each raises GarminError("invalid_request")


def test_dailysummaries_limit_is_366():
    assert load_catalog().endpoints["/usersummary-service/v2/dailysummaries"].max_range_days == 366


@pytest.mark.parametrize("params", [{"limit": "-5"}, {"limit": "2.5"}, {"start": "-1"}])
async def test_activity_search_rejects_bad_numbers(fetcher, params): ...  # GarminError invalid_request


async def test_activity_search_non_list_response_is_upstream_error(fetcher, respx_mock): ...  # body {"error":"x"}


async def test_redirect_is_upstream_error_not_empty(client, respx_mock): ...  # 302 → GarminError("upstream")


async def test_chunk_error_keeps_previous_chunks_as_partial(fetcher, respx_mock):
    # steps endpoint, 60-day window, first chunk 200 OK, second chunk 500
    result = await fetcher.fetch(STEPS, {"startDate": "2026-01-01", "endDate": "2026-03-01"})
    assert result.partial and len(result.data) == len(FIRST_CHUNK)
    assert "2026-01-29" in result.notes[0]  # first day not covered


async def test_token_refreshed_with_clock_skew(): ...  # exp 30 s ahead of clock is treated as expired (margin 60 s kept) and a token whose iat is 120 s in the future is accepted


def test_fields_all_null_adds_note():
    data, notes = compact(ACTIVITY_SEARCH_PATH, [{"a": 1}, {"a": 2}], ["a", "distnace"])
    assert any("distnace" in n for n in notes)


def test_items_with_no_data_add_note():
    data, notes = compact(
        "/sleep-service/sleep/dailySleepSummariesByDate",
        [{"calendarDate": "2026-11-01", "sleepTimeSeconds": None, "deepSleepSeconds": None}],
        None,
    )
    assert any("no data" in n for n in notes)
```

- [ ] **Step 2: Run** `uv run pytest -q` → the new tests FAIL.
- [ ] **Step 3: Implement.**
  - Regexes compiled with `re.ASCII` and used with `fullmatch`.
  - `max_range_days: 366` for dailysummaries in `catalog_overrides.json`; regenerate the catalog (Task 6 later replaces the source of truth; for now run the existing build script on `scripts/openapi.json`).
  - Activity search: `start`/`limit` must match `^\d+$`; a non-list page raises `GarminError("upstream", …)`.
  - Client: any 3xx → `GarminError("upstream", "Garmin answered with an unexpected redirect (HTTP 3xx)…")`; use `follow_redirects=False`.
  - `_chunked`: on `GarminError` after at least one chunk, return the merged chunks with `partial=True` and a note naming the covered range, the first missing day and the error message; with zero chunks, re-raise.
  - "No data" note: for list results, count items whose values other than date-like keys (`calendarDate`, `date`, keys ending in `Date`) are all `None`; note `"N of M items have no data (the device recorded nothing for those days)."`.
  - "Unknown field" note: for each requested field that is `None` in every item of a non-empty list → `"No item has field 'X'; check the name (fields are dotted paths, e.g. activityType.typeKey)."`.
  - Server passes compact notes into `notes`.
- [ ] **Step 4: Run** `uv run pytest -q && uv run mypy && uv run ruff check .` → all PASS.
- [ ] **Step 5: Commit** — `fix: stricter validation, partial results on chunk errors, no-data and unknown-field notes`

---

### Task 3: Keystore

**Files:**
- Create: `src/garmin_dynamic_mcp/keystore.py`
- Modify: `src/garmin_dynamic_mcp/server.py` (`_Runtime.ensure` uses the loader), `src/garmin_dynamic_mcp/auth.py` (messages point to `setup`), `tests/conftest.py`
- Test: `tests/test_keystore.py`, `tests/test_server.py`

**Interfaces:**
- Produces:
  - `SERVICE = "garmin-dynamic-mcp"`, `ACCOUNT = "api-key"`, `KeySource = Literal["env", "keychain", "file"]`
  - `fallback_path(home: Path | None = None) -> Path` → `<home>/.config/garmin-dynamic-mcp/api-key`
  - `keychain_available() -> bool` (False when the active backend is `keyring.backends.fail.Keyring` or priority ≤ 0)
  - `load_key(env: Mapping[str, str], home: Path | None = None) -> tuple[str, KeySource]` — raises `GarminError("key_missing", "No Garmin key found. Run: uvx garmin-dynamic-mcp setup")`; a `KeyringError` that is not "missing" raises `GarminError("key_missing", "The system keychain could not be read (…type name…). Run: uvx garmin-dynamic-mcp doctor")`
  - `save_key(key: str, *, allow_file: bool = False, home: Path | None = None) -> KeySource` — raises `KeychainUnavailable` (subclass of `Exception`) if no keychain and `allow_file` is False
  - `delete_key(home: Path | None = None) -> list[KeySource]` — removes from keychain and file, returns where it was found
  - `build_server(env, http=None, key_loader: Callable[[Mapping[str, str]], tuple[str, KeySource]] = load_key)`
  - `tests/conftest.py`: autouse fixture installing an in-memory `keyring` backend (`MemoryKeyring(KeyringBackend)` with `priority = 1`) so no test touches the real keychain; fixture `no_keychain` that installs `keyring.backends.fail.Keyring()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_env_wins_over_keychain():
    keyring.set_password(SERVICE, ACCOUNT, "kc")
    assert load_key({"GARMIN_API_KEY": " env "}) == ("env", "env")


def test_keychain_used_when_no_env():
    keyring.set_password(SERVICE, ACCOUNT, "kc")
    assert load_key({}) == ("kc", "keychain")


def test_file_fallback(tmp_path, no_keychain): ...  # file content "\ufeffkey\n" → ("key", "file")
def test_missing_everywhere_says_run_setup(
    tmp_path, no_keychain
): ...  # message contains "uvx garmin-dynamic-mcp setup"
def test_locked_keychain_gives_doctor_hint(
    tmp_path, monkeypatch
): ...  # get_password raises KeyringError("denied") → GarminError mentions "doctor", not "denied"? (message contains type name only)
def test_save_without_keychain_requires_allow_file(
    tmp_path, no_keychain
): ...  # raises KeychainUnavailable; with allow_file=True writes file
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_fallback_file_is_owner_only(tmp_path, no_keychain): ...  # stat mode & 0o777 == 0o600
def test_delete_reports_sources(tmp_path): ...
async def test_server_tool_without_key_says_run_setup(): ...  # build_server({}, http, key_loader=raising) → ToolError text contains "setup"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_keystore.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `keystore.py`. File write: create parent dirs, `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`, then `os.chmod(path, 0o600)` on POSIX. Keys go through `normalize_key`. `auth.py` messages: rejected key → `"…Create a new key at {KEY_PAGE} and run: uvx garmin-dynamic-mcp setup"`; expiry warning likewise.
- [ ] **Step 4: Run** `uv run pytest -q && uv run mypy` → PASS.
- [ ] **Step 5: Commit** — `feat: keep the key in the OS keychain (env and owner-only file fallbacks)`

---

### Task 4: Tool surface — `query`, annotations, titles

**Files:**
- Modify: `src/garmin_dynamic_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `list_endpoints(query: str | None = None) -> str`; both tools registered with `title` and `ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False, idempotentHint=True)` (from `mcp.types`; check the `MCPServer.tool()` kwargs in the installed mcp 2.x and use them).

- [ ] **Step 1: Write the failing tests**

```python
async def test_list_endpoints_query_filters_case_insensitive(client):
    out = json.loads(await call(client, "list_endpoints", {"query": "SLEEP"}))
    assert out["endpoints"] and all("sleep" in (e["path"] + e["summary"]).lower() for e in out["endpoints"])


async def test_tools_are_read_only_annotated(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["get"].annotations.readOnlyHint is True and tools["list_endpoints"].title
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Empty result for a query returns `{"endpoints": [], "note": "No endpoint matches '<query>'. Call list_endpoints without query to see all."}`.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** — `feat: list_endpoints query filter and read-only tool annotations`

---

### Task 5: Update notice

**Files:**
- Create: `src/garmin_dynamic_mcp/updates.py`, `src/garmin_dynamic_mcp/version.py`
- Modify: `src/garmin_dynamic_mcp/server.py`
- Test: `tests/test_updates.py`, `tests/test_server.py`

**Interfaces:**
- Produces:
  - `version.py`: `__version__: str` from `importlib.metadata.version("garmin-dynamic-mcp")`, fallback `"0.0.0"`.
  - `PYPI_URL = "https://pypi.org/pypi/garmin-dynamic-mcp/json"`, `RELEASES_URL = "https://github.com/fabriziodebortoli/garmin-dynamic-mcp/releases/tag/v{version}"`
  - `parse_version(text: str) -> tuple[int, ...] | None` (only `X.Y.Z` digits; pre-releases/dev → None)
  - `class UpdateChecker(current: str, http: httpx.AsyncClient, env: Mapping[str, str])` with `def start(self) -> None` (spawns the check once as an asyncio task, no-op when disabled or already started) and `@property notice -> dict[str, str] | None` returning `{"current", "latest", "how_to_update": "Run: uvx garmin-dynamic-mcp@latest update — then restart your MCP client.", "release_notes": RELEASES_URL.format(...)}`.
  - Server: both tools call `checker.start()`; `get` payload and `list_endpoints` payload include `"update_available"` only when `notice` is not None. Tool docstrings: "If update_available is present, tell the user once."

- [ ] **Step 1: Write the failing tests**

```python
async def test_newer_version_produces_notice(
    respx_mock,
): ...  # PyPI {"info": {"version": "0.3.0"}}, current "0.2.0" → notice["latest"] == "0.3.0"
@pytest.mark.parametrize("body,status", [("<html>", 200), ('{"info":{"version":"0.3.0rc1"}}', 200), ("", 503)])
async def test_bad_or_prerelease_answers_give_no_notice(respx_mock, body, status): ...
async def test_timeout_gives_no_notice_and_tool_is_not_delayed(
    respx_mock,
): ...  # route side_effect sleeps 10 s; get returns in < 1 s and has no update_available
async def test_opt_out_makes_no_request(respx_mock): ...  # env GARMIN_MCP_NO_UPDATE_CHECK=1 → route.called is False
async def test_check_runs_once_per_process(respx_mock): ...  # two start() calls → one request
async def test_get_includes_update_available(client_with_newer_pypi): ...
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Request with `timeout=3.0`; any exception or non-200 → no notice; the tool never awaits the task (it reads `notice` as it is at that moment).
- [ ] **Step 4: Run** `uv run pytest -q && uv run mypy` → PASS.
- [ ] **Step 5: Commit** — `feat: tell the user when a newer release exists (opt-out)`

---

### Task 6: Dynamic catalog pipeline (scripts)

**Files:**
- Create: `scripts/fetch_openapi.py`, `scripts/diff_catalog.py`, `scripts/prepare_catalog_release.py`, `tests/fixtures/swagger_page.html` (trimmed: just the `<script src=…>` tags), `tests/fixtures/swagger_bundle.js` (a short JS file containing `JSON.parse('…')` with a 2-path OpenAPI document using `\'` and `\u00e8` escapes)
- Modify: `scripts/build_catalog.py`, `.gitignore` (`build/`)
- Delete: `scripts/openapi.json` (no longer committed)
- Test: `tests/test_fetch_openapi.py`, `tests/test_build_catalog.py` (move the catalog-building tests here), `tests/test_diff_catalog.py`, `tests/test_prepare_release.py`

**Interfaces:**
- Produces:
  - `fetch_openapi.py`: `SWAGGER_PAGE = "https://developer.garmin.com/gc-developer-program/personal/swagger-docs/"`; `find_bundle_url(html: str, base: str) -> str`; `extract_spec(bundle_js: str) -> dict[str, Any]`; `fetch_spec(http: httpx.Client) -> tuple[dict[str, Any], str]`; `main(argv) -> int` writes the spec to `argv[1]` (default `build/openapi.json`). Raises/exit 1 with a one-line reason: `"swagger page has no swagger-docs bundle"`, `"bundle has no embedded OpenAPI document"`, `"not an OpenAPI 3.x document with paths"`.
  - `build_catalog.py`: `parse_range_limit(text: str) -> int | None`; `spec_sha256(openapi: dict) -> str` (sha256 of `json.dumps(openapi, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`); `build_catalog(openapi, overrides, *, generated_at: str) -> dict` with top-level `source_url` (= `SWAGGER_PAGE`), `spec_sha256`, `generated_at`, `endpoints`; CLI `python scripts/build_catalog.py build/openapi.json [--check]` — `--check` prints `unchanged`/`changed` by comparing `spec_sha256` with the committed catalog and writes nothing; without it, writes only if the hash changed (so `generated_at` doesn't churn).
  - `diff_catalog.py`: `@dataclass CatalogDiff(added: list[str], removed: list[str], changed: dict[str, list[str]])`; `diff_catalogs(old: dict, new: dict) -> CatalogDiff`; `to_markdown(d: CatalogDiff) -> str`; `bump_kind(d) -> Literal["minor", "patch", "none"]` (added or removed → minor; only changed → patch; nothing → none). CLI: `python scripts/diff_catalog.py OLD NEW` prints Markdown.
  - `prepare_catalog_release.py`: `bump_version(version: str, kind: str) -> str`; `add_changelog_entry(changelog: str, version: str, date: str, body: str) -> str` (inserts `## [X.Y.Z] - DATE` under `## [Unreleased]`); CLI `python scripts/prepare_catalog_release.py OLD_CATALOG NEW_CATALOG` updates `pyproject.toml` version, `server.json` versions (Task 11 creates it; skip if absent), `CHANGELOG.md`, and writes the PR body to `build/pr_body.md`; exit 0 and no edits when `bump_kind == "none"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_find_bundle_url(): assert find_bundle_url(PAGE, "https://developer.garmin.com").endswith("swagger-docs-js-715115a6210d45afc282.js")
def test_extract_spec_unescapes(): spec = extract_spec(BUNDLE); assert spec["openapi"].startswith("3.") and "è" in spec["paths"]["/a"]["get"]["summary"]
@pytest.mark.parametrize("bad", ["<html></html>", "var x = 1;"]) def test_missing_markers_fail_loudly(bad): ...
@pytest.mark.parametrize("text,days", [("maximum of 31 days", 31), ("Maximum of 28 days.", 28), ("maximum of 1 year", 366), ("no limit here", None)])
def test_parse_range_limit(text, days): assert parse_range_limit(text) == days
def test_override_beats_parsed_limit(): ...
def test_new_endpoint_is_unverified_and_sensitive_by_prefix(): ...
def test_hash_is_stable_across_key_order(): ...
def test_diff_added_removed_changed(): ...  # param added on one path → changed[path] contains "param added: x"
def test_bump_kind(): ...
def test_add_changelog_entry_under_unreleased(): ...
def test_current_catalog_matches_live_spec_hash():  # regression guard
    assert load_catalog_json()["spec_sha256"] == "<hash computed in Step 3>"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Port the extraction loop from the development scratch script (scan from the `'` after `JSON.parse(` to the matching unescaped `'`, unescape `\\n \\t \\r \\uXXXX \\xXX \\<char>`). Range text searched in operation summary, description and parameter descriptions; regex `maximum of (\d+)\s*(day|days|year|years)` case-insensitive; years × 366. Run `uv run python scripts/fetch_openapi.py build/openapi.json` once and `uv run python scripts/build_catalog.py build/openapi.json`; confirm the endpoint list is unchanged from the previous catalog except the new top-level fields and parsed limits that agree with overrides; record the hash in the regression test. Delete `scripts/openapi.json`; update `scripts/live_probe.py` docs to use `build/openapi.json`.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check .` → PASS.
- [ ] **Step 5: Commit** — `feat: catalog pipeline — fetch Garmin's spec, parse limits, provenance, diff and release prep`

---

### Task 7: Client config writers

**Files:**
- Create: `src/garmin_dynamic_mcp/clients.py`
- Test: `tests/test_clients.py`

**Interfaces:**
- Produces:
  - `SERVER_NAME = "garmin"`, `PACKAGE = "garmin-dynamic-mcp"`
  - `@dataclass(frozen=True) class ClientSpec: id: str; name: str; kind: Literal["json", "cli"]; paths: tuple[Path, ...] = (); root_key: str = "mcpServers"; entry_extra: Mapping[str, str] = {}; cli: str | None = None`
  - `known_clients(home: Path, platform: str, environ: Mapping[str, str]) -> list[ClientSpec]` with ids `claude-desktop`, `claude-code` (cli `claude`), `cursor` (`entry_extra={"type": "stdio"}`), `vscode` (`root_key="servers"`, `entry_extra={"type": "stdio"}`), `windsurf` (all three Windsurf/Devin paths), `gemini`, `codex` (cli `codex`); paths per the spec's appendix (Windows uses `environ["APPDATA"]`).
  - `detected_paths(spec: ClientSpec, which: Callable[[str], str | None]) -> list[Path]` — for json: paths whose file or parent directory exists (Claude Desktop Linux and Gemini: file must exist); for cli: `[]` but `is_detected` true when `which(spec.cli)`.
  - `is_detected(spec, which) -> bool`
  - `server_entry(uvx: str, version: str, extra: Mapping[str, str] = {}) -> dict[str, Any]` → `{**extra, "command": uvx, "args": [f"{PACKAGE}=={version}"]}`
  - `is_ours(entry: Mapping[str, Any]) -> bool` — any arg starts with `"garmin-dynamic-mcp"`
  - `pinned_version(entry) -> str | None`
  - `@dataclass class WriteResult: client: str; status: Literal["written", "unchanged", "skipped", "snippet", "removed", "error"]; detail: str; path: Path | None = None`
  - `write_json_entry(client: str, path: Path, root_key: str, entry: dict, *, confirm_replace: Callable[[dict], bool], now: Callable[[], datetime]) -> WriteResult`
  - `remove_json_entry(client: str, path: Path, root_key: str) -> WriteResult`
  - `read_json_entry(path: Path, root_key: str) -> dict | None`
  - `configure_cli(spec: ClientSpec, uvx: str, version: str, run: Callable[..., subprocess.CompletedProcess]) -> WriteResult` — Claude Code: `[claude, "mcp", "remove", "garmin", "--scope", "user"]` (ignore failure) then `[claude, "mcp", "add", "--scope", "user", "--transport", "stdio", "garmin", "--", uvx, f"{PACKAGE}=={version}"]`; Codex: `[codex, "mcp", "remove", "garmin"]` then `[codex, "mcp", "add", "garmin", "--", uvx, …]`. `run` called with a list, `shell=False`, `capture_output=True`, `text=True`, `timeout=30`.
  - `remove_cli(spec, run) -> WriteResult`
  - `generic_snippet(uvx: str, version: str) -> str` — pretty JSON `{"mcpServers": {"garmin": {...}}}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_writes_new_file(
    tmp_path,
): ...  # file absent, parent exists → created with {"mcpServers":{"garmin":{...}}}, status "written"
@pytest.mark.parametrize("content", ["", "  \n"])
def test_empty_file_is_treated_as_empty_object(tmp_path, content): ...
def test_keeps_other_servers_and_key_order(
    tmp_path,
): ...  # {"mcpServers":{"a":{...}},"other":1} → a and other untouched, order preserved
def test_comments_or_invalid_json_are_never_written(
    tmp_path,
): ...  # '{ // c\n }' → status "snippet", file bytes unchanged
def test_unexpected_shape_is_never_written(tmp_path): ...  # {"mcpServers": []}
def test_backup_created_once(
    tmp_path,
): ...  # first write creates claude_desktop_config.json.bak-garmin-<ts>; second write no new backup
def test_same_entry_is_unchanged(tmp_path): ...
def test_foreign_garmin_entry_needs_confirmation(
    tmp_path,
): ...  # confirm_replace returns False → "skipped", file unchanged
def test_vscode_uses_servers_and_type_stdio(tmp_path): ...
def test_uvx_path_with_spaces_kept_as_one_string(tmp_path): ...
def test_cli_client_uses_argv_without_shell(): ...  # fake run records calls; uvx "C:\\Users\\A B\\uvx.exe" is one element; shell not passed or False
def test_cli_failure_reports_error_without_raising(): ...
def test_remove_entry(tmp_path): ...
def test_known_clients_windows_paths(
    tmp_path,
): ...  # APPDATA → <appdata>/Claude/claude_desktop_config.json, <appdata>/Code/User/mcp.json
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Strict parse with `json.loads`; root must be a dict and `root_key` (if present) a dict. Write: `json.dumps(data, indent=2, ensure_ascii=False) + "\n"` to `path.with_suffix(path.suffix + ".tmp")` then `os.replace`. Backup name `f"{path.name}.bak-garmin-{now():%Y%m%d%H%M%S}"`, only when no `*.bak-garmin-*` sibling exists and the file existed with content.
- [ ] **Step 4: Run** `uv run pytest tests/test_clients.py -q && uv run mypy` → PASS.
- [ ] **Step 5: Commit** — `feat: MCP client config writers (JSON merge, CLI clients, safe writes)`

---

### Task 8: Clipboard helper

**Files:**
- Create: `src/garmin_dynamic_mcp/clipboard.py`
- Test: `tests/test_clipboard.py`

**Interfaces:**
- Produces: `read_clipboard(*, platform: str = sys.platform, which=shutil.which, run=subprocess.run) -> str | None`; `clear_clipboard_if(value: str, *, platform=…, which=…, run=…) -> bool` (clears only if the clipboard currently equals `value` after normalization).
  - Windows: `["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]` / `Set-Clipboard -Value $null`… use `["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ' '"]` if `$null` is rejected; macOS: `pbpaste` / `pbcopy` with empty stdin; Linux: first available of `wl-paste --no-newline` / `xclip -selection clipboard -o` / `xsel --clipboard --output` and the matching clear commands. Any failure → `None` / `False`.

- [ ] **Step 1: Write the failing tests** — fake `run`/`which`: `test_windows_reads_with_powershell`, `test_macos_reads_with_pbpaste`, `test_linux_prefers_wl_paste_then_xclip`, `test_no_tool_returns_none`, `test_command_failure_returns_none`, `test_clear_only_when_clipboard_still_holds_value`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat: clipboard helper for setup`

---

### Task 9: CLI — serve, setup, doctor, update, forget

**Files:**
- Create: `src/garmin_dynamic_mcp/cli.py`, `src/garmin_dynamic_mcp/__main__.py`
- Modify: `pyproject.toml` (script → `garmin_dynamic_mcp.cli:main`), `src/garmin_dynamic_mcp/server.py` (`main` → `serve()`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `keystore.*` (Task 3), `clients.*` (Task 7), `clipboard.*` (Task 8), `updates.parse_version`, `PYPI_URL` (Task 5), `auth.TokenManager`, `auth.KEY_PAGE`, `version.__version__`.
- Produces:
  - `@dataclass class Deps: stdin_isatty: Callable[[], bool]; getpass: Callable[[str], str]; ask: Callable[[str], str]; out: TextIO; err: TextIO; open_browser: Callable[[str], bool]; read_clipboard: Callable[[], str | None]; clear_clipboard_if: Callable[[str], bool]; which: Callable[[str], str | None]; run: Callable[..., Any]; home: Path; platform: str; environ: Mapping[str, str]; http_factory: Callable[[], httpx.AsyncClient]; now: Callable[[], datetime]` and `default_deps() -> Deps`.
  - `async def verify_key(key: str, http: httpx.AsyncClient) -> float` → token lifetime in seconds; raises `GarminError`.
  - `main(argv: list[str] | None = None, deps: Deps | None = None) -> int`. No subcommand → if `stdin_isatty()` print the hint line to `err`, then `serve()`.
  - `setup` flags: `--key-stdin`, `--clients` (comma list of client ids, `all`, or `none`), `--yes`, `--allow-file-storage`.
  - `doctor` (no flags), `update` (no flags), `forget` with `--clients`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_setup_happy_path(tmp_home, respx_token_ok):
    # deps: getpass returns "" (→ clipboard "  test-key\n"), which("uvx") → "/u/bin/uvx", Claude Desktop dir exists, ask→"y"
    code = main(["setup"], deps)
    assert code == 0 and keyring.get_password(SERVICE, ACCOUNT) == "test-key"
    assert deps.opened == [KEY_PAGE] and deps.cleared == ["test-key"]
    entry = json.loads(desktop_cfg.read_text())["mcpServers"]["garmin"]
    assert entry == {"command": "/u/bin/uvx", "args": ["garmin-dynamic-mcp==" + __version__]}
    assert "test-key" not in deps.out.getvalue() + deps.err.getvalue()

async def test_setup_rejected_key_asks_again_and_stores_nothing(...): ...  # first token POST 401, second 200
async def test_setup_without_uvx_stops_with_install_hint(...): ...  # exit 1, message contains "astral.sh/uv"
async def test_setup_no_keychain_needs_allow_file(...): ...  # without flag: exit 1 and nothing written; with --allow-file-storage: file written
async def test_setup_twice_is_idempotent(...): ...  # second run reports "unchanged" for Claude Desktop
async def test_setup_noninteractive(...): ...  # --key-stdin --clients cursor,vscode --yes
async def test_setup_prints_snippet_for_unparseable_config(...): ...
async def test_doctor_all_green_exit_0_and_never_prints_key(...): ...
async def test_doctor_missing_key_exit_1(...): ...
async def test_update_rewrites_pins_only_for_our_entries(...): ...  # cursor entry pinned 0.1.9 → current version; foreign entry untouched
async def test_forget_removes_key_and_optionally_entries(...): ...
def test_no_subcommand_on_tty_prints_hint(monkeypatch): ...  # serve patched to a no-op
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `argparse` (no new dependency). `setup` copy (exact first lines):
  ```
  Garmin Dynamic MCP setup
  1. Create a Personal API key on Garmin Connect (opening it in your browser):
     https://connect.garmin.com/app/settings/personalApiToken
  2. Copy the key, then come back here.
  Paste the key and press Enter, or just press Enter to read it from the clipboard:
  ```
  Final lines: per-client result lines (`✓ Claude Desktop — written (…path…)`, `• VS Code — paste this into …`), then `Restart your MCP client(s), then ask: "How many km did I run last week?"`. Use ASCII fallbacks if `out.encoding` cannot encode `✓`.
  `doctor` checks, one line each, `OK`/`FAIL`/`WARN`: key source; token exchange (+ lifetime in hours, warn < 24 h); version vs PyPI; uvx on PATH; per detected client: entry present / pinned version / matches running version. Exit 0 if no FAIL.
- [ ] **Step 4: Run** `uv run pytest -q && uv run mypy && uv run ruff check .` → PASS.
- [ ] **Step 5: Manual smoke** (no real key): `uv run garmin-dynamic-mcp --help`, `uv run garmin-dynamic-mcp doctor` (expect FAIL on key, no traceback), and the existing stdio smoke test (initialize → 2 tools).
- [ ] **Step 6: Commit** — `feat: setup, doctor, update and forget commands`

---

### Task 10: CI, Dependabot, catalog-watch workflow

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/catalog-watch.yml`, `.github/dependabot.yml`, `scripts/pin_actions.md` (one table: action, tag, SHA — the source of the pins)

**Interfaces:**
- Consumes: Task 6 script CLIs.
- Produces: `ci.yml` job names `lint` and `test (<os>, <python>)` — the names branch protection will require; triggers `push` (main), `pull_request`, `workflow_dispatch`.

- [ ] **Step 1:** Resolve SHAs with `git ls-remote https://github.com/<owner>/<repo> refs/tags/<tag>` (dereference annotated tags with `^{}`) for: `actions/checkout`, `astral-sh/setup-uv`, `peter-evans/create-pull-request`, `actions/upload-artifact`, `actions/download-artifact`, `pypa/gh-action-pypi-publish`, `actions/configure-pages`, `actions/upload-pages-artifact`, `actions/deploy-pages` (latest major tag of each). Record in `scripts/pin_actions.md`.
- [ ] **Step 2:** `ci.yml`: `permissions: contents: read`; `lint` job (ubuntu, uv, `ruff check`, `ruff format --check`, `mypy`); `test` matrix `os: [ubuntu-latest, macos-latest, windows-latest]`, `python: ["3.10", "3.13"]`, `uv run --python ${{ matrix.python }} pytest --cov=garmin_dynamic_mcp --cov-fail-under=85 -q`; `build` job: `uv build`, `uvx twine check dist/*`.
- [ ] **Step 3:** `catalog-watch.yml`: `schedule: cron "17 5 * * *"` + `workflow_dispatch`; top-level `permissions: contents: read`; job permissions `contents: write, pull-requests: write, issues: write, actions: write`. Steps: checkout → setup-uv → `uv run python scripts/fetch_openapi.py build/openapi.json` (id `fetch`, `continue-on-error: true`) → if fetch failed: `gh issue list --label catalog-watch-broken --state open` and either comment or `gh issue create --label catalog-watch-broken` with the run URL, then fail the job → `uv run python scripts/build_catalog.py build/openapi.json --check` (output `changed`) → if changed: copy current catalog to `build/old_catalog.json`, build, `prepare_catalog_release.py`, `uv run pytest -q`, `peter-evans/create-pull-request` (`branch: catalog-update`, `title: "Catalog update: Garmin API changed"`, `body-path: build/pr_body.md`, `labels: catalog-update`, `delete-branch: true`) → `gh workflow run ci.yml --ref catalog-update`.
- [ ] **Step 4:** `dependabot.yml`: `pip` (uv) and `github-actions`, weekly, grouped.
- [ ] **Step 5: Verify** — `uvx zizmor .github/workflows` (workflow security linter) reports no high findings; `uvx check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/*.yml` passes. Local dry run of the watcher logic: `uv run python scripts/build_catalog.py build/openapi.json --check` prints `unchanged`.
- [ ] **Step 6: Commit** — `ci: tests on three OSes, Dependabot, daily catalog watcher`

---

### Task 11: Release workflow and MCP Registry metadata

**Files:**
- Create: `.github/workflows/release.yml`, `server.json`, `scripts/changelog_section.py`, `scripts/release_check.py`
- Test: `tests/test_metadata.py`, `tests/test_changelog_section.py`

**Interfaces:**
- Produces: `changelog_section(text: str, version: str) -> str`; `release_check.py` prints `version=X.Y.Z` and `release=true|false` to `$GITHUB_OUTPUT` (true when tag `vX.Y.Z` does not exist: `git ls-remote --tags origin`); `server.json` with `$schema` `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`, `name` `io.github.fabriziodebortoli/garmin-dynamic-mcp`, `title` `Garmin Dynamic MCP`, `description` (≤100 chars), `version`, `repository {url, source: "github"}`, `packages: [{registryType: "pypi", identifier: "garmin-dynamic-mcp", version, runtimeHint: "uvx", transport: {type: "stdio"}, environmentVariables: [{name: "GARMIN_API_KEY", description: "Optional: Garmin Personal API key (otherwise read from the OS keychain set by `setup`)", isRequired: false, isSecret: true}]}]`.

- [ ] **Step 1: Write the failing tests** — `test_server_json_version_matches_pyproject`, `test_readme_has_mcp_name_marker` (`<!-- mcp-name: io.github.fabriziodebortoli/garmin-dynamic-mcp -->`), `test_changelog_has_section_for_current_version`, `test_changelog_section_extracts_body`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** scripts and `server.json`. `release.yml`: on `push: branches: [main]` + `workflow_dispatch`; jobs: `check` (outputs) → `build` (if release; uv build, twine check, upload artifact) → `test` (reuse: `uv run pytest -q` on ubuntu) → `publish-pypi` (`environment: {name: pypi, url: https://pypi.org/p/garmin-dynamic-mcp}`, `permissions: id-token: write`, download artifact, `pypa/gh-action-pypi-publish`) → `github-release` (`permissions: contents: write`; `gh release create vX.Y.Z dist/* --title vX.Y.Z --notes-file notes.md` from `changelog_section.py`; also attaches `garmin-dynamic-mcp.mcpb` if Task 13 produced it) → `mcp-registry` (`permissions: id-token: write`; download a pinned `mcp-publisher` release binary and verify its SHA-256 from the release checksums; `./mcp-publisher login github-oidc && ./mcp-publisher publish`).
- [ ] **Step 4: Run** `uv run pytest -q` → PASS; `uvx zizmor .github/workflows` clean.
- [ ] **Step 5: Commit** — `ci: single merge-to-main release path (PyPI trusted publishing, GitHub release, MCP Registry)`

---

### Task 12: Documentation and community files

**Files:**
- Rewrite: `README.md`, `docs/garmin-api-findings.md`
- Create: `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `docs/security.md`, `docs/releasing.md`, `.github/ISSUE_TEMPLATE/{bug_report.yml,feature_request.yml,endpoint_problem.yml,config.yml}`, `.github/pull_request_template.md`, `.github/CODEOWNERS`
- Test: `tests/test_metadata.py` (extend)

- [ ] **Step 1: Write the failing tests** — `test_readme_quick_start_first` (the first `##` heading is `Quick start`, and it contains the key page URL and `uvx garmin-dynamic-mcp setup`), `test_no_italian_left` (none of `" della "`, `" chiave"`, `"Questo "` in `README.md`, `docs/**/*.md`, `src/**/*.py`), `test_issue_templates_warn_about_keys` (each template contains "Never paste your Garmin key").
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Write.**
  - README order: title, badges (CI, PyPI version, Python versions, license), pitch ("The Garmin Connect MCP server that updates itself when Garmin's API changes — and keeps your key in the OS keychain."), `mcp-name` marker, **Quick start** (1. install uv: `winget install astral-sh.uv` / `brew install uv` / `curl -LsSf https://astral.sh/uv/install.sh | sh`; 2. `uvx garmin-dynamic-mcp setup` — it opens <https://connect.garmin.com/app/settings/personalApiToken>; 3. restart the client and ask), What you can ask, Supported clients (table: client, configured automatically?), How it stays up to date, Security, Privacy, Updating, Troubleshooting (`doctor`), Manual configuration (generic snippet + Claude Code command), Sensitive endpoints, Development, Disclaimer (not affiliated with or endorsed by Garmin; Garmin is a trademark of Garmin Ltd.), License.
  - `CHANGELOG.md` (Keep a Changelog): `## [Unreleased]`, `## [0.2.0] - <release date placeholder replaced at release>` listing phase 1 features.
  - `SECURITY.md`: supported versions, private reporting via GitHub Security Advisories, scope, link to `docs/security.md`.
  - `docs/security.md`: threat model, network destinations table, key storage, catalog review, supply chain.
  - `docs/releasing.md`: release = version bump + CHANGELOG entry merged to main; catalog auto-PR flow; repository settings required (Actions may create PRs, `pypi` environment, Trusted Publisher, branch protection with the `ci.yml` job names, Pages source "GitHub Actions").
  - `CONTRIBUTING.md`: dev setup with uv, tests/lint/type commands, TDD expectation, how to add catalog overrides, live probe usage, commit style.
  - `CODE_OF_CONDUCT.md`: Contributor Covenant 2.1 (fetch the canonical text from https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md; contact = GitHub private advisory / maintainer profile, no e-mail address).
  - `docs/garmin-api-findings.md` in English, with no account-specific numbers.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** — `docs: English README, security policy, contribution guide, templates`

---

### Task 13: Claude Desktop extension (MCPB) — conditional

**Files:**
- Create: `mcpb/manifest.json`, `mcpb/pyproject.toml`, `mcpb/src/server.py`, `scripts/build_mcpb.py`, `mcpb/icon.png` (simple generated icon)
- Modify: `.github/workflows/release.yml` (build step), `.gitignore`

**Interfaces:**
- Produces: `scripts/build_mcpb.py VERSION` → `build/garmin-dynamic-mcp.mcpb`, with `manifest_version: "0.4"`, `server.type: "uv"`, dependency `garmin-dynamic-mcp==VERSION`, `user_config.garmin_api_key` (`type: string`, `sensitive: true`, `required: true`, title "Garmin Personal API key", description with the key page URL) passed as env `GARMIN_API_KEY`.

- [ ] **Step 1:** Write the bundle files following the MCPB `hello-world-uv` example (`mcp_config: {command: "uv", args: ["run", "--directory", "${__dirname}", "src/server.py"], env: {"GARMIN_API_KEY": "${user_config.garmin_api_key}"}}`); `src/server.py` imports `garmin_dynamic_mcp.server` and runs it.
- [ ] **Step 2:** Validate and pack: `npx -y @anthropic-ai/mcpb validate mcpb/manifest.json` then `npx -y @anthropic-ai/mcpb pack mcpb build/garmin-dynamic-mcp.mcpb`.
- [ ] **Step 3: Manual check by Fabrizio** — install the `.mcpb` in Claude Desktop (double-click), enter a key, ask one question. Because the bundle pins a PyPI version, this runs after the first PyPI release; until then test with a bundle whose dependency points to the local wheel path.
- [ ] **Step 4:** If it works: release workflow builds and attaches it; README gets a "One-click install for Claude Desktop" line. If not: remove the files and record the outcome in `docs/releasing.md`.
- [ ] **Step 5: Commit** — `feat: Claude Desktop extension bundle` (or `docs: MCPB not supported yet`)

---

### Task 14: GitHub Pages landing

**Files:**
- Create: `site/index.html`, `site/style.css`, `.github/workflows/pages.yml`

- [ ] **Step 1:** One static English page: pitch, quick start (same three steps and key link as README), supported clients, "how it stays up to date", security summary, links to GitHub and PyPI. No external scripts; system font stack; light and dark via `prefers-color-scheme`; readable at 375 px.
- [ ] **Step 2:** `pages.yml`: on push to main affecting `site/**` + `workflow_dispatch`; `permissions: pages: write, id-token: write, contents: read`; configure-pages → upload-pages-artifact (`path: site`) → deploy-pages. Add the Pages URL to `pyproject.toml` `[project.urls] Documentation` and the README.
- [ ] **Step 3: Verify** — open `site/index.html` in the browser pane at desktop and 375 px; `uvx zizmor .github/workflows` clean.
- [ ] **Step 4: Commit** — `docs: GitHub Pages landing`

---

### Task 15: Final verification and publication prep

- [ ] **Step 1:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov=garmin_dynamic_mcp -q` → all green, coverage ≥ 85 %.
- [ ] **Step 2:** `uv build && uvx twine check dist/*` → PASSED; install the wheel in a throwaway env from a clean folder: `uvx --from dist/garmin_dynamic_mcp-0.2.0-py3-none-any.whl garmin-dynamic-mcp --help` and the stdio smoke test (initialize, 2 tools, catalog loads).
- [ ] **Step 3:** Secret scan of the working tree and full history: `uvx detect-secrets scan --all-files` (or gitleaks binary) and a literal search for the development key prefix supplied in-session (never written to disk) → no findings.
- [ ] **Step 4:** Whole-branch review by a fresh reviewer on the most capable model; fix Critical/Important findings.
- [ ] **Step 5:** Write `docs/launch-checklist.md` for Fabrizio: revoke dev key; history decision; PyPI pending publisher (owner `fabriziodebortoli`, repo `garmin-dynamic-mcp`, workflow `release.yml`, environment `pypi`); GitHub settings (Actions can create PRs, `pypi` environment, private vulnerability reporting, secret scanning + push protection, Dependabot alerts, branch protection requiring `lint` and `test (…)`, Pages source GitHub Actions); clean-machine acceptance run (Windows Claude Desktop + Claude Code); README walkthrough by someone else; launch post drafts (Reddit r/Garmin and r/ClaudeAI, Hacker News "Show HN") and awesome-list PR texts.
- [ ] **Step 6:** Merge `feature/server` into `main` locally. **Stop and ask Fabrizio** for: the history decision, the first push, and enabling the release (the first push to `main` triggers `release.yml`).
