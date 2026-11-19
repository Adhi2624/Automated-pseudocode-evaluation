"""Startup: indexes, first-run sample test, and one-time migration from the old single-contest layout."""
from pymongo import ASCENDING

from app.services import contest, questions, tests

# Fields that used to live on the participant document and now live on a per-test attempt.
ATTEMPT_FIELDS = ("started_at", "submitted_at", "extra_minutes", "pseudoCodeAnswers", "evaluation", "totalScore",
                  "evaluatedAt", "flags", "events", "last_seen", "previous_attempts")


def _migrate_legacy(db, users, tid: str) -> int:
    """Move answers/scores from participant documents into attempts of test `tid`."""
    moved = 0
    probe = {"$or": [{"pseudoCodeAnswers": {"$exists": True}}, {"started_at": {"$exists": True}}, {"evaluation": {"$exists": True}}]}
    for u in list(users.find(probe)):
        attempt = {k: u[k] for k in ATTEMPT_FIELDS if k in u and k != "last_seen"}
        if not attempt:
            continue
        db["attempts"].insert_one({"test_id": tid, "RegNo": u["RegNo"], **attempt})
        users.update_one({"_id": u["_id"]}, {"$unset": {k: "" for k in ATTEMPT_FIELDS}})
        moved += 1
    return moved


def run(db, users_collection: str) -> None:
    users = db[users_collection]
    users.create_index([("RegNo", ASCENDING)], unique=True)
    if not db[tests.COLLECTION].count_documents({}, limit=1):
        legacy_cfg = db["contest"].find_one({"_id": "config"})
        legacy_questions = list(db[questions.COLLECTION].find({"test_id": {"$exists": False}}))
        legacy_users = users.count_documents({"$or": [{"pseudoCodeAnswers": {"$exists": True}}, {"started_at": {"$exists": True}}]}, limit=1)
        data = {"title": "Sample pseudocode test"}
        if legacy_cfg:
            data = {k: legacy_cfg[k] for k in ("title", "duration_minutes", "opens_at", "closes_at", "published", "announcement") if k in legacy_cfg}
        elif legacy_questions or legacy_users:
            data = {"title": "Pseudocode contest"}
        test = tests.create(db, data)
        if legacy_questions:
            for q in sorted(legacy_questions, key=lambda d: d["_id"]):
                doc = {"_id": f"{test['id']}:{q['_id']}", "test_id": test["id"], "qid": q["_id"], "text": q["text"], "max_score": q.get("max_score", 10)}
                db[questions.COLLECTION].delete_one({"_id": q["_id"]})
                db[questions.COLLECTION].insert_one(doc)
        else:
            questions.seed_from_file(db, test["id"])
        _migrate_legacy(db, users, test["id"])
    db["attempts"].create_index([("test_id", ASCENDING), ("RegNo", ASCENDING)], unique=True)
    db[questions.COLLECTION].create_index([("test_id", ASCENDING), ("qid", ASCENDING)], unique=True)
