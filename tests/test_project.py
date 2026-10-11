import copy
from contextlib import redirect_stderr
from http.client import RemoteDisconnected
import io
import itertools
from http.client import HTTPConnection
import json
import shutil
import subprocess
import socket
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from maternity_copilot.core import (
    BANNER, DATA, OPTIONS, catalog, evaluate, fingerprint, load_model, retrieve, train, validate,
)
from maternity_copilot.server import make_server


REQUEST = {"stage": "pregnancy", "topic": "appointments",
           "format": "guide", "focus": "planning"}


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = Path("models") / ("test-" + uuid.uuid4().hex)
        cls.path = cls.workspace / "model.json"
        cls.model = train(cls.path)
        cls.server = make_server(cls.model, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        shutil.rmtree(cls.workspace)

    def test_learned_representation_and_persistence(self):
        self.assertEqual(load_model(self.path), self.model)
        self.assertGreater(len(set(self.model["idf"].values())), 1)
        repeat = train(self.workspace / "repeat.json")
        self.assertEqual(repeat, self.model)
        changed = dict(self.model, catalog_sha256="outdated")
        (self.workspace / "old.json").write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_model(self.workspace / "old.json")

    def test_invalid_port_precedes_model_loading(self):
        for port in ("-1", "65536", "999999999999999999999"):
            with self.subTest(port=port):
                result = subprocess.run(
                    [sys.executable, "-m", "maternity_copilot",
                     "--model", "models/missing-port-test.json", "serve", "--port", port],
                    cwd=Path(__file__).resolve().parents[1],
                    text=True, capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("--port must be between 0 and 65535", result.stderr)
                self.assertIn("use 0 to choose an available port", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_failed_training_publish_preserves_previous_artifact(self):
        path = self.workspace / "atomic.json"
        train(path)
        original = path.read_bytes()
        with patch("maternity_copilot.core.os.replace", side_effect=PermissionError("Isolated write failure")):
            with self.assertRaises(PermissionError):
                train(path)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.workspace.glob(".atomic.json.*.tmp")), [])
        self.assertEqual(load_model(path), self.model)

    def test_cli_occupied_port_has_actionable_recovery(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            result = subprocess.run(
                [sys.executable, "-m", "maternity_copilot", "--model", str(self.path),
                 "serve", "--port", str(port)], text=True, capture_output=True, timeout=10,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"port {port}", result.stderr)
        self.assertIn("--port 0", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_corrupt_model_weights_are_rejected(self):
        for mutate in (
            lambda model: model.update(version=True),
            lambda model: model["idf"].update({next(iter(model["idf"])): float("nan")}),
            lambda model: model["vectors"].update({next(iter(model["vectors"])): {}}),
        ):
            model = copy.deepcopy(self.model)
            mutate(model)
            path = self.workspace / "corrupt.json"
            path.write_text(json.dumps(model), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Run train again"):
                load_model(path)
        for value in ([], None):
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_model(path)

    def test_catalog_rejects_ambiguous_ids_and_unusable_resources(self):
        original = catalog()
        for rows in ([], [original[0], original[0]], [None]):
            with patch("maternity_copilot.core.json.loads", return_value=rows), self.assertRaises(ValueError):
                catalog()
        for field, value in (("title", ""), ("topic", "diagnosis"),
                             ("questions", []), ("questions", ["same", "same"]),
                             ("stages", ["pregnancy", "pregnancy"])):
            rows = copy.deepcopy(original)
            rows[0][field] = value
            with patch("maternity_copilot.core.json.loads", return_value=rows), self.assertRaises(ValueError):
                catalog()

    def test_boolean_weights_cannot_impersonate_numeric_training_values(self):
        model = copy.deepcopy(self.model)
        model["idf"][next(iter(model["idf"]))] = True
        path = self.workspace / "boolean.json"
        path.write_text(json.dumps(model), encoding="utf-8")
        with patch("maternity_copilot.core.fitted_model", return_value=model), self.assertRaises(ValueError):
            load_model(path)

    def test_relevance_and_stage(self):
        for stage, expected in [("pregnancy", "appointments-guide"),
                                ("postpartum", "appointments-checklist")]:
            result = retrieve(self.model, {**REQUEST, "stage": stage})
            self.assertEqual(result["resources"][0]["id"], expected)
            self.assertTrue(all(stage in row["stages"] for row in result["resources"]))

    def test_display_rounding_does_not_change_resource_order(self):
        rows = copy.deepcopy(catalog()[:2])
        rows[0]["id"], rows[1]["id"] = "a", "z"
        for row in rows:
            row["stages"] = ["pregnancy"]
        model = {"catalog_sha256": fingerprint(rows), "idf": {"planning": 1},
                 "vectors": {"a": {"planning": .5000001}, "z": {"planning": .5000002}}}
        with patch("maternity_copilot.core.catalog", return_value=rows), patch("maternity_copilot.core.vector", return_value={"planning": 1}):
            ranked = retrieve(model, REQUEST)["resources"]
        self.assertEqual([row["id"] for row in ranked], ["z", "a"])
        self.assertEqual(ranked[0]["retrieval_score"], ranked[1]["retrieval_score"])

    def test_preferences_affect_ranking(self):
        guide = {**REQUEST, "topic": "support", "focus": "support"}
        checklist = {**guide, "format": "checklist", "focus": "planning"}
        self.assertEqual(retrieve(self.model, guide)["resources"][0]["id"], "support-guide")
        self.assertEqual(retrieve(self.model, checklist)["resources"][0]["id"], "support-checklist")

    def test_catalog_drift_is_a_recoverable_service_error_not_a_request_error(self):
        changed = copy.deepcopy(catalog())
        changed[0]["summary"] += " New authored content."
        for failure in ({"return_value": changed}, {"side_effect": FileNotFoundError("isolated catalog")}):
            with patch("maternity_copilot.core.catalog", **failure):
                with self.assertRaisesRegex(ValueError, "train.*restart"):
                    retrieve(self.model, REQUEST)
                with self.assertRaises(HTTPError) as caught:
                    self.post(json.dumps(REQUEST).encode())
                self.assertEqual(caught.exception.code, 503)
                self.assertEqual(json.load(caught.exception)["notice"], BANNER)
                caught.exception.close()
                with self.assertRaises(HTTPError) as health:
                    urlopen(self.base + "/api/health", timeout=5)
                self.assertEqual(health.exception.code, 503)
                self.assertEqual(json.load(health.exception)["status"], "unavailable")
                health.exception.close()
        self.assertEqual(retrieve(self.model, REQUEST)["resources"][0]["id"], "appointments-guide")

    def test_invalid_and_symptom_inputs_rejected(self):
        bad = [None, [], "symptoms", {}, {**REQUEST, "symptoms": "pain"},
               {**REQUEST, "name": "Person"}, {**REQUEST, "topic": "bleeding"},
               {**REQUEST, "stage": ["pregnancy"]}, {**REQUEST, "format": None},
               {**REQUEST, "focus": "treatment"}, {**REQUEST, "limit": True},
               {**REQUEST, "limit": 0}, {**REQUEST, "limit": 7},
               {**REQUEST, "limit": 2.5}]
        for request in bad:
            with self.subTest(request=request), self.assertRaises(ValueError):
                validate(request)

    def test_all_outputs_are_fixed_educational_catalog_content(self):
        source = {row["id"]: row for row in catalog()}
        for values in itertools.product(*OPTIONS.values()):
            request = dict(zip(OPTIONS, values))
            result = retrieve(self.model, request)
            self.assertEqual(result["notice"], BANNER)
            self.assertEqual(set(result), {"notice", "prototype", "synthetic_catalog",
                                          "catalog_sha256", "score_meaning", "resources"})
            for row in result["resources"]:
                self.assertEqual({key: value for key, value in row.items()
                                  if key != "retrieval_score"}, source[row["id"]])
                self.assertGreaterEqual(row["retrieval_score"], 0)
                self.assertLessEqual(row["retrieval_score"], 1)

    def test_metrics_computed_from_independent_queries(self):
        benchmark = json.loads((DATA / "benchmark.json").read_text(encoding="utf-8"))
        signatures = [tuple(case[key] for key in OPTIONS)
                      for cases in benchmark.values() for case in cases]
        self.assertEqual(len(signatures), len(set(signatures)))
        report = evaluate(self.model, k=1)
        self.assertEqual(report["catalog_sha256"], fingerprint(catalog()))
        self.assertEqual(report["benchmark_sha256"], fingerprint(benchmark))
        changed = copy.deepcopy(benchmark)
        changed["held_out"][0]["relevant"] = [changed["held_out"][0]["relevant"][0]]
        if changed == benchmark:
            changed["held_out"].reverse()
        decode = json.loads
        with patch("maternity_copilot.core.json.loads", side_effect=lambda text, **kwargs: changed if "held_out" in text else decode(text, **kwargs)):
            self.assertNotEqual(evaluate(self.model)["benchmark_sha256"], report["benchmark_sha256"])
        cases = benchmark["held_out"]
        expected = sum(
            int(retrieve(self.model, {key: case[key] for key in OPTIONS})["resources"][0]["id"]
                in case["relevant"]) / len(case["relevant"]) for case in cases
        ) / len(cases)
        self.assertEqual(report["recall_at_k"], expected)
        self.assertEqual(report["queries"], len(cases))
        for split in benchmark:
            for k in (1, 3, 6):
                metrics = evaluate(self.model, split, k)
                for key in ("recall_at_k", "ndcg_at_k", "mrr_at_k"):
                    self.assertTrue(0 <= metrics[key] <= 1)

    def post(self, payload, headers=None):
        return urlopen(Request(self.base + "/api/resources", data=payload,
                              headers=headers or {"Content-Type": "application/json"}), timeout=5)

    def test_invalid_benchmark_splits_and_relevance_labels_are_rejected(self):
        decode = json.loads
        original = json.loads((DATA / "benchmark.json").read_text(encoding="utf-8"))
        for mutate in (
            lambda data: data.update(held_out=[]),
            lambda data: data["held_out"][0].update(relevant=["unknown"]),
            lambda data: data["held_out"][0].update(relevant=["appointments-guide"] * 2),
            lambda data: data["held_out"][0].update(relevant="appointments-guide"),
        ):
            benchmark = copy.deepcopy(original)
            mutate(benchmark)
            with patch("maternity_copilot.core.json.loads", side_effect=lambda text, **kwargs: benchmark if "held_out" in text else decode(text, **kwargs)), self.assertRaises(ValueError):
                evaluate(self.model)

    def test_evaluation_cases_reconcile_with_aggregate_metrics(self):
        report = evaluate(self.model, k=2)
        cases = report["cases"]
        self.assertEqual(len(cases), report["queries"])
        for case in cases:
            ranked = retrieve(self.model, {**case["request"], "limit": 2})["resources"]
            self.assertEqual(case["ranked"], [row["id"] for row in ranked])
            self.assertAlmostEqual(case["recall_at_k"],
                                   len(set(case["ranked"]) & set(case["relevant"])) / len(case["relevant"]))
        for aggregate, field in (("recall_at_k", "recall_at_k"),
                                 ("ndcg_at_k", "ndcg_at_k"), ("mrr_at_k", "reciprocal_rank_at_k")):
            self.assertAlmostEqual(report[aggregate], sum(case[field] for case in cases) / len(cases))
        self.assertEqual(evaluate(self.model, split="development")["split"], "development")

    def test_http_inference_and_dashboard(self):
        with self.post(json.dumps(REQUEST).encode()) as response:
            result = json.load(response)
            self.assertEqual(result, retrieve(self.model, REQUEST))
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        with urlopen(self.base + "/?clawpilotTheme=dark", timeout=5) as response:
            html = response.read().decode()
            self.assertIn("Synthetic personas", html)
            self.assertNotIn("localStorage", html)
            self.assertNotIn("textarea", html)
        with urlopen(self.base + "/api/health", timeout=5) as response:
            self.assertEqual(json.load(response)["status"], "ready")

    def test_duplicate_routing_and_media_headers_are_rejected(self):
        body = json.dumps(REQUEST).encode()
        expected = f"127.0.0.1:{self.server.server_port}"
        for duplicated, value, status in (("Host", expected, 403),
                                           ("Origin", f"http://{expected}", 403),
                                           ("Content-Type", "application/json", 415)):
            connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            try:
                connection.putrequest("POST", "/api/resources", skip_host=True)
                connection.putheader("Host", expected)
                connection.putheader("Origin", f"http://{expected}")
                connection.putheader("Content-Type", "application/json")
                connection.putheader(duplicated, value)
                connection.putheader("Content-Length", str(len(body)))
                connection.endheaders(body)
                response = connection.getresponse()
                self.assertEqual(response.status, status)
                self.assertEqual(json.loads(response.read())["notice"], BANNER)
            finally:
                connection.close()
        with self.post(body, {"Content-Type": "Application/JSON; charset=utf-8"}) as response:
            self.assertEqual(response.status, 200)

    def test_malformed_get_targets_do_not_crash_or_alias_dashboard(self):
        for target in ("http://[", "//[", "http://example.invalid/", "/#fragment"):
            connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            try:
                connection.request("GET", target, headers={"Host": f"127.0.0.1:{self.server.server_port}"})
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                self.assertEqual(json.loads(response.read())["notice"], BANNER)
            finally:
                connection.close()
        with urlopen(self.base + "/api/health", timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_unsupported_methods_return_nonreflective_json_and_correct_head_framing(self):
        for method in ("OPTIONS", "DELETE", "PATCH", "PERSONAL_VALUE", "HEAD"):
            connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            try:
                connection.request(method, "/api/health")
                response = connection.getresponse()
                self.assertEqual(response.status, 405)
                self.assertEqual(response.headers["Allow"], "GET, POST")
                body = response.read()
                if method == "HEAD":
                    self.assertEqual(body, b"")
                    self.assertGreater(int(response.headers["Content-Length"]), 0)
                else:
                    self.assertEqual(json.loads(body)["notice"], BANNER)
                    self.assertNotIn(b"PERSONAL_VALUE", body)
            finally:
                connection.close()

    def test_http_catalog_browsing_is_bounded_read_only_and_handles_catalog_failures(self):
        def browse_call(payload):
            return urlopen(Request(self.base + "/api/catalog", data=json.dumps(payload).encode(),
                                   headers={"Content-Type": "application/json"}), timeout=5)
        with browse_call({"stage": "pregnancy", "topic": "access", "limit": 1}) as response:
            page = json.load(response)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["next_offset"], 1)
        self.assertNotIn("retrieval_score", page["resources"][0])
        for payload in ({"name": "not accepted"}, {"offset": True}, {"limit": 13}):
            with self.assertRaises(HTTPError) as error:
                browse_call(payload)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        with patch("maternity_copilot.audit.catalog", side_effect=FileNotFoundError):
            with self.assertRaises(HTTPError) as error:
                browse_call({})
            self.assertEqual(error.exception.code, 503)
            self.assertEqual(json.load(error.exception)["notice"], BANNER)
            error.exception.close()

    def test_http_batch_rejects_partial_invalid_batches(self):
        def batch_call(payload):
            return urlopen(Request(self.base + "/api/batch", data=json.dumps(payload).encode(),
                                   headers={"Content-Type": "application/json"}), timeout=5)
        with batch_call([REQUEST, {**REQUEST, "limit": 1}]) as response:
            result = json.load(response)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["results"][0], retrieve(self.model, REQUEST))
        with self.assertRaises(HTTPError) as error:
            batch_call([REQUEST, {**REQUEST, "symptoms": "not accepted"}])
        self.assertEqual(error.exception.code, 400)
        self.assertNotIn("results", json.load(error.exception))
        error.exception.close()

    def test_stalled_request_returns_timeout_without_breaking_server(self):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=8)
        try:
            connection.request("POST", "/api/resources", "{}", {
                "Content-Type": "application/json", "Content-Length": "100",
            })
            response = connection.getresponse()
            self.assertEqual(response.status, 408)
            self.assertEqual(json.loads(response.read())["notice"], BANNER)
        finally:
            connection.close()
        with urlopen(self.base + "/api/health", timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_client_disconnect_does_not_log_a_server_failure(self):
        logs = io.StringIO()
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            with redirect_stderr(logs), patch.object(self.server.RequestHandlerClass, "send", side_effect=ConnectionResetError("client closed")):
                connection.request("GET", "/api/health")
                with self.assertRaises(RemoteDisconnected):
                    connection.getresponse()
        finally:
            connection.close()
        self.assertEqual(logs.getvalue(), "")
        with urlopen(self.base + "/api/health", timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_http_invalid_inputs_and_origin(self):
        invalid = [
            json.dumps(REQUEST).encode("utf-16"),
            ('{"limit":1,"limit":2,' + json.dumps(REQUEST)[1:]).encode(),
            b"[" * 1000 + b"]" * 1000,
        ]
        for body in invalid:
            with self.assertRaises(HTTPError) as error:
                self.post(body)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        for body in (b"not-json", b"\xff", b"[]",
                     json.dumps({**REQUEST, "symptoms": "pain"}).encode(),
                     b"x" * 2049):
            with self.subTest(body=body[:30]), self.assertRaises(HTTPError) as error:
                self.post(body)
            self.assertEqual(error.exception.code, 400)
            payload = json.load(error.exception)
            self.assertEqual(payload["notice"], BANNER)
            self.assertNotIn("pain", json.dumps(payload))
            error.exception.close()
        for headers, code in [
            ({"Content-Type": "text/plain"}, 415),
            ({"Content-Type": "application/json", "Origin": "https://example.org"}, 403),
            ({"Content-Type": "application/json", "Host": "example.org"}, 403),
        ]:
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as error:
                self.post(json.dumps(REQUEST).encode(), headers)
            self.assertEqual(error.exception.code, code)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/../LICENSE", timeout=5)
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
