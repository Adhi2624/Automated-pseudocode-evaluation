from datetime import timedelta

import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo import ASCENDING
from pymongo.errors import PyMongoError

from app import security
from app.config import get_settings
from app.dependencies import get_collection, get_db
from app.main import app
from app.services import contest
from app.services import bootstrap, questions as qsvc, tests as tsvc
from app.services.questions import fetch_questions

VALID = {
    "Name": "Alice", "email": "a@example.com", "MobNo": "9876543210",
    "RegNo": 1001, "dob": "2004-05-17", "year": 2, "Branch": "CSE", "Sec": "A",
}
LOGIN = {"RegNo": 1001, "dob": "2004-05-17"}
STAFF = {"username": "staff", "password": "s3cret-pass"}


@pytest.fixture
def db():
    d = mongomock.MongoClient()["testdb"]
    d["user-details"].create_index([("RegNo", ASCENDING)], unique=True)
    d["attempts"].create_index([("test_id", ASCENDING), ("RegNo", ASCENDING)], unique=True)
    return d


@pytest.fixture(autouse=True)
def fresh_limiter():
    security.limiter._fails.clear()


@pytest.fixture
def make_client(db):
    app.dependency_overrides[get_db] = lambda: db
    clients = []

    def make():
        c = TestClient(app, raise_server_exceptions=False)
        clients.append(c)
        return c

    yield make
    app.dependency_overrides.clear()


@pytest.fixture
def anon(make_client):
    return make_client()


@pytest.fixture
def student(make_client, db):
    c = make_client()
    db["user-details"].insert_one(dict(VALID))
    assert c.post("/api/student/login", json=LOGIN).status_code == 200
    return c


@pytest.fixture
def staff(make_client):
    c = make_client()
    assert c.post("/api/staff/login", json=STAFF).status_code == 200
    return c


def add_student(db, **over):
    db["user-details"].insert_one({**VALID, **over})


def make_test(db, nq=3, **over):
    """Create a test with `nq` questions; returns its id."""
    cfg = {"title": "T", "duration_minutes": 30, "opens_at": None, "closes_at": None, "published": True}
    t = tsvc.create(db, {**cfg, **over})
    for i in range(nq):
        qsvc.add(db, t["id"], f"Question {i}", 10)
    return t["id"]


def open_contest(db, **over):
    return make_test(db, **over)


def attempt(db, tid, reg=1001):
    return db["attempts"].find_one({"test_id": tid, "RegNo": reg})


def add_attempt(db, tid, reg, **fields):
    db["attempts"].insert_one({"test_id": tid, "RegNo": reg, **fields})


# ---------- no self-registration / old single-test routes are gone ----------

def test_removed_routes(anon):
    assert anon.post("/api/register", json=VALID).status_code in (404, 405)
    assert anon.get("/register").status_code == 404
    assert anon.get("/api/questions").status_code == 404
    assert anon.get("/api/test").status_code == 404
    assert anon.post("/submit", json=VALID).status_code in (404, 405)


# ---------- student login ----------

def test_login_wrong_dob_401(anon, db):
    add_student(db)
    assert anon.post("/api/student/login", json={**LOGIN, "dob": "2004-05-18"}).status_code == 401


def test_login_unknown_regno_same_message(anon, db):
    add_student(db)
    a = anon.post("/api/student/login", json={**LOGIN, "RegNo": 9999}).json()
    b = anon.post("/api/student/login", json={**LOGIN, "dob": "2000-01-01"}).json()
    assert a == b  # no user enumeration


def test_login_rate_limited(anon, db):
    add_student(db)
    codes = [anon.post("/api/student/login", json={**LOGIN, "dob": "2000-01-01"}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[8] == 429
    assert anon.post("/api/student/login", json=LOGIN).status_code == 429


def test_login_sets_httponly_cookie(anon, db):
    add_student(db)
    cookie = anon.post("/api/student/login", json=LOGIN).headers["set-cookie"].lower()
    assert "student_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_student_endpoints_require_login(anon, db):
    tid = make_test(db)
    assert anon.get("/api/tests").status_code == 401
    assert anon.get(f"/api/tests/{tid}").status_code == 401
    assert anon.post(f"/api/tests/{tid}/start").status_code == 401
    assert anon.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {}}).status_code == 401


def test_forged_cookie_rejected(anon):
    anon.cookies.set("student_session", security.sign({"role": "student", "sub": 1001, "sid": "x"}, "wrong-key", 600))
    assert anon.get("/api/tests").status_code == 401


def test_staff_cookie_is_not_a_student_session(staff):
    assert staff.get("/api/tests").status_code == 401


def test_single_active_session_new_login_kicks_old(make_client, db):
    add_student(db)
    a, b = make_client(), make_client()
    assert a.post("/api/student/login", json=LOGIN).status_code == 200
    assert a.get("/api/tests").status_code == 200
    assert b.post("/api/student/login", json=LOGIN).status_code == 200
    r = a.get("/api/tests")
    assert r.status_code == 401 and "elsewhere" in r.json()["detail"]
    assert b.get("/api/tests").status_code == 200


# ---------- the student's test list ----------

def test_list_shows_only_published_tests_and_hides_dob(student, db):
    pub = make_test(db, title="Live one")
    make_test(db, title="Secret draft", published=False)
    body = student.get("/api/tests").json()
    assert [t["title"] for t in body["tests"]] == ["Live one"]
    assert body["tests"][0]["id"] == pub and body["tests"][0]["attempt"]["state"] == "not_started"
    assert "dob" not in str(body) and body["profile"]["RegNo"] == 1001


