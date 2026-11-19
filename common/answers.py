"""Answer shape helpers."""


def flatten_answers(raw) -> dict:
    """Return a flat {question_id_str: answer_str} dict.

    Tolerates the legacy shape {"pseudoCodeAnswers": {...}} nested inside the
    stored answers (possibly repeatedly).
    """
    if not isinstance(raw, dict):
        return {}
    while isinstance(raw.get("pseudoCodeAnswers"), dict):
        raw = raw["pseudoCodeAnswers"]
    return {str(k): "" if v is None else str(v) for k, v in raw.items()}
