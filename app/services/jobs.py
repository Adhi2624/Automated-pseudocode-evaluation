"""Grading job queue in MongoDB. The web app enqueues jobs; the worker process polls and runs them."""
import secrets
from datetime import timedelta

from pymongo import ReturnDocument

from app.services import contest

COLLECTION = "jobs"
WORKER_COLLECTION = "worker_status"
STALE_SECONDS = 300      # a running job with no heartbeat for this long is considered abandoned
MAX_ATTEMPTS = 3
WORKER_ONLINE_SECONDS = 30


def enqueue(db, test_id: str, trigger: str = "manual", force: bool = False, run_at=None):
    """Queue a grading job. At most one pending job per test: returns (job_id, created)."""
    pending = db[COLLECTION].find_one({"test_id": test_id, "status": "pending"})
    if pending:
        if force and not pending.get("force"):
            db[COLLECTION].update_one({"_id": pending["_id"]}, {"$set": {"force": True}})
        return pending["_id"], False
    now = contest.now()
    job_id = secrets.token_hex(6)
    db[COLLECTION].insert_one({
        "_id": job_id, "type": "grade", "test_id": test_id, "trigger": trigger, "force": force,
        "status": "pending", "run_at": run_at or now, "created_at": now, "attempts": 0,
        "progress": {"done": 0, "total": 0}, "log": [],
    })
    return job_id, True


def has_active(db, test_id: str) -> bool:
    return bool(db[COLLECTION].find_one({"test_id": test_id, "status": {"$in": ["pending", "running"]}}, {"_id": 1}))


def claim(db, now=None):
    """Atomically take the oldest due pending job (skipping tests that already have a running job)."""
    now = now or contest.now()
    busy = db[COLLECTION].distinct("test_id", {"status": "running"})
    return db[COLLECTION].find_one_and_update(
        {"status": "pending", "run_at": {"$lte": now}, "test_id": {"$nin": busy}},
        {"$set": {"status": "running", "started_at": now, "heartbeat_at": now}, "$inc": {"attempts": 1}},
        sort=[("run_at", 1)], return_document=ReturnDocument.AFTER,
    )


def requeue_stale(db, now=None) -> int:
    """Recover jobs whose worker died mid-run."""
    now = now or contest.now()
    n = 0
    for job in list(db[COLLECTION].find({"status": "running", "heartbeat_at": {"$lt": now - timedelta(seconds=STALE_SECONDS)}})):
        if job.get("attempts", 0) >= MAX_ATTEMPTS:
            db[COLLECTION].update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "finished_at": now, "error": "worker stopped while running this job"}})
        else:
            db[COLLECTION].update_one({"_id": job["_id"]}, {"$set": {"status": "pending", "run_at": now}})
        n += 1
    return n


def progress(db, job_id: str, done: int, total: int, log_tail: list) -> None:
    db[COLLECTION].update_one(
        {"_id": job_id, "status": "running"},
        {"$set": {"progress": {"done": done, "total": total}, "log": log_tail[-30:], "heartbeat_at": contest.now()}},
    )


def finish(db, job_id: str, status: str, log_tail: list, result=None, error=None) -> None:
    db[COLLECTION].update_one(
        {"_id": job_id},
        {"$set": {"status": status, "finished_at": contest.now(), "log": log_tail[-30:], "result": result, "error": error}},
    )


def cancel(db, job_id: str, test_id: str) -> bool:
    res = db[COLLECTION].update_one({"_id": job_id, "test_id": test_id, "status": "pending"},
                                    {"$set": {"status": "cancelled", "finished_at": contest.now()}})
    return res.matched_count > 0


def list_for_test(db, test_id: str, limit: int = 10) -> list:
    return list(db[COLLECTION].find({"test_id": test_id}).sort([("created_at", -1), ("_id", -1)]).limit(limit))


def view(job: dict) -> dict:
    return {
        "id": job["_id"], "status": job["status"], "trigger": job.get("trigger"), "force": bool(job.get("force")),
        "run_at": contest.iso(job.get("run_at")), "created_at": contest.iso(job.get("created_at")),
        "started_at": contest.iso(job.get("started_at")), "finished_at": contest.iso(job.get("finished_at")),
        "progress": job.get("progress") or {"done": 0, "total": 0}, "log": job.get("log") or [],
        "error": job.get("error"), "result": job.get("result"),
    }


def touch_worker(db) -> None:
    db[WORKER_COLLECTION].update_one({"_id": "grader"}, {"$set": {"last_seen": contest.now()}}, upsert=True)


def worker_status(db) -> dict:
    doc = db[WORKER_COLLECTION].find_one({"_id": "grader"})
    seen = doc.get("last_seen") if doc else None
    ago = (contest.now() - seen).total_seconds() if seen else None
    return {"online": ago is not None and ago <= WORKER_ONLINE_SECONDS, "seen_seconds_ago": None if ago is None else int(ago)}
