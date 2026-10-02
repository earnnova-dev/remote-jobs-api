"""Regression: /v1/snapshot and /v1/salary-band must honor their "USD" contract.

The endpoints advertise currency="USD" and pool parsed salary_min values.
Before the fix, salary_min was kept in each job's NATIVE currency with no FX
conversion, so e.g. a 300,900-PLN listing was counted as a "USD 300k+" job and
contaminated the median/p75/distribution and every per-skill band.

These tests are offline + deterministic (monkeypatch _cached_all with a fixed
mix of USD + native-currency floors) so the exclusion is exactly assertable.
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
    def __init__(self, d):
        self.d = d

    def to_dict(self):
        return self.d


def _jobs():
    return [
        # USD floors
        _Stub({"source": "jobicy", "salary_min": 100000, "salary_max": 130000,
               "salary_currency": "USD", "salary_period": "year",
               "tags": ["python", "backend"], "title": "A", "company": "X"}),
        _Stub({"source": "wwr", "salary_min": 150000, "salary_max": 180000,
               "salary_currency": "USD", "salary_period": "year",
               "tags": ["python"], "title": "B", "company": "Y"}),
        # NON-USD floors that must be EXCLUDED from any USD aggregation
        _Stub({"source": "jobicy", "salary_min": 300900, "salary_max": 340000,
               "salary_currency": "PLN", "salary_period": "year",
               "tags": ["python"], "title": "PLN-huge", "company": "P"}),  # ~$73k, was the "max:300900" bug
        _Stub({"source": "remotive", "salary_min": 82250, "salary_max": 95000,
               "salary_currency": "EUR", "salary_period": "year",
               "tags": ["backend"], "title": "EUR", "company": "E"}),
        _Stub({"source": "jobicy", "salary_min": 84000, "salary_max": 90000,
               "salary_currency": "GBP", "salary_period": "year",
               "tags": ["backend"], "title": "GBP", "company": "G"}),
        # no salary
        _Stub({"source": "remotive", "salary_min": None, "salary_max": None,
               "salary_currency": None, "salary_period": None,
               "tags": ["design"], "title": "N", "company": "N"}),
    ]


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import remote_jobs_api.server as srv
        cls.srv_mod = srv
        cls._orig = srv._cached_all
        srv._cached_all = lambda *a, **k: _jobs()
        cls.port = _free_port()
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.port}"
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.2)
        raise AssertionError("server not ready")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv_mod._cached_all = cls._orig
        finally:
            try:
                cls.srv.shutdown()
            except Exception:
                pass

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=20) as r:
            return r.status, json.loads(r.read().decode())


class SnapshotUSDTTests(_Base):
    def test_snapshot_usd_only(self):
        status, snap = self._get("/v1/snapshot")
        self.assertEqual(status, 200)
        sal = snap["salary"]
        self.assertEqual(sal["currency"], "USD")
        # Only the two USD floors are pooled: [100000, 150000].
        self.assertEqual(sal["count_with_salary"], 2)
        self.assertEqual(sal["count_non_usd_excluded"], 3)  # PLN, EUR, GBP
        self.assertEqual(sal["max"], 150000)          # NOT 300900 (PLN)
        self.assertEqual(sal["median_min"], 150000)
        self.assertEqual(sal["p75_min"], 150000)
        # distribution has no 300k+ bin (the PLN phantom is gone)
        self.assertEqual(sal["distribution"]["300k+"], 0)
        # count_live still counts all 6 jobs (non-USD are real jobs)
        self.assertEqual(snap["count_live"], 6)


class SalaryBandUSDTTests(_Base):
    def test_salary_band_usd_only(self):
        status, body = self._get("/v1/salary-band")
        self.assertEqual(status, 200)
        self.assertEqual(body["currency"], "USD")
        m = {r["skill"]: r for r in body["skills"]}
        # python: 3 listings carry the tag (A, B, PLN-huge); only 2 are USD
        self.assertEqual(m["python"]["jobs"], 3)
        self.assertEqual(m["python"]["count_with_salary"], 2)  # PLN excluded
        self.assertEqual(m["python"]["max"], 150000)          # NOT 300900
        self.assertEqual(m["python"]["min"], 100000)
        # backend: 3 listings (A USD, EUR, GBP); only 1 USD
        self.assertEqual(m["backend"]["jobs"], 3)
        self.assertEqual(m["backend"]["count_with_salary"], 1)
        self.assertEqual(m["backend"]["max"], 100000)
        # design: 1 listing, no salary -> omitted
        self.assertNotIn("design", m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