def test_draft_and_unknown_tests_404(student, db):
    draft = make_test(db, published=False)
    for tid in (draft, "nope"):
        assert student.get(f"/api/tests/{tid}").status_code == 404
        assert student.post(f"/api/tests/{tid}/start").status_code == 404


def test_list_reflects_per_test_state(student, db):
    a, b = make_test(db, title="A"), make_test(db, title="B")
    student.post(f"/api/tests/{a}/start")
    student.put(f"/api/tests/{a}/answers", json={"pseudoCodeAnswers": {"0": "x"}, "final": True})
    student.post(f"/api/tests/{b}/start")
    states = {t["title"]: t["attempt"]["state"] for t in student.get("/api/tests").json()["tests"]}
    assert states == {"A": "submitted", "B": "in_progress"}


# ---------- taking a test ----------

def test_start_blocked_when_not_open(student, db):
    for cfg, expected in [({"published": True, "opens_at": contest.now() + timedelta(hours=1)}, "upcoming"),
                          ({"closes_at": contest.now() - timedelta(minutes=1)}, "closed")]:
        tid = make_test(db, **cfg)
        assert student.get(f"/api/tests/{tid}").json()["contest"]["phase"] == expected
        assert student.post(f"/api/tests/{tid}/start").status_code == 403


def test_questions_not_exposed_before_start(student, db):
    tid = make_test(db)
    assert "questions" not in student.get(f"/api/tests/{tid}").json()


def test_start_returns_that_tests_questions_and_is_idempotent(student, db):
    t1, t2 = make_test(db, nq=2), make_test(db, nq=4)
    a = student.post(f"/api/tests/{t1}/start").json()
    assert len(a["questions"]) == 2 and student.post(f"/api/tests/{t2}/start").json()["questions"].__len__() == 4
    b = student.post(f"/api/tests/{t1}/start").json()
    assert a["attempt"]["started_at"] == b["attempt"]["started_at"] and a["attempt"]["deadline"]
    assert db["attempts"].count_documents({"test_id": t1, "RegNo": 1001}) == 1


def test_deadline_capped_by_closing_time(student, db):
    tid = make_test(db, duration_minutes=120, closes_at=contest.now() + timedelta(minutes=10))
    d = student.post(f"/api/tests/{tid}/start").json()["attempt"]
    assert d["deadline"] < contest.iso(contest.now() + timedelta(minutes=11))


def test_answers_require_start(student, db):
    tid = make_test(db)
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "x"}}).status_code == 403


def test_autosave_resume_and_final_submit(student, db):
    tid = make_test(db)
    student.post(f"/api/tests/{tid}/start")
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "a", "1": "b"}}).status_code == 200
    assert student.post(f"/api/tests/{tid}/start").json()["answers"] == {"0": "a", "1": "b"}
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "z"}, "final": True}).status_code == 200
    assert student.get(f"/api/tests/{tid}").json()["attempt"]["submitted"] is True
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "late"}}).status_code == 409
    assert attempt(db, tid)["pseudoCodeAnswers"] == {"0": "z"}


def test_answers_are_isolated_between_tests(student, db):
    a, b = make_test(db), make_test(db)
    student.post(f"/api/tests/{a}/start"); student.post(f"/api/tests/{b}/start")
    student.put(f"/api/tests/{a}/answers", json={"pseudoCodeAnswers": {"0": "in A"}, "final": True})
    student.put(f"/api/tests/{b}/answers", json={"pseudoCodeAnswers": {"0": "in B"}})
    assert attempt(db, a)["pseudoCodeAnswers"] == {"0": "in A"} and attempt(db, b)["pseudoCodeAnswers"] == {"0": "in B"}
    assert student.get(f"/api/tests/{a}").json()["attempt"]["submitted"] is True
    assert student.get(f"/api/tests/{b}").json()["attempt"]["submitted"] is False


def test_answer_ids_validated_against_this_tests_questions(student, db):
    small, big = make_test(db, nq=1), make_test(db, nq=5)
    student.post(f"/api/tests/{small}/start"); student.post(f"/api/tests/{big}/start")
    assert student.put(f"/api/tests/{big}/answers", json={"pseudoCodeAnswers": {"4": "ok"}}).status_code == 200
    assert student.put(f"/api/tests/{small}/answers", json={"pseudoCodeAnswers": {"4": "nope"}}).status_code == 422


def test_answers_rejected_after_deadline(student, db):
    tid = make_test(db, duration_minutes=5)
    student.post(f"/api/tests/{tid}/start")
    db["attempts"].update_one({"test_id": tid}, {"$set": {"started_at": contest.now() - timedelta(minutes=6)}})
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "x"}}).status_code == 403


def test_grace_window_allows_final_autosubmit(student, db):
    tid = make_test(db, duration_minutes=5)
    student.post(f"/api/tests/{tid}/start")
    db["attempts"].update_one({"test_id": tid}, {"$set": {"started_at": contest.now() - timedelta(minutes=5, seconds=5)}})
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "x"}, "final": True}).status_code == 200


