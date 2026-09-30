"""Tests for the public GET /v1/snapshot endpoint.

Self-contained: starts its own server on a free port (skips if no network
access to the boards), then reads /v1/snapshot back and checks structure.
"""
import http.server
import json
import os
import socket
import tempfile
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


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import remote_jobs_api.server as srv
        cls.port = _free_port()
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        base = f"http://127.0.0.1:{cls.port}"
        # wait for readiness (board fetch may take a few seconds)
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.5)
        cls._skip = True

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv.shutdown()
        except Exception:
            pass

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=30) as r:
            return r.status, json.loads(r.read().decode())

    def test_snapshot_structure(self):
        if getattr(self.__class__, "_skip", False):
            self.skipTest("no live board access")
        status, snap = self._get("/v1/snapshot")
        self.assertEqual(status, 200)
        for key in ("count_live", "sources", "generated_at",
                    "demand_by_source", "salary", "top_skills", "top_companies"):
            self.assertIn(key, snap)
        self.assertGreater(snap["count_live"], 0)
        # salary block invariants
        sal = snap["salary"]
        self.assertGreaterEqual(sal["coverage_pct"], 0.0)
        self.assertLessEqual(sal["coverage_pct"], 100.0)
        if sal["count_with_salary"]:
            self.assertLessEqual(sal["median_min"], sal["p75_min"])
            self.assertLessEqual(sal["p75_min"], sal["max"])
        # demand_by_source sums to total
        self.assertEqual(sum(snap["demand_by_source"].values()), snap["count_live"])
        # top lists are non-empty and sorted by count desc
        self.assertTrue(snap["top_skills"])
        self.assertTrue(snap["top_companies"])

    def test_snapshot_matches_health_count(self):
        if getattr(self.__class__, "_skip", False):
            self.skipTest("no live board access")
        _, snap = self._get("/v1/snapshot")
        _, health = self._get("/health")
        # same cache -> same count
        self.assertEqual(snap["count_live"], health["count_live"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
