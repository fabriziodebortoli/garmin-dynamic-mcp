import json
from pathlib import Path

from changelog_section import changelog_section
from release_check import project_version

ROOT = Path(__file__).resolve().parent.parent
MCP_NAME = "io.github.fabriziodebortoli/garmin-dynamic-mcp"


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_server_json_version_matches_pyproject():
    version = project_version(_read("pyproject.toml"))
    server = json.loads(_read("server.json"))
    assert server["version"] == version
    assert [p["version"] for p in server["packages"]] == [version]


def test_server_json_identifies_the_pypi_package():
    server = json.loads(_read("server.json"))
    assert server["name"] == MCP_NAME
    assert server["repository"] == {
        "url": "https://github.com/fabriziodebortoli/garmin-dynamic-mcp",
        "source": "github",
    }
    package = server["packages"][0]
    assert package["registryType"] == "pypi" and package["identifier"] == "garmin-dynamic-mcp"
    assert package["transport"] == {"type": "stdio"}
    key = package["environmentVariables"][0]
    assert key["name"] == "GARMIN_API_KEY" and key["isSecret"] is True and key["isRequired"] is False
    assert len(server["description"]) <= 100


def test_readme_has_mcp_name_marker():
    assert f"<!-- mcp-name: {MCP_NAME} -->" in _read("README.md")


def test_changelog_has_section_for_current_version():
    version = project_version(_read("pyproject.toml"))
    assert changelog_section(_read("CHANGELOG.md"), version).strip()


def test_issue_templates_warn_about_keys():
    templates = sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
    forms = [t for t in templates if t.name != "config.yml"]
    assert len(forms) == 3
    for form in forms:
        assert "Never paste your Garmin key" in form.read_text(encoding="utf-8"), form.name


def test_readme_quick_start_comes_first_and_has_the_one_command():
    readme = _read("README.md")
    headings = [line for line in readme.splitlines() if line.startswith("## ")]
    assert headings[0] == "## Quick start"
    quick_start = readme.split("## Quick start", 1)[1].split("\n## ", 1)[0]
    assert "https://connect.garmin.com/app/settings/personalApiToken" in quick_start
    assert "uvx garmin-dynamic-mcp setup" in quick_start


ITALIAN_MARKERS = (" della ", " chiave", "Questo ", " non è ", " sono ", " per il ")


def test_no_italian_left_in_public_files():
    files = [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "SECURITY.md", ROOT / "CONTRIBUTING.md"]
    files += [p for p in (ROOT / "docs").rglob("*.md") if p.name != "project_spec.md" and "superpowers" not in p.parts]
    files += list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))
    offenders = [
        f"{p.relative_to(ROOT)}: {marker.strip()!r}"
        for p in files
        if p.exists()
        for marker in ITALIAN_MARKERS
        if marker in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_landing_page_has_the_install_command_and_loads_nothing_external():
    html = _read("site/index.html")
    assert "uvx garmin-dynamic-mcp setup" in html
    assert "https://connect.garmin.com/app/settings/personalApiToken" in html
    assert "not affiliated" in html.lower()
    assert "<script" not in html
    assert 'name="viewport"' in html
    css = _read("site/style.css")
    assert "prefers-color-scheme: dark" in css and "@import" not in css and "url(http" not in css


# --- review fixes -------------------------------------------------------------------------------


def test_release_workflow_only_runs_from_main():
    text = _read(".github/workflows/release.yml")
    check_job = text.split("  check:", 1)[1].split("\n  test:", 1)[0]
    assert "if: github.ref == 'refs/heads/main'" in check_job


def test_catalog_watch_does_not_expose_the_token_to_every_step():
    lines = _read(".github/workflows/catalog-watch.yml").splitlines()
    job_level = [line for line in lines if line.startswith("      GH_TOKEN:")]  # 6 spaces = job-level env
    assert job_level == []
    assert any(line.startswith("          GH_TOKEN:") for line in lines)  # steps that need it set it themselves


def test_release_docs_require_a_protected_pypi_environment():
    docs = _read("docs/releasing.md")
    assert "Deployment branches" in docs and "Require review from Code Owners" in docs


def test_readme_links_work_on_pypi():
    import re

    links = re.findall(r"\]\(([^)\s]+)\)", _read("README.md"))
    relative = [link for link in links if not link.startswith(("http://", "https://", "#", "mailto:"))]
    assert relative == []


def test_coverage_data_is_not_committed():
    ignored = _read(".gitignore").splitlines()
    assert ".coverage" in ignored
    assert not (ROOT / ".git").exists() or ".coverage" not in _tracked_files()


def _tracked_files():
    import subprocess

    result = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return result.stdout.splitlines()
