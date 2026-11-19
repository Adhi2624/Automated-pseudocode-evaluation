"""Worker, job queue and evaluation scheduling (everything runs against mongomock; the LLM is stubbed)."""
from datetime import timedelta

import mongomock
import pytest

from app import worker
from app.config import get_settings
from app.grader import evaluator
from app.services import contest, jobs, questions as qsvc, tests as tsvc


@pytest.fixture
def db():
    return mongomock.MongoClient()["workerdb"]


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    calls = []

    def fake(attempt, questions, settings, session, force=False):
        calls.append((attempt["RegNo"], force))
        return {str(q): {"score": 7, "status": "ok"} for q in questions}

    monkeypatch.setattr(evaluator, "evaluate_user", fake)
    return calls


def make_test(db, **over):
    t = tsvc.create(db, {"title": "T", "duration_minutes": 30, "published": True, **over})
    qsvc.add(db, t["id"], "Q0", 10)
    qsvc.add(db, t["id"], "Q1", 10)
    return tsvc.get(db, t["id"])


def student(db, reg):
    db["user-details"].insert_one({"RegNo": reg, "Name": f"S{reg}", "dob": "2004-01-01"})


def attempt(db, tid, reg, **fields):
    db["attempts"].insert_one({"test_id": tid, "RegNo": reg, "pseudoCodeAnswers": {"0": "a"}, **fields})


def finished(db, tid, reg):
    student(db, reg)
    attempt(db, tid, reg, started_at=contest.now() - timedelta(minutes=5), submitted_at=contest.now())


def in_progress(db, tid, reg):
    student(db, reg)
    attempt(db, tid, reg, started_at=contest.now())


def timed_out(db, tid, reg):
    student(db, reg)
    attempt(db, tid, reg, started_at=contest.now() - timedelta(hours=2))


# ---------- queue ----------

def test_enqueue_dedups_pending_and_upgrades_force(db):
    a, created = jobs.enqueue(db, "t1")
    b, created2 = jobs.enqueue(db, "t1", force=True)
    assert a == b and created and not created2 and db["jobs"].find_one({"_id": a})["force"] is True
    assert jobs.enqueue(db, "t2")[0] != a


def test_claim_is_atomic_and_one_job_per_test_at_a_time(db):
    jobs.enqueue(db, "t1")
    first = jobs.claim(db)
    assert first["status"] == "running" and first["attempts"] == 1
    assert jobs.claim(db) is None                                  # nothing else pending
    jobs.enqueue(db, "t1")                                        # new request while t1 is running
    assert jobs.claim(db) is None                                  # ...waits: never two jobs on one test
    jobs.enqueue(db, "t2")
    assert jobs.claim(db)["test_id"] == "t2"


def test_claim_waits_for_run_at(db):
    jobs.enqueue(db, "t1", run_at=contest.now() + timedelta(minutes=10))
    assert jobs.claim(db) is None
    assert jobs.claim(db, now=contest.now() + timedelta(minutes=11))["test_id"] == "t1"


def test_stale_running_job_is_requeued_then_failed(db):
    jid, _ = jobs.enqueue(db, "t1")
    jobs.claim(db)
    old = contest.now() - timedelta(seconds=jobs.STALE_SECONDS + 5)
    db["jobs"].update_one({"_id": jid}, {"$set": {"heartbeat_at": old}})
    assert jobs.requeue_stale(db) == 1 and db["jobs"].find_one({"_id": jid})["status"] == "pending"
    db["jobs"].update_one({"_id": jid}, {"$set": {"status": "running", "heartbeat_at": old, "attempts": jobs.MAX_ATTEMPTS}})
    jobs.requeue_stale(db)
    j = db["jobs"].find_one({"_id": jid})
    assert j["status"] == "failed" and "worker stopped" in j["error"]


# ---------- running a job ----------

