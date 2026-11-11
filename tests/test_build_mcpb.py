import json
from pathlib import Path

from build_mcpb import stage_bundle

SOURCE = Path(__file__).resolve().parent.parent / "mcpb"


def test_stage_bundle_pins_the_pypi_version(tmp_path):
    stage_bundle(SOURCE, tmp_path, "0.2.0")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.0"
    pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '"garmin-dynamic-mcp==0.2.0"' in pyproject and 'version = "0.2.0"' in pyproject


def test_manifest_uses_the_uv_runtime_and_a_sensitive_key(tmp_path):
    stage_bundle(SOURCE, tmp_path, "0.2.0")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == "0.4"
    assert manifest["server"]["type"] == "uv"
    key = manifest["user_config"]["garmin_api_key"]
    assert key["type"] == "string" and key["sensitive"] is True and key["required"] is True
    assert manifest["server"]["mcp_config"]["env"] == {"GARMIN_API_KEY": "${user_config.garmin_api_key}"}
    assert "connect.garmin.com/app/settings/personalApiToken" in key["description"]


def test_bundle_has_entry_point_icon_and_no_bundled_dependencies(tmp_path):
    stage_bundle(SOURCE, tmp_path, "0.2.0")
    assert (tmp_path / "src" / "server.py").is_file() and (tmp_path / "icon.png").is_file()
    assert not (tmp_path / "server" / "lib").exists() and not (tmp_path / "server" / "venv").exists()
    assert "garmin_dynamic_mcp" in (tmp_path / "src" / "server.py").read_text(encoding="utf-8")
