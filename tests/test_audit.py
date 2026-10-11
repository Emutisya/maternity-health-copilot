import copy
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from maternity_copilot.core import BANNER, catalog, decode_json, evaluate, fingerprint, fitted_model, load_benchmark, retrieve, train, write_json
from maternity_copilot.audit import browse, explain, inspect_model


class CatalogBoundaryTests(unittest.TestCase):
    def test_report_publication_preserves_prior_file_on_failure(self):
        directory = Path("models") / ("report-" + uuid.uuid4().hex)
        path = directory / "report.json"
        try:
            write_json(path, {"existing": True})
            original = path.read_bytes()
            with patch("maternity_copilot.core.os.replace", side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    write_json(path, evaluate(fitted_model(catalog())))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(directory.glob("*.tmp")), [])
            with self.assertRaises(ValueError):
                write_json(path, {"invalid": float("nan")})
            self.assertEqual(path.read_bytes(), original)
        finally:
            shutil.rmtree(directory)

    def test_report_manifest_is_reproducible_and_self_identifying(self):
        model = fitted_model(catalog())
        report = evaluate(model)
        self.assertEqual(report, evaluate(model))
        digest = report.pop("report_sha256")
        self.assertEqual(digest, fingerprint(report))
        self.assertEqual(report["model_sha256"], fingerprint(model))
        self.assertEqual(report["notice"], BANNER)
        self.assertNotEqual(digest, evaluate(model, k=1)["report_sha256"])

    def test_evaluation_explains_cutoff_losses_without_hiding_ceiling(self):
        model = fitted_model(catalog())
        report = evaluate(model, k=1)
        for case in report["cases"]:
            full = explain(model, case["request"])["ranking"]
            ranks = {row["id"]: row["rank"] for row in full}
            self.assertEqual({row["id"] for row in case["missing_relevant"]},
                             set(case["relevant"]) - set(case["ranked"]))
            for row in case["missing_relevant"]:
                self.assertEqual(row["rank"], ranks[row["id"]])
                self.assertGreater(row["rank"], 1)
            self.assertEqual(case["recall_ceiling_at_k"], 1 / len(case["relevant"]))

    def test_precision_and_average_precision_penalize_irrelevant_ranks(self):
        model = fitted_model(catalog())
        report = evaluate(model, k=3)
        for case in report["cases"]:
            hits = [identifier in case["relevant"] for identifier in case["ranked"]]
            self.assertEqual(case["precision_at_k"], sum(hits) / 3)
            expected = sum(hit * sum(hits[:i + 1]) / (i + 1)
                           for i, hit in enumerate(hits)) / min(3, len(case["relevant"]))
            self.assertEqual(case["average_precision_at_k"], expected)
        self.assertLess(report["precision_at_k"], 1)
        self.assertEqual(report["map_at_k"], sum(case["average_precision_at_k"]
                                               for case in report["cases"]) / report["queries"])

    def test_benchmark_rejects_unbounded_extras(self):
        benchmark = load_benchmark()
        rows = catalog()
        benchmark["held_out"][0]["notes"] = "Not a bounded selection."
        with patch("maternity_copilot.core.decode_json", return_value=benchmark):
            with self.assertRaisesRegex(ValueError, "only bounded"):
                load_benchmark(rows)

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
