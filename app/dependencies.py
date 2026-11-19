"""FastAPI dependencies (override get_db in tests via app.dependency_overrides)."""
from fastapi import Depends, HTTPException, Request
from pymongo.collection import Collection
from pymongo.database import Database

from app import security
from app.config import get_settings

STUDENT_COOKIE = "student_session"
STAFF_COOKIE = "staff_session"


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_collection(db: Database = Depends(get_db)) -> Collection:
    """The participants collection."""
    return db[get_settings().mongo_collection]


def get_attempts(db: Database = Depends(get_db)) -> Collection:
    """One document per (test, student): start time, answers, scores, integrity flags."""
    return db["attempts"]


def _session(request: Request, cookie: str, role: str):
    token = request.cookies.get(cookie)
    payload = security.verify(token, get_settings().secret_key) if token else None
    if not payload or payload.get("role") != role:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return payload


def current_student(request: Request, collection: Collection = Depends(get_collection)) -> dict:
    payload = _session(request, STUDENT_COOKIE, "student")
    user = collection.find_one({"RegNo": payload.get("sub")})
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not payload.get("sid") or payload["sid"] != user.get("sid"):
        # A newer login (another device/tab) replaced this session.
        raise HTTPException(status_code=401, detail="You were signed out because this account signed in elsewhere.")
    return user


def current_staff(request: Request) -> str:
    return _session(request, STAFF_COOKIE, "staff")["sub"]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
