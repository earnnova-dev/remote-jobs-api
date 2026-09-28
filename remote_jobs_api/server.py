"""Remote-Jobs Data API + SaaS storefront — stdlib HTTP server.

Endpoints
  Public API:
    GET  /health                 -> {"status":"ok",...}
    GET  /v1/jobs                -> normalized jobs (requires API key)
    GET  /v1/jobs/sources        -> {"sources":[...]}

  Storefront (browser):
    GET  /                        -> landing / pricing
    GET  /register   POST /register
    GET  /login      POST /login
    POST /logout
    GET  /dashboard               (session)
    GET  /checkout/<plan>  POST /checkout/<plan>   (Stripe)
    GET  /billing/portal        (Stripe customer portal)
    GET/POST /billing/cancel    (cancel at period end)

  Webhook:
    POST /webhooks/stripe        (Stripe-Signature verified)

  Admin (requires RJA_ADMIN_TOKEN):
    POST /admin/keys, GET /admin/keys, DELETE /admin/keys?k=***

Env:
  PORT, RJA_CACHE_TTL, RJA_ADMIN_TOKEN, RJA_KEYS_PATH, RJA_OPEN_MODE
  RJA_ACCOUNTS_PATH      (default ./accounts.json)
  RJA_BASE_URL           (default https://remote-jobs-api.tten.no)
  RJA_STRIPE_SECRET_KEY
  RJA_STRIPE_WEBHOOK_SECRET
  RJA_STRIPE_PRICE_PRO
  RJA_STRIPE_PRICE_TEAM
Run:  python3 -m remote_jobs_api.server
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import feed
from .feed import SOURCES
from .auth import KeyStore, RateLimitError, bearer_token_from_headers
from .accounts import UserStore
from . import web
from .stripe_client import StripeClient, verify_signature, StripeError

# --- .env loader (stdlib, no deps) --------------------------------------
def _load_dotenv(path: str):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_here = os.path.dirname(__file__)
_load_dotenv(os.path.join(_here, "..", "..", ".env"))
_load_dotenv(os.path.join(_here, ".env"))
_load_dotenv(".env")

# --- configuration -------------------------------------------------------
_CACHE_TTL = int(os.environ.get("RJA_CACHE_TTL", "300"))
# Default state paths live in /tmp (always writable) so register/login never
# crash on a read-only filesystem if the env vars are unset. In production the
# Helm chart points these at the /data PVC (RJA_KEYS_PATH / RJA_ACCOUNTS_PATH)
# so state survives pod restarts.
_KEYS_PATH = os.environ.get("RJA_KEYS_PATH", "/tmp/rja_keys.json")
_ACCOUNTS_PATH = os.environ.get("RJA_ACCOUNTS_PATH", "/tmp/rja_accounts.json")
_ADMIN_TOKEN = os.environ.get("RJA_ADMIN_TOKEN", "")
_OPEN_MODE = os.environ.get("RJA_OPEN_MODE", "0") == "1"
_BASE_URL = os.environ.get("RJA_BASE_URL", "https://remote-jobs-api.tten.no").rstrip("/")

_STRIPE_KEY = os.environ.get("RJA_STRIPE_SECRET_KEY", "")
_STRIPE_WEBHOOK_SECRET = os.environ.get("RJA_STRIPE_WEBHOOK_SECRET", "")
_PRICE_PRO = os.environ.get("RJA_STRIPE_PRICE_PRO", "")
_PRICE_TEAM = os.environ.get("RJA_STRIPE_PRICE_TEAM", "")
_STRIPE = StripeClient(_STRIPE_KEY) if _STRIPE_KEY else None
_STRIPE_CONFIGURED = bool(_STRIPE_KEY and _PRICE_PRO and _PRICE_TEAM)
_PRICE_TO_PLAN = {p: pl for p, pl in [(_PRICE_PRO, "pro"), (_PRICE_TEAM, "team")] if p}

PLAN_DEFAULT_PRICES = {"free": 0, "pro": 19, "team": 49}

_cache: dict = {"ts": 0.0, "jobs": []}
_store = KeyStore(_KEYS_PATH)
_accounts = UserStore(_ACCOUNTS_PATH)


def _prices() -> dict:
    """Marketing prices. Real Stripe prices are handled at checkout."""
    return dict(PLAN_DEFAULT_PRICES)


def _cached_all(force: bool = False) -> list:
    now = time.time()
    if not force and now - _cache["ts"] < _CACHE_TTL and _cache["jobs"]:
        return _cache["jobs"]
    jobs = feed.collect(per_source_limit=120)
    _cache["ts"] = now
    _cache["jobs"] = jobs
    return jobs


class Handler(BaseHTTPRequestHandler):
    server_version = "RemoteJobsAPI/1.1"

    def log_message(self, *a):
        pass

    # ---------- helpers ----------
    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _html(self, code: int, html: str):
        self._send(code, html.encode("utf-8"), "text/html; charset=utf-8")

    def _send_file(self, path: str, ctype: str):
        try:
            with open(path, "rb") as fh:
                self._send(200, fh.read(), ctype)
        except OSError:
            self._json(404, {"error": "not found"})

    def _redirect(self, url: str, set_cookie: str = ""):
        self.send_response(302)
        self.send_header("Location", url)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _form(self) -> dict:
        raw = self._read_body()
        if not raw:
            return {}
        ctype = self.headers.get("Content-Type") or ""
        if "application/json" in ctype:
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return {}
        out = {}
        for k, v in parse_qs(raw.decode("utf-8", "replace")).items():
            out[k] = v[0] if v else ""
        return out

    def _get_cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith(name + "="):
                return part[len(name) + 1:]
        return ""

    def _session_email(self):
        tok = self._get_cookie("rja_session")
        if not tok:
            tok = bearer_token_from_headers(self.headers) or ""
        return _accounts.session_email(tok)

    # ---------- public API ----------
    def _handle_health(self):
        live = len(_cached_all())
        return self._json(200, {"status": "ok", "sources": SOURCES, "count_live": live})

    def _handle_sources(self):
        return self._json(200, {"sources": SOURCES})

    def _handle_jobs(self, q: dict):
        token = bearer_token_from_headers(self.headers)
        if token and token == _ADMIN_TOKEN:
            return self._do_jobs(q, key_label="admin")
        if token:
            try:
                info = _store.check(token)
            except RateLimitError as e:
                return self._json(429, {"error": str(e), "retry": "next month"})
            if info is None:
                return self._json(401, {"error": "invalid API key"})
            return self._do_jobs(q, key_label=info.label or info.plan)
        if _OPEN_MODE:
            return self._do_jobs(q, key_label="open")
        return self._json(401, {
            "error": "missing API key",
            "hint": "send 'Authorization: Bearer ***'. Get a key from your dashboard or /admin/keys.",
        })

    def _do_jobs(self, q: dict, key_label: str):
        skills = [s.strip() for s in (q.get("skills", [""])[0]).split(",") if s.strip()]
        source = (q.get("source", [""])[0] or "").strip() or None
        if source and source not in SOURCES:
            return self._json(400, {"error": f"unknown source {source!r}; choose from {SOURCES}"})
        try:
            limit = int(q.get("limit", ["50"])[0])
        except (ValueError, TypeError):
            return self._json(400, {"error": "limit must be an int"})
        if not 1 <= limit <= 500:
            return self._json(400, {"error": "limit must be between 1 and 500"})
        min_score = None
        if q.get("min_score", [""])[0].strip():
            try:
                min_score = int(q["min_score"][0])
            except (ValueError, TypeError):
                return self._json(400, {"error": "min_score must be an int"})
            if not 0 <= min_score <= 100:
                return self._json(400, {"error": "min_score must be between 0 and 100"})
            if not skills:
                return self._json(400, {"error": "min_score requires skills"})
        fmt = (q.get("format", ["json"])[0] or "json").lower()
        if fmt not in ("json", "csv"):
            return self._json(400, {"error": "format must be json or csv"})
        jobs = feed.filter_and_rank(_cached_all(), skills=skills, source=source, min_score=min_score)[:limit]
        if fmt == "csv":
            buf = io.StringIO()
            cols = ["id", "title", "company", "location", "salary",
                    "category", "source", "published", "fit_score", "url"]
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for j in jobs:
                w.writerow(j)
            return self._send(200, buf.getvalue().encode("utf-8"), "text/csv")
        return self._json(200, {
            "count": len(jobs),
            "generated_at": int(time.time()),
            "query": {"skills": skills, "source": source, "min_score": min_score, "limit": limit},
            "jobs": jobs,
        })

    # ---------- storefront ----------
    def _handle_landing(self):
        return self._html(200, web.landing(stripe_configured=_STRIPE_CONFIGURED,
                                           prices=_prices(), sources=SOURCES))

    def _handle_register_page(self, error="", ok=""):
        return self._html(200, web.register_page(error=error, ok=ok))

    def _handle_register(self):
        data = self._form()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        try:
            _accounts.register(email, password, plan="free")
        except ValueError as e:
            return self._handle_register_page(error=str(e))
        key = _store.create(plan="free", label=email, owner=email)
        _accounts.set_api_key(email, key.key)
        token = _accounts.create_session(email)
        cookie = f"rja_session={token}; HttpOnly; Path=/; SameSite=Lax"
        return self._redirect("/dashboard", set_cookie=cookie)

    def _handle_login_page(self, error="", ok=""):
        return self._html(200, web.auth_page("Sign in", error=error, ok=ok))

    def _handle_login(self):
        data = self._form()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        api_key = _accounts.verify(email, password)
        if api_key is None:
            return self._handle_login_page(error="Incorrect email or password.")
        token = _accounts.create_session(email)
        cookie = f"rja_session={token}; HttpOnly; Path=/; SameSite=Lax"
        return self._redirect("/dashboard", set_cookie=cookie)

    def _handle_logout(self):
        tok = self._get_cookie("rja_session") or (bearer_token_from_headers(self.headers) or "")
        _accounts.delete_session(tok)
        return self._redirect("/", set_cookie="rja_session=; HttpOnly; Path=/; Max-Age=0")

    def _handle_dashboard(self):
        email = self._session_email()
        if not email:
            return self._redirect("/login")
        user = _accounts.get(email) or {}
        api_key = user.get("api_key", "")
        usage = 0
        if api_key:
            try:
                usage = _store._info(api_key).calls_this_month
            except Exception:
                usage = 0
        user = dict(user)
        user["calls_this_month"] = usage
        return self._html(200, web.dashboard(user, prices=_prices()))

    def _handle_checkout_page(self, plan_id):
        if plan_id not in ("pro", "team"):
            return self._html(404, web.checkout_page("bad"))
        return self._html(200, web.checkout_page(plan_id, prices=_prices()))

    def _handle_checkout(self, plan_id):
        if plan_id not in ("pro", "team"):
            return self._json(404, {"error": "unknown plan"})
        if not _STRIPE_CONFIGURED:
            return self._html(400, web.checkout_page(plan_id) +
                              '<div class="wrap"><p class="error">Stripe is not configured yet.</p></div>')
        data = self._form()
        email = (data.get("email") or "").strip().lower()
        if not email:
            return self._handle_checkout_page(plan_id)
        if not _accounts.exists(email):
            return self._redirect("/register")
        customer = _accounts.get(email).get("stripe_customer", "")
        try:
            if not customer:
                customer = _STRIPE.create_customer(email)
                _accounts.set_stripe(email, customer=customer)
            url = _STRIPE.create_checkout_session(
                customer=customer,
                price_id=(_PRICE_PRO if plan_id == "pro" else _PRICE_TEAM),
                success_url=f"{_BASE_URL}/dashboard",
                cancel_url=f"{_BASE_URL}/checkout/{plan_id}",
                client_reference=email,
            )
        except StripeError as e:
            return self._html(502, web.checkout_page(plan_id) +
                              f'<div class="wrap"><p class="error">Stripe error: {e}</p></div>')
        return self._redirect(url)

    def _handle_portal(self):
        email = self._session_email()
        if not email:
            return self._redirect("/login")
        user = _accounts.get(email) or {}
        customer = user.get("stripe_customer", "")
        if not _STRIPE_CONFIGURED or not customer:
            return self._json(400, {"error": "no stripe customer on this account"})
        try:
            url = _STRIPE.create_portal_session(customer=customer, return_url=f"{_BASE_URL}/dashboard")
        except StripeError as e:
            return self._json(502, {"error": f"stripe portal error: {e}"})
        return self._redirect(url)

    def _handle_cancel(self):
        email = self._session_email()
        if not email:
            return self._redirect("/login")
        user = _accounts.get(email) or {}
        sub = user.get("stripe_sub", "")
        if _STRIPE_CONFIGURED and sub:
            try:
                _STRIPE.cancel_at_period_end(sub)
            except StripeError as e:
                return self._json(502, {"error": f"cancel failed: {e}"})
        _accounts.set_plan(email, "free", sub_status="canceled")
        key = user.get("api_key", "")
        if key:
            _store.set_plan(key, "free")
        return self._redirect("/dashboard")

    def _handle_webhook(self):
        raw = self._read_body()
        sig = self.headers.get("Stripe-Signature", "")
        if _STRIPE_WEBHOOK_SECRET and not verify_signature(raw, sig, _STRIPE_WEBHOOK_SECRET):
            return self._json(400, {"error": "invalid signature"})
        try:
            event = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON"})
        etype = event.get("type", "")
        obj = event.get("data", {}).get("object", {})
        if etype == "checkout.session.completed":
            self._on_checkout_completed(obj)
        elif etype == "customer.subscription.created":
            self._on_subscription_changed(obj, "active")
        elif etype == "customer.subscription.updated":
            self._on_subscription_changed(obj, obj.get("status", "active"))
        elif etype == "customer.subscription.deleted":
            self._on_subscription_changed(obj, "canceled")
        return self._json(200, {"received": True})

    # ---------- webhook handlers ----------
    def _price_to_plan(self, price_id: str) -> str:
        return _PRICE_TO_PLAN.get(price_id, "pro")

    def _on_checkout_completed(self, obj: dict):
        email = obj.get("client_reference_id") or ""
        customer = obj.get("customer") or ""
        sub_id = obj.get("subscription") or ""
        price_id = ""
        try:
            price_id = obj["subscription_details"]["items"]["data"][0]["price"]
        except (KeyError, IndexError, TypeError):
            price_id = ""
        plan = self._price_to_plan(price_id)
        if not email:
            return
        if _accounts.exists(email):
            _accounts.set_stripe(email, customer=customer, sub=sub_id, status="active")
            _accounts.set_plan(email, plan, sub_status="active")
            key = _accounts.get(email).get("api_key", "")
            if key:
                _store.set_plan(key, plan)
            else:
                info = _store.create(plan=plan, label=email, owner=email)
                _accounts.set_api_key(email, info.key)
        print(f"[stripe] checkout completed email={email} plan={plan} sub={sub_id}", flush=True)

    def _on_subscription_changed(self, obj: dict, status: str):
        sub_id = obj.get("id", "")
        customer = obj.get("customer", "")
        price_id = ""
        try:
            items = obj.get("items", {}).get("data", [])
            if items:
                price_id = items[0].get("price", {}).get("id", "")
        except (AttributeError, IndexError):
            pass
        if status in ("canceled", "unpaid", "incomplete_expired"):
            plan = "free"
        else:
            plan = self._price_to_plan(price_id) if price_id else "pro"
        email = self._find_email_by_customer(customer) or self._find_email_by_sub(sub_id)
        if not email:
            return
        _accounts.set_plan(email, plan, sub_status=status)
        _accounts.set_stripe(email, customer=customer, sub=sub_id, status=status)
        key = _accounts.get(email).get("api_key", "")
        if key:
            _store.set_plan(key, plan)
        print(f"[stripe] subscription {status} email={email} plan={plan}", flush=True)

    def _find_email_by_customer(self, customer: str):
        if not customer:
            return None
        for email in _accounts.list_emails():
            if _accounts.get(email).get("stripe_customer") == customer:
                return email
        return None

    def _find_email_by_sub(self, sub: str):
        if not sub:
            return None
        for email in _accounts.list_emails():
            if _accounts.get(email).get("stripe_sub") == sub:
                return email
        return None

    # ---------- admin ----------
    def _require_admin(self) -> bool:
        if not _ADMIN_TOKEN:
            self._json(503, {"error": "admin token not configured (set RJA_ADMIN_TOKEN)"})
            return False
        token = bearer_token_from_headers(self.headers)
        if token != _ADMIN_TOKEN:
            self._json(401, {"error": "invalid admin token"})
            return False
        return True

    def _handle_admin_keys_create(self):
        if not self._require_admin():
            return
        data = self._form()
        plan = (data.get("plan") or "free").strip().lower()
        label = (data.get("label") or "").strip()
        try:
            info = _store.create(plan=plan, label=label)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        return self._json(201, {"key": info.key, "plan": info.plan, "label": info.label,
                                "limit_per_month": info.limit, "created": info.created,
                                "hint": "store this key now; it is shown once"})

    def _handle_admin_keys_list(self):
        if not self._require_admin():
            return
        keys = _store.list_keys()
        return self._json(200, {"count": len(keys), "keys": [
            {"key": k.key, "plan": k.plan, "label": k.label,
             "calls_this_month": k.calls_this_month, "limit": k.limit, "created": k.created}
            for k in keys]})

    def _handle_admin_keys_revoke(self, q: dict):
        if not self._require_admin():
            return
        k = (q.get("k", [""])[0] or "").strip()
        if not k:
            return self._json(400, {"error": "missing ?k=***"})
        if _store.revoke(k):
            return self._json(200, {"revoked": k})
        return self._json(404, {"error": "key not found"})

    # ---------- routing ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        q = parse_qs(parsed.query)
        if path == "/health":
            return self._handle_health()
        if path == "/docs":
            return self._html(200, web.docs_page())
        if path == "/openapi.yaml":
            return self._send_file(os.path.join(_here, "openapi.yaml"), "application/yaml")
        if path == "/v1/jobs/sources":
            return self._handle_sources()
        if path == "/v1/jobs":
            return self._handle_jobs(q)
        if path == "/":
            return self._handle_landing()
        if path == "/register":
            return self._handle_register_page()
        if path == "/login":
            return self._handle_login_page()
        if path == "/dashboard":
            return self._handle_dashboard()
        if path.startswith("/checkout/"):
            return self._handle_checkout_page(path.split("/", 2)[2])
        if path == "/billing/portal":
            return self._handle_portal()
        if path == "/billing/cancel":
            return self._handle_cancel()
        if path == "/admin/keys":
            return self._handle_admin_keys_list()
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/register":
            return self._handle_register()
        if path == "/login":
            return self._handle_login()
        if path == "/logout":
            return self._handle_logout()
        if path.startswith("/checkout/"):
            return self._handle_checkout(path.split("/", 2)[2])
        if path == "/billing/cancel":
            return self._handle_cancel()
        if path == "/webhooks/stripe":
            return self._handle_webhook()
        if path == "/admin/keys":
            return self._handle_admin_keys_create()
        return self._json(404, {"error": "not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        q = parse_qs(parsed.query)
        if path == "/admin/keys":
            return self._handle_admin_keys_revoke(q)
        return self._json(404, {"error": "not found"})


def main():
    port = int(os.environ.get("PORT", "8321"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Remote-Jobs Data API + Storefront listening on :{port}", flush=True)
    print(f"  base url:     {_BASE_URL}", flush=True)
    print(f"  admin token:  {'set' if _ADMIN_TOKEN else 'NOT SET'}", flush=True)
    print(f"  stripe:       {'configured' if _STRIPE_CONFIGURED else 'NOT configured'}", flush=True)
    print(f"  keys file:    {_KEYS_PATH}", flush=True)
    print(f"  accounts:     {_ACCOUNTS_PATH}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
