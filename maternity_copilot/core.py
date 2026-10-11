"""Standard-library TF-IDF fitting, bounded retrieval and offline evaluation."""

import hashlib
import json
import math
import re
import os
import tempfile
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


class ModelError(ValueError):
    pass


def decode_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate fields in local JSON. Restore the authored file.")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite numbers in local JSON are not accepted.")

    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)


def catalog():
    rows = decode_json((DATA / "catalog.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Educational catalog must contain at least one resource.")
    ids = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) !=
                {"id", "title", "summary", "topic", "format", "focus", "stages", "questions"}):
            raise ValueError("Each educational resource must use only the documented catalog fields.")
        for field in ("id", "title", "summary"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Educational resource {field} must be nonempty text.")
        if row["id"] in ids:
            raise ValueError("Educational resource IDs must be unique.")
        ids.add(row["id"])
        if not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", row["id"]):
            raise ValueError("Educational resource IDs must be lowercase hyphenated words.")
        for field in ("topic", "format", "focus"):
            if row.get(field) not in OPTIONS[field]:
                raise ValueError(f"Educational resource {field} must use a supported selection.")
        stages = row.get("stages")
        if (not isinstance(stages, list) or not stages
                or any(stage not in OPTIONS["stage"] for stage in stages)
                or len(stages) != len(set(stages))):
            raise ValueError("Educational resource stages must be unique supported selections.")
        questions = row.get("questions")
        if (not isinstance(questions, list) or not questions
                or any(not isinstance(question, str) or not question.strip() for question in questions)
                or len(questions) != len(set(questions))):
            raise ValueError("Educational resources require unique nonempty discussion questions.")
    return rows


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


def fitted_model(rows):
    texts = [document(row) for row in rows]
    frequency = Counter(term for text in texts for term in set(tokens(text)))
    idf = {term: math.log((1 + len(rows)) / (1 + count)) + 1
           for term, count in sorted(frequency.items())}
    return {"version": 1, "catalog_sha256": fingerprint(rows), "idf": idf,
             "vectors": {row["id"]: vector(text, idf)
                         for row, text in zip(rows, texts)}}


def train(destination):
    model = fitted_model(catalog())
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(json.dumps(model, indent=2))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return model


def load_model(path):
    try:
        model = decode_json(Path(path).read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as error:
        raise ValueError("Model JSON is invalid. Run train again.") from error
    if (not isinstance(model, dict) or type(model.get("version")) is not int
            or not isinstance(model.get("idf"), dict)
            or any(type(value) not in (int, float) for value in model["idf"].values())
            or not isinstance(model.get("vectors"), dict)
            or any(not isinstance(weights, dict)
                   or any(type(value) not in (int, float) for value in weights.values())
                   for weights in model["vectors"].values())
            or model != fitted_model(catalog())):
        raise ValueError("Model does not match this catalog and implementation. Run train again.")
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


def model_catalog(model):
    try:
        rows = catalog()
    except (OSError, ValueError, RecursionError) as error:
        raise ModelError("The educational catalog is unavailable or invalid. Restore the catalog, train and restart the server.") from error
    if not isinstance(model, dict) or model.get("catalog_sha256") != fingerprint(rows):
        raise ModelError("The educational catalog changed after training. Run train again and restart the server.")
    return rows


def rank_resources(model, request):
    validate(request)
    rows = model_catalog(model)
    return _rank_rows(model, request, rows)


def _rank_rows(model, request, rows):
    query = vector(" ".join(request[key] for key in OPTIONS), model["idf"])
    results = []
    for row in rows:
        if request["stage"] not in row["stages"]:
            continue
        score = sum(value * model["vectors"][row["id"]].get(term, 0)
                    for term, value in query.items())
        results.append((score, row))
    results.sort(key=lambda item: (-item[0], item[1]["id"]))
    return results


def retrieve(model, request):
    limit = validate(request)
    results = rank_resources(model, request)
    return {"notice": BANNER, "prototype": True, "synthetic_catalog": True,
            "score_meaning": "Cosine text similarity, not risk, confidence or probability.",
            "resources": [{**row, "retrieval_score": round(score, 6)}
                          for score, row in results[:limit]]}


def load_benchmark(rows=None):
    benchmark = decode_json((DATA / "benchmark.json").read_text(encoding="utf-8"))
    if not isinstance(benchmark, dict) or set(benchmark) != {"development", "held_out"}:
        raise ValueError("Benchmark must contain development and held_out splits.")
    seen = set()
    rows = catalog() if rows is None else rows
    for cases in benchmark.values():
        if not isinstance(cases, list) or not cases:
            raise ValueError("Each benchmark split must contain at least one query.")
        for case in cases:
            if not isinstance(case, dict) or set(case) != set(OPTIONS) | {"relevant"}:
                raise ValueError("Benchmark queries require only bounded selections and relevance IDs.")
            request = {key: case[key] for key in OPTIONS}
            validate(request)
            signature = tuple(request.values())
            if signature in seen:
                raise ValueError("Duplicate benchmark query across splits.")
            seen.add(signature)
            eligible = {row["id"] for row in rows if case["stage"] in row["stages"]}
            relevant = case.get("relevant")
            if (not isinstance(relevant, list) or not relevant
                    or any(not isinstance(identifier, str) for identifier in relevant)
                    or len(set(relevant)) != len(relevant) or not set(relevant) <= eligible):
                raise ValueError("Invalid benchmark relevance labels.")
    return benchmark


def evaluate(model, split="held_out", k=3):
    if split not in ("development", "held_out") or type(k) is not int or not 1 <= k <= 6:
        raise ValueError("Use development or held_out, and k from 1 to 6.")
    rows = model_catalog(model)
    benchmark = load_benchmark(rows)
    recalls, ndcgs, reciprocal_ranks, precisions, average_precisions, cases = [], [], [], [], [], []
    for case in benchmark[split]:
        request = {key: case[key] for key in OPTIONS}
        ids = [row["id"] for _, row in _rank_rows(model, request, rows)[:k]]
        gold = set(case["relevant"])
        hits = [int(identifier in gold) for identifier in ids]
        precisions.append(sum(hits) / k)
        average_precisions.append(sum(
            hit * sum(hits[:i + 1]) / (i + 1) for i, hit in enumerate(hits)
        ) / min(k, len(gold)))
        recalls.append(sum(hits) / len(gold))
        dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
        ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
        ndcgs.append(dcg / ideal)
        reciprocal_ranks.append(next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0))
        cases.append({"request": request, "relevant": sorted(gold), "ranked": ids,
                      "recall_at_k": recalls[-1], "ndcg_at_k": ndcgs[-1],
                      "precision_at_k": precisions[-1],
                      "average_precision_at_k": average_precisions[-1],
                      "reciprocal_rank_at_k": reciprocal_ranks[-1]})
    return {"split": split, "queries": len(recalls), "k": k,
            "catalog_sha256": fingerprint(rows),
            "benchmark_sha256": fingerprint(benchmark),
            "recall_at_k": sum(recalls) / len(recalls),
            "ndcg_at_k": sum(ndcgs) / len(ndcgs),
            "mrr_at_k": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "precision_at_k": sum(precisions) / len(precisions),
            "map_at_k": sum(average_precisions) / len(average_precisions),
            "cases": cases,
            "limits": "Tiny authored synthetic relevance benchmark; no clinical validation or population evidence."}
