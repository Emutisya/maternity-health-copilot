"""Deterministic local inspection of authored synthetic educational content."""

from .core import BANNER, OPTIONS, catalog, fingerprint


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