def test_answer_validation(student, db):
    tid = make_test(db)
    student.post(f"/api/tests/{tid}/start")
    for bad in ("9999", "abc", "-1"):
        assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {bad: "x"}}).status_code == 422, bad
    big = "x" * (get_settings().max_answer_chars + 1)
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": big}}).status_code == 422
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": 5}}).status_code == 422


def test_student_cannot_touch_other_student(make_client, db):
    tid = make_test(db)
    add_student(db); add_student(db, RegNo=2002, email="b@example.com")
    a, b = make_client(), make_client()
    a.post("/api/student/login", json=LOGIN)
    b.post("/api/student/login", json={"RegNo": 2002, "dob": "2004-05-17"})
    for c, text in ((a, "mine"), (b, "theirs")):
        c.post(f"/api/tests/{tid}/start")
        c.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": text}})
    assert attempt(db, tid, 1001)["pseudoCodeAnswers"] == {"0": "mine"}
    assert attempt(db, tid, 2002)["pseudoCodeAnswers"] == {"0": "theirs"}


# ---------- live heartbeat, integrity events ----------

def test_heartbeat_and_announcement_are_per_test(student, staff, db):
    a, b = make_test(db), make_test(db)
    student.post(f"/api/tests/{a}/start"); student.post(f"/api/tests/{b}/start")
    staff.put(f"/api/staff/tests/{a}/announcement", json={"text": "  10 minutes left  "})
    hb_a = student.post(f"/api/tests/{a}/heartbeat").json()
    assert hb_a["phase"] == "open" and hb_a["announcement"]["text"] == "10 minutes left"
    assert student.post(f"/api/tests/{b}/heartbeat").json()["announcement"] is None
    staff.put(f"/api/staff/tests/{a}/announcement", json={"text": ""})
    assert student.post(f"/api/tests/{a}/heartbeat").json()["announcement"] is None
    assert staff.put(f"/api/staff/tests/{a}/announcement", json={"text": "x" * 301}).status_code == 422


def test_events_logged_per_test_and_capped(student, staff, db):
    a, b = make_test(db), make_test(db)
    assert student.post(f"/api/tests/{a}/event", json={"type": "blur"}).json()["recorded"] is False  # not started
    student.post(f"/api/tests/{a}/start"); student.post(f"/api/tests/{b}/start")
    for _ in range(3):
        student.post(f"/api/tests/{a}/event", json={"type": "blur"})
    student.post(f"/api/tests/{a}/event", json={"type": "paste", "detail": "Q1"})
    assert student.post(f"/api/tests/{a}/event", json={"type": "bogus"}).status_code == 422
    row = staff.get(f"/api/staff/tests/{a}/monitor").json()["students"][0]
    assert row["blur"] == 3 and row["paste"] == 1
    assert staff.get(f"/api/staff/tests/{b}/monitor").json()["students"][0]["blur"] == 0
    assert staff.get(f"/api/staff/tests/{a}/monitor").json()["counts"]["flagged"] == 1
    ev = staff.get(f"/api/staff/tests/{a}/students/1001/events").json()
    assert ev["flags"]["blur"] == 3 and len(ev["events"]) == 4
    for _ in range(205):
        student.post(f"/api/tests/{b}/event", json={"type": "copy"})
    assert len(attempt(db, b)["events"]) == 200


# ---------- staff auth ----------

def test_staff_login_wrong_password(anon):
    assert anon.post("/api/staff/login", json={**STAFF, "password": "nope"}).status_code == 401


def test_staff_login_rate_limited(anon):
    codes = [anon.post("/api/staff/login", json={**STAFF, "password": "x"}).status_code for _ in range(9)]
    assert codes[-1] == 429


def test_staff_login_disabled_without_credentials(anon, monkeypatch):
    import app.routers.staff as staff_mod
    monkeypatch.setattr(staff_mod, "get_settings", lambda: get_settings().__class__(
        **{**get_settings().__dict__, "staff_username": "", "staff_password": ""}))
    assert anon.post("/api/staff/login", json=STAFF).status_code == 503


T1 = "abc"  # any id: auth is checked before the test is looked up


@pytest.mark.parametrize("method,url,body", [
    ("get", "/api/staff/tests", None), ("post", "/api/staff/tests", {"title": "x"}),
    ("get", f"/api/staff/tests/{T1}", None), ("put", f"/api/staff/tests/{T1}", {"title": "x", "duration_minutes": 5}),
    ("delete", f"/api/staff/tests/{T1}", None),
    ("get", f"/api/staff/tests/{T1}/questions", None), ("post", f"/api/staff/tests/{T1}/questions", {"text": "q"}),
    ("put", f"/api/staff/tests/{T1}/questions/0", {"text": "q"}), ("delete", f"/api/staff/tests/{T1}/questions/0", None),
    ("get", f"/api/staff/tests/{T1}/submissions", None), ("get", f"/api/staff/tests/{T1}/submissions/1", None),
    ("get", f"/api/staff/tests/{T1}/monitor", None), ("get", f"/api/staff/tests/{T1}/results", None),
    ("get", f"/api/staff/tests/{T1}/results.csv", None), ("post", f"/api/staff/tests/{T1}/grade", None),
    ("get", f"/api/staff/tests/{T1}/grade", None), ("put", f"/api/staff/tests/{T1}/announcement", {"text": "x"}),
    ("post", f"/api/staff/tests/{T1}/students/1/extend", {"minutes": 5}),
    ("post", f"/api/staff/tests/{T1}/students/1/reset", None), ("post", f"/api/staff/tests/{T1}/students/1/force-submit", None),
    ("get", f"/api/staff/tests/{T1}/students/1/events", None),
    ("get", "/api/staff/students", None), ("post", "/api/staff/students", {"RegNo": 5, "Name": "x", "dob": "2004-01-01"}),
    ("delete", "/api/staff/students/1", None), ("post", "/api/staff/students/upload", None),
])
def test_staff_endpoints_require_staff(anon, student, method, url, body):
    for c in (anon, student):  # a logged-in student is not staff
        assert getattr(c, method)(url, **({"json": body} if body else {})).status_code == 401


