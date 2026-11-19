"""Staff operations for one test: live monitor, interventions, announcements, submissions, grading, results."""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pymongo.collection import Collection

from app.dependencies import current_staff, get_attempts, get_collection, get_db
from app.routers.staff import test_or_404
from app.services import contest, jobs, questions, tests
from app.services.answers import flatten_answers

router = APIRouter(prefix="/api/staff/tests/{tid}")

ONLINE_SECONDS = 30


def _join(users: Collection, attempts: Collection, tid: str):
    """Yield (student, attempt-or-None) for the whole roster; the attempt belongs to test `tid`."""
    by_reg = {a["RegNo"]: a for a in attempts.find({"test_id": tid}, {"events": 0})}
    for u in users.find({}, {"dob": 0, "sid": 0}).sort("RegNo", 1):
        yield u, by_reg.get(u["RegNo"])


def _answers(attempt) -> dict:
    return flatten_answers(attempt.get("pseudoCodeAnswers")) if attempt else {}


@router.get("/monitor")
def monitor(tid: str, _: str = Depends(current_staff), db=Depends(get_db),
            users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    test, at = test_or_404(db, tid), contest.now()
    rows = []
    counts = {"registered": 0, "not_started": 0, "in_progress": 0, "online": 0, "submitted": 0, "timed_out": 0, "flagged": 0}
    for u, a in _join(users, attempts, tid):
        state = contest.attempt_state(a, test, at)
        seen = a.get("last_seen") if a else None
        ago = (at - seen).total_seconds() if seen else None
        online = state == "in_progress" and ago is not None and ago <= ONLINE_SECONDS
        remaining = None
        if state == "in_progress":
            remaining = (contest.deadline(test, a["started_at"], a.get("extra_minutes", 0)) - at).total_seconds()
        flags = (a.get("flags") if a else None) or {}
        rows.append({
            "RegNo": u["RegNo"], "Name": u.get("Name"), "state": state, "online": online,
            "seen_seconds_ago": None if ago is None else int(ago),
            "remaining_seconds": None if remaining is None else int(remaining),
            "answered": sum(1 for x in _answers(a).values() if x.strip()),
            "blur": flags.get("blur", 0), "paste": flags.get("paste", 0), "copy": flags.get("copy", 0),
            "extra_minutes": (a.get("extra_minutes", 0) if a else 0),
        })
        counts["registered"] += 1
        counts[state] += 1
        counts["online"] += online
        counts["flagged"] += bool(flags.get("blur", 0) >= 3 or flags.get("paste", 0))
    ann = test.get("announcement")
    return {
        "server_time": contest.iso(at), "contest": contest.public(test), "total_questions": questions.count(db, tid),
        "counts": counts, "students": rows, "announcement": ann["text"] if ann else None,
    }


def _student_attempt(tid: str, reg_no: int, users: Collection, attempts: Collection):
    if not users.find_one({"RegNo": reg_no}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Student not found.")
    return attempts.find_one({"test_id": tid, "RegNo": reg_no})


class ExtendIn(BaseModel):
    minutes: int = Field(ge=1, le=240)


@router.post("/students/{reg_no}/extend")
def extend(tid: str, reg_no: int, body: ExtendIn, _: str = Depends(current_staff), db=Depends(get_db),
           users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    """Grant extra minutes to one student (e.g. after a power or network failure). Works past the closing time."""
    test_or_404(db, tid)
    a = _student_attempt(tid, reg_no, users, attempts)
    if not a or not a.get("started_at"):
        raise HTTPException(status_code=409, detail="This student has not started yet.")
    if a.get("submitted_at"):
        raise HTTPException(status_code=409, detail="This student already submitted. Reset the attempt to let them retake.")
    attempts.update_one({"_id": a["_id"]}, {"$inc": {"extra_minutes": body.minutes}})
    return {"extra_minutes": a.get("extra_minutes", 0) + body.minutes}


@router.post("/students/{reg_no}/force-submit")
def force_submit(tid: str, reg_no: int, _: str = Depends(current_staff), db=Depends(get_db),
                 users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    test_or_404(db, tid)
    a = _student_attempt(tid, reg_no, users, attempts)
    if not a or not a.get("started_at"):
        raise HTTPException(status_code=409, detail="This student has not started yet.")
    attempts.update_one({"_id": a["_id"], "submitted_at": {"$exists": False}}, {"$set": {"submitted_at": contest.now()}})
    return {"message": "Submitted."}


@router.post("/students/{reg_no}/reset")
def reset_attempt(tid: str, reg_no: int, _: str = Depends(current_staff), db=Depends(get_db),
                  users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    """Give the student a fresh attempt at this test. The old answers are archived, not deleted."""
    test_or_404(db, tid)
    a = _student_attempt(tid, reg_no, users, attempts)
    if not a:
        raise HTTPException(status_code=409, detail="This student has no attempt to reset.")
    archive = {
        "archived_at": contest.now(), "started_at": a.get("started_at"), "submitted_at": a.get("submitted_at"),
        "answers": _answers(a), "evaluation": a.get("evaluation"), "totalScore": a.get("totalScore"),
    }
    attempts.update_one(
        {"_id": a["_id"]},
        {"$push": {"previous_attempts": archive},
         "$unset": {"started_at": "", "submitted_at": "", "extra_minutes": "", "pseudoCodeAnswers": "", "evaluation": "",
                    "totalScore": "", "evaluatedAt": "", "flags": "", "events": ""}},
    )
    return {"message": "Attempt reset."}


class AnnouncementIn(BaseModel):
    text: Optional[str] = Field(default=None, max_length=300)


@router.put("/announcement")
def announce(tid: str, body: AnnouncementIn, _: str = Depends(current_staff), db=Depends(get_db)):
    """Broadcast a message to everyone taking this test. Empty text clears it."""
    test_or_404(db, tid)
    text = (body.text or "").strip()
    tests.set_announcement(db, tid, {"text": text, "id": contest.iso(contest.now())} if text else None)
    return {"announcement": text or None}


@router.get("/students/{reg_no}/events")
def student_events(tid: str, reg_no: int, _: str = Depends(current_staff), db=Depends(get_db),
                   users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    test_or_404(db, tid)
    a = _student_attempt(tid, reg_no, users, attempts) or {}
    return {"flags": a.get("flags") or {}, "events": [{**e, "t": contest.iso(e["t"])} for e in a.get("events", [])][-100:]}


# ---- submissions ----

def _row(u: dict, a, test: dict) -> dict:
    return {
        "RegNo": u["RegNo"], "Name": u.get("Name"), "Branch": u.get("Branch"), "year": u.get("year"), "Sec": u.get("Sec"),
        "answered": sum(1 for x in _answers(a).values() if x.strip()),
        "started_at": contest.iso(a.get("started_at")) if a else None,
        "submitted_at": contest.iso(a.get("submitted_at")) if a else None,
        "totalScore": a.get("totalScore") if a else None,
    }


@router.get("/submissions")
def submissions(tid: str, _: str = Depends(current_staff), db=Depends(get_db),
                users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    test = test_or_404(db, tid)
    return [_row(u, a, test) for u, a in _join(users, attempts, tid)]


@router.get("/submissions/{reg_no}")
def submission_detail(tid: str, reg_no: int, _: str = Depends(current_staff), db=Depends(get_db),
                      users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    test = test_or_404(db, tid)
    u = users.find_one({"RegNo": reg_no}, {"dob": 0, "sid": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Student not found.")
    a = attempts.find_one({"test_id": tid, "RegNo": reg_no})
    evaluation = a.get("evaluation") if a and isinstance(a.get("evaluation"), dict) else {}
    return {
        **_row(u, a, test), "email": u.get("email"), "MobNo": u.get("MobNo"),
        "answers": _answers(a), "evaluation": evaluation, "questions": list(questions.fetch_questions(db, tid).values()),
    }


# ---- grading (jobs are queued here and executed by the worker process) ----

@router.get("/grade")
def grade_status(tid: str, _: str = Depends(current_staff), db=Depends(get_db)):
    test = test_or_404(db, tid)
    rows = [jobs.view(j) for j in jobs.list_for_test(db, tid)]
    return {
        "worker": jobs.worker_status(db),
        "evaluation": {"mode": test["eval_mode"], "at": contest.iso(test["eval_at"]), "delay_minutes": test["eval_delay_minutes"],
                       "scheduled_for": contest.iso(tests.eval_start_time(test)), "fired": bool(test.get("eval_fired_at"))},
        "active": any(r["status"] in ("pending", "running") for r in rows),
        "jobs": rows,
    }


@router.post("/grade", status_code=202)
def grade(tid: str, force: bool = False, _: str = Depends(current_staff), db=Depends(get_db)):
    """Queue a grading job now. The worker picks it up within a few seconds."""
    test_or_404(db, tid)
    job_id, created = jobs.enqueue(db, tid, trigger="manual", force=force)
    return {"id": job_id, "queued": created, "worker": jobs.worker_status(db)}


@router.post("/grade/{job_id}/cancel")
def grade_cancel(tid: str, job_id: str, _: str = Depends(current_staff), db=Depends(get_db)):
    test_or_404(db, tid)
    if not jobs.cancel(db, job_id, tid):
        raise HTTPException(status_code=409, detail="Only a job that is still waiting can be cancelled.")
    return {"message": "Cancelled."}


# ---- results ----

def _results(db, users: Collection, attempts: Collection, tid: str, cutoff: Optional[float]):
    test, qs, at = test_or_404(db, tid), questions.fetch_questions(db, tid), contest.now()
    rows = []
    for u, a in _join(users, attempts, tid):
        evaluation = a.get("evaluation") if a and isinstance(a.get("evaluation"), dict) else {}
        total = a.get("totalScore") if a else None
        flags = (a.get("flags") if a else None) or {}
        rows.append({
            "RegNo": u["RegNo"], "Name": u.get("Name"), "Branch": u.get("Branch"), "year": u.get("year"), "Sec": u.get("Sec"),
            "email": u.get("email"), "MobNo": u.get("MobNo"), "state": contest.attempt_state(a, test, at),
            "answered": sum(1 for x in _answers(a).values() if x.strip()),
            "scores": {qid: (evaluation.get(str(qid)) or {}).get("score") for qid in qs},
            "totalScore": total, "blur": flags.get("blur", 0), "paste": flags.get("paste", 0),
            "shortlisted": cutoff is not None and total is not None and total >= cutoff,
        })
    rows.sort(key=lambda r: (r["totalScore"] is None, -(r["totalScore"] or 0), r["RegNo"]))
    return test, qs, rows


@router.get("/results")
def results(tid: str, cutoff: Optional[float] = Query(default=None, ge=0), _: str = Depends(current_staff), db=Depends(get_db),
            users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    _t, qs, rows = _results(db, users, attempts, tid, cutoff)
    return {
        "max_total": sum(q["max_score"] for q in qs.values()),
        "graded": sum(1 for r in rows if r["totalScore"] is not None),
        "shortlisted": sum(1 for r in rows if r["shortlisted"]),
        "rows": rows,
    }


def _cell(value):
    """Neutralise spreadsheet formula injection in exported text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


@router.get("/results.csv")
def results_csv(tid: str, cutoff: Optional[float] = Query(default=None, ge=0), _: str = Depends(current_staff), db=Depends(get_db),
                users: Collection = Depends(get_collection), attempts: Collection = Depends(get_attempts)):
    test, qs, rows = _results(db, users, attempts, tid, cutoff)
    out = io.StringIO()
    w = csv.writer(out)
    head = ["Rank", "RegNo", "Name", "Branch", "Year", "Section", "Email", "Mobile", "Status", "Answered"]
    head += [f"Q{i + 1} (/{q['max_score']})" for i, q in enumerate(qs.values())]
    head += ["Total", "Tab switches", "Pastes"] + (["Shortlisted"] if cutoff is not None else [])
    w.writerow(head)
    for rank, r in enumerate(rows, start=1):
        line = [rank if r["totalScore"] is not None else "", r["RegNo"], r["Name"], r["Branch"], r["year"], r["Sec"], r["email"], r["MobNo"], r["state"], r["answered"]]
        line += [r["scores"][qid] for qid in qs]
        line += [r["totalScore"], r["blur"], r["paste"]] + (["YES" if r["shortlisted"] else "no"] if cutoff is not None else [])
        w.writerow([_cell(c) for c in line])
    safe = "".join(c if c.isalnum() else "-" for c in test["title"]).strip("-")[:40] or "results"
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}-results.csv"'})
