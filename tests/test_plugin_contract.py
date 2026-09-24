"""Plugin contributions: UI injection, plugin settings, attachments and hot reload."""

from __future__ import annotations

import json
import threading
import urllib.request

from pyclaw import plugins as plugin_mod
from pyclaw.config import Config


def make_plugin(root, name="demo", **fields):
    plugin_dir = root / name
    (plugin_dir / ".pyclaw-plugin").mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "version": "2.0.0", "enabled": True}
    payload.update(fields)
    (plugin_dir / ".pyclaw-plugin" / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    return plugin_dir


def test_plugin_injects_css_and_js(tmp_path):
    plugin_dir = make_plugin(tmp_path, webui={"css": "ui/a.css", "js": "ui/a.js"})
    (plugin_dir / "ui").mkdir()
    (plugin_dir / "ui" / "a.css").write_text(".x{color:red}", encoding="utf-8")
    (plugin_dir / "ui" / "a.js").write_text("console.log('hi')", encoding="utf-8")
    css, js, _ = plugin_mod.ui_bundle(plugin_mod.discover([tmp_path]))
    assert ".x{color:red}" in css and "console.log" in js


def test_disabled_plugin_contributes_nothing(tmp_path):
    plugin_dir = make_plugin(tmp_path, webui={"css": "ui/a.css"})
    (plugin_dir / "ui").mkdir()
    (plugin_dir / "ui" / "a.css").write_text(".x{}", encoding="utf-8")
    found = plugin_mod.discover([tmp_path], enabled=["!demo"])
    assert found[0].enabled is False
    assert plugin_mod.ui_bundle(found)[0] == ""


def test_plugin_settings_reach_the_form_and_validator(tmp_path):
    config = Config(tmp_path / "pyclaw.json", tmp_path / "missing")
    make_plugin(tmp_path, settings=[{"key": "DEMO_LIMIT", "type": "int", "default": 7,
                                     "flags": [], "label": "演示上限", "help": "只用于测试"}])
    rows = plugin_mod.ui_bundle(plugin_mod.discover([tmp_path]))[2]
    assert config.register_plugin_keys(rows) == ["DEMO_LIMIT"]
    assert config.get("DEMO_LIMIT") == 7
    form = {row["key"]: row for row in config.public("zh-CN")}
    assert form["DEMO_LIMIT"]["label"] == "演示上限"
    assert "plugin" in form["DEMO_LIMIT"]["flags"]
    config.update({"DEMO_LIMIT": 9})
    assert config.get("DEMO_LIMIT") == 9


def test_attachment_transformer_wins_over_the_path_note(tmp_path):
    plugin_dir = make_plugin(tmp_path, attachments="attach.py")
    (plugin_dir / "attach.py").write_text(
        "def transform(item, context):\n"
        "    if item.get('kind') != 'image':\n"
        "        return None\n"
        "    return [{'type': 'image_url', 'image_url': {'url': item.get('data', '')}}]\n", encoding="utf-8")
    found = plugin_mod.discover([tmp_path])
    blocks = plugin_mod.transform_attachment(found, {"kind": "image", "data": "data:image/png;base64,AA"}, {})
    assert blocks[0]["image_url"]["url"].startswith("data:image/png")
    assert plugin_mod.transform_attachment(found, {"kind": "text"}, {}) is None


def test_broken_attachment_handler_is_contained(tmp_path):
    plugin_dir = make_plugin(tmp_path, attachments="attach.py")
    (plugin_dir / "attach.py").write_text("def transform(item, context):\n    raise RuntimeError('boom')\n",
                                          encoding="utf-8")
    found = plugin_mod.discover([tmp_path])
    assert plugin_mod.transform_attachment(found, {"kind": "image"}, {}) is None
    assert any("boom" in error for error in found[0].errors)


def test_plugin_revision_changes_when_a_file_changes(tmp_path):
    plugin_dir = make_plugin(tmp_path)
    first = plugin_mod.revision([tmp_path])
    manifest = plugin_dir / ".pyclaw-plugin" / "plugin.json"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("2.0.0", "2.0.1"), encoding="utf-8")
    assert plugin_mod.revision([tmp_path]) != first


def test_unknown_plugin_keys_survive_a_reload(tmp_path):
    path = tmp_path / "pyclaw.json"
    path.write_text(json.dumps({"API_KEY": "k", "ENDPOINT": "https://x/v1", "DEMO_LIMIT": 42}), encoding="utf-8")
    config = Config(path)
    assert config.get("DEMO_LIMIT") == 42
    config.save()
    assert json.loads(path.read_text(encoding="utf-8")).get("DEMO_LIMIT") == 42