# ---------- staff: managing tests ----------

def test_create_list_update_delete_tests(staff, db):
    t = staff.post("/api/staff/tests", json={"title": "  Round 1  ", "duration_minutes": 45})
    assert t.status_code == 201 and t.json()["title"] == "Round 1" and t.json()["phase"] == "draft"
    tid = t.json()["id"]
    assert [x["id"] for x in staff.get("/api/staff/tests").json()] == [tid]
    body = {"title": "Round 1", "duration_minutes": 45, "published": False,
            "opens_at": "2030-01-01T09:00:00Z", "closes_at": "2030-01-01T12:00:00Z"}
    assert staff.put(f"/api/staff/tests/{tid}", json=body).status_code == 200
    assert staff.delete(f"/api/staff/tests/{tid}").status_code == 200
    assert staff.get(f"/api/staff/tests/{tid}").status_code == 404 and staff.delete(f"/api/staff/tests/{tid}").status_code == 404


def test_test_config_validation_and_timezones(staff):
    tid = staff.post("/api/staff/tests", json={"title": "t"}).json()["id"]
    qid_url = f"/api/staff/tests/{tid}/questions"
    staff.post(qid_url, json={"text": "q"})
    body = {"title": "t", "duration_minutes": 45, "published": True, "opens_at": "2030-01-01T10:00:00+05:30", "closes_at": "2030-01-01T12:00:00Z"}
    r = staff.put(f"/api/staff/tests/{tid}", json=body).json()
    assert r["opens_at"] == "2030-01-01T04:30:00Z" and r["phase"] == "upcoming"
    assert staff.put(f"/api/staff/tests/{tid}", json={**body, "closes_at": "2030-01-01T03:00:00Z"}).status_code == 422
    assert staff.put(f"/api/staff/tests/{tid}", json={**body, "duration_minutes": 0}).status_code == 422
    assert staff.post("/api/staff/tests", json={"title": "   "}).status_code == 422


def test_cannot_publish_without_questions(staff):
    tid = staff.post("/api/staff/tests", json={"title": "t"}).json()["id"]
    r = staff.put(f"/api/staff/tests/{tid}", json={"title": "t", "duration_minutes": 5, "published": True})
    assert r.status_code == 400


def test_duplicate_test_copies_questions(staff):
    src = staff.post("/api/staff/tests", json={"title": "src"}).json()["id"]
    staff.post(f"/api/staff/tests/{src}/questions", json={"text": "one", "max_score": 4})
    staff.post(f"/api/staff/tests/{src}/questions", json={"text": "two"})
    new = staff.post("/api/staff/tests", json={"title": "copy", "copy_from": src}).json()
    assert new["questions"] == 2
    got = staff.get(f"/api/staff/tests/{new['id']}/questions").json()
    assert [(q["text"], q["max_score"]) for q in got] == [("one", 4), ("two", 10)]
    assert staff.post("/api/staff/tests", json={"title": "x", "copy_from": "missing"}).status_code == 404


def test_delete_test_with_attempts_needs_force(staff, student, db):
    tid = make_test(db)
    other = make_test(db)
    student.post(f"/api/tests/{tid}/start"); student.post(f"/api/tests/{other}/start")
    r = staff.delete(f"/api/staff/tests/{tid}")
    assert r.status_code == 409 and "1 student" in r.json()["detail"]
    assert staff.delete(f"/api/staff/tests/{tid}?force=true").status_code == 200
    assert db["attempts"].count_documents({"test_id": tid}) == 0 and db["questions"].count_documents({"test_id": tid}) == 0
    assert db["attempts"].count_documents({"test_id": other}) == 1 and db["questions"].count_documents({"test_id": other}) == 3


def test_questions_are_per_test_with_crud(staff, student, db):
    a, b = make_test(db, nq=1), make_test(db, nq=1)
    created = staff.post(f"/api/staff/tests/{a}/questions", json={"text": "  New one  ", "max_score": 7})
    assert created.status_code == 201 and created.json() == {"id": 1, "text": "New one", "max_score": 7}
    assert len(staff.get(f"/api/staff/tests/{a}/questions").json()) == 2
    assert len(staff.get(f"/api/staff/tests/{b}/questions").json()) == 1
    assert staff.put(f"/api/staff/tests/{a}/questions/1", json={"text": "Edited", "max_score": 8}).status_code == 200
    qs = student.post(f"/api/tests/{a}/start").json()["questions"]
    assert {"id": 1, "text": "Edited", "max_score": 8} in qs
    assert staff.delete(f"/api/staff/tests/{a}/questions/1").status_code == 200
    assert staff.delete(f"/api/staff/tests/{a}/questions/1").status_code == 404
    assert staff.put(f"/api/staff/tests/{b}/questions/1", json={"text": "x"}).status_code == 404
    assert staff.post("/api/staff/tests/nope/questions", json={"text": "q"}).status_code == 404


