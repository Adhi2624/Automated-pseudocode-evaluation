"""Staff API: login, tests (create/configure/delete) and their question banks."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pymongo.collection import Collection

from app import security
from app.config import get_settings
from app.dependencies import STAFF_COOKIE, client_ip, current_staff, get_attempts, get_db
from app.schemas import QuestionIn, StaffLogin, TestConfig, TestCreate
from app.services import contest, questions, tests

router = APIRouter(prefix="/api/staff")


def test_or_404(db, tid: str) -> dict:
    test = tests.get(db, tid)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found.")
    return test


@router.post("/login")
def staff_login(form: StaffLogin, request: Request, response: Response):
    settings = get_settings()
    if not settings.staff_username or not settings.staff_password:
        raise HTTPException(status_code=503, detail="Staff login is not configured (set STAFF_USERNAME and STAFF_PASSWORD).")
    keys = (f"staff:{form.username}", f"ip:{client_ip(request)}")
    if security.limiter.blocked(*keys):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    ok_user = security.safe_equal(form.username, settings.staff_username)
    ok_pass = security.safe_equal(form.password, settings.staff_password)
    if not (ok_user and ok_pass):
        security.limiter.fail(*keys)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    security.limiter.reset(*keys)
    token = security.sign({"role": "staff", "sub": settings.staff_username}, settings.secret_key, settings.session_hours * 3600)
    response.set_cookie(
        STAFF_COOKIE, token, max_age=settings.session_hours * 3600,
        httponly=True, samesite="lax", secure=settings.cookie_secure,
    )
    return {"message": "Signed in."}


@router.post("/logout")
def staff_logout(response: Response):
    response.delete_cookie(STAFF_COOKIE)
    return {"message": "Signed out."}


@router.get("/me")
def staff_me(username: str = Depends(current_staff)):
    return {"username": username}


# ---- tests ----

def _summary(db, test: dict, attempts: Collection) -> dict:
    started = submitted = 0
    for a in attempts.find({"test_id": test["id"]}, {"started_at": 1, "submitted_at": 1}):
        started += bool(a.get("started_at"))
        submitted += bool(a.get("submitted_at"))
    return {
        **contest.public(test), "questions": questions.count(db, test["id"]), "started": started, "submitted": submitted,
        "eval_mode": test["eval_mode"], "eval_at": contest.iso(test["eval_at"]), "eval_delay_minutes": test["eval_delay_minutes"],
    }


@router.get("/tests")
def list_tests(_: str = Depends(current_staff), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    return [_summary(db, t, attempts) for t in tests.list_all(db)]


@router.post("/tests", status_code=201)
def create_test(body: TestCreate, _: str = Depends(current_staff), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    if body.copy_from:
        test_or_404(db, body.copy_from)
    test = tests.create(db, {"title": body.title, "duration_minutes": body.duration_minutes})
    if body.copy_from:
        questions.copy_all(db, body.copy_from, test["id"])
    return _summary(db, test, attempts)


@router.get("/tests/{tid}")
def get_test(tid: str, _: str = Depends(current_staff), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    return _summary(db, test_or_404(db, tid), attempts)


@router.put("/tests/{tid}")
def update_test(tid: str, body: TestConfig, _: str = Depends(current_staff), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    test_or_404(db, tid)
    if body.published and not questions.count(db, tid):
        raise HTTPException(status_code=400, detail="Add at least one question before publishing.")
    # eval_fired_at is cleared so an edited schedule can fire again
    tests.update(db, tid, {**body.model_dump(), "eval_fired_at": None})
    return _summary(db, tests.get(db, tid), attempts)


@router.delete("/tests/{tid}")
def delete_test(tid: str, force: bool = False, _: str = Depends(current_staff), db=Depends(get_db), attempts: Collection = Depends(get_attempts)):
    test_or_404(db, tid)
    taken = attempts.count_documents({"test_id": tid, "started_at": {"$exists": True}})
    if taken and not force:
        raise HTTPException(status_code=409, detail=f"{taken} student(s) have started this test. Deleting removes their answers and scores; confirm to proceed.")
    tests.delete(db, tid)
    return {"message": "Deleted."}


# ---- questions (per test) ----

@router.get("/tests/{tid}/questions")
def list_questions(tid: str, _: str = Depends(current_staff), db=Depends(get_db)):
    test_or_404(db, tid)
    return list(questions.fetch_questions(db, tid).values())


@router.post("/tests/{tid}/questions", status_code=201)
def add_question(tid: str, body: QuestionIn, _: str = Depends(current_staff), db=Depends(get_db)):
    test_or_404(db, tid)
    return questions.add(db, tid, body.text, body.max_score)


@router.put("/tests/{tid}/questions/{qid}")
def update_question(tid: str, qid: int, body: QuestionIn, _: str = Depends(current_staff), db=Depends(get_db)):
    if not questions.update(db, tid, qid, body.text, body.max_score):
        raise HTTPException(status_code=404, detail="Question not found.")
    return {"id": qid, "text": body.text, "max_score": body.max_score}


@router.delete("/tests/{tid}/questions/{qid}")
def delete_question(tid: str, qid: int, _: str = Depends(current_staff), db=Depends(get_db)):
    if not questions.delete(db, tid, qid):
        raise HTTPException(status_code=404, detail="Question not found.")
    return {"message": "Deleted."}
