"""Minimal Stripe API client — stdlib only (urllib + hmac).

Covers exactly what the SaaS tier needs:
  - customers: create / find by email
  - checkout.sessions: create (subscription)
  - billing_portal.sessions: create
  - subscriptions: update (cancel_at_period_end)
  - webhook signature verification (Stripe-Signature: t=...,v1=...)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from typing import Optional, Any

API_BASE = "https://api.stripe.com/v1"


class StripeError(Exception):
    def __init__(self, message: str, code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.code = code
        self.payload = payload


class StripeClient:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def _request(self, method: str, path: str, fields: Optional[dict] = None,
                 query: Optional[dict] = None) -> dict:
        url = API_BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        body = None
        headers = {
            "Authorization": "Basic " + _b64(self.secret_key),
            "Accept": "application/json",
        }
        if method == "POST" and fields is not None:
            # Stripe expects form-encoded bodies.
            body = urllib.parse.urlencode(_flatten(fields)).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8"))
                msg = err.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            raise StripeError(msg, code=e.code, payload=err if isinstance(err, dict) else None)
        except urllib.error.URLError as e:
            raise StripeError(f"stripe network error: {e.reason}")

    def get_price(self, price_id: str) -> Optional[dict]:
        """Fetch a price object by id (used to map a price -> plan at webhook time)."""
        try:
            return self._request("GET", f"/prices/{price_id}")
        except StripeError:
            return None

    def resolve_prices(self) -> dict:
        """Map plan name -> price id, looked up live from Stripe.

        Prices are matched by the 'rja_plan' metadata tag on their product
        (pro / team). This removes the need to hardcode price ids in env: the
        app always uses whatever prices actually exist in the Stripe account,
        in whichever mode (test or live) the secret key is. Returns
        {'pro': price_id, 'team': price_id} with missing plans omitted.
        """
        out: dict = {}
        data = self._request("GET", "/prices",
                             query={"active": "true", "limit": "100"})
        for p in data.get("data", []):
            if p.get("recurring") is None:
                continue
            prod = self._request("GET", f"/products/{p['product']}")
            plan = (prod.get("metadata") or {}).get("rja_plan", "")
            if plan in ("pro", "team") and plan not in out:
                out[plan] = p["id"]
        return out

    # ---------- customers ----------
    def create_customer(self, email: str) -> str:
        data = self._request("POST", "/customers", {"email": email})
        return data["id"]

    def find_customer(self, email: str) -> Optional[str]:
        """Return the customer id for an email, or None."""
        data = self._request("GET", "/customers", query={"email": email})
        items = data.get("data", [])
        return items[0]["id"] if items else None

    # ---------- checkout ----------
    def create_checkout_session(self, *, customer: str, price_id: str,
                                success_url: str, cancel_url: str,
                                client_reference: str) -> str:
        fields = {
            "mode": "subscription",
            "customer": customer,
            "client_reference_id": client_reference,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": 1,
            "subscription_data[metadata][rja_user]": client_reference,
        }
        data = self._request("POST", "/checkout/sessions", fields)
        return data["url"]

    # ---------- billing portal ----------
    def create_portal_session(self, *, customer: str, return_url: str) -> str:
        fields = {"customer": customer, "return_url": return_url}
        data = self._request("POST", "/billing_portal/sessions", fields)
        return data["url"]

    # ---------- subscriptions ----------
    def cancel_at_period_end(self, subscription_id: str) -> None:
        self._request("POST", f"/subscriptions/{subscription_id}",
                      {"cancel_at_period_end": "true"})

    def cancel_now(self, subscription_id: str) -> None:
        self._request("DELETE", f"/subscriptions/{subscription_id}")


def _b64(secret: str) -> str:
    import base64
    return base64.b64encode(secret.encode("utf-8")).decode("ascii")


def _flatten(d: dict) -> dict:
    return {str(k): str(v) for k, v in d.items()}


def verify_signature(payload: bytes, header: str, secret: str,
                     tolerance: int = 300) -> bool:
    """Verify a Stripe-Signature header for a webhook payload.

    header looks like:  t=1614559516,v1=5257a869...,v0=...
    We sign  "{t}.{payload}"  and compare against v1 with a 5-minute window.
    """
    if not header:
        return False
    parts = {}
    for part in header.split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            parts[k.strip()] = v.strip()
    t = parts.get("t")
    sig = parts.get("v1")
    if not t or not sig:
        return False
    try:
        t_int = int(t)
    except ValueError:
        return False
    if abs(time.time() - t_int) > tolerance:
        return False
    expected = hmac.new(secret.encode("utf-8"),
                        (t + "." + payload.decode("utf-8", "replace")).encode("utf-8"),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
