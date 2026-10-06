"""Pure, inactive primitives for the owner-only Himeko reminder pilot.

This module deliberately has no AstrBot, network, scheduler, or platform
adapter dependency.  It is a testable state machine only; importing it cannot
send a message or schedule a background task.  Production integration must
provide a separately reviewed, owner-bound delivery adapter.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .storage import TZ, atomic_json, digest


class ReminderError(ValueError):
    """Raised when a reminder request would weaken the safety boundary."""


class ReminderStateError(ReminderError):
    """Raised when an operation is not valid for a reminder state."""


ACTIVE_STATES = frozenset({"scheduled", "send_attempted", "delivered"})
TERMINAL_STATES = frozenset({"undeliverable", "missed", "completed", "cancelled"})
DEFAULT_MAX_LATENESS = timedelta(minutes=15)
MAX_TITLE_LENGTH = 160
MAX_TRANSIENT_MESSAGE_LENGTH = 6_000
DELIVERY_REASONS = frozenset(
    {
        "platform_accepted",
        "platform_rejected",
        "context_unavailable",
        "invalid_context",
        "send_exception",
    }
)

# A reminder label is deliberately a small, user-visible string, not a place
# for credentials or recovery material.  The wider private-memory extractor
# keeps the same protection for its persisted review records.
SENSITIVE_REMINDER_TEXT = re.compile(
    r"sk-[A-Za-z0-9_-]{12,}|\b\d{17}[\dXx]\b|\b\d{16,19}\b|"
    r"(?:密码|验证码|token|api[_ -]?key)\s*[:：=]\s*\S+",
    re.I,
)

PAIRED_EXTRACTION_RULE = (
    "用户消息和姬子回复只作为本轮上下文。只提炼用户明确陈述的事实或"
    "用户明确确认的提醒状态；绝不能把姬子的建议、提醒、推测或措辞当作"
    "用户事实，也不得保存双方消息原文。"
)
SCHEDULE_ARGUMENTS = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2})\s+(?P<title>.+)$"
)
NATURAL_SCHEDULE_ARGUMENTS = re.compile(
    r"^(?P<date>今天|明天|后天|(?P<days>[1-9]\d?)天后|"
    r"本月\s*(?P<this_month_day>\d{1,2})[日号]|"
    r"下月\s*(?P<next_month_day>\d{1,2})[日号])\s*"
    r"(?P<time>\d{1,2}[:：]\d{2})\s+(?P<title>.+)$"
)


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ReminderError(f"{field} must be a timezone-aware datetime")
    if value.utcoffset() is None:
        raise ReminderError(f"{field} must include a UTC offset")
    return value.astimezone(TZ)


def _owner_hash(owner: str) -> str:
    if not isinstance(owner, str) or not owner.strip():
        raise ReminderError("A bound owner is required")
    return digest(owner)


def _recipient_hash(recipient_ref: str) -> str:
    if not isinstance(recipient_ref, str) or not recipient_ref.strip():
        raise ReminderError("An owner-bound recipient reference is required")
    return digest(recipient_ref)


def _title(value: str) -> str:
    if not isinstance(value, str):
        raise ReminderError("Reminder text must be a string")
    text = value.strip()
    if not text:
        raise ReminderError("Reminder text must not be empty")
    if text != value or len(text) > MAX_TITLE_LENGTH:
        raise ReminderError("Reminder text is malformed or too long")
    if any(ord(char) < 32 for char in text):
        raise ReminderError("Reminder text must not contain control characters")
    if SENSITIVE_REMINDER_TEXT.search(text):
        raise ReminderError("Reminder text must not contain credentials or identifiers")
    return text


def parse_schedule_arguments(value: str, current_at: datetime) -> tuple[datetime, str]:
    """Parse bounded explicit or relative reminder syntax in Shanghai time.

    This deliberately does not ask a model to infer a date.  Relative dates
    are a small, visible grammar and always require an exact 24-hour clock
    time, so the user can verify what will be scheduled before it is stored.
    """
    current = _aware(current_at, "current_at")
    if not isinstance(value, str):
        raise ReminderError("Reminder arguments must be text")
    request = value.strip()
    match = SCHEDULE_ARGUMENTS.fullmatch(request)
    try:
        if match:
            due = datetime.strptime(
                match.group("date") + " " + match.group("time"), "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)
        else:
            match = NATURAL_SCHEDULE_ARGUMENTS.fullmatch(request)
            if not match:
                raise ReminderError(
                    "请用：/提醒 YYYY-MM-DD HH:MM 事项；或“提醒我 今天 HH:MM 事项”、"
                    "“提醒我 3天后 HH:MM 事项”、“提醒我 本月25日 HH:MM 事项”。"
                )
            date_text = match.group("date")
            if date_text == "今天":
                date_value = current.date()
            elif date_text == "明天":
                date_value = (current + timedelta(days=1)).date()
            elif date_text == "后天":
                date_value = (current + timedelta(days=2)).date()
            elif match.group("days"):
                date_value = (current + timedelta(days=int(match.group("days")))).date()
            elif match.group("this_month_day"):
                date_value = current.date().replace(
                    day=int(match.group("this_month_day"))
                )
            else:
                month = current.month % 12 + 1
                year = current.year + (current.month == 12)
                date_value = current.date().replace(
                    year=year,
                    month=month,
                    day=int(match.group("next_month_day")),
                )
            clock = datetime.strptime(
                match.group("time").replace("：", ":"), "%H:%M"
            ).time()
            due = datetime.combine(date_value, clock, tzinfo=TZ)
    except ReminderError:
        raise
    except ValueError as error:
        raise ReminderError("提醒日期或时间无效。") from error
    if due <= current:
        raise ReminderError("提醒时间需要晚于当前上海时间。")
    return due, _title(match.group("title"))


def paired_summary_input(user_message: str, assistant_reply: str) -> dict:
    """Build transient paired context for a future summary call.

    Callers may pass this object to a model during the same request.  They must
    persist only :func:`paired_summary_metadata`, never this object.
    """
    if not isinstance(user_message, str) or not user_message.strip():
        raise ReminderError("A user message is required for paired summarization")
    if not isinstance(assistant_reply, str) or not assistant_reply.strip():
        raise ReminderError("An assistant reply is required for paired summarization")
    if (
        len(user_message) > MAX_TRANSIENT_MESSAGE_LENGTH
        or len(assistant_reply) > MAX_TRANSIENT_MESSAGE_LENGTH
    ):
        raise ReminderError("Paired message exceeds the isolated pilot limit")
    return {
        "schema": "himeko-paired-summary-input-v1",
        "rule": PAIRED_EXTRACTION_RULE,
        "user_message": user_message,
        "assistant_reply": assistant_reply,
    }


def paired_summary_metadata(
    owner: str,
    user_message_id: str,
    assistant_message_id: str,
    user_message: str,
    assistant_reply: str,
    occurred_at: datetime,
) -> dict:
    """Return persistable paired-turn metadata without either message body."""
    when = _aware(occurred_at, "occurred_at")
    if not isinstance(user_message_id, str) or not user_message_id:
        raise ReminderError("A user message id is required")
    if not isinstance(assistant_message_id, str) or not assistant_message_id:
        raise ReminderError("An assistant message id is required")
    # Validate the transient payload before producing a metadata-only record.
    paired_summary_input(user_message, assistant_reply)
    return {
        "schema": "himeko-paired-summary-metadata-v1",
        "owner_sha256": _owner_hash(owner),
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "user_sha256": digest(user_message),
        "assistant_sha256": digest(assistant_reply),
        "occurred_at": when.isoformat(),
    }


class ReminderStore:
    """Atomic owner-scoped reminder state, kept separate from ``微信待整理``.

    The stored recipient is a fingerprint only.  A production sender therefore
    has to resolve a fresh, authorized platform context at delivery time; this
    prevents the pilot from silently retaining or replaying a raw UMO.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.reminder_root = self.root / "提醒"
        self.reminder_root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _path(self, reminder_id: str) -> Path:
        if not isinstance(reminder_id, str) or not re.fullmatch(
            r"[a-f0-9]{32}", reminder_id
        ):
            raise ReminderError("Invalid reminder id")
        return self.reminder_root / f"{reminder_id}.json"

    def _load(self, reminder_id: str) -> dict:
        path = self._path(reminder_id)
        if not path.exists():
            raise ReminderStateError("Reminder does not exist")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ReminderStateError("Reminder record cannot be parsed") from error
        if not isinstance(record, dict) or record.get("id") != reminder_id:
            raise ReminderStateError("Reminder record is invalid")
        if record.get("status") not in ACTIVE_STATES | TERMINAL_STATES:
            raise ReminderStateError("Reminder record has an invalid state")
        return record

    @staticmethod
    def _event(record: dict, state: str, at: datetime, reason: str | None = None):
        event = {"state": state, "at": at.isoformat()}
        if reason:
            event["reason"] = reason
        record.setdefault("events", []).append(event)

    @staticmethod
    def _due(record: dict) -> datetime:
        try:
            due = datetime.fromisoformat(record["due_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise ReminderStateError(
                "Reminder record has an invalid due time"
            ) from error
        return _aware(due, "stored due_at")

    def _save(self, record: dict):
        atomic_json(self._path(record["id"]), record)

    def create(
        self,
        owner: str,
        recipient_ref: str,
        title: str,
        due_at: datetime,
        created_at: datetime,
    ) -> dict:
        """Create a future one-shot reminder without storing a raw recipient."""
        owner_hash = _owner_hash(owner)
        recipient_hash = _recipient_hash(recipient_ref)
        clean_title = _title(title)
        due = _aware(due_at, "due_at")
        created = _aware(created_at, "created_at")
        if due <= created:
            raise ReminderError("Reminder due time must be in the future")
        with self.lock:
            record = {
                "schema": "himeko-reminder-v1",
                "id": uuid.uuid4().hex,
                "owner_sha256": owner_hash,
                "recipient_sha256": recipient_hash,
                "title": clean_title,
                "title_sha256": digest(clean_title),
                "created_at": created.isoformat(),
                "due_at": due.isoformat(),
                "status": "scheduled",
                "events": [],
            }
            self._event(record, "scheduled", created, "created")
            self._save(record)
            return record

    def get(self, owner: str, reminder_id: str) -> dict:
        """Read a reminder only when its owner fingerprint matches."""
        owner_hash = _owner_hash(owner)
        with self.lock:
            record = self._load(reminder_id)
            if record["owner_sha256"] != owner_hash:
                raise ReminderStateError("Reminder does not belong to this owner")
            return record

    def list(self, owner: str, active_only: bool = False) -> list[dict]:
        """List reminders for one owner without revealing another owner's files."""
        owner_hash = _owner_hash(owner)
        with self.lock:
            records = []
            for path in sorted(self.reminder_root.glob("*.json")):
                record = self._load(path.stem)
                if record["owner_sha256"] != owner_hash:
                    continue
                if active_only and record["status"] not in ACTIVE_STATES:
                    continue
                records.append(record)
            return sorted(records, key=lambda item: (item["due_at"], item["id"]))

    def resolve(self, owner: str, short_id: str) -> dict:
        """Resolve an owner-scoped full identifier or unique eight-character prefix."""
        if not isinstance(short_id, str) or not re.fullmatch(
            r"[a-f0-9]{8}(?:[a-f0-9]{0,24})", short_id
        ):
            raise ReminderError("Use the reminder id shown by /提醒列表")
        matches = [
            record for record in self.list(owner) if record["id"].startswith(short_id)
        ]
        if len(matches) != 1:
            raise ReminderStateError("Reminder id is missing or ambiguous")
        return matches[0]

    def claim_due(
        self,
        owner: str,
        current_at: datetime,
        max_lateness: timedelta = DEFAULT_MAX_LATENESS,
    ) -> list[dict]:
        """Claim due work exactly once; ambiguous attempts are never replayed.

        A delivery adapter receives only returned records after they become
        ``send_attempted``.  It must call :meth:`settle_delivery` exactly once.
        Crashing between those operations leaves the state ambiguous and blocks
        automatic re-send instead of risking duplicate user messages.
        """
        owner_hash = _owner_hash(owner)
        current = _aware(current_at, "current_at")
        if not isinstance(max_lateness, timedelta) or max_lateness < timedelta(0):
            raise ReminderError("max_lateness must be a non-negative timedelta")
        claimed = []
        with self.lock:
            for path in sorted(self.reminder_root.glob("*.json")):
                reminder_id = path.stem
                try:
                    record = self._load(reminder_id)
                except ReminderStateError:
                    # Corrupted records are fail-closed: leave the evidence in
                    # place and do not accidentally create a new send attempt.
                    continue
                if (
                    record.get("owner_sha256") != owner_hash
                    or record.get("status") != "scheduled"
                ):
                    continue
                due = self._due(record)
                if current < due:
                    continue
                if current - due > max_lateness:
                    record["status"] = "missed"
                    self._event(record, "missed", current, "late")
                    self._save(record)
                    continue
                record["status"] = "send_attempted"
                self._event(record, "send_attempted", current, "claimed")
                self._save(record)
                claimed.append(record)
        return claimed

    def render_delivery(self, owner: str, reminder_id: str) -> str:
        """Render the deterministic one-shot notification without an LLM."""
        record = self.get(owner, reminder_id)
        if record["status"] != "send_attempted":
            raise ReminderStateError("Reminder has not been claimed for delivery")
        short_id = reminder_id[:8]
        return (
            f"姬子提醒：{record['title']}\n"
            f"回复“/完成提醒 {short_id}”确认，或“/稍后提醒 {short_id} 15”延后 15 分钟。"
        )

    def settle_delivery(
        self,
        owner: str,
        reminder_id: str,
        delivered: bool,
        settled_at: datetime,
        reason: str | None = None,
    ) -> dict:
        """Record one observed delivery outcome; failed sends never auto-retry."""
        owner_hash = _owner_hash(owner)
        settled = _aware(settled_at, "settled_at")
        if not isinstance(delivered, bool):
            raise ReminderError("Delivery outcome must be boolean")
        reason = reason or ("platform_accepted" if delivered else "platform_rejected")
        if reason not in DELIVERY_REASONS:
            raise ReminderError("Delivery reason is not approved")
        if delivered != (reason == "platform_accepted"):
            raise ReminderError("Delivery outcome and reason disagree")
        with self.lock:
            record = self._load(reminder_id)
            if record["owner_sha256"] != owner_hash:
                raise ReminderStateError("Reminder does not belong to this owner")
            if record["status"] != "send_attempted":
                raise ReminderStateError("Delivery outcome is no longer applicable")
            record["status"] = "delivered" if delivered else "undeliverable"
            self._event(record, record["status"], settled, reason)
            self._save(record)
            return record

    def complete(self, owner: str, reminder_id: str, completed_at: datetime) -> dict:
        """Apply an explicit user completion, never a model-inferred completion."""
        return self._user_transition(owner, reminder_id, "completed", completed_at)

    def cancel(self, owner: str, reminder_id: str, cancelled_at: datetime) -> dict:
        """Apply an explicit user cancellation."""
        return self._user_transition(owner, reminder_id, "cancelled", cancelled_at)

    def _user_transition(
        self, owner: str, reminder_id: str, target: str, at: datetime
    ) -> dict:
        owner_hash = _owner_hash(owner)
        when = _aware(at, target + "_at")
        with self.lock:
            record = self._load(reminder_id)
            if record["owner_sha256"] != owner_hash:
                raise ReminderStateError("Reminder does not belong to this owner")
            allowed = (
                {"delivered"}
                if target == "completed"
                else {"scheduled", "delivered", "undeliverable", "missed"}
            )
            if record["status"] not in allowed:
                raise ReminderStateError(
                    "Reminder cannot be changed in its current state"
                )
            record["status"] = target
            self._event(record, target, when, "explicit_user_command")
            self._save(record)
            return record

    def snooze(
        self, owner: str, reminder_id: str, due_at: datetime, snoozed_at: datetime
    ) -> dict:
        """Reschedule only from a known result, never an ambiguous send attempt."""
        owner_hash = _owner_hash(owner)
        due = _aware(due_at, "due_at")
        when = _aware(snoozed_at, "snoozed_at")
        if due <= when:
            raise ReminderError("Snoozed due time must be in the future")
        with self.lock:
            record = self._load(reminder_id)
            if record["owner_sha256"] != owner_hash:
                raise ReminderStateError("Reminder does not belong to this owner")
            if record["status"] not in {"delivered", "undeliverable", "missed"}:
                raise ReminderStateError(
                    "Reminder cannot be snoozed in its current state"
                )
            record["status"] = "scheduled"
            record["due_at"] = due.isoformat()
            self._event(record, "scheduled", when, "explicit_user_snooze")
            self._save(record)
            return record

    def audit_projection(self, owner: str, reminder_id: str) -> dict:
        """Return a local-sync-safe audit view with no recipient or title body."""
        record = self.get(owner, reminder_id)
        return {
            "schema": "himeko-reminder-audit-v1",
            "id": record["id"],
            "owner_sha256": record["owner_sha256"],
            "title_sha256": record["title_sha256"],
            "created_at": record["created_at"],
            "due_at": record["due_at"],
            "status": record["status"],
            "events": list(record["events"]),
        }