def test_question_validation(staff, db):
    tid = make_test(db)
    assert staff.post(f"/api/staff/tests/{tid}/questions", json={"text": "   "}).status_code == 422
    assert staff.post(f"/api/staff/tests/{tid}/questions", json={"text": "q", "max_score": 0}).status_code == 422


# ---------- staff: monitoring one test ----------

def test_monitor_states_are_per_test(staff, db):
    t1, t2 = make_test(db, duration_minutes=10), make_test(db, duration_minutes=10)
    for r in (1, 2, 3, 4):
        add_student(db, RegNo=r, email=f"{r}@x.com")
    add_attempt(db, t1, 2, started_at=contest.now())
    add_attempt(db, t1, 3, started_at=contest.now() - timedelta(minutes=30))
    add_attempt(db, t1, 4, started_at=contest.now(), submitted_at=contest.now())
    add_attempt(db, t2, 1, started_at=contest.now())
    s1 = {r["RegNo"]: r["state"] for r in staff.get(f"/api/staff/tests/{t1}/monitor").json()["students"]}
    s2 = {r["RegNo"]: r["state"] for r in staff.get(f"/api/staff/tests/{t2}/monitor").json()["students"]}
    assert s1 == {1: "not_started", 2: "in_progress", 3: "timed_out", 4: "submitted"}
    assert s2 == {1: "in_progress", 2: "not_started", 3: "not_started", 4: "not_started"}


def test_monitor_online_after_heartbeat(student, staff, db):
    tid = make_test(db)
    student.post(f"/api/tests/{tid}/start")
    student.post(f"/api/tests/{tid}/heartbeat")
    m = staff.get(f"/api/staff/tests/{tid}/monitor").json()
    row = m["students"][0]
    assert row["online"] is True and row["remaining_seconds"] > 0
    assert m["counts"]["in_progress"] == 1 and m["counts"]["online"] == 1 and m["total_questions"] == 3


def test_extend_time_per_test_works_past_closing(student, staff, db):
    tid, other = make_test(db, duration_minutes=10, closes_at=contest.now() + timedelta(minutes=10)), make_test(db, duration_minutes=10)
    student.post(f"/api/tests/{tid}/start"); student.post(f"/api/tests/{other}/start")
    before = student.post(f"/api/tests/{tid}/heartbeat").json()["attempt"]["deadline"]
    assert staff.post(f"/api/staff/tests/{tid}/students/1001/extend", json={"minutes": 15}).json()["extra_minutes"] == 15
    assert student.post(f"/api/tests/{tid}/heartbeat").json()["attempt"]["deadline"] > before
    assert "extra_minutes" not in attempt(db, other)           # other test untouched
    db["attempts"].update_one({"test_id": tid}, {"$set": {"started_at": contest.now() - timedelta(minutes=20)}})
    assert student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "x"}}).status_code == 200


def test_extend_validation(staff, db):
    tid = make_test(db)
    add_student(db)
    url = f"/api/staff/tests/{tid}/students/1001/extend"
    assert staff.post(url, json={"minutes": 5}).status_code == 409      # not started
    add_attempt(db, tid, 1001, started_at=contest.now())
    assert staff.post(url, json={"minutes": 0}).status_code == 422
    assert staff.post(url, json={"minutes": 999}).status_code == 422
    assert staff.post(f"/api/staff/tests/{tid}/students/404/extend", json={"minutes": 5}).status_code == 404
    db["attempts"].update_one({"test_id": tid}, {"$set": {"submitted_at": contest.now()}})
    assert staff.post(url, json={"minutes": 5}).status_code == 409      # already submitted


def test_force_submit(student, staff, db):
    tid = make_test(db)
    student.post(f"/api/tests/{tid}/start")
    student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "partial"}})
    assert staff.post(f"/api/staff/tests/{tid}/students/1001/force-submit").status_code == 200
    assert student.post(f"/api/tests/{tid}/heartbeat").json()["attempt"]["submitted"] is True
    assert attempt(db, tid)["pseudoCodeAnswers"] == {"0": "partial"}


def test_reset_attempt_archives_and_only_affects_that_test(student, staff, db):
    a, b = make_test(db), make_test(db)
    student.post(f"/api/tests/{a}/start"); student.post(f"/api/tests/{b}/start")
    student.put(f"/api/tests/{a}/answers", json={"pseudoCodeAnswers": {"0": "old"}, "final": True})
    student.put(f"/api/tests/{b}/answers", json={"pseudoCodeAnswers": {"0": "keep"}})
    assert staff.post(f"/api/staff/tests/{a}/students/1001/reset").status_code == 200
    doc = attempt(db, a)
    assert "started_at" not in doc and "pseudoCodeAnswers" not in doc and doc["previous_attempts"][0]["answers"] == {"0": "old"}
    assert attempt(db, b)["pseudoCodeAnswers"] == {"0": "keep"}
    assert student.get(f"/api/tests/{a}").json()["attempt"]["started"] is False
    assert student.post(f"/api/tests/{a}/start").json()["answers"] == {}
    assert staff.post(f"/api/staff/tests/{a}/students/777/reset").status_code == 404


