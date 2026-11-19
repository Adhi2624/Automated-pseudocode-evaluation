"""Timing rules for a test. A "test" is a document from the tests collection; all datetimes are naive UTC."""
from datetime import datetime, timedelta, timezone

GRACE_SECONDS = 15  # tolerance for the final auto-submit arriving slightly late


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def phase(test: dict, at: datetime = None) -> str:
    """draft (unpublished) | upcoming | open | closed"""
    at = at or now()
    if not test["published"]:
        return "draft"
    if test["opens_at"] and at < test["opens_at"]:
        return "upcoming"
    if test["closes_at"] and at >= test["closes_at"]:
        return "closed"
    return "open"


def deadline(test: dict, started_at: datetime, extra_minutes: int = 0) -> datetime:
    """Personal end time: start + duration capped at the closing time, plus staff-granted extra minutes."""
    end = started_at + timedelta(minutes=test["duration_minutes"])
    if test["closes_at"] and test["closes_at"] < end:
        end = test["closes_at"]
    return end + timedelta(minutes=extra_minutes or 0)


def public(test: dict) -> dict:
    return {
        "id": test["id"],
        "title": test["title"],
        "duration_minutes": test["duration_minutes"],
        "opens_at": iso(test["opens_at"]),
        "closes_at": iso(test["closes_at"]),
        "published": test["published"],
        "phase": phase(test),
    }


def attempt_state(attempt, test: dict, at: datetime = None) -> str:
    """not_started | in_progress | timed_out | submitted"""
    at = at or now()
    if attempt and attempt.get("submitted_at"):
        return "submitted"
    if not attempt or not attempt.get("started_at"):
        return "not_started"
    return "timed_out" if at > deadline(test, attempt["started_at"], attempt.get("extra_minutes", 0)) else "in_progress"
