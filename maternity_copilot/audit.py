"""Deterministic local inspection of authored synthetic educational content."""

import itertools
import math
import re

from .core import BANNER, OPTIONS, _evaluate_snapshot, _rank_rows, catalog, evaluate, fingerprint, fitted_model, load_benchmark, load_model_snapshot, model_catalog, rank_resources, read_json, validate, vector


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


def compare_resources(stage, identifiers):
    if (stage not in OPTIONS["stage"] or not isinstance(identifiers, list)
            or not 2 <= len(identifiers) <= 4
            or any(not isinstance(identifier, str) for identifier in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        raise ValueError("Compare two to four unique catalog IDs for a supported stage.")
    rows = catalog()
    source = {row["id"]: row for row in rows}
    if any(identifier not in source or stage not in source[identifier]["stages"]
           for identifier in identifiers):
        raise ValueError("All comparison resources must be compatible with the selected stage.")
    selected = [source[identifier] for identifier in identifiers]
    shared = set(selected[0]["questions"]).intersection(*(row["questions"] for row in selected[1:]))
    return {"notice": BANNER, "synthetic_catalog": True, "human_review_required": True,
            "catalog_sha256": fingerprint(rows), "stage": stage, "resources": selected,
            "shared_questions": sorted(shared),
            "contrasting_fields": [field for field in ("topic", "format", "focus")
                                   if len({row[field] for row in selected}) > 1],
            "meaning": "Fixed content comparison in chosen order; no clinical superiority or recommendation."}


def related_resources(model, stage, identifier, limit=3):
    if stage not in OPTIONS["stage"] or type(limit) is not int or not 1 <= limit <= 6:
        raise ValueError("Related resources use a supported stage and limit 1–6.")
    rows = model_catalog(model)
    source = next((row for row in rows if row["id"] == identifier and stage in row["stages"]), None)
    if source is None:
        raise ValueError("Choose a catalog resource compatible with the selected stage.")
    query = model["vectors"][identifier]
    candidates = []
    for row in rows:
        if row["id"] == identifier or stage not in row["stages"]:
            continue
        score = sum(value * model["vectors"][row["id"]].get(term, 0) for term, value in query.items())
        candidates.append((score, row))
    candidates.sort(key=lambda item: (-item[0], item[1]["id"]))
    return {"notice": BANNER, "synthetic_catalog": True, "catalog_sha256": fingerprint(rows),
            "source_id": identifier, "stage": stage,
            "resources": [{**row, "retrieval_score": round(score, 6)}
                          for score, row in candidates[:limit]],
            "meaning": "Document-to-document lexical similarity only, not a suggested care pathway."}


def inspect_model(path):
    model, artifact_sha256 = load_model_snapshot(path)
    documents = [{"id": identifier, "nonzero_terms": len(weights),
                  "l2_norm": math.sqrt(sum(value * value for value in weights.values()))}
                 for identifier, weights in sorted(model["vectors"].items())]
    return {"notice": BANNER, "synthetic_catalog": True,
            "version": model["version"], "catalog_sha256": model["catalog_sha256"],
            "artifact_sha256": artifact_sha256,
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


def coverage():
    rows = catalog()
    benchmark = load_benchmark(rows)
    cases = [case for split in benchmark.values() for case in split]
    signatures = {tuple(case[key] for key in OPTIONS) for case in cases}
    missing = [dict(zip(OPTIONS, values)) for values in itertools.product(*OPTIONS.values())
               if values not in signatures]
    return {"notice": BANNER, "synthetic_catalog": True,
            "catalog_sha256": fingerprint(rows), "benchmark_sha256": fingerprint(benchmark),
            "possible_queries": math.prod(len(values) for values in OPTIONS.values()),
            "benchmark_queries": len(cases), "unrepresented_queries": missing,
            "selection_counts": {
                key: {value: sum(case[key] == value for case in cases) for value in allowed}
                for key, allowed in OPTIONS.items()},
            "relevance_label_counts": {
                row["id"]: sum(row["id"] in case["relevant"] for case in cases)
                for row in sorted(rows, key=lambda item: item["id"])},
            "stage_topic_cells": [
                {"stage": stage, "topic": topic,
                 "resource_ids": sorted(row["id"] for row in rows
                                        if stage in row["stages"] and row["topic"] == topic),
                 "benchmark_queries": sum(case["stage"] == stage and case["topic"] == topic
                                          for case in cases)}
                for stage, topic in itertools.product(OPTIONS["stage"], OPTIONS["topic"])],
            "meaning": "Coverage of authored selections and labels, not real users or clinical coverage."}


def sweep(model, k=3):
    if type(k) is not int or not 1 <= k <= 6:
        raise ValueError("Sweep k must be an integer from 1 to 6.")
    rows = model_catalog(model)
    cases = []
    for values in itertools.product(*OPTIONS.values()):
        request = dict(zip(OPTIONS, values))
        ranked = _rank_rows(model, request, rows)
        ids = [row["id"] for _, row in ranked[:k]]
        relevant = {row["id"] for row in rows
                    if request["stage"] in row["stages"] and row["topic"] == request["topic"]}
        cases.append({"request": request, "ranked": ids, "relevant": sorted(relevant),
                      "recall_at_k": len(set(ids) & relevant) / len(relevant) if relevant else None,
                      "top_preference_matches": {key: ranked[0][1][key] == request[key]
                                                 for key in ("topic", "format", "focus")} if ranked else {}})
    labeled = [case for case in cases if case["recall_at_k"] is not None]
    return {"notice": BANNER, "synthetic_catalog": True, "catalog_sha256": fingerprint(rows),
            "k": k, "queries": len(cases), "cases": cases,
            "macro_metadata_recall_at_k": sum(case["recall_at_k"] for case in labeled) / len(labeled) if labeled else None,
            "unlabeled_queries": len(cases) - len(labeled),
            "top_preference_match_counts": {
                key: sum(case["top_preference_matches"].get(key, False) for case in cases)
                for key in ("topic", "format", "focus")},
            "meaning": "Exhaustive metadata stress check; labels are derived from this catalog, not independent evaluation."}


def sensitivity(model, request, field):
    limit = validate(request)
    if field not in OPTIONS:
        raise ValueError("Sensitivity varies only one documented selection field.")
    rows = model_catalog(model)
    base = [row["id"] for _, row in _rank_rows(model, request, rows)[:limit]]
    variants = []
    for value in OPTIONS[field]:
        changed = {**request, field: value}
        ids = [row["id"] for _, row in _rank_rows(model, changed, rows)[:limit]]
        variants.append({"value": value, "ranked": ids,
                         "retained": sorted(set(base) & set(ids)),
                         "entered": sorted(set(ids) - set(base)), "left": sorted(set(base) - set(ids)),
                         "rank_shifts": {identifier: base.index(identifier) - ids.index(identifier)
                                         for identifier in sorted(set(base) & set(ids))}})
    return {"notice": BANNER, "synthetic_catalog": True,
            "catalog_sha256": fingerprint(rows), "request": dict(request),
            "field": field, "baseline_ranked": base, "variants": variants,
            "meaning": "One-selection lexical sensitivity; positive shifts mean earlier rank, not better care."}


def grouped_evaluation(model, split="held_out", k=3, by="topic"):
    if by not in OPTIONS:
        raise ValueError("Group evaluation by a documented bounded selection only.")
    report = evaluate(model, split, k)
    groups = []
    fields = {"mrr_at_k": "reciprocal_rank_at_k", "map_at_k": "average_precision_at_k"}
    for value in OPTIONS[by]:
        cases = [case for case in report["cases"] if case["request"][by] == value]
        groups.append({"value": value, "queries": len(cases),
                       "metrics": {key: sum(case[fields.get(key, key)] for case in cases) / len(cases)
                                   if cases else None for key in METRICS}})
    return {"notice": BANNER, "synthetic_catalog": True,
            "source_report_sha256": report["report_sha256"], "split": split, "k": k,
            "group_by": by, "groups": groups,
            "meaning": "Authored selection groups, not patient subgroups, fairness or population evidence."}


def cutoff_curve(model, split="held_out"):
    if split not in ("development", "held_out"):
        raise ValueError("Curve split must be development or held_out.")
    rows = model_catalog(model)
    benchmark = load_benchmark(rows)
    points = []
    for k in range(1, 7):
        report = _evaluate_snapshot(model, rows, benchmark, split, k)
        points.append({"k": k, "metrics": {key: report[key] for key in METRICS},
                       "mean_returned": sum(len(case["ranked"]) for case in report["cases"]) / report["queries"],
                       "mean_recall_ceiling": sum(case["recall_ceiling_at_k"] for case in report["cases"]) / report["queries"]})
    return {"notice": BANNER, "synthetic_catalog": True,
            "catalog_sha256": fingerprint(rows), "benchmark_sha256": fingerprint(benchmark),
            "split": split, "queries": len(benchmark[split]), "points": points,
            "meaning": "Cutoff trade-offs on authored labels, not optimal care recommendations."}


def evaluate_baselines(model, split="held_out", k=3):
    report = evaluate(model, split, k)
    rows = model_catalog(model)
    strategies = []
    for strategy in ("resource_id", "topic_metadata"):
        cases = []
        for case in report["cases"]:
            request, gold = case["request"], set(case["relevant"])
            eligible = [row for row in rows if request["stage"] in row["stages"]]
            eligible.sort(key=lambda row: (
                int(row["topic"] != request["topic"]) if strategy == "topic_metadata" else 0,
                row["id"]))
            ids = [row["id"] for row in eligible[:k]]
            hits = [int(identifier in gold) for identifier in ids]
            dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
            ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
            cases.append({"request": request, "ranked": ids,
                          "recall_at_k": sum(hits) / len(gold),
                          "ndcg_at_k": dcg / ideal,
                          "precision_at_k": sum(hits) / k})
        metrics = {key: sum(case[key] for case in cases) / len(cases)
                   for key in ("recall_at_k", "ndcg_at_k", "precision_at_k")}
        strategies.append({"strategy": strategy, "metrics": metrics, "cases": cases,
                           "tfidf_minus_baseline": {key: report[key] - value for key, value in metrics.items()}})
    return {"notice": BANNER, "synthetic_catalog": True, "split": split, "k": k,
            "source_report_sha256": report["report_sha256"], "baselines": strategies,
            "meaning": "ID baseline ignores preferences; topic baseline directly reuses label metadata. Neither is independent clinical evidence."}


def read_report(path):
    report = read_json(path)
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