def test_announcement_does_not_clobber_settings(staff, db):
    tid = make_test(db)
    staff.put(f"/api/staff/tests/{tid}/announcement", json={"text": "hello"})
    staff.put(f"/api/staff/tests/{tid}", json={"title": "New", "duration_minutes": 20, "published": True})
    assert staff.get(f"/api/staff/tests/{tid}/monitor").json()["announcement"] == "hello"


def test_unknown_test_404_for_live_endpoints(staff):
    for path in ("monitor", "results", "submissions", "results.csv"):
        assert staff.get(f"/api/staff/tests/zzz/{path}").status_code == 404


# ---------- staff: submissions, results, grading ----------

def test_submissions_list_and_detail_hide_dob(staff, student, db):
    tid = make_test(db)
    student.post(f"/api/tests/{tid}/start")
    student.put(f"/api/tests/{tid}/answers", json={"pseudoCodeAnswers": {"0": "hello"}, "final": True})
    rows = staff.get(f"/api/staff/tests/{tid}/submissions").json()
    assert rows[0]["RegNo"] == 1001 and rows[0]["answered"] == 1 and rows[0]["submitted_at"]
    detail = staff.get(f"/api/staff/tests/{tid}/submissions/1001").json()
    assert detail["answers"] == {"0": "hello"} and len(detail["questions"]) == 3
    assert "dob" not in str(rows) and "dob" not in str(detail) and "sid" not in str(detail)
    assert staff.get(f"/api/staff/tests/{tid}/submissions/42").status_code == 404


def test_legacy_nested_answers_flattened(staff, db):
    tid = make_test(db)
    add_student(db)
    add_attempt(db, tid, 1001, started_at=contest.now(), pseudoCodeAnswers={"pseudoCodeAnswers": {"0": "a"}})
    assert staff.get(f"/api/staff/tests/{tid}/submissions/1001").json()["answers"] == {"0": "a"}


def test_results_ranking_cutoff_and_csv(staff, db):
    tid, other = make_test(db, title="Round: A/B"), make_test(db)
    add_student(db, RegNo=1, Name="Low"); add_student(db, RegNo=2, Name='=HYPERLINK("x")'); add_student(db, RegNo=3, Name="Ungraded")
    add_attempt(db, tid, 1, started_at=contest.now(), totalScore=5, evaluation={"0": {"score": 5, "status": "ok"}})
    add_attempt(db, tid, 2, started_at=contest.now(), totalScore=18, evaluation={"0": {"score": 10}, "1": {"score": 8}})
    add_attempt(db, other, 3, started_at=contest.now(), totalScore=99)          # different test: must not leak in
    res = staff.get(f"/api/staff/tests/{tid}/results?cutoff=10").json()
    assert [r["RegNo"] for r in res["rows"]] == [2, 1, 3]
    assert res["shortlisted"] == 1 and res["graded"] == 2 and res["max_total"] == 30
    assert res["rows"][0]["shortlisted"] and not res["rows"][1]["shortlisted"] and res["rows"][2]["totalScore"] is None
    resp = staff.get(f"/api/staff/tests/{tid}/results.csv?cutoff=10")
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("Rank,RegNo,Name") and lines[0].endswith("Shortlisted")
    assert "'=HYPERLINK" in resp.text and ",YES" in lines[1]
    assert 'filename="Round--A-B-results.csv"' in resp.headers["content-disposition"]
    assert staff.get(f"/api/staff/tests/{tid}/results?cutoff=-1").status_code == 422


def test_grade_endpoint_queues_a_job_for_the_worker(staff, db):
    tid, other = make_test(db), make_test(db)
    r = staff.post(f"/api/staff/tests/{tid}/grade")
    assert r.status_code == 202 and r.json()["queued"] is True and r.json()["worker"]["online"] is False
    job = db["jobs"].find_one({"_id": r.json()["id"]})
    assert job["test_id"] == tid and job["status"] == "pending" and job["trigger"] == "manual" and job["force"] is False
    # one pending job per test: asking again reuses it (and can upgrade it to force)
    again = staff.post(f"/api/staff/tests/{tid}/grade?force=true").json()
    assert again["id"] == r.json()["id"] and again["queued"] is False
    assert db["jobs"].find_one({"_id": again["id"]})["force"] is True
    assert staff.post(f"/api/staff/tests/{other}/grade").json()["id"] != r.json()["id"]
    assert staff.post("/api/staff/tests/missing/grade").status_code == 404
    status = staff.get(f"/api/staff/tests/{tid}/grade").json()
    assert status["active"] is True and status["jobs"][0]["status"] == "pending" and status["evaluation"]["mode"] == "manual"


def test_cancel_only_pending_jobs(staff, db):
    tid = make_test(db)
    jid = staff.post(f"/api/staff/tests/{tid}/grade").json()["id"]
    assert staff.post(f"/api/staff/tests/{tid}/grade/{jid}/cancel").status_code == 200
    assert staff.post(f"/api/staff/tests/{tid}/grade/{jid}/cancel").status_code == 409
    assert db["jobs"].find_one({"_id": jid})["status"] == "cancelled"
    db["jobs"].update_one({"_id": jid}, {"$set": {"status": "running"}})
    assert staff.post(f"/api/staff/tests/{tid}/grade/{jid}/cancel").status_code == 409


def test_worker_status_in_grade_status(staff, db):
    from app.services import jobs
    tid = make_test(db)
    assert staff.get(f"/api/staff/tests/{tid}/grade").json()["worker"]["online"] is False
    jobs.touch_worker(db)
    assert staff.get(f"/api/staff/tests/{tid}/grade").json()["worker"]["online"] is True


