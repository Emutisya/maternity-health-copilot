import copy
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from maternity_copilot.core import BANNER, catalog, decode_json, evaluate, fingerprint, fitted_model, load_benchmark, retrieve, train, write_json
from maternity_copilot.audit import browse, compare_reports, coverage, explain, inspect_model, read_report, sensitivity, sweep
from maternity_copilot.planning import make_plan, read_plan, render_plan, save_plan, select_questions


class CatalogBoundaryTests(unittest.TestCase):
    def test_cli_missing_model_explains_recovery_without_traceback(self):
        result = subprocess.run([sys.executable, "-m", "maternity_copilot",
                                 "--model", "models\\no-such-audit-model.json", "inspect"],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("same --model path", result.stderr)
        self.assertIn(BANNER, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_plain_text_plan_retains_notice_review_and_source_provenance(self):
        plan = make_plan("pregnancy", ["access-guide"])
        text = render_plan(plan)
        self.assertEqual(text.count(BANNER), 2)
        self.assertIn("Human review required", text)
        for index, question in enumerate(plan["questions"], 1):
            self.assertIn(f"{index}. {question['text']}", text)
            self.assertIn(f"access-guide question {index}", text)
        plan["questions"][0]["text"] = "Unreviewed text"
        with self.assertRaises(ValueError):
            render_plan(plan)

    def test_portable_question_selectors_reconstruct_and_reject_edits(self):
        directory = Path("models") / ("plan-" + uuid.uuid4().hex)
        path = directory / "selection.json"
        try:
            plan = make_plan("pregnancy", ["access-guide"])
            capsule = save_plan(path, plan)
            self.assertNotIn("questions", capsule)
            self.assertEqual(read_plan(path), plan)
            capsule["selections"][0]["question_number"] = 2
            write_json(path, capsule)
            with self.assertRaisesRegex(ValueError, "integrity"):
                read_plan(path)
            capsule = save_plan(path, plan)
            capsule["notes"] = "unbounded"
            write_json(path, capsule)
            with self.assertRaisesRegex(ValueError, "synthetic-only"):
                read_plan(path)
        finally:
            shutil.rmtree(directory)

    def test_question_selection_preserves_chosen_order_without_free_text(self):
        picks = [{"resource_id": "support-guide", "question_number": 2},
                 {"resource_id": "access-guide", "question_number": 1}]
        plan = select_questions("pregnancy", picks)
        self.assertEqual([row["sources"][0] for row in plan["questions"]], picks)
        for bad in ([picks[0], picks[0]],
                    [{"resource_id": "support-guide", "question_number": 99}],
                    [{"resource_id": "support-guide", "question_number": True}],
                    [{**picks[0], "text": "arbitrary"}]):
            with self.assertRaises(ValueError):
                select_questions("pregnancy", bad)

    def test_question_plan_contains_only_eligible_authored_questions(self):
        plan = make_plan("pregnancy", ["access-guide", "support-guide"])
        self.assertTrue(plan["human_review_required"])
        self.assertEqual(plan["notice"], BANNER)
        self.assertEqual(len(plan["questions"]), 4)
        source = {row["id"]: row for row in catalog()}
        for question in plan["questions"]:
            for origin in question["sources"]:
                self.assertEqual(question["text"], source[origin["resource_id"]]["questions"][origin["question_number"] - 1])
        for ids in ([], ["unknown"], ["access-guide"] * 2, ["appointments-checklist"]):
            with self.assertRaises(ValueError):
                make_plan("pregnancy", ids)

    def test_sensitivity_changes_only_one_enum_and_exposes_stage_exclusion(self):
        model = fitted_model(catalog())
        request = {"stage": "pregnancy", "topic": "appointments", "format": "guide", "focus": "planning"}
        report = sensitivity(model, request, "stage")
        self.assertEqual(report["variants"][0]["ranked"], report["baseline_ranked"])
        changed = report["variants"][1]
        self.assertIn("appointments-guide", changed["left"])
        self.assertIn("appointments-checklist", changed["entered"])
        self.assertEqual(request["stage"], "pregnancy")
        with self.assertRaises(ValueError):
            sensitivity(model, request, "symptoms")

    def test_exhaustive_sweep_reconciles_metadata_labels_and_preference_counts(self):
        report = sweep(fitted_model(catalog()), k=1)
        self.assertEqual(report["queries"], 48)
        self.assertEqual(report["unlabeled_queries"], 0)
        for case in report["cases"]:
            self.assertEqual(case["recall_at_k"],
                             len(set(case["ranked"]) & set(case["relevant"])) / len(case["relevant"]))
        for key in ("topic", "format", "focus"):
            self.assertEqual(report["top_preference_match_counts"][key],
                             sum(case["top_preference_matches"][key] for case in report["cases"]))

    def test_coverage_exposes_all_unrepresented_bounded_queries(self):
        report = coverage()
        self.assertEqual(report["possible_queries"], 48)
        self.assertEqual(report["benchmark_queries"] + len(report["unrepresented_queries"]), 48)
        self.assertEqual(len({tuple(case.values()) for case in report["unrepresented_queries"]}), 36)
        self.assertTrue(all(cell["resource_ids"] for cell in report["stage_topic_cells"]))
        self.assertEqual(sum(report["selection_counts"]["stage"].values()), 12)
        self.assertTrue(all(count > 0 for count in report["relevance_label_counts"].values()))

    def test_saved_report_comparison_rejects_forged_metrics_and_mismatched_k(self):
        directory = Path("models") / ("compare-" + uuid.uuid4().hex)
        path, other = directory / "before.json", directory / "after.json"
        try:
            report = evaluate(fitted_model(catalog()))
            write_json(path, report)
            write_json(other, report)
            self.assertEqual(compare_reports(path, other)["changed_cases"], [])
            forged = copy.deepcopy(report)
            forged["recall_at_k"] = 0
            forged["report_sha256"] = fingerprint({key: value for key, value in forged.items()
                                                  if key != "report_sha256"})
            write_json(other, forged)
            with self.assertRaisesRegex(ValueError, "aggregate"):
                read_report(other)
            write_json(other, evaluate(fitted_model(catalog()), k=1))
            with self.assertRaisesRegex(ValueError, "same split, k"):
                compare_reports(path, other)
        finally:
            shutil.rmtree(directory)

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
