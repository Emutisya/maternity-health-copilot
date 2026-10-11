import copy
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from maternity_copilot.core import catalog, decode_json, evaluate, fitted_model, retrieve, train
from maternity_copilot.audit import browse, explain, inspect_model


class CatalogBoundaryTests(unittest.TestCase):
    def test_evaluation_uses_one_validated_catalog_snapshot(self):
        rows = catalog()
        model = fitted_model(rows)
        with patch("maternity_copilot.core.catalog", return_value=rows) as read:
            report = evaluate(model)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(report["queries"], 6)
        changed = copy.deepcopy(rows)
        changed[0]["summary"] += " Updated."
        with patch("maternity_copilot.core.catalog", return_value=changed):
            with self.assertRaisesRegex(ValueError, "train"):
                evaluate(model)

    def test_explanation_reconciles_scores_and_selection_order(self):
        model = fitted_model(catalog())
        request = {"stage": "pregnancy", "topic": "support", "format": "guide", "focus": "support"}
        report = explain(model, request)
        self.assertEqual([row["id"] for row in report["ranking"][:3]],
                         [row["id"] for row in retrieve(model, request)["resources"]])
        for row in report["ranking"]:
            self.assertAlmostEqual(row["score"], sum(row["term_contributions"].values()))
        self.assertEqual(report["excluded_stage_ids"], ["appointments-checklist"])
        self.assertGreater(len(report["ranking"]), 6)

    def test_inspect_distinguishes_bytes_from_representation(self):
        directory = Path("models") / ("inspect-" + uuid.uuid4().hex)
        try:
            path = directory / "model.json"
            model = train(path)
            first = inspect_model(path)
            path.write_text(json.dumps(model, sort_keys=True), encoding="utf-8")
            second = inspect_model(path)
            self.assertNotEqual(first["artifact_sha256"], second["artifact_sha256"])
            self.assertEqual(first["representation_sha256"], second["representation_sha256"])
            self.assertTrue(all(abs(row["l2_norm"] - 1) < 1e-12 for row in first["documents"]))
        finally:
            shutil.rmtree(directory)

    def test_browse_filters_paginate_without_similarity_claims(self):
        page = browse({"stage": "pregnancy", "topic": "appointments"})
        self.assertEqual([row["id"] for row in page["resources"]], ["appointments-guide"])
        first, second = browse(limit=6), browse(offset=6, limit=6)
        self.assertEqual(first["next_offset"], 6)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(len({row["id"] for row in first["resources"] + second["resources"]}), 12)
        self.assertEqual(browse({"topic": "appointments", "focus": "support"})["total"], 0)
        for filters in ({"name": "person"}, {"stage": ["pregnancy"]}):
            with self.assertRaises(ValueError):
                browse(filters)

    def test_local_json_is_unambiguous_and_finite(self):
        for text in ('{"version":1,"version":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                decode_json(text)
        self.assertEqual(decode_json('{"x":1}'), {"x": 1})

    def test_catalog_does_not_export_undocumented_fields(self):
        original = catalog()
        for change in ({"notes": "unreviewed"}, {"id": "Name@example.com"}, {"id": "UPPER"}):
            rows = copy.deepcopy(original)
            rows[0].update(change)
            with patch("maternity_copilot.core.json.loads", return_value=rows):
                with self.assertRaises(ValueError):
                    catalog()
