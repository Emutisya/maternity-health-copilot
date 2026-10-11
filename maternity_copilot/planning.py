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


def select_questions(stage, selections):
    if (not isinstance(selections, list) or not 1 <= len(selections) <= 12
            or any(not isinstance(item, dict) or set(item) != {"resource_id", "question_number"}
                   or not isinstance(item["resource_id"], str)
                   or type(item["question_number"]) is not int or item["question_number"] < 1
                   for item in selections)):
        raise ValueError("Choose one to twelve fixed resource/question-number selections.")
    signatures = [(item["resource_id"], item["question_number"]) for item in selections]
    if len(set(signatures)) != len(signatures):
        raise ValueError("Question selections must be unique.")
    identifiers = list(dict.fromkeys(item["resource_id"] for item in selections))
    plan = make_plan(stage, identifiers)
    lookup = {(origin["resource_id"], origin["question_number"]): question["text"]
              for question in plan["questions"] for origin in question["sources"]}
    if any(signature not in lookup for signature in signatures):
        raise ValueError("Question numbers must refer to existing fixed catalog questions.")
    questions = {}
    for item, signature in zip(selections, signatures):
        questions.setdefault(lookup[signature], []).append(dict(item))
    plan["questions"] = [{"text": text, "sources": origins} for text, origins in questions.items()]
    return plan
