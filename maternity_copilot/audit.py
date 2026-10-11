"""Deterministic local inspection of authored synthetic educational content."""

import hashlib
import math
import re
from pathlib import Path

from .core import BANNER, OPTIONS, catalog, decode_json, evaluate, fingerprint, fitted_model, load_model, rank_resources, validate, vector


def browse(filters=None, offset=0, limit=6):
    filters = {} if filters is None else filters
    if (not isinstance(filters, dict) or set(filters) - set(OPTIONS)
            or any(value not in OPTIONS[key] for key, value in filters.items())
            or type(offset) is not int or offset < 0
            or type(limit) is not int or not 1 <= limit <= 12):
        raise ValueError("Browse uses bounded filters, a nonnegative offset and limit 1–12.")
    rows = catalog()
    selected = sorted(
        (row for row in rows if all(
            value in row["stages"] if key == "stage" else row[key] == value
            for key, value in filters.items())), key=lambda row: row["id"])
    return {"notice": BANNER, "synthetic_catalog": True,
            "catalog_sha256": fingerprint(rows), "filters": dict(filters),
            "total": len(selected), "offset": offset,
            "resources": selected[offset:offset + limit],
            "next_offset": offset + limit if offset + limit < len(selected) else None,
            "ordering": "Resource ID, not medical relevance or ranking."}


def inspect_model(path):
    model = load_model(path)
    documents = [{"id": identifier, "nonzero_terms": len(weights),
                  "l2_norm": math.sqrt(sum(value * value for value in weights.values()))}
                 for identifier, weights in sorted(model["vectors"].items())]
    return {"notice": BANNER, "synthetic_catalog": True,
            "version": model["version"], "catalog_sha256": model["catalog_sha256"],
            "artifact_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "representation_sha256": fingerprint(model),
            "terms": len(model["idf"]), "documents": documents,
            "meaning": "Reproducibility diagnostics, not clinical validation."}


def explain(model, request):
    ranked = rank_resources(model, request)
    query = vector(" ".join(request[key] for key in OPTIONS), model["idf"])
    rows = []
    for position, (score, row) in enumerate(ranked, 1):
        contributions = {term: value * model["vectors"][row["id"]].get(term, 0)
                         for term, value in sorted(query.items())
                         if model["vectors"][row["id"]].get(term, 0)}
        rows.append({"id": row["id"], "rank": position, "score": score,
                     "term_contributions": contributions,
                     "preference_matches": {key: row[key] == request[key]
                                            for key in ("topic", "format", "focus")}})
    return {"notice": BANNER, "synthetic_catalog": True,
            "catalog_sha256": model["catalog_sha256"],
            "query_terms": dict(sorted(query.items())), "ranking": rows,
            "excluded_stage_ids": sorted(row["id"] for row in catalog()
                                         if request["stage"] not in row["stages"]),
            "ordering": "Full-precision cosine descending, then resource ID ascending.",
            "meaning": "Lexical contribution diagnostics, not health relevance or confidence."}


METRICS = ("recall_at_k", "ndcg_at_k", "mrr_at_k", "precision_at_k", "map_at_k")


