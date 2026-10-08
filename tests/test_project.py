import itertools
import json
import shutil
import subprocess
import sys
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from maternity_copilot.core import (
    BANNER, DATA, OPTIONS, catalog, evaluate, load_model, retrieve, train, validate,
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

    def test_relevance_and_stage(self):
        for stage, expected in [("pregnancy", "appointments-guide"),
                                ("postpartum", "appointments-checklist")]:
            result = retrieve(self.model, {**REQUEST, "stage": stage})
            self.assertEqual(result["resources"][0]["id"], expected)
            self.assertTrue(all(stage in row["stages"] for row in result["resources"]))

    def test_preferences_affect_ranking(self):
        guide = {**REQUEST, "topic": "support", "focus": "support"}
        checklist = {**guide, "format": "checklist", "focus": "planning"}
        self.assertEqual(retrieve(self.model, guide)["resources"][0]["id"], "support-guide")
        self.assertEqual(retrieve(self.model, checklist)["resources"][0]["id"], "support-checklist")

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
                                          "score_meaning", "resources"})
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

    def test_http_invalid_inputs_and_origin(self):
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
