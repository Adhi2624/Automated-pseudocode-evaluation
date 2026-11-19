"""Question bank: seed-file parsing and per-test question storage in MongoDB."""
import json
from pathlib import Path

from app.config import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "data" / "questions.json"
COLLECTION = "questions"


def load_questions(path=None) -> dict:
    """Parse a questions file into {id: {"id", "text", "max_score"}}; raises ValueError if invalid."""
    path = Path(path) if path else DEFAULT_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("questions file must contain a list")
    result = {}
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each question must be an object")
        qid = item.get("id")
        if isinstance(qid, bool) or not isinstance(qid, int):
            raise ValueError(f"question id must be an int: {qid!r}")
        if qid in result:
            raise ValueError(f"duplicate question id: {qid}")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"question {qid} has empty text")
        result[qid] = {"id": qid, "text": text, "max_score": item.get("max_score", 10)}
    return result


def _public(d: dict) -> dict:
    return {"id": d["qid"], "text": d["text"], "max_score": d.get("max_score", 10)}


def fetch_questions(db, tid: str) -> dict:
    """{qid: {"id", "text", "max_score"}} for one test, in order."""
    return {d["qid"]: _public(d) for d in db[COLLECTION].find({"test_id": tid}).sort("qid", 1)}


def count(db, tid: str) -> int:
    return db[COLLECTION].count_documents({"test_id": tid})


def add(db, tid: str, text: str, max_score: int = 10) -> dict:
    last = db[COLLECTION].find_one({"test_id": tid}, sort=[("qid", -1)])
    qid = (last["qid"] + 1) if last else 0
    doc = {"_id": f"{tid}:{qid}", "test_id": tid, "qid": qid, "text": text, "max_score": max_score}
    db[COLLECTION].insert_one(doc)
    return _public(doc)


def update(db, tid: str, qid: int, text: str, max_score: int) -> bool:
    res = db[COLLECTION].update_one({"test_id": tid, "qid": qid}, {"$set": {"text": text, "max_score": max_score}})
    return res.matched_count > 0


def delete(db, tid: str, qid: int) -> bool:
    return db[COLLECTION].delete_one({"test_id": tid, "qid": qid}).deleted_count > 0


def copy_all(db, src_tid: str, dst_tid: str) -> int:
    n = 0
    for q in fetch_questions(db, src_tid).values():
        add(db, dst_tid, q["text"], q["max_score"])
        n += 1
    return n


def seed_from_file(db, tid: str, path=None) -> int:
    n = 0
    for q in load_questions(path).values():
        add(db, tid, q["text"], q["max_score"])
        n += 1
    return n