def test_evaluation_settings_saved_validated_and_rearmed(staff, db):
    tid = make_test(db)
    base = {"title": "T", "duration_minutes": 30, "published": True, "closes_at": "2030-01-01T12:00:00Z"}
    r = staff.put(f"/api/staff/tests/{tid}", json={**base, "eval_mode": "after_close", "eval_delay_minutes": 15})
    assert r.status_code == 200 and r.json()["eval_mode"] == "after_close" and r.json()["eval_delay_minutes"] == 15
    st = staff.get(f"/api/staff/tests/{tid}/grade").json()["evaluation"]
    assert st["mode"] == "after_close" and st["scheduled_for"] == "2030-01-01T12:15:00Z"
    r = staff.put(f"/api/staff/tests/{tid}", json={**base, "eval_mode": "scheduled", "eval_at": "2030-02-01T08:00:00+05:30"})
    assert r.json()["eval_at"] == "2030-02-01T02:30:00Z"
    # invalid combinations
    assert staff.put(f"/api/staff/tests/{tid}", json={**base, "eval_mode": "scheduled"}).status_code == 422
    assert staff.put(f"/api/staff/tests/{tid}", json={"title": "T", "duration_minutes": 5, "eval_mode": "after_close"}).status_code == 422
    assert staff.put(f"/api/staff/tests/{tid}", json={**base, "eval_mode": "bogus"}).status_code == 422
    assert staff.put(f"/api/staff/tests/{tid}", json={**base, "eval_mode": "after_close", "eval_delay_minutes": -1}).status_code == 422
    # saving the settings re-arms a schedule that already fired
    db["tests"].update_one({"_id": tid}, {"$set": {"eval_fired_at": contest.now()}})
    staff.put(f"/api/staff/tests/{tid}", json={**base, "eval_mode": "scheduled", "eval_at": "2030-03-01T00:00:00Z"})
    assert db["tests"].find_one({"_id": tid})["eval_fired_at"] is None


# ---------- staff: roster ----------

CSV_OK = (
    "RegNo,Name,DOB,Email,Mobile,Year,Branch,Section\n"
    "3001,Asha Rao,2005-03-09,asha@example.com,9876543210,2,CSE,A\n"
    "3002,Ben Joy,09-03-2004,,,,,\n"
)


def upload(client, content, name="roster.csv"):
    body = content.encode() if isinstance(content, str) else content
    return client.post("/api/staff/students/upload", content=body, headers={"X-Filename": name})


def test_upload_csv_creates_students_who_can_log_in(staff, anon, db):
    r = upload(staff, CSV_OK)
    assert r.status_code == 200 and r.json() == {"created": 2, "updated": 0, "skipped": 0, "errors": []}
    assert db["user-details"].find_one({"RegNo": 3002})["dob"] == "2004-03-09"   # DD-MM-YYYY, day first
    assert anon.post("/api/student/login", json={"RegNo": 3001, "dob": "2005-03-09"}).status_code == 200
    assert [s["RegNo"] for s in staff.get("/api/staff/students").json()] == [3001, 3002]
    assert "dob" not in str(staff.get("/api/staff/students").json())


def test_upload_updates_existing_and_keeps_attempts(staff, db):
    tid = make_test(db)
    db["user-details"].insert_one({"RegNo": 3001, "Name": "Old", "dob": "2000-01-01"})
    add_attempt(db, tid, 3001, pseudoCodeAnswers={"0": "keep"})
    r = upload(staff, "RegNo,Name,DOB\n3001,New Name,2005-03-09\n").json()
    assert r["created"] == 0 and r["updated"] == 1
    assert db["user-details"].find_one({"RegNo": 3001})["Name"] == "New Name"
    assert attempt(db, tid, 3001)["pseudoCodeAnswers"] == {"0": "keep"}


def test_upload_reports_bad_rows_and_applies_good_ones(staff, db):
    csv = ("regno,name,date of birth\n1,Good,2005-01-02\nabc,Bad Reg,2005-01-02\n3,No Dob,\n4,Bad Date,31/31/2005\n1,Dup,2005-01-02\n")
    r = upload(staff, csv).json()
    assert r["created"] == 1 and r["skipped"] == 4
    assert any("Row 3" in e for e in r["errors"]) and any("duplicate" in e for e in r["errors"])
    assert db["user-details"].count_documents({}) == 1


def test_upload_header_aliases_and_semicolons(staff, db):
    r = upload(staff, "Roll No;Student Name;Date of Birth\n77;Zed;2003-12-31\n").json()
    assert r["created"] == 1 and db["user-details"].find_one({"RegNo": 77})["Name"] == "Zed"


def test_upload_xlsx(staff, db):
    import io
    from datetime import datetime
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["RegNo", "Name", "DOB"])
    ws.append([4001, "Excel Kid", datetime(2004, 7, 1)])
    ws.append([4002.0, "Text Date", "01/07/2004"])
    buf = io.BytesIO(); wb.save(buf)
    assert upload(staff, buf.getvalue(), "list.xlsx").json()["created"] == 2
    assert db["user-details"].find_one({"RegNo": 4001})["dob"] == "2004-07-01"
    assert db["user-details"].find_one({"RegNo": 4002})["dob"] == "2004-07-01"


