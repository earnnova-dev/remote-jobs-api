"""Stripe webhook upgrade/downgrade flow tests (integration).

Hits a live server on 127.0.0.1:8477 with a simulated Stripe webhook (no
secret configured, so signatures are not enforced — this exercises the
account/plan mutation logic). Skips when no server is running.
"""
import json
import os
import socket
import unittest
import urllib.parse
import urllib.request

B = "http://127.0.0.1:8477"
ACCOUNTS = os.environ.get("RJA_ACCOUNTS_PATH", "/tmp/rjaa.json")


def _server_alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8477), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(_server_alive(), "no live server on :8477 (see docstring)")
class StripeWebhook(unittest.TestCase):
    def _post(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(B + path, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        return urllib.request.urlopen(req, timeout=10)

    def _post_json(self, path, obj):
        req = urllib.request.Request(B + path, data=json.dumps(obj).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        return urllib.request.urlopen(req, timeout=10)

    def _user(self, email):
        return json.load(open(ACCOUNTS))["users"][email]

    def test_upgrade_and_cancel(self):
        self._post("/register", {"email": "upg@example.com", "password": "secret123"})
        self.assertEqual(self._user("upg@example.com")["plan"], "free")

        # checkout.session.completed -> upgrade to pro
        r = self._post_json("/webhooks/stripe", {
            "type": "checkout.session.completed",
            "data": {"object": {
                "client_reference_id": "upg@example.com",
                "customer": "cus_test123",
                "subscription": "sub_test123",
                "subscription_details": {"items": {"data": [{"price": "price_pro_123"}]}},
            }},
        })
        self.assertEqual(r.status, 200)
        u = self._user("upg@example.com")
        self.assertEqual(u["plan"], "pro")
        self.assertEqual(u["sub_status"], "active")
        self.assertEqual(u["stripe_customer"], "cus_test123")
        self.assertTrue(u["api_key"].startswith("rja_live_"))

        # pro key works at the higher tier
        req = urllib.request.Request(B + "/v1/jobs?limit=3", method="GET")
        req.add_header("Authorization", "Bearer " + u["api_key"])
        self.assertEqual(urllib.request.urlopen(req, timeout=10).status, 200)

        # subscription deleted -> back to free
        r = self._post_json("/webhooks/stripe", {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_test123", "customer": "cus_test123",
                                "status": "canceled",
                                "items": {"data": [{"price": {"id": "price_pro_123"}}]}}},
        })
        self.assertEqual(r.status, 200)
        self.assertEqual(self._user("upg@example.com")["plan"], "free")
