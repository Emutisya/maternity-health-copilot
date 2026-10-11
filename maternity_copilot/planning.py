"""Fixed catalog questions for human-reviewed educational conversation planning."""

from .core import BANNER, OPTIONS, catalog, fingerprint


def make_plan(stage, identifiers):
    if stage not in OPTIONS["stage"]:
        raise ValueError("Choose a supported educational stage.")
    if (not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 6
            or any(not isinstance(identifier, str) for identifier in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        raise ValueError("Choose one to six unique catalog resource IDs.")
    rows = catalog()
    source = {row["id"]: row for row in rows}
    if any(identifier not in source or stage not in source[identifier]["stages"]
           for identifier in identifiers):
        raise ValueError("Only catalog resources compatible with the selected stage can be planned.")
    questions = {}
    for identifier in identifiers:
        for index, text in enumerate(source[identifier]["questions"], 1):
            questions.setdefault(text, []).append({"resource_id": identifier, "question_number": index})
    return {"notice": BANNER, "synthetic_catalog": True, "human_review_required": True,
            "catalog_sha256": fingerprint(rows), "stage": stage,
            "resource_ids": list(identifiers),
            "questions": [{"text": text, "sources": origins} for text, origins in questions.items()],
            "scope": "Fixed discussion questions for a qualified professional; not an individualized care plan."}