def read_report(path):
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("Evaluation report exceeds the local 2 MB inspection limit.")
    report = decode_json(raw.decode("utf-8"))
    if not isinstance(report, dict):
        raise ValueError("Expected a versioned synthetic evaluation report.")
    reference = evaluate(fitted_model(catalog()), report.get("split"), report.get("k"))
    if set(report) != set(reference) or type(report["report_version"]) is not int or report["report_version"] != 1:
        raise ValueError("Unsupported evaluation report schema.")
    for key in ("notice", "synthetic_catalog", "catalog_sha256", "benchmark_sha256",
                "limits", "split", "k", "queries"):
        if type(report[key]) is not type(reference[key]) or report[key] != reference[key]:
            raise ValueError("Evaluation report manifest does not match this synthetic benchmark.")
    for key in ("model_sha256", "report_sha256"):
        if not isinstance(report[key], str) or not re.fullmatch("[0-9a-f]{64}", report[key]):
            raise ValueError("Invalid evaluation report fingerprint.")
    unsigned = {key: value for key, value in report.items() if key != "report_sha256"}
    if fingerprint(unsigned) != report["report_sha256"]:
        raise ValueError("Evaluation report integrity check failed.")
    if not isinstance(report["cases"], list) or len(report["cases"]) != reference["queries"]:
        raise ValueError("Evaluation case count does not match its manifest.")
    for case, expected in zip(report["cases"], reference["cases"]):
        if not isinstance(case, dict) or set(case) != set(expected):
            raise ValueError("Unsupported evaluation case schema.")
        if case["request"] != expected["request"] or case["relevant"] != expected["relevant"]:
            raise ValueError("Evaluation case selections or labels changed.")
        validate(case["request"])
        eligible = {row["id"] for row in catalog() if case["request"]["stage"] in row["stages"]}
        ids = case["ranked"]
        if (not isinstance(ids, list) or len(ids) != min(report["k"], len(eligible))
                or any(not isinstance(identifier, str) for identifier in ids)
                or len(set(ids)) != len(ids) or not set(ids) <= eligible):
            raise ValueError("Invalid evaluation ranking.")
        gold = set(case["relevant"])
        hits = [int(identifier in gold) for identifier in ids]
        values = {
            "recall_at_k": sum(hits) / len(gold),
            "precision_at_k": sum(hits) / report["k"],
            "ndcg_at_k": sum(hit / math.log2(i + 2) for i, hit in enumerate(hits)) /
                sum(1 / math.log2(i + 2) for i in range(min(report["k"], len(gold)))),
            "reciprocal_rank_at_k": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0),
            "average_precision_at_k": sum(hit * sum(hits[:i + 1]) / (i + 1)
                                        for i, hit in enumerate(hits)) / min(report["k"], len(gold)),
        }
        for key, value in values.items():
            if type(case[key]) not in (int, float) or case[key] != value:
                raise ValueError("Evaluation case metrics do not reconcile with rankings.")
        if (type(case["eligible_count"]) is not int or case["eligible_count"] != len(eligible)
                or type(case["recall_ceiling_at_k"]) not in (int, float)
                or case["recall_ceiling_at_k"] != min(report["k"], len(gold)) / len(gold)
                or case["irrelevant_returned"] != [identifier for identifier in ids if identifier not in gold]):
            raise ValueError("Evaluation case diagnostics do not reconcile.")
        missing = case["missing_relevant"]
        if (not isinstance(missing, list) or len(missing) != len(gold - set(ids))
                or any(not isinstance(row, dict) or set(row) != {"id", "rank"}
                       or not isinstance(row["id"], str)
                       or row["id"] not in gold - set(ids) or type(row["rank"]) is not int
                       or not report["k"] < row["rank"] <= len(eligible) for row in missing)
                or len({row["id"] for row in missing}) != len(missing)
                or len({row["rank"] for row in missing}) != len(missing)):
            raise ValueError("Invalid missed-relevance diagnostics.")
    fields = {"mrr_at_k": "reciprocal_rank_at_k", "map_at_k": "average_precision_at_k"}
    for key in METRICS:
        value = sum(case[fields.get(key, key)] for case in report["cases"]) / report["queries"]
        if type(report[key]) not in (int, float) or report[key] != value:
            raise ValueError("Evaluation aggregate metrics do not reconcile.")
    return report


def compare_reports(before_path, after_path):
    before, after = read_report(before_path), read_report(after_path)
    for key in ("split", "k", "catalog_sha256", "benchmark_sha256"):
        if before[key] != after[key]:
            raise ValueError("Compare requires the same split, k, catalog and benchmark.")
    return {"notice": BANNER, "synthetic_catalog": True,
            "before_report_sha256": before["report_sha256"],
            "after_report_sha256": after["report_sha256"],
            "metric_deltas": {key: after[key] - before[key] for key in METRICS},
            "changed_cases": [{"request": old["request"], "before": old["ranked"], "after": new["ranked"]}
                              for old, new in zip(before["cases"], after["cases"])
                              if old["ranked"] != new["ranked"]],
            "meaning": "Authored relevance comparison only; no statistical or clinical significance."}
