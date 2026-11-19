import json
from pathlib import Path

import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo import ASCENDING
from pymongo.errors import PyMongoError

import main

ROOT = Path(__file__).resolve().parent.parent

VALID = {
    "Name": "Alice", "email": "a@example.com", "MobNo": "9876543210",
    "RegNo": 1001, "year": 2, "Branch": "CSE", "Sec": "A",
}


@pytest.fixture
def coll():
    c = mongomock.MongoClient()["testdb"]["users"]
    c.create_index([("RegNo", ASCENDING)], unique=True)
    return c


@pytest.fixture
def client(coll):
    main.app.dependency_overrides[main.get_collection] = lambda: coll
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()


def test_submit_ok(client, coll):
    r = client.post("/submit", json=VALID)
    assert r.status_code == 200
    assert "id" in r.json()
    assert coll.count_documents({"RegNo": 1001}) == 1


def test_submit_duplicate_regno_400(client):
    assert client.post("/submit", json=VALID).status_code == 200
    r = client.post("/submit", json={**VALID, "email": "b@example.com"})
    assert r.status_code == 400


def test_submit_invalid_payload_422(client):
    assert client.post("/submit", json={**VALID, "MobNo": "12"}).status_code == 422


def test_get_unknown_user_404(client):
    assert client.get("/get-user-details/999").status_code == 404


def test_put_unknown_user_404(client):
    r = client.put("/submit-answers/999", json={"pseudoCodeAnswers": {"0": "x"}})
    assert r.status_code == 404


def test_put_valid_and_get(client):
    client.post("/submit", json=VALID)
    r = client.put("/submit-answers/1001", json={"pseudoCodeAnswers": {"0": "a", "1": "b"}})
    assert r.status_code == 200
    g = client.get("/get-user-details/1001").json()
    assert g["pseudoCodeAnswers"] == {"0": "a", "1": "b"}
    assert g["RegNo"] == 1001 and "id" in g


def test_put_unknown_question_id_422(client):
    client.post("/submit", json=VALID)
    for bad in ("9999", "abc", "-1"):
        r = client.put("/submit-answers/1001", json={"pseudoCodeAnswers": {bad: "x"}})
        assert r.status_code == 422, bad


def test_put_overlength_422(client):
    client.post("/submit", json=VALID)
    big = "x" * (main.settings.max_answer_chars + 1)
    r = client.put("/submit-answers/1001", json={"pseudoCodeAnswers": {"0": big}})
    assert r.status_code == 422
    ok = "x" * main.settings.max_answer_chars
    r = client.put("/submit-answers/1001", json={"pseudoCodeAnswers": {"0": ok}})
    assert r.status_code == 200


def test_put_non_string_answer_422(client):
    client.post("/submit", json=VALID)
    r = client.put("/submit-answers/1001", json={"pseudoCodeAnswers": {"0": 5}})
    assert r.status_code == 422


def test_legacy_nested_answers_flattened(client, coll):
    coll.insert_one({**VALID, "pseudoCodeAnswers": {"pseudoCodeAnswers": {"0": "a", "1": "b"}}})
    r = client.get("/get-user-details/1001")
    assert r.status_code == 200
    assert r.json()["pseudoCodeAnswers"] == {"0": "a", "1": "b"}


class _Boom:
    def __getattr__(self, name):
        def f(*a, **k):
            raise PyMongoError("mongodb://secret-host:27017 internal failure")
        return f


@pytest.mark.parametrize("method,url,body", [
    ("get", "/get-user-details/1", None),
    ("post", "/submit", VALID),
    ("put", "/submit-answers/1", {"pseudoCodeAnswers": {"0": "x"}}),
])
def test_db_outage_503_no_leak(method, url, body):
    main.app.dependency_overrides[main.get_collection] = lambda: _Boom()
    try:
        c = TestClient(main.app, raise_server_exceptions=False)
        r = getattr(c, method)(url, **({"json": body} if body else {}))
    finally:
        main.app.dependency_overrides.clear()
    assert r.status_code == 503
    assert "secret-host" not in r.text and "PyMongo" not in r.text
    assert "Traceback" not in r.text


def test_questions_match_file(client):
    expected = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    r = client.get("/api/questions")
    assert r.status_code == 200
    assert r.json() == [{"id": q["id"], "text": q["text"]} for q in expected]
    assert "max_score" not in r.json()[0]


def test_cors_no_header_for_random_origin(client):
    r = client.get("/api/questions", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    r = client.options(
        "/submit",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in r.headers
