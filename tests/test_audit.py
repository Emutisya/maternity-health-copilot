import copy
import hashlib
import json
import io
import math
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from maternity_copilot.core import BANNER, DATA, catalog, decode_json, evaluate, fingerprint, fitted_model, load_benchmark, read_json, retrieve, retrieve_batch, train, write_json
from maternity_copilot.audit import browse, catalog_audit, compare_reports, compare_resources, coverage, cutoff_curve, evaluate_baselines, explain, grouped_evaluation, inspect_model, read_report, regression_gate, related_resources, sensitivity, sweep, vocabulary_audit
from maternity_copilot.planning import compare_plans, edit_plan, make_plan, merge_plans, read_plan, render_plan, save_plan, select_questions


class CatalogBoundaryTests(unittest.TestCase):
    def test_cli_match_and_explain_share_bounded_result_limit(self):
        directory = Path("models") / ("limit-" + uuid.uuid4().hex)
        path = directory / "model.json"
        try:
            train(path)
            selections = ["--stage", "pregnancy", "--topic", "access", "--format", "guide", "--focus", "support", "--limit", "1"]
            for command in ("match", "explain"):
                result = subprocess.run([sys.executable, "-m", "maternity_copilot",
                                         "--model", str(path), command, *selections],
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                if command == "match":
                    self.assertEqual(len(report["resources"]), 1)
                else:
                    self.assertEqual(report["cutoff"]["limit"], 1)
        finally:
            shutil.rmtree(directory)

    def test_plan_edit_requires_existing_removals_and_complete_retained_order(self):
        plan = make_plan("pregnancy", ["access-guide", "support-guide"])
        picks = [origin for question in plan["questions"] for origin in question["sources"]]
        edited = edit_plan(plan, [picks[0]], list(reversed(picks[1:])))
        self.assertEqual(edited["questions"][0]["sources"], [picks[-1]])
        self.assertEqual(len(edited["questions"]), 3)
        self.assertEqual(len(plan["questions"]), 4)
        for remove, order in ((picks, None), (None, picks[:1]),
                              ([{"resource_id": "feeding-guide", "question_number": 1}], None)):
            with self.assertRaises(ValueError):
                edit_plan(plan, remove, order)

    def test_per_case_gate_catches_regressions_masked_by_equal_aggregate(self):
        request = {"stage": "pregnancy", "topic": "support", "format": "guide", "focus": "support"}
        comparison = {"metric_deltas": {"ndcg_at_k": 0},
                      "changed_cases": [{"request": request, "metric_deltas": {"ndcg_at_k": -.2}},
                                        {"request": {**request, "stage": "postpartum"},
                                         "metric_deltas": {"ndcg_at_k": .2}}]}
        self.assertTrue(regression_gate(comparison, ["ndcg_at_k"])["passed"])
        gate = regression_gate(comparison, ["ndcg_at_k"], per_case=True)
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["failed_cases"], [{"request": request, "failed_metrics": ["ndcg_at_k"]}])
        self.assertTrue(regression_gate(comparison, ["ndcg_at_k"], .2, True)["passed"])

    def test_batch_validates_every_request_before_loading_one_snapshot(self):
        request = {"stage": "pregnancy", "topic": "support", "format": "guide", "focus": "support"}
        model, rows = fitted_model(catalog()), catalog()
        requests = [request, {**request, "stage": "postpartum", "limit": 1}]
        with patch("maternity_copilot.core.catalog", return_value=rows) as read:
            batch = retrieve_batch(model, requests)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(batch["results"], [retrieve(model, item) for item in requests])
        with patch("maternity_copilot.core.catalog") as read:
            with self.assertRaises(ValueError):
                retrieve_batch(model, [request, {**request, "name": "not accepted"}])
            read.assert_not_called()
        for invalid in ([], requests * 5, {"requests": requests}):
            with self.assertRaises(ValueError):
                retrieve_batch(model, invalid)

    def test_plan_diff_distinguishes_reordering_from_membership_and_stage_changes(self):
        picks = [{"resource_id": "access-guide", "question_number": 1},
                 {"resource_id": "support-guide", "question_number": 2}]
        first = select_questions("pregnancy", picks)
        reversed_plan = select_questions("pregnancy", list(reversed(picks)))
        difference = compare_plans(first, reversed_plan)
        self.assertTrue(difference["retained_order_changed"])
        self.assertEqual(difference["added"], [])
        self.assertEqual(difference["removed"], [])
        stage_difference = compare_plans(first, select_questions("postpartum", picks))
        self.assertTrue(stage_difference["stage_changed"])
        self.assertFalse(stage_difference["retained_order_changed"])
        removed = compare_plans(first, select_questions("pregnancy", picks[:1]))
        self.assertEqual(removed["removed"], picks[1:])

    def test_merging_question_lists_deduplicates_and_rejects_stage_changes(self):
        first = make_plan("pregnancy", ["access-guide"])
        second = make_plan("pregnancy", ["access-guide", "support-guide"])
        merged = merge_plans([first, second])
        self.assertEqual(merged, second)
        self.assertTrue(merged["human_review_required"])
        with self.assertRaisesRegex(ValueError, "same stage"):
            merge_plans([first, make_plan("postpartum", ["support-guide"])])
        for count in (1, 5):
            with self.assertRaises(ValueError):
                merge_plans([first] * count)

    def test_compare_cli_detects_valid_ranking_regression_with_exit_one(self):
        directory = Path("models") / ("gate-" + uuid.uuid4().hex)
        before_path, after_path = directory / "before.json", directory / "after.json"
        try:
            before = evaluate(fitted_model(catalog()))
            after = copy.deepcopy(before)
            case = after["cases"][0]
            case["ranked"].reverse()
            case["irrelevant_returned"] = [identifier for identifier in case["ranked"]
                                          if identifier not in case["relevant"]]
            case["ndcg_at_k"] = .5
            case["reciprocal_rank_at_k"] = 1 / 3
            case["average_precision_at_k"] = 1 / 3
            for key, field in (("ndcg_at_k", "ndcg_at_k"), ("mrr_at_k", "reciprocal_rank_at_k"),
                               ("map_at_k", "average_precision_at_k")):
                after[key] = sum(item[field] for item in after["cases"]) / after["queries"]
            after["model_sha256"] = "0" * 64
            after["report_sha256"] = fingerprint({key: value for key, value in after.items()
                                                 if key != "report_sha256"})
            write_json(before_path, before)
            write_json(after_path, after)
            result = subprocess.run([sys.executable, "-m", "maternity_copilot", "compare",
                                     "--before", str(before_path), "--after", str(after_path),
                                     "--fail-on-regression", "ndcg_at_k"],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            comparison = json.loads(result.stdout)
            self.assertEqual(len(comparison["changed_cases"]), 1)
            self.assertEqual(comparison["regression_gate"]["failed_metrics"], ["ndcg_at_k"])
        finally:
            shutil.rmtree(directory)

    def test_synthetic_regression_gate_uses_explicit_metrics_and_absolute_tolerance(self):
        comparison = {"metric_deltas": {"recall_at_k": -.1, "ndcg_at_k": .2}}
        self.assertFalse(regression_gate(comparison, ["recall_at_k"])["passed"])
        self.assertTrue(regression_gate(comparison, ["ndcg_at_k"])["passed"])
        self.assertTrue(regression_gate(comparison, ["recall_at_k"], .1)["passed"])
        for tolerance in (-1, float("nan"), True):
            with self.assertRaises(ValueError):
                regression_gate(comparison, ["recall_at_k"], tolerance)
        with self.assertRaises(ValueError):
            regression_gate(comparison, ["clinical_safety"])

    def test_development_benchmark_includes_unavailable_format_and_conflicting_focus(self):
        report = evaluate(fitted_model(catalog()), split="development")
        unavailable = next(case for case in report["cases"]
                           if case["request"]["topic"] == "appointments"
                           and case["request"]["format"] == "checklist")
        self.assertEqual(unavailable["relevant"], ["appointments-guide"])
        self.assertNotIn("appointments-checklist", unavailable["ranked"])
        self.assertEqual(report["queries"], 12)
        self.assertEqual(len(load_benchmark()["held_out"]), 6)

    def test_overflowing_json_literals_and_material_metric_drift_are_not_accepted(self):
        for text in ('{"x":1e999}', '{"x":-1e999}'):
            with self.assertRaises(ValueError):
                decode_json(text)
        directory = Path("models") / ("numeric-" + uuid.uuid4().hex)
        path = directory / "report.json"
        try:
            report = evaluate(fitted_model(catalog()))
            report["cases"][0]["ndcg_at_k"] -= 1e-14
            report["ndcg_at_k"] -= 1e-14 / report["queries"]
            report["report_sha256"] = fingerprint({key: value for key, value in report.items()
                                                  if key != "report_sha256"})
            write_json(path, report)
            self.assertEqual(read_report(path), report)
            report["cases"][0]["ndcg_at_k"] -= .001
            report["report_sha256"] = fingerprint({key: value for key, value in report.items()
                                                  if key != "report_sha256"})
            write_json(path, report)
            with self.assertRaisesRegex(ValueError, "metrics"):
                read_report(path)
        finally:
            shutil.rmtree(directory)

    def test_artifact_writes_cannot_destroy_authored_source_or_catalog(self):
        original = (DATA / "catalog.json").read_bytes()
        with patch("maternity_copilot.core.os.replace") as replace:
            for path in (DATA / "catalog.json", DATA.parent / "artifact.json", Path("README.md")):
                with self.assertRaisesRegex(ValueError, "outside the packaged"):
                    write_json(path, {})
            with self.assertRaises(ValueError):
                train(DATA / "catalog.json")
        replace.assert_not_called()
        self.assertEqual((DATA / "catalog.json").read_bytes(), original)

    def test_vocabulary_reconciles_smoothed_idf_and_selection_coverage(self):
        report = vocabulary_audit(fitted_model(catalog()), selection_only=True)
        self.assertEqual(report["missing_selection_terms"], [])
        for term in report["terms"]:
            self.assertTrue(term["used_in_selections"])
            self.assertEqual(term["document_frequency"], len(term["resource_ids"]))
            self.assertEqual(term["idf"], math.log(13 / (1 + term["document_frequency"])) + 1)

    def test_catalog_review_audit_retains_duplicate_question_provenance(self):
        rows = copy.deepcopy(catalog())
        rows[1]["questions"][0] = rows[0]["questions"][0]
        with patch("maternity_copilot.audit.catalog", return_value=rows):
            report = catalog_audit()
        self.assertEqual(report["question_count"] - report["unique_questions"], 1)
        self.assertEqual(len(report["shared_questions"][0]["sources"]), 2)
        self.assertEqual(len(report["resources"]), 12)
        self.assertTrue(report["human_review_required"])
        self.assertIn("not undergone clinical review", report["review_status"])

    def test_ranking_diagnostics_separate_exact_ties_from_display_collisions(self):
        model = fitted_model(catalog())
        source = catalog()[:4]
        ranked = list(zip((.5000002, .5000001, .5, .5), source))
        request = {"stage": "pregnancy", "topic": "support", "format": "guide", "focus": "support", "limit": 3}
        with patch("maternity_copilot.audit.rank_resources", return_value=ranked):
            report = explain(model, request)
        self.assertTrue(report["cutoff"]["exact_tie"])
        self.assertEqual(report["cutoff"]["gap"], 0)
        self.assertEqual(report["exact_score_ties"], [[row["id"] for row in source[2:]]])
        self.assertEqual(report["display_rounding_collisions"], [[row["id"] for row in source]])
        self.assertGreater(report["top_margin"], 0)

    def test_baselines_expose_direct_metadata_overlap_without_inventing_learning(self):
        model = fitted_model(catalog())
        report = evaluate_baselines(model, k=1)
        id_baseline, metadata = report["baselines"]
        self.assertLess(id_baseline["metrics"]["ndcg_at_k"], metadata["metrics"]["ndcg_at_k"])
        self.assertEqual(metadata["metrics"]["ndcg_at_k"], 1)
        for case in id_baseline["cases"]:
            expected = sorted(row["id"] for row in catalog() if case["request"]["stage"] in row["stages"])[:1]
            self.assertEqual(case["ranked"], expected)

    def test_related_resources_exclude_self_and_incompatible_stage(self):
        model = fitted_model(catalog())
        result = related_resources(model, "pregnancy", "access-guide", 6)
        ids = [row["id"] for row in result["resources"]]
        self.assertNotIn("access-guide", ids)
        self.assertNotIn("appointments-checklist", ids)
        scores = [row["retrieval_score"] for row in result["resources"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(result, related_resources(model, "pregnancy", "access-guide", 6))
        with self.assertRaises(ValueError):
            related_resources(model, "pregnancy", "appointments-checklist")

    def test_resource_comparison_preserves_chosen_order_and_exact_contrasts(self):
        ids = ["access-guide", "access-checklist"]
        result = compare_resources("pregnancy", ids)
        self.assertEqual([row["id"] for row in result["resources"]], ids)
        self.assertEqual(result["contrasting_fields"], ["format", "focus"])
        self.assertEqual(result["shared_questions"], [])
        for invalid in ([ids[0]], ids * 2, ["access-guide", "appointments-checklist"]):
            with self.assertRaises(ValueError):
                compare_resources("pregnancy", invalid)

    def test_cutoff_curve_uses_one_snapshot_and_reconciles_every_point(self):
        model = fitted_model(catalog())
        rows = catalog()
        with patch("maternity_copilot.core.catalog", return_value=rows) as read:
            curve = cutoff_curve(model)
        self.assertEqual(read.call_count, 1)
        self.assertEqual([point["k"] for point in curve["points"]], list(range(1, 7)))
        recall = [point["metrics"]["recall_at_k"] for point in curve["points"]]
        self.assertEqual(recall, sorted(recall))
        for point in curve["points"]:
            report = evaluate(model, k=point["k"])
            self.assertEqual(point["metrics"]["ndcg_at_k"], report["ndcg_at_k"])

    def test_grouped_evaluation_weights_reconcile_with_macro_report(self):
        model = fitted_model(catalog())
        report = evaluate(model, k=1)
        for by in ("stage", "topic", "format", "focus"):
            groups = grouped_evaluation(model, k=1, by=by)["groups"]
            self.assertEqual(sum(group["queries"] for group in groups), report["queries"])
            for key in ("recall_at_k", "ndcg_at_k", "mrr_at_k"):
                weighted = sum(group["metrics"][key] * group["queries"]
                               for group in groups if group["queries"]) / report["queries"]
                self.assertAlmostEqual(weighted, report[key])

    def test_artifact_inspection_hashes_the_same_bytes_it_validates(self):
        rows = catalog()
        raw = json.dumps(fitted_model(rows)).encode()
        with patch("maternity_copilot.core.catalog", return_value=rows):
            with patch("pathlib.Path.open", return_value=io.BytesIO(raw)) as read:
                report = inspect_model("unused")
        self.assertEqual(read.call_count, 1)
        self.assertEqual(report["artifact_sha256"], hashlib.sha256(raw).hexdigest())

    def test_local_reader_caps_bytes_before_decoding(self):
        stream = io.BytesIO(b" " * 20)
        with patch("pathlib.Path.open", return_value=stream):
            with self.assertRaisesRegex(ValueError, "10-byte"):
                read_json("unused", 10)
        with patch("pathlib.Path.open", return_value=io.BytesIO(b'{"x":1}')):
            self.assertEqual(read_json("unused", 7), {"x": 1})
        with patch("pathlib.Path.open", return_value=io.BytesIO('{"x":1}'.encode("utf-16"))):
            with self.assertRaises(ValueError):
                read_json("unused")

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
        self.assertEqual(len({tuple(case.values()) for case in report["unrepresented_queries"]}), 30)
        self.assertTrue(all(cell["resource_ids"] for cell in report["stage_topic_cells"]))
        self.assertEqual(sum(report["selection_counts"]["stage"].values()), 18)
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
