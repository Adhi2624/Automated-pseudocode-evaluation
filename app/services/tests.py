"""The tests collection: several independent tests, each with its own settings and question set."""
import secrets
from datetime import timedelta

from app.services import contest

COLLECTION = "tests"

DEFAULTS = {
    "title": "Untitled test",
    "duration_minutes": 60,
    "opens_at": None,
    "closes_at": None,
    "published": False,
    "announcement": None,  # {"text": str, "id": iso time} broadcast to students taking this test
    # When grading starts: manual | immediate | scheduled (at eval_at) | after_close (closes_at + eval_delay_minutes)
    "eval_mode": "manual",
    "eval_at": None,
    "eval_delay_minutes": 0,
    "eval_fired_at": None,  # set by the worker once a scheduled run has been queued; cleared when the schedule is edited
}
EVAL_MODES = ("manual", "immediate", "scheduled", "after_close")


def new_id() -> str:
    return secrets.token_hex(4)


def _normalize(doc):
    if doc is None:
        return None
    return {**DEFAULTS, **doc, "id": doc["_id"]}


def get(db, tid: str):
    return _normalize(db[COLLECTION].find_one({"_id": tid}))


def list_all(db) -> list:
    return [_normalize(d) for d in db[COLLECTION].find().sort([("created_at", 1), ("_id", 1)])]


def create(db, data: dict) -> dict:
    tid = new_id()
    db[COLLECTION].insert_one({**DEFAULTS, **data, "_id": tid, "created_at": contest.now()})
    return get(db, tid)


def update(db, tid: str, data: dict) -> None:
    db[COLLECTION].update_one({"_id": tid}, {"$set": data})


def set_announcement(db, tid: str, value) -> None:
    db[COLLECTION].update_one({"_id": tid}, {"$set": {"announcement": value}})


def delete(db, tid: str) -> None:
    """Remove a test with its questions and every student's attempt at it."""
    db[COLLECTION].delete_one({"_id": tid})
    db["questions"].delete_many({"test_id": tid})
    db["attempts"].delete_many({"test_id": tid})


def eval_start_time(test: dict):
    """When a scheduled / after_close evaluation should start (naive UTC), or None for manual / immediate."""
    if test["eval_mode"] == "scheduled":
        return test["eval_at"]
    if test["eval_mode"] == "after_close" and test["closes_at"]:
        return test["closes_at"] + timedelta(minutes=test["eval_delay_minutes"] or 0)
    return None
