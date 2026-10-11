"""Fixed catalog questions for human-reviewed educational conversation planning."""

from pathlib import Path

from .core import BANNER, OPTIONS, catalog, decode_json, fingerprint, write_json


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


def save_plan(path, plan):
    selections = [dict(origin) for question in plan["questions"] for origin in question["sources"]]
    checked = select_questions(plan["stage"], selections)
    if plan != checked:
        raise ValueError("Only unchanged fixed catalog question plans can be exported.")
    capsule = {"version": 1, "notice": BANNER, "synthetic_catalog": True,
               "human_review_required": True, "catalog_sha256": checked["catalog_sha256"],
               "stage": checked["stage"], "selections": selections}
    capsule["selection_sha256"] = fingerprint(capsule)
    write_json(path, capsule)
    return capsule


def read_plan(path):
    raw = Path(path).read_bytes()
    if len(raw) > 16_384:
        raise ValueError("Selection files must be at most 16 KB.")
    capsule = decode_json(raw.decode("utf-8"))
    keys = {"version", "notice", "synthetic_catalog", "human_review_required",
            "catalog_sha256", "stage", "selections", "selection_sha256"}
    if (not isinstance(capsule, dict) or set(capsule) != keys
            or type(capsule["version"]) is not int or capsule["version"] != 1
            or capsule["notice"] != BANNER or capsule["synthetic_catalog"] is not True
            or capsule["human_review_required"] is not True):
        raise ValueError("Use a synthetic-only fixed-question selection file.")
    unsigned = {key: value for key, value in capsule.items() if key != "selection_sha256"}
    if fingerprint(unsigned) != capsule["selection_sha256"]:
        raise ValueError("Question selection integrity check failed.")
    plan = select_questions(capsule["stage"], capsule["selections"])
    if plan["catalog_sha256"] != capsule["catalog_sha256"]:
        raise ValueError("The catalog changed. Review current questions and create a new selection file.")
    return plan
