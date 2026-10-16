"""Volatile, owner- and conversation-scoped memory confirmation state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

CONFIRMATION_TTL = timedelta(minutes=10)
SUGGESTION_INTERVAL = 10

ACCEPTED_REPLIES = frozenset(
    {
        "可以",
        "可以的",
        "好",
        "好的",
        "行",
        "嗯",
        "是",
        "是的",
        "同意",
        "确认",
        "确认保存",
        "记住吧",
        "保存吧",
        "ok",
        "okay",
        "yes",
    }
)
REJECTED_REPLIES = frozenset(
    {
        "不要",
        "不用",
        "不需要",
        "不必",
        "别记住",
        "不要记住",
        "不保存",
        "拒绝",
        "算了",
        "no",
    }
)

NEGATED_MEMORY_REQUEST = re.compile(
    r"(?:不要|别|不用|不需要|不必|勿|禁止|不能|拒绝).{0,8}(?:记住|记下来|保存)"
    r"|(?:don't|do not|never)\s+(?:remember|save)",
    re.IGNORECASE,
)
DIRECT_MEMORY_REQUEST = re.compile(
    r"(?:^|[。！？!?]\s*)(?:请|麻烦)?(?:帮我|请你|希望你|我希望你|我想让你)?(?:把|将)?"
    r"(?:这条|这个|以下)?(?:内容|偏好|信息)?\s*(?:记住|记下来|保存)(?:下来|吧)?"
    r"(?:\s*[:：,，]?\s*.+)?[。！？!?]?$",
    re.IGNORECASE,
)
ENGLISH_DIRECT_MEMORY_REQUEST = re.compile(
    r"(?:please\s+)?(?:remember|save)(?:\s+(?:this|that))?\s*[:,-]?\s+.+[.!?]?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PendingMemory:
    """A proposed fact that cannot be recalled or persisted by itself."""

    owner: str
    conversation: str
    topic: str
    fact: str
    previous_fact: str | None
    expires_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_direct_memory_request(text: object) -> bool:
    """Recognize an affirmative request without treating mentions or quotes as consent."""
    value = str(text or "").strip()
    if not value or NEGATED_MEMORY_REQUEST.search(value):
        return False
    if value.startswith(("\"", "'", "“", "‘", "《", "<")):
        return False
    return bool(
        DIRECT_MEMORY_REQUEST.fullmatch(value) or ENGLISH_DIRECT_MEMORY_REQUEST.fullmatch(value)
    )


def reply_kind(text: object) -> str:
    """Return accepted, rejected, or other for a complete confirmation reply."""
    normalized = str(text or "").strip().casefold().rstrip("。！!?？")
    if normalized in ACCEPTED_REPLIES:
        return "accepted"
    if normalized in REJECTED_REPLIES:
        return "rejected"
    return "other"


class PendingMemoryStore:
    """Keep at most one expiring proposal for an owner in process memory only."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingMemory] = {}
        self._message_counts: dict[str, int] = {}
        self._last_suggestion: dict[str, int] = {}

    @staticmethod
    def _key(owner: str, conversation: str) -> tuple[str, str]:
        return owner, conversation

    def note_user_message(self, owner: str) -> None:
        self._message_counts[owner] = self._message_counts.get(owner, 0) + 1

    def clear_other_conversations(self, owner: str, conversation: str) -> None:
        """A new private conversation never inherits an older candidate."""
        for key in list(self._pending):
            if key[0] == owner and key[1] != conversation:
                self._pending.pop(key, None)

    def active(
        self, owner: str, conversation: str, current: datetime | None = None
    ) -> PendingMemory | None:
        key = self._key(owner, conversation)
        candidate = self._pending.get(key)
        if candidate and candidate.expires_at <= (current or utc_now()):
            self._pending.pop(key, None)
            return None
        return candidate

    def propose(
        self,
        owner: str,
        conversation: str,
        topic: str,
        fact: str,
        previous_fact: str | None,
        current: datetime | None = None,
    ) -> PendingMemory | None:
        """Register one candidate, throttling newly initiated proactive suggestions."""
        timestamp = current or utc_now()
        self.clear_other_conversations(owner, conversation)
        previous = self.active(owner, conversation, timestamp)
        if previous is None:
            count = self._message_counts.get(owner, 0)
            last = self._last_suggestion.get(owner, -SUGGESTION_INTERVAL)
            if count - last < SUGGESTION_INTERVAL:
                return None
            self._last_suggestion[owner] = count
        if previous and (
            previous.topic == topic
            and previous.fact == fact
            and previous.previous_fact == previous_fact
        ):
            return previous
        candidate = PendingMemory(
            owner=owner,
            conversation=conversation,
            topic=topic,
            fact=fact,
            previous_fact=previous_fact,
            expires_at=timestamp + CONFIRMATION_TTL,
        )
        self._pending[self._key(owner, conversation)] = candidate
        return candidate

    def consume_reply(
        self, owner: str, conversation: str, text: object, current: datetime | None = None
    ) -> tuple[str, PendingMemory | None]:
        """Consume a confirmation, rejection, expiry, or changed-topic reply once."""
        key = self._key(owner, conversation)
        candidate = self._pending.get(key)
        if candidate is None:
            return "none", None
        if candidate.expires_at <= (current or utc_now()):
            self._pending.pop(key, None)
            return "expired", candidate
        kind = reply_kind(text)
        if kind == "accepted":
            self._pending.pop(key, None)
            return "accepted", candidate
        if kind == "rejected":
            self._pending.pop(key, None)
            return "rejected", candidate
        self._pending.pop(key, None)
        return "changed_topic", candidate
