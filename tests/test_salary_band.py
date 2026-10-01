"""Tests for the public GET /v1/salary-band endpoint.

Offline and deterministic: monkeypatches the server's _cached_all() with a
fixed set of synthetic jobs, so the band math is exactly assertable without
any network access to the boards.
"""
import http.server
import json
import socket
import threading
import time
import unittest
import urllib.request


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Stub:
    """Stand-in for a Job: the handler only reads .to_dict() and then
    pulls source / salary_min / tags from it."""

    def __init__(self, d):
        self.d = d

    def to_dict(self):
        return self.d


def _synthetic_jobs():
    return [
        _Stub({"source": "jobicy", "salary_min": 100000, "salary_max": 120000,
               "salary_currency": "USD", "salary_period": "year",
               "tags": ["python", "backend"], "title": "A", "company": "X"}),
        _Stub({"source": "jobicy", "salary_min": 120000, "salary_max": 150000,
               "salary_currency": "USD", "salary_period": "year",
               "tags": ["python"], "title": "B", "company": "X"}),
        _Stub({"source": "wwr", "salary_min": 140000, "salary_max": 160000,
               "salary_currency": "USD", "salary_period": "year",
               "tags": ["python"], "title": "C", "company": "Y"}),
        _Stub({"source": "wwr", "salary_min": 200000, "salary_max": 220000,
               "salary_currency": "USD", "salary_period": "year",
               "tags": ["python", "golang"], "title": "D", "company": "Y"}),
        _Stub({"source": "remotive", "salary_min": None, "salary_max": None,
               "salary_currency": None, "salary_period": None,
               "tags": ["python"], "title": "E", "company": "Z"}),   # python, no salary
        _Stub({"source": "jobicy", "salary_min": None, "salary_max": None,
               "salary_currency": None, "salary_period": None,
               "tags": ["design"], "title": "F", "company": "X"}),   # design, no salary -> omitted
    ]


class SalaryBandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import remote_jobs_api.server as srv
        cls.srv_mod = srv
        cls._orig_cached_all = srv._cached_all
        cls.srv_mod._cached_all = lambda *a, **k: _synthetic_jobs()
        cls.port = _free_port()
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        base = f"http://127.0.0.1:{cls.port}"
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.2)
        raise AssertionError("server did not become ready")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv_mod._cached_all = cls._orig_cached_all
        finally:
            try:
                cls.srv.shutdown()
            except Exception:
                pass

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=20) as r:
            return r.status, json.loads(r.read().decode())

    def _by_skill(self, body):
        return {row["skill"]: row for row in body["skills"]}

    def test_structure_and_python_band(self):
        status, body = self._get("/v1/salary-band")
        self.assertEqual(status, 200)
        for key in ("count_live", "sources", "generated_at", "currency", "note", "skills"):
            self.assertIn(key, body)
        self.assertEqual(body["currency"], "USD")
        self.assertEqual(body["count_live"], 6)

        m = self._by_skill(body)
        # design has no salary-bearing job -> must be omitted
        self.assertNotIn("design", m)
        self.assertIn("python", m)
        self.assertIn("golang", m)

        py = m["python"]
        # 5 jobs carry the python tag, 4 of them carry a salary
        self.assertEqual(py["jobs"], 5)
        self.assertEqual(py["count_with_salary"], 4)
        self.assertEqual(py["coverage_pct"], 80.0)
        # over [100000, 120000, 140000, 200000]
        self.assertEqual(py["min"], 100000)
        self.assertEqual(py["max"], 200000)
        self.assertEqual(py["median"], 140000)
        # invariant: min <= p25 <= median <= p75 <= max
        self.assertLessEqual(py["min"], py["p25"])
        self.assertLessEqual(py["p25"], py["median"])
        self.assertLessEqual(py["median"], py["p75"])
        self.assertLessEqual(py["p75"], py["max"])

        # sorted by count_with_salary desc -> python(4) before golang(1)
        self.assertEqual(body["skills"][0]["skill"], "python")

    def test_skills_filter(self):
        _, body = self._get("/v1/salary-band?skills=golang")
        self.assertEqual([r["skill"] for r in body["skills"]], ["golang"])
        self.assertEqual(body["skills"][0]["count_with_salary"], 1)

    def test_source_filter(self):
        _, body = self._get("/v1/salary-band?source=jobicy&skills=python")
        py = self._by_skill(body)["python"]
        # only the two jobicy python jobs with salary
        self.assertEqual(py["count_with_salary"], 2)
        self.assertEqual(py["coverage_pct"], 100.0)
        self.assertEqual(py["min"], 100000)
        self.assertEqual(py["max"], 120000)

    def test_limit(self):
        _, body = self._get("/v1/salary-band?limit=1")
        self.assertEqual(len(body["skills"]), 1)

    def test_matches_health_count(self):
        _, body = self._get("/v1/salary-band")
        _, health = self._get("/health")
        self.assertEqual(body["count_live"], health["count_live"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
