"""Fixed catalog questions for human-reviewed educational conversation planning."""

from .core import BANNER, OPTIONS, catalog, fingerprint, read_json, write_json


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


def checked_plan(plan):
    if (not isinstance(plan, dict) or not isinstance(plan.get("questions"), list)
            or any(not isinstance(question, dict) or set(question) != {"text", "sources"}
                   or not isinstance(question["sources"], list) for question in plan["questions"])):
        raise ValueError("Use a fixed catalog question plan.")
    selections = [origin for question in plan["questions"] for origin in question["sources"]]
    checked = select_questions(plan.get("stage"), selections)
    if plan != checked:
        raise ValueError("Only unchanged fixed catalog question plans can be rendered or exported.")
    return checked


def render_plan(plan):
    plan = checked_plan(plan)
    lines = ["SYNTHETIC EDUCATIONAL CONVERSATION LIST", BANNER, "",
             "Human review required. Discuss these fixed questions with a qualified professional.",
             "Not an individualized care plan.", f"Stage selection: {plan['stage']}",
             f"Catalog SHA-256: {plan['catalog_sha256']}", ""]
    for number, question in enumerate(plan["questions"], 1):
        lines.append(f"{number}. {question['text']}")
        lines.append("   Source: " + ", ".join(
            f"{origin['resource_id']} question {origin['question_number']}" for origin in question["sources"]))
    lines.extend(["", BANNER])
    return "\n".join(lines) + "\n"


def save_plan(path, plan):
    checked = checked_plan(plan)
    selections = [dict(origin) for question in checked["questions"] for origin in question["sources"]]
    capsule = {"version": 1, "notice": BANNER, "synthetic_catalog": True,
               "human_review_required": True, "catalog_sha256": checked["catalog_sha256"],
               "stage": checked["stage"], "selections": selections}
    capsule["selection_sha256"] = fingerprint(capsule)
    write_json(path, capsule)
    return capsule


def read_plan(path):
    capsule = read_json(path, 16_384)
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


def merge_plans(plans):
    if not isinstance(plans, list) or not 2 <= len(plans) <= 4:
        raise ValueError("Merge two to four synthetic fixed-question plans.")
    checked = [checked_plan(plan) for plan in plans]
    if len({plan["stage"] for plan in checked}) != 1:
        raise ValueError("Merged plans must use the same stage; review stage changes separately.")
    selections, seen = [], set()
    for plan in checked:
        for question in plan["questions"]:
            for origin in question["sources"]:
                signature = (origin["resource_id"], origin["question_number"])
                if signature not in seen:
                    selections.append(origin)
                    seen.add(signature)
    return select_questions(checked[0]["stage"], selections)


def compare_plans(before, after):
    before, after = checked_plan(before), checked_plan(after)
    old = [(origin["resource_id"], origin["question_number"])
           for question in before["questions"] for origin in question["sources"]]
    new = [(origin["resource_id"], origin["question_number"])
           for question in after["questions"] for origin in question["sources"]]
    def picks(signatures):
        return [{"resource_id": identifier, "question_number": number} for identifier, number in signatures]
    shared = set(old) & set(new)
    return {"notice": BANNER, "synthetic_catalog": True, "human_review_required": True,
            "catalog_sha256": before["catalog_sha256"],
            "before_stage": before["stage"], "after_stage": after["stage"],
            "stage_changed": before["stage"] != after["stage"],
            "added": picks(item for item in new if item not in set(old)),
            "removed": picks(item for item in old if item not in set(new)),
            "retained_order_changed": [item for item in old if item in shared] !=
                                      [item for item in new if item in shared],
            "meaning": "Fixed selector changes only, not a change in care needs or a clinical record."}