def test_run_once_grades_only_finished_attempts(db, fake_llm):
    t = make_test(db)
    finished(db, t["id"], 1)
    timed_out(db, t["id"], 2)
    in_progress(db, t["id"], 3)                  # still writing: must not be graded yet
    jid, _ = jobs.enqueue(db, t["id"])
    assert worker.run_once(db, get_settings()) == 1
    assert sorted(r for r, _ in fake_llm) == [1, 2]
    assert db["attempts"].find_one({"RegNo": 1})["totalScore"] == 14
    assert "evaluatedAt" in db["attempts"].find_one({"RegNo": 2})
    assert "evaluation" not in db["attempts"].find_one({"RegNo": 3})
    job = db["jobs"].find_one({"_id": jid})
    assert job["status"] == "done" and job["result"] == {"graded": 2, "failures": 0}
    assert job["progress"] == {"done": 2, "total": 2} and job["finished_at"]


def test_job_passes_force_flag_and_grades_other_tests_not_at_all(db, fake_llm):
    a, b = make_test(db, title="A"), make_test(db, title="B")
    finished(db, a["id"], 1)
    attempt(db, b["id"], 1, started_at=contest.now() - timedelta(minutes=5), submitted_at=contest.now())
    jobs.enqueue(db, a["id"], force=True)
    worker.run_once(db, get_settings())
    assert fake_llm == [(1, True)]
    assert "evaluation" not in db["attempts"].find_one({"test_id": b["id"]})


def test_job_fails_cleanly_for_missing_test_or_no_questions(db):
    jobs.enqueue(db, "ghost")
    t = tsvc.create(db, {"title": "empty", "published": True})
    jobs.enqueue(db, t["id"])
    assert worker.run_once(db, get_settings()) == 2
    errors = sorted(j["error"] for j in db["jobs"].find())
    assert errors == ["test has no questions", "test no longer exists"]


