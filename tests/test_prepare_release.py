from prepare_catalog_release import add_changelog_entry, bump_version

CHANGELOG = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-11-12

- First public release.
"""


def test_bump_version():
    assert bump_version("0.2.0", "minor") == "0.3.0"
    assert bump_version("0.2.5", "patch") == "0.2.6"
    assert bump_version("1.4.2", "minor") == "1.5.0"


def test_add_changelog_entry_under_unreleased():
    out = add_changelog_entry(CHANGELOG, "0.3.0", "2026-12-01", "### Catalog\n\n- Added `/d`.")
    assert out.index("## [Unreleased]") < out.index("## [0.3.0] - 2026-12-01") < out.index("## [0.2.0]")
    assert "- Added `/d`." in out
