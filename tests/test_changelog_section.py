import pytest
from changelog_section import changelog_section
from release_check import project_version, release_needed

CHANGELOG = """# Changelog

## [Unreleased]

- Something not released yet.

## [0.3.0] - 2026-12-01

### Catalog

- Added `/d`.

## [0.2.0] - 2026-11-12

- First public release.

[Unreleased]: https://example.invalid/compare/v0.3.0...HEAD
"""


def test_changelog_section_extracts_body_only():
    body = changelog_section(CHANGELOG, "0.3.0")
    assert body == "### Catalog\n\n- Added `/d`."


def test_changelog_section_last_version_stops_before_link_references():
    assert changelog_section(CHANGELOG, "0.2.0") == "- First public release."


def test_changelog_section_missing_version_raises():
    with pytest.raises(ValueError, match="no section"):
        changelog_section(CHANGELOG, "9.9.9")


def test_project_version_reads_pyproject_text():
    assert project_version('[project]\nname = "x"\nversion = "1.2.3"\n') == "1.2.3"
    with pytest.raises(ValueError):
        project_version("[project]\nname = 'x'\n")


def test_release_needed_only_when_tag_is_missing():
    assert release_needed("0.2.0", existing_tags=["v0.1.0"]) is True
    assert release_needed("0.2.0", existing_tags=["v0.1.0", "v0.2.0"]) is False