@pytest.mark.parametrize("content,name", [
    ("RegNo,Name\n1,A\n", "x.csv"), ("RegNo,Name,DOB\n", "x.csv"),
    ("RegNo,Name,DOB\n1,A,2005-01-01\n", "x.pdf"), (b"not really an xlsx", "x.xlsx"),
])
def test_upload_bad_files_400(staff, content, name):
    assert upload(staff, content, name).status_code == 400


def test_upload_too_large_413(staff):
    assert upload(staff, "RegNo,Name,DOB\n" + "x" * 2_100_000).status_code == 413


def test_add_delete_student_removes_their_attempts(staff, db):
    tid = make_test(db)
    body = {"RegNo": 5005, "Name": " Cy ", "dob": "2004-02-02", "Branch": "IT"}
    assert staff.post("/api/staff/students", json=body).json()["created"] is True
    assert staff.post("/api/staff/students", json={**body, "Name": "Cy 2"}).json()["created"] is False
    assert db["user-details"].find_one({"RegNo": 5005})["Name"] == "Cy 2"
    add_attempt(db, tid, 5005, started_at=contest.now())
    assert staff.delete("/api/staff/students/5005").status_code == 200
    assert db["attempts"].count_documents({"RegNo": 5005}) == 0
    assert staff.delete("/api/staff/students/5005").status_code == 404


@pytest.mark.parametrize("patch", [{"dob": "2999-01-01"}, {"dob": "x"}, {"MobNo": "12"}, {"RegNo": 0}, {"Name": " "}, {"email": "no"}])
def test_add_student_validation(staff, patch):
    assert staff.post("/api/staff/students", json={"RegNo": 6, "Name": "N", "dob": "2004-02-02", **patch}).status_code == 422


# ---------- startup: first run + migration from the old single-contest layout ----------

def test_bootstrap_first_run_creates_sample_test():
    d = mongomock.MongoClient()["fresh"]
    bootstrap.run(d, "user-details")
    ts = tsvc.list_all(d)
    assert len(ts) == 1 and ts[0]["published"] is False and qsvc.count(d, ts[0]["id"]) >= 1
    bootstrap.run(d, "user-details")                        # idempotent
    assert len(tsvc.list_all(d)) == 1


def test_bootstrap_migrates_legacy_single_contest():
    d = mongomock.MongoClient()["legacy"]
    started = contest.now()
    d["contest"].insert_one({"_id": "config", "title": "Old Contest", "duration_minutes": 45, "published": True,
                             "opens_at": None, "closes_at": None})
    d["questions"].insert_many([{"_id": 0, "text": "Q zero", "max_score": 10}, {"_id": 1, "text": "Q one", "max_score": 5}])
    d["user-details"].insert_many([
        {"RegNo": 1, "Name": "Done", "dob": "2004-01-01", "started_at": started, "submitted_at": started,
         "pseudoCodeAnswers": {"0": "a"}, "evaluation": {"0": {"score": 9}}, "totalScore": 9, "flags": {"blur": 2}},
        {"RegNo": 2, "Name": "Idle", "dob": "2004-01-02"},
    ])
    bootstrap.run(d, "user-details")
    (t,) = tsvc.list_all(d)
    assert t["title"] == "Old Contest" and t["duration_minutes"] == 45 and t["published"] is True
    assert {q["text"] for q in fetch_questions(d, t["id"]).values()} == {"Q zero", "Q one"}
    assert d["questions"].count_documents({"test_id": {"$exists": False}}) == 0
    att = d["attempts"].find_one({"test_id": t["id"], "RegNo": 1})
    assert att["pseudoCodeAnswers"] == {"0": "a"} and att["totalScore"] == 9 and att["flags"] == {"blur": 2}
    assert d["attempts"].count_documents({}) == 1                                 # idle student gets no attempt
    u = d["user-details"].find_one({"RegNo": 1})
    assert "pseudoCodeAnswers" not in u and "started_at" not in u and u["Name"] == "Done"


# ---------- misc ----------

class _Boom:
    def __getattr__(self, name):
        def f(*a, **k):
            raise PyMongoError("mongodb://secret-host:27017 internal failure")
        return f


def test_db_outage_503_no_leak(make_client):
    app.dependency_overrides[get_collection] = lambda: _Boom()
    r = make_client().post("/api/student/login", json=LOGIN)
    assert r.status_code == 503
    assert "secret-host" not in r.text and "PyMongo" not in r.text and "Traceback" not in r.text


@pytest.mark.parametrize("path", ["/", "/login", "/tests", "/tests/abc123", "/thank", "/staff/login", "/staff"])
def test_pages_render(anon, path):
    r = anon.get(path)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and "/static/css/app.css" in r.text


def test_static_assets(anon):
    for f in ("css/app.css", "js/app.js", "js/test.js", "js/tests.js", "js/staff.js", "js/login.js"):
        assert anon.get("/static/" + f).status_code == 200


def test_cors_no_header_for_random_origin(anon):
    assert "access-control-allow-origin" not in anon.get("/", headers={"Origin": "https://evil.example"}).headers


def test_token_expiry_and_tamper():
    t = security.sign({"role": "x"}, "k", 60)
    assert security.verify(t, "k")["role"] == "x"
    assert security.verify(t + "a", "k") is None
    assert security.verify(security.sign({"role": "x"}, "k", -1), "k") is None
    assert security.verify("garbage", "k") is None
