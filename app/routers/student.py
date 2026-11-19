"""Student-facing API: login, the list of tests, and taking a test (students are added by staff)."""
import secrets
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from app import security
from app.config import get_settings
from app.dependencies import STUDENT_COOKIE, client_ip, current_student, get_attempts, get_collection, get_db
from app.schemas import AnswersPayload, StudentLogin
from app.services import contest, questions, tests
from app.services.answers import flatten_answers

router = APIRouter(prefix="/api")


@router.post("/student/login")
def student_login(
    form: StudentLogin,
    request: Request,
    response: Response,
    collection: Collection = Depends(get_collection),
):
    keys = (f"student:{form.RegNo}", f"ip:{client_ip(request)}")
    if security.limiter.blocked(*keys):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    user = collection.find_one({"RegNo": form.RegNo})
    if not user or not security.safe_equal(str(user.get("dob", "")), form.dob.isoformat()):
        security.limiter.fail(*keys)
        raise HTTPException(status_code=401, detail="Register number and date of birth do not match.")
    security.limiter.reset(f"student:{form.RegNo}")
    settings = get_settings()
    # One active session per student: a new login invalidates any earlier one.
    sid = secrets.token_hex(8)
    collection.update_one({"_id": user["_id"]}, {"$set": {"sid": sid}})
    token = security.sign({"role": "student", "sub": form.RegNo, "sid": sid}, settings.secret_key, settings.session_hours * 3600)
    response.set_cookie(
        STUDENT_COOKIE, token, max_age=settings.session_hours * 3600,
        httponly=True, samesite="lax", secure=settings.cookie_secure,
    )
    return {"message": "Signed in.", "Name": user["Name"]}


@router.post("/student/logout")
def student_logout(response: Response):
    response.delete_cookie(STUDENT_COOKIE)
    return {"message": "Signed out."}


def _profile(user: dict) -> dict:
    return {k: user.get(k) for k in ("Name", "email", "RegNo", "year", "Branch", "Sec")}


def _published(db, tid: str) -> dict:
    test = tests.get(db, tid)
    if not test or not test["published"]:
        raise HTTPException(status_code=404, detail="Test not found.")
    return test


def _attempt_view(test: dict, attempt) -> dict:
    started = attempt.get("started_at") if attempt else None
    return {
        "state": contest.attempt_state(attempt, test),
        "started": bool(started),
        "started_at": contest.iso(started),
        "deadline": contest.iso(contest.deadline(test, started, attempt.get("extra_minutes", 0))) if started else None,
        "submitted": bool(attempt and attempt.get("submitted_at")),
        "server_time": contest.iso(contest.now()),
    }


def _find_attempt(attempts: Collection, tid: str, user: dict):
    return attempts.find_one({"test_id": tid, "RegNo": user["RegNo"]})