def test_crash_inside_a_job_fails_that_job_only(db, monkeypatch):
    t = make_test(db)
    finished(db, t["id"], 1)
    monkeypatch.setattr(evaluator, "grade_test", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    jid, _ = jobs.enqueue(db, t["id"])
    other, _ = jobs.enqueue(db, make_test(db, title="B")["id"])
    assert worker.run_once(db, get_settings()) == 2
    j = db["jobs"].find_one({"_id": jid})
    assert j["status"] == "failed" and "RuntimeError: boom" in j["error"]
    assert db["jobs"].find_one({"_id": other})["status"] == "failed"      # also boom, but the loop survived


def test_nothing_to_grade_still_completes(db):
    t = make_test(db)
    jid, _ = jobs.enqueue(db, t["id"])
    worker.run_once(db, get_settings())
    j = db["jobs"].find_one({"_id": jid})
    assert j["status"] == "done" and j["result"]["graded"] == 0 and any("nothing to grade" in l for l in j["log"])


def test_run_once_updates_worker_heartbeat(db):
    assert jobs.worker_status(db)["online"] is False
    worker.run_once(db, get_settings())
    assert jobs.worker_status(db)["online"] is True


# ---------- evaluation kinds ----------

def test_manual_mode_never_auto_queues(db):
    t = make_test(db, eval_mode="manual", closes_at=contest.now() - timedelta(hours=1))
    finished(db, t["id"], 1)
    assert worker.tick_schedule(db) == 0 and db["jobs"].count_documents({}) == 0


def test_immediate_mode_queues_when_work_appears_and_not_twice(db, fake_llm):
    t = make_test(db, eval_mode="immediate")
    in_progress(db, t["id"], 1)
    assert worker.tick_schedule(db) == 0                          # nobody finished yet
    finished(db, t["id"], 2)
    assert worker.tick_schedule(db) == 1
    assert worker.tick_schedule(db) == 0                          # a job is already waiting
    worker.run_once(db, get_settings())
    assert [r for r, _ in fake_llm] == [2]
    assert worker.tick_schedule(db) == 0                          # graded; nothing new
    finished(db, t["id"], 4)                                      # a later submission is picked up
    assert worker.tick_schedule(db) == 1


def test_immediate_mode_ignores_unpublished_tests(db):
    t = make_test(db, eval_mode="immediate", published=False)
    finished(db, t["id"], 1)
    assert worker.tick_schedule(db) == 0


def test_scheduled_mode_fires_once_at_the_time(db):
    when = contest.now() + timedelta(minutes=30)
    t = make_test(db, eval_mode="scheduled", eval_at=when)
    finished(db, t["id"], 1)
    assert worker.tick_schedule(db) == 0                          # too early
    assert worker.tick_schedule(db, now=when + timedelta(seconds=1)) == 1
    job = db["jobs"].find_one({})
    assert job["trigger"] == "schedule" and job["status"] == "pending"
    assert tsvc.get(db, t["id"])["eval_fired_at"] is not None
    db["jobs"].delete_many({})
    assert worker.tick_schedule(db, now=when + timedelta(hours=1)) == 0   # already fired: no repeat
    tsvc.update(db, t["id"], {"eval_fired_at": None})                     # editing the schedule re-arms it
    assert worker.tick_schedule(db, now=when + timedelta(hours=1)) == 1


def test_after_close_mode_waits_for_close_plus_delay(db):
    closes = contest.now().replace(microsecond=0) + timedelta(minutes=20)
    t = make_test(db, eval_mode="after_close", closes_at=closes, eval_delay_minutes=10)
    assert tsvc.eval_start_time(tsvc.get(db, t["id"])) == closes + timedelta(minutes=10)
    assert worker.tick_schedule(db, now=closes + timedelta(minutes=9)) == 0
    assert worker.tick_schedule(db, now=closes + timedelta(minutes=10)) == 1


def test_scheduled_run_after_close_skips_students_still_in_progress(db, fake_llm):
    when = contest.now() - timedelta(minutes=1)
    t = make_test(db, eval_mode="scheduled", eval_at=when)
    finished(db, t["id"], 1)
    in_progress(db, t["id"], 2)
    worker.run_once(db, get_settings())
    assert [r for r, _ in fake_llm] == [1]


# ---------- embedded worker (single-service deployments) ----------

def test_serve_runs_jobs_until_stopped(db, fake_llm):
    import threading
    t = make_test(db)
    finished(db, t["id"], 1)
    jobs.enqueue(db, t["id"])
    stop = threading.Event()
    settings = get_settings().__class__(**{**get_settings().__dict__, "worker_poll_seconds": 1})
    th = threading.Thread(target=worker.serve, args=(db, settings, stop), daemon=True)
    th.start()
    for _ in range(50):                                   # wait (max 5 s) for the job to finish
        if db["jobs"].find_one({"test_id": t["id"]})["status"] == "done":
            break
        stop.wait(0.1)
    stop.set()
    th.join(timeout=5)
    assert not th.is_alive()
    assert db["jobs"].find_one({"test_id": t["id"]})["status"] == "done" and fake_llm == [(1, False)]


def test_app_starts_embedded_worker_only_when_enabled(monkeypatch):
    import app.main as m
    started = []
    monkeypatch.setattr(m.worker, "serve", lambda db, s, stop: started.append(1) or stop.wait(2))
    fake_db = mongomock.MongoClient()["emb"]
    monkeypatch.setattr(m, "get_client", lambda s: type("C", (), {"__getitem__": lambda self, k: fake_db, "close": lambda self: None})())
    from fastapi.testclient import TestClient
    on = m.settings.__class__(**{**m.settings.__dict__, "embedded_worker": True})
    for flag, expected in ((False, 0), (True, 1)):
        started.clear()
        monkeypatch.setattr(m, "settings", on if flag else m.settings)
        with TestClient(m.app):
            pass
        assert len(started) == expected
