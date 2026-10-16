"""Unit tests for volatile explicit-memory confirmation behavior."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_himeko.memory_confirmation import (
    CONFIRMATION_TTL,
    PendingMemoryStore,
    is_direct_memory_request,
)


class Event:
    def __init__(self, message: str, sender: str = "owner") -> None:
        self.message_str = message
        self.sender = sender
        self.unified_msg_origin = "wechat:fictional"
        self.stopped = False

    def get_group_id(self):
        return ""

    def get_sender_id(self):
        return self.sender

    def get_platform_id(self):
        return "fictional"

    def get_platform_name(self):
        return "fictional"

    def stop_event(self):
        self.stopped = True

    @staticmethod
    def plain_result(text: str) -> str:
        return text


async def output(generator):
    return [item async for item in generator]


def configured_plugin(tmp_path):
    previous_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        from astrbot_plugin_himeko.main import HimekoPlugin, MemoryStore
    finally:
        os.chdir(previous_cwd)
    plugin = object.__new__(HimekoPlugin)
    plugin.config = {"owner_id": "owner", "platform_id": "fictional", "enable_memory": True}
    plugin.store = MemoryStore(tmp_path / "memory.sqlite3")
    plugin.pending_memories = PendingMemoryStore()
    return plugin


def candidate(store: PendingMemoryStore, current: datetime):
    return store.propose("owner", "wechat:fictional", "偏好", "优先免费工具", None, current)


def test_confirmation_requires_an_exact_affirmative_reply():
    store = PendingMemoryStore()
    current = datetime(2026, 10, 16, tzinfo=timezone.utc)
    proposed = candidate(store, current)
    outcome, confirmed = store.consume_reply("owner", "wechat:fictional", "可以", current)
    assert outcome == "accepted"
    assert confirmed == proposed
    assert store.consume_reply("owner", "wechat:fictional", "可以", current)[0] == "none"


def test_plugin_writes_only_after_same_owner_confirms(tmp_path):
    plugin = configured_plugin(tmp_path)
    event = Event("可以")
    owner = plugin.owner(event)
    assert owner is not None
    plugin.pending_memories.propose(
        owner,
        event.unified_msg_origin,
        "偏好",
        "优先免费工具",
        None,
    )
    messages = asyncio.run(output(plugin.confirm_pending_memory(event)))
    assert event.stopped
    assert messages == ["已记住「偏好」。"]
    assert plugin.store.execute(owner, "list") == [("偏好", "优先免费工具")]


def test_non_owner_cannot_confirm_an_owner_candidate(tmp_path):
    plugin = configured_plugin(tmp_path)
    owner_event = Event("普通消息")
    owner = plugin.owner(owner_event)
    assert owner is not None
    plugin.pending_memories.propose(
        owner,
        owner_event.unified_msg_origin,
        "偏好",
        "优先免费工具",
        None,
    )
    messages = asyncio.run(output(plugin.confirm_pending_memory(Event("可以", sender="other"))))
    assert not messages
    assert plugin.pending_memories.active(owner, owner_event.unified_msg_origin) is not None


def test_rejection_and_changed_topic_discard_the_candidate():
    current = datetime(2026, 10, 16, tzinfo=timezone.utc)
    store = PendingMemoryStore()
    candidate(store, current)
    assert store.consume_reply("owner", "wechat:fictional", "不用", current)[0] == "rejected"
    store = PendingMemoryStore()
    candidate(store, current)
    outcome, _ = store.consume_reply("owner", "wechat:fictional", "换个话题", current)
    assert outcome == "changed_topic"


def test_candidate_expires_after_ten_minutes():
    store = PendingMemoryStore()
    current = datetime(2026, 10, 16, tzinfo=timezone.utc)
    candidate(store, current)
    assert (
        store.consume_reply("owner", "wechat:fictional", "可以", current + CONFIRMATION_TTL)[0]
        == "expired"
    )


def test_new_conversation_cannot_confirm_an_older_candidate():
    store = PendingMemoryStore()
    current = datetime(2026, 10, 16, tzinfo=timezone.utc)
    candidate(store, current)
    store.clear_other_conversations("owner", "wechat:new-fictional")
    assert store.consume_reply("owner", "wechat:fictional", "可以", current)[0] == "none"


def test_changed_candidate_replaces_the_pending_fact_and_restarts_its_window():
    store = PendingMemoryStore()
    current = datetime(2026, 10, 16, tzinfo=timezone.utc)
    first = candidate(store, current)
    changed = store.propose(
        "owner",
        "wechat:fictional",
        "偏好",
        "优先开源工具",
        None,
        current + timedelta(minutes=2),
    )
    assert changed != first
    assert changed and changed.expires_at == current + timedelta(minutes=12)
    assert store.consume_reply("owner", "wechat:fictional", "好", current)[0] == "accepted"


def test_candidate_carries_the_old_fact_for_an_explicit_update_prompt():
    store = PendingMemoryStore()
    current = datetime(2026, 10, 16, tzinfo=timezone.utc)
    proposed = store.propose("owner", "wechat:fictional", "偏好", "优先免费工具", "旧内容", current)
    assert proposed and proposed.previous_fact == "旧内容"


def test_proactive_suggestions_are_limited_to_one_per_ten_messages():
    store = PendingMemoryStore()
    current = datetime(2026, 10, 16, tzinfo=timezone.utc)
    store.note_user_message("owner")
    assert candidate(store, current)
    store.consume_reply("owner", "wechat:fictional", "不用", current)
    for _ in range(9):
        store.note_user_message("owner")
    assert candidate(store, current) is None
    store.note_user_message("owner")
    assert candidate(store, current)


def test_direct_request_guard_rejects_negations_and_quoted_mentions():
    assert is_direct_memory_request("请记住：优先推荐免费工具")
    assert is_direct_memory_request("请把这个偏好保存下来")
    assert is_direct_memory_request("Please remember I prefer free tools")
    assert not is_direct_memory_request("不要记住这条内容")
    assert not is_direct_memory_request("“请记住这个偏好”这句话只是引用")
