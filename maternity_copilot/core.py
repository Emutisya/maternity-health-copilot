"""Standard-library TF-IDF fitting, bounded retrieval and offline evaluation."""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent / "data"
BANNER = ("Not medical advice. For symptoms or concerns, contact a qualified "
          "healthcare professional. If you think there is an emergency, contact "
          "local emergency services.")
OPTIONS = {
    "stage": ["pregnancy", "postpartum"],
    "topic": ["appointments", "support", "wellbeing", "feeding", "access", "care_team"],
    "format": ["guide", "checklist"],
    "focus": ["planning", "support"],
}


def catalog():
    return json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def tokens(text):
    return re.findall(r"[a-z_]+", text.lower())


def document(row):
    return " ".join([row["title"], row["summary"], row["topic"],
                     row["format"], row["focus"], *row["stages"]])


def vector(text, idf):
    counts = Counter(tokens(text))
    values = {term: (1 + math.log(count)) * idf[term]
              for term, count in counts.items() if term in idf}
    norm = math.sqrt(sum(value * value for value in values.values()))
    return {term: value / norm for term, value in values.items()} if norm else {}


def train(destination):
    rows = catalog()
    texts = [document(row) for row in rows]
    frequency = Counter(term for text in texts for term in set(tokens(text)))
    idf = {term: math.log((1 + len(rows)) / (1 + count)) + 1
           for term, count in sorted(frequency.items())}
    model = {"version": 1, "catalog_sha256": fingerprint(rows), "idf": idf,
             "vectors": {row["id"]: vector(text, idf)
                         for row, text in zip(rows, texts)}}
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    return model


def load_model(path):
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    if model.get("version") != 1 or model.get("catalog_sha256") != fingerprint(catalog()):
        raise ValueError("Model is incompatible with this catalog. Run train again.")
    if set(model.get("vectors", {})) != {row["id"] for row in catalog()}:
        raise ValueError("Model is incomplete. Run train again.")
    return model


def validate(request):
    if not isinstance(request, dict):
        raise ValueError("Use a JSON object of bounded selections only. " + BANNER)
    if set(request) - (set(OPTIONS) | {"limit"}):
        raise ValueError("Unsupported fields. Symptoms, personal data and free text are not accepted. " + BANNER)
    for key, allowed in OPTIONS.items():
        if not isinstance(request.get(key), str) or request[key] not in allowed:
            raise ValueError(f"{key} must be one of: {', '.join(allowed)}. " + BANNER)
    limit = request.get("limit", 3)
    if type(limit) is not int or not 1 <= limit <= 6:
        raise ValueError("limit must be an integer from 1 to 6. " + BANNER)
    return limit


def retrieve(model, request):
    limit = validate(request)
    query = vector(" ".join(request[key] for key in OPTIONS), model["idf"])
    results = []
    for row in catalog():
        if request["stage"] not in row["stages"]:
            continue
        score = sum(value * model["vectors"][row["id"]].get(term, 0)
                    for term, value in query.items())
        results.append({**row, "retrieval_score": round(score, 6)})
    results.sort(key=lambda row: (-row["retrieval_score"], row["id"]))
    return {"notice": BANNER, "prototype": True, "synthetic_catalog": True,
            "score_meaning": "Cosine text similarity, not risk, confidence or probability.",
            "resources": results[:limit]}


def evaluate(model, split="held_out", k=3):
    if split not in ("development", "held_out") or type(k) is not int or not 1 <= k <= 6:
        raise ValueError("Use development or held_out, and k from 1 to 6.")
    benchmark = json.loads((DATA / "benchmark.json").read_text(encoding="utf-8"))
    seen = set()
    rows = catalog()
    for cases in benchmark.values():
        for case in cases:
            request = {key: case[key] for key in OPTIONS}
            validate(request)
            signature = tuple(request.values())
            if signature in seen:
                raise ValueError("Duplicate benchmark query across splits.")
            seen.add(signature)
            eligible = {row["id"] for row in rows if case["stage"] in row["stages"]}
            if not case["relevant"] or not set(case["relevant"]) <= eligible:
                raise ValueError("Invalid benchmark relevance labels.")
    recalls, ndcgs, reciprocal_ranks = [], [], []
    for case in benchmark[split]:
        request = {key: case[key] for key in OPTIONS}
        ids = [row["id"] for row in retrieve(model, {**request, "limit": k})["resources"]]
        gold = set(case["relevant"])
        hits = [int(identifier in gold) for identifier in ids]
        recalls.append(sum(hits) / len(gold))
        dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
        ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
        ndcgs.append(dcg / ideal)
        reciprocal_ranks.append(next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0))
    return {"split": split, "queries": len(recalls), "k": k,
            "recall_at_k": sum(recalls) / len(recalls),
            "ndcg_at_k": sum(ndcgs) / len(ndcgs),
            "mrr_at_k": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "limits": "Tiny authored synthetic relevance benchmark; no clinical validation or population evidence."}
