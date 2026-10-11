"""Deterministic local inspection of authored synthetic educational content."""

import hashlib
import math
from pathlib import Path

from .core import BANNER, OPTIONS, catalog, fingerprint, load_model, rank_resources, vector


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