@router.get("/tests")
def list_tests(user: dict = Depends(current_student), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    """Every published test with this student's status in it."""
    mine = {a["test_id"]: a for a in attempts.find({"RegNo": user["RegNo"]})}
    out = []
    for t in tests.list_all(db):
        if t["published"]:
            out.append({**contest.public(t), "attempt": _attempt_view(t, mine.get(t["id"]))})
    return {"profile": _profile(user), "tests": out, "server_time": contest.iso(contest.now())}


@router.get("/tests/{tid}")
def test_state(tid: str, user: dict = Depends(current_student), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    """Profile, test info and attempt status. Questions are only sent by /start."""
    test = _published(db, tid)
    return {
        "profile": _profile(user),
        "contest": contest.public(test),
        "attempt": _attempt_view(test, _find_attempt(attempts, tid, user)),
        "limits": {"max_answer_chars": get_settings().max_answer_chars},
    }


@router.post("/tests/{tid}/start")
def start_test(tid: str, user: dict = Depends(current_student), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    test = _published(db, tid)
    attempt = _find_attempt(attempts, tid, user)
    limits = {"max_answer_chars": get_settings().max_answer_chars}
    if attempt and attempt.get("submitted_at"):
        return {"contest": contest.public(test), "attempt": _attempt_view(test, attempt), "questions": [], "answers": {}, "limits": limits}
    if not attempt or not attempt.get("started_at"):
        if contest.phase(test) != "open":
            raise HTTPException(status_code=403, detail="This test is not open right now.")
        if attempt:
            attempts.update_one({"_id": attempt["_id"]}, {"$set": {"started_at": contest.now()}})
        else:
            try:
                attempts.insert_one({"test_id": tid, "RegNo": user["RegNo"], "started_at": contest.now()})
            except DuplicateKeyError:  # double-click / two tabs: the other request won
                pass
        attempt = _find_attempt(attempts, tid, user)
    qs = list(questions.fetch_questions(db, tid).values())
    return {
        "contest": contest.public(test),
        "attempt": _attempt_view(test, attempt),
        "questions": qs,
        "answers": flatten_answers(attempt.get("pseudoCodeAnswers")),
        "limits": limits,
    }


@router.put("/tests/{tid}/answers")
def save_answers(
    tid: str,
    payload: AnswersPayload,
    user: dict = Depends(current_student),
    db=Depends(get_db),
    attempts: Collection = Depends(get_attempts),
):
    test = _published(db, tid)
    attempt = _find_attempt(attempts, tid, user)
    if not attempt or not attempt.get("started_at"):
        raise HTTPException(status_code=403, detail="Start the test first.")
    if attempt.get("submitted_at"):
        raise HTTPException(status_code=409, detail="You have already submitted.")
    limit = contest.deadline(test, attempt["started_at"], attempt.get("extra_minutes", 0)).timestamp() + contest.GRACE_SECONDS
    if contest.now().timestamp() > limit:
        raise HTTPException(status_code=403, detail="Time is up. Your last saved answers were kept.")
    valid = questions.fetch_questions(db, tid)
    for key in payload.pseudoCodeAnswers:
        if not key.isdigit() or int(key) not in valid:
            raise HTTPException(status_code=422, detail=f"invalid question id: {key}")
    update = {"pseudoCodeAnswers": payload.pseudoCodeAnswers}
    if payload.final:
        update["submitted_at"] = contest.now()
    attempts.update_one({"_id": attempt["_id"]}, {"$set": update})
    return {"message": "Submitted." if payload.final else "Saved.", "final": payload.final}


@router.post("/tests/{tid}/heartbeat")
def heartbeat(tid: str, user: dict = Depends(current_student), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    """Called every few seconds by the test page: marks the student online and returns live state
    (deadline changes from staff extensions, force-submit/reset, announcements)."""
    test = _published(db, tid)
    attempt = _find_attempt(attempts, tid, user)
    if attempt:
        attempts.update_one({"_id": attempt["_id"]}, {"$set": {"last_seen": contest.now()}})
    return {"attempt": _attempt_view(test, attempt), "phase": contest.phase(test), "announcement": test.get("announcement")}


class EventIn(BaseModel):
    type: Literal["blur", "paste", "copy"]
    detail: Optional[str] = Field(default=None, max_length=100)


@router.post("/tests/{tid}/event")
def log_event(
    tid: str,
    body: EventIn,
    user: dict = Depends(current_student),
    db=Depends(get_db),
    attempts: Collection = Depends(get_attempts),
):
    """Integrity log (tab/window switches, paste, copy). Recorded for staff; never blocks the student."""
    _published(db, tid)
    attempt = _find_attempt(attempts, tid, user)
    if not attempt or not attempt.get("started_at") or attempt.get("submitted_at"):
        return {"recorded": False}
    attempts.update_one(
        {"_id": attempt["_id"]},
        {
            "$inc": {f"flags.{body.type}": 1},
            "$push": {"events": {"$each": [{"t": contest.now(), "type": body.type, "detail": body.detail}], "$slice": -200}},
        },
    )
    return {"recorded": True}
