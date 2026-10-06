import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))


def plugin_modules():
    from astrbot_plugin_himeko import attachments, reminders, storage

    return attachments, reminders, storage


def test_sensitive_features_default_to_off():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert schema["owner_id"]["default"] == ""
    assert schema["enable_character_prompt"]["default"] is False
    assert schema["enable_memory"]["default"] is False
    assert schema["enable_reminders"]["default"] is False
    assert schema["enable_attachments"]["default"] is False


def test_storage_writes_only_the_requested_file(tmp_path):
    _, _, storage = plugin_modules()
    destination = tmp_path / "plugin-data" / "record.json"
    storage.atomic_json(destination, {"value": "fictional"})
    assert json.loads(destination.read_text(encoding="utf-8")) == {"value": "fictional"}
    assert not list(destination.parent.glob("*.tmp"))


def test_attachment_page_input_is_bounded():
    attachments, _, _ = plugin_modules()
    assert attachments.parse_page_spec("1-3,5") == [1, 2, 3, 5]
    try:
        attachments.parse_page_spec("../../secret")
    except attachments.AttachmentError:
        pass
    else:
        raise AssertionError("path-like page input must be rejected")


def test_reminder_rejects_past_time():
    from datetime import datetime

    _, reminders, storage = plugin_modules()
    current = datetime(2026, 10, 6, 12, 0, tzinfo=storage.TZ)
    try:
        reminders.parse_schedule_arguments("2026-10-06 11:59 fictional task", current)
    except reminders.ReminderError:
        pass
    else:
        raise AssertionError("past reminder must be rejected")


def test_search_terms_do_not_require_personal_data():
    _, _, storage = plugin_modules()
    assert "阅读" in storage.search_terms("阅读笔记")
    assert not storage.search_terms("a")


def test_public_source_has_no_private_path_fallback():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "HIMEKO_PROJECT_ROOT" not in source
    assert "个人" + "分身" not in source
    assert "Obsi" + "dian" not in source


def test_plugin_entry_imports_against_astrbot():
    from astrbot_plugin_himeko.main import HimekoPlugin

    assert HimekoPlugin.__name__ == "HimekoPlugin"


def test_missing_or_non_owner_identity_fails_closed():
    from astrbot_plugin_himeko.main import HimekoPlugin

    class Event:
        def __init__(self, sender="owner", group="", platform="demo"):
            self.sender = sender
            self.group = group
            self.platform = platform

        def get_group_id(self):
            return self.group

        def get_sender_id(self):
            return self.sender

        def get_platform_id(self):
            return self.platform

        def get_platform_name(self):
            return "fictional"

    plugin = object.__new__(HimekoPlugin)
    plugin.config = {"owner_id": "", "platform_id": ""}
    assert plugin.owner(Event()) is None
    plugin.config = {"owner_id": "owner", "platform_id": "demo"}
    assert plugin.owner(Event(sender="other")) is None
    assert plugin.owner(Event(group="fictional-group")) is None
    assert plugin.owner(Event(platform="other-platform")) is None
    assert plugin.owner(Event()) is not None


def test_bilingual_guides_cover_the_same_core_topics():
    chinese = (ROOT / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "[English](README.en.md)" in chinese
    assert "[中文](README.md)" in english
    for chinese_marker, english_marker in (
        ("安装与第一次互动", "Install and first interaction"),
        ("记忆、提醒与附件", "Memory, reminders, and attachments"),
        ("数据与隐私", "Data and privacy"),
        ("已验证环境与限制", "Verified environment and limitations"),
        ("卸载", "Uninstall"),
    ):
        assert chinese_marker in chinese
        assert english_marker in english
