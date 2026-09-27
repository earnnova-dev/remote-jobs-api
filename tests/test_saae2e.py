"""End-to-end SaaS flow tests (integration).

These hit a *live* server on 127.0.0.1:8477. They skip automatically when no
server is running, so they are safe to include in the CI test suite.

Run manually:
    RJA_KEYS_PATH=/tmp/kt.json RJA_ACCOUNTS_PATH=/tmp/ka.json \
    PORT=8477 python3 -m remote_jobs_api.server   &
    python3 -m unittest tests.test_saae2e -v
"""
import http.cookiejar
import json
import os
import re
import socket
import unittest
import urllib.error
import urllib.parse
import urllib.request

B = "http://127.0.0.1:8477"
ACCOUNTS = os.environ.get("RJA_ACCOUNTS_PATH", "/tmp/rjaa.json")
KEYS = os.environ.get("RJA_KEYS_PATH", "/tmp/rjakeys.json")


def _server_alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8477), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(_server_alive(), "no live server on :8477 (see docstring)")
class Saae2e(unittest.TestCase):
    def setUp(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def _post(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(B + path, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        r = self.op.open(req, timeout=10)
        return r.status, r.geturl(), r.read().decode()

    def _get(self, path):
        r = self.op.open(B + path, timeout=10)
        return r.status, r.geturl(), r.read().decode()

    def test_full_account_flow(self):
        # 1 landing
        s, _, body = self._get("/")
        self.assertEqual(s, 200)
        self.assertIn("One API for all remote jobs", body)

        # 2 register
        s, url, _ = self._post("/register", {"email": "e2e@example.com", "password": "secret123"})
        self.assertEqual(s, 200)
        self.assertTrue(url.endswith("/dashboard"))

        # 3 dashboard + key
        s, _, body = self._get("/dashboard")
        self.assertEqual(s, 200)
        self.assertIn("Dashboard", body)
        m = re.search(r"(rja_(?:free|live)_[a-f0-9]+)", body)
        api_key = m.group(1) if m else ""
        self.assertTrue(api_key)

        # 4 API with key
        req = urllib.request.Request(B + "/v1/jobs?limit=3", method="GET")
        req.add_header("Authorization", "Bearer " + api_key)
        r = self.op.open(req, timeout=10)
        self.assertEqual(r.status, 200)
        self.assertIsNotNone(json.loads(r.read().decode()).get("count"))

        # 5 API without key
        try:
            self.op.open(B + "/v1/jobs", timeout=10)
            self.fail("expected 401")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

        # 6 key tied to owner
        keys = json.load(open(KEYS))
        mine = [v for v in keys["keys"].values() if v.get("owner") == "e2e@example.com"]
        self.assertGreaterEqual(len(mine), 1)

        # 7 logout
        s, url, _ = self._post("/logout", {})
        self.assertTrue(url.endswith("/"))
        _, url, body = self._get("/dashboard")
        self.assertTrue(url.endswith("/login") or "Sign in" in body)

        # 8 login again
        self.cj.clear()
        s, url, _ = self._post("/login", {"email": "e2e@example.com", "password": "secret123"})
        self.assertTrue(url.endswith("/dashboard"))

        # 9 wrong password
        self.cj.clear()
        _, _, body = self._post("/login", {"email": "e2e@example.com", "password": "wrongpass"})
        self.assertIn("Incorrect email or password", body)

        # 10 duplicate register
        _, _, body = self._post("/register", {"email": "e2e@example.com", "password": "secret123"})
        self.assertIn("already exists", body)

        # 11 health
        s, _, body = self._get("/health")
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(body).get("status"), "ok")
