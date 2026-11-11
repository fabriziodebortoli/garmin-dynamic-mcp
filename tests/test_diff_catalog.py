from diff_catalog import CatalogDiff, bump_kind, diff_catalogs, to_markdown


def _ep(path, params=(), max_range_days=None, summary="s"):
    return {
        "path": path,
        "summary": summary,
        "params": [{"name": n, "location": "query", "required": False, "type": "string"} for n in params],
        "max_range_days": max_range_days,
    }


OLD = {"endpoints": [_ep("/a", ["x"]), _ep("/b"), _ep("/c", max_range_days=28)]}
NEW = {"endpoints": [_ep("/a", ["x", "y"]), _ep("/c", max_range_days=31, summary="t"), _ep("/d")]}


def test_diff_added_removed_changed():
    d = diff_catalogs(OLD, NEW)
    assert d.added == ["/d"] and d.removed == ["/b"]
    assert d.changed["/a"] == ["param added: y"]
    assert "max_range_days: 28 → 31" in d.changed["/c"] and "summary changed" in d.changed["/c"]


def test_bump_kind():
    assert bump_kind(CatalogDiff([], [], {})) == "none"
    assert bump_kind(CatalogDiff([], [], {"/a": ["param added: y"]})) == "patch"
    assert bump_kind(CatalogDiff(["/d"], [], {})) == "minor"
    assert bump_kind(CatalogDiff([], ["/b"], {})) == "minor"


def test_markdown_lists_everything():
    md = to_markdown(diff_catalogs(OLD, NEW))
    for text in ("/d", "/b", "param added: y", "Added", "Removed", "Changed"):
        assert text in md
