"""Question bank loader."""
import json
from pathlib import Path

from .config import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "questions.json"


def load_questions(path=None) -> dict:
    """Return {id: {"id", "text", "max_score"}}; raises ValueError if invalid."""
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
