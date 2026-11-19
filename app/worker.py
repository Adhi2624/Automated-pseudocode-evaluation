"""Grading worker: polls MongoDB for jobs and for schedules that are due.

Run as its own process:  python -m app.worker
The web app only inserts documents into `jobs`; this process claims and runs them, so grading never blocks
requests and survives web restarts. Several workers may run: jobs are claimed atomically.
"""
import logging
import signal
import threading
import time
from collections import deque

import requests

from app.config import get_settings
from app.db import get_client
from app.grader import evaluator
from app.services import contest, jobs, tests
from app.services.questions import fetch_questions

log = logging.getLogger("worker")


def tick_schedule(db, now=None) -> int:
    """Queue grading jobs that the tests' evaluation settings call for. Returns how many jobs were queued."""
    now = now or contest.now()
    queued = 0
    for test in tests.list_all(db):
        if not test["published"]:
            continue
        mode = test["eval_mode"]
        if mode in ("scheduled", "after_close"):
            when = tests.eval_start_time(test)
            if when and now >= when and not test.get("eval_fired_at"):
                _id, created = jobs.enqueue(db, test["id"], trigger="schedule")
                tests.update(db, test["id"], {"eval_fired_at": now})
                queued += created
        elif mode == "immediate":
            ungraded = [a for a in evaluator.pending_attempts(db, test) if not a.get("evaluatedAt")]
            if ungraded and not jobs.has_active(db, test["id"]):
                _id, created = jobs.enqueue(db, test["id"], trigger="immediate")
                queued += created
    return queued


class _Tail(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines = deque(maxlen=30)

    def emit(self, record):
        self.lines.append(f"{time.strftime('%H:%M:%S')} {record.getMessage()}"[:300])


def run_job(db, settings, job, session) -> None:
    tid = job["test_id"]
    tail = _Tail()
    evaluator.log.addHandler(tail)
    evaluator.log.setLevel(logging.INFO)
    try:
        test = tests.get(db, tid)
        if not test:
            return jobs.finish(db, job["_id"], "failed", list(tail.lines), error="test no longer exists")
        questions = fetch_questions(db, tid)
        if not questions:
            return jobs.finish(db, job["_id"], "failed", list(tail.lines), error="test has no questions")
        done, failures = evaluator.grade_test(
            db, settings, test, questions, session, force=bool(job.get("force")),
            on_progress=lambda d, t: jobs.progress(db, job["_id"], d, t, list(tail.lines)),
        )
        if not done:
            tail.lines.append("nothing to grade: no finished attempts")
        jobs.finish(db, job["_id"], "done", list(tail.lines), result={"graded": len(done), "failures": failures})
    except Exception as exc:  # the job fails, the worker keeps running
        log.exception("job %s failed", job["_id"])
        jobs.finish(db, job["_id"], "failed", list(tail.lines), error=f"{type(exc).__name__}: {exc}")
    finally:
        evaluator.log.removeHandler(tail)


def run_once(db, settings, session=None) -> int:
    """One poll: heartbeat, recover stale jobs, queue due schedules, run every claimable job. Returns jobs run."""
    jobs.touch_worker(db)
    jobs.requeue_stale(db)
    tick_schedule(db)
    ran = 0
    own = session is None
    session = session or requests.Session()
    try:
        while True:
            job = jobs.claim(db)
            if not job:
                break
            log.info("running job %s (test %s, %s)", job["_id"], job["test_id"], job.get("trigger"))
            run_job(db, settings, job, session)
            jobs.touch_worker(db)
            ran += 1
    finally:
        if own:
            session.close()
    return ran


def serve(db, settings, stop: threading.Event) -> None:
    """Poll until `stop` is set. Used by the standalone worker and by the web app's embedded worker thread."""
    log.info("worker started; polling every %ss", settings.worker_poll_seconds)
    while not stop.is_set():
        try:
            run_once(db, settings)
        except Exception:
            log.exception("poll failed")
        stop.wait(max(settings.worker_poll_seconds, 1))
    log.info("worker stopped")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    serve(get_client(settings)[settings.mongo_db], settings, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
