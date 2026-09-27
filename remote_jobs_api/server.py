"""Remote-Jobs Data API — stdlib HTTP server.

Endpoints:
  GET /health                 -> {"status":"ok","sources":[...],"count_live":N}
  GET /v1/jobs                -> normalized job listings (requires API key)
  GET /v1/jobs/sources        -> {"sources":[...]}

Admin (requires RJA_ADMIN_TOKEN in env):
  POST /admin/keys            -> create a new API key  {"plan":"pro","label":"acme"}
  GET  /admin/keys            -> list all keys + usage
  DELETE /admin/keys?k=***    -> revoke a key

Query params on /v1/jobs:
  skills   comma-separated keywords (e.g. "python,backend,api") -> fit_score 0-100
  source   remotive|remoteok|jobicy|wwr|hn   (filter to one board)
  limit    max results (default 50, max 500)
  min_score   minimum fit_score to return (0-100)
  format   json|csv (default json)

Auth:
  - /v1/jobs requires `Authorization: Bearer <api-key>`
  - /health and /v1/jobs/sources are public (useful for load-balancer
    health checks and docs)
  - Admin endpoints require `Authorization: Bearer <RJA_ADMIN_TOKEN>`
  - If no keys exist yet and RJA_OPEN_MODE=1, /v1/jobs is open (useful
    for first-boot / dev). In production: create a key first.

Env vars:
  PORT            (default 8321)
  RJA_CACHE_TTL   (default 300) — upstream fetch cache TTL in seconds
  RJA_ADMIN_TOKEN admin bearer token for /admin/*
  RJA_KEYS_PATH   (default ./keys.json) — where the key store is persisted
  RJA_OPEN_MODE   (default 0) — allow /v1/jobs without a key (dev only)

Design: stdlib-only, no deps. Run:  python3 -m remote_jobs_api.server
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

# --- .env loader (stdlib, no deps) --------------------------------------
def _load_dotenv(path: str = ".env"):
    """Load KEY=VALUE lines from path into os.environ (no override)."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                # strip matching quotes
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv(os.path.dirname(__file__) + "/../../.env")
_load_dotenv(os.path.dirname(__file__) + "/.env")
_load_dotenv(".env")

# --- configuration -------------------------------------------------------
_CACHE_TTL = int(os.environ.get("RJA_CACHE_TTL", "300"))  # 5 min
_KEYS_PATH = os.environ.get("RJA_KEYS_PATH", os.path.join(os.path.dirname(__file__), "..", "keys.json"))
_ADMIN_TOKEN = os.environ.get("RJA_ADMIN_TOKEN", "")
_OPEN_MODE = os.environ.get("RJA_OPEN_MODE", "0") == "1"

_cache: dict = {"ts": 0.0, "jobs": []}
_store = KeyStore(_KEYS_PATH)


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

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    # ---------- public ----------
    def _handle_health(self):
        live = len(_cached_all())
        return self._json(200, {"status": "ok", "sources": SOURCES, "count_live": live})

    def _handle_sources(self):
        return self._json(200, {"sources": SOURCES})

    # ---------- jobs (auth required) ----------
    def _handle_jobs(self, q: dict):
        token = bearer_token_from_headers(self.headers)
        if token and token == _ADMIN_TOKEN:
            # admin token acts as an unlimited key
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
            "hint": "send 'Authorization: Bearer <key>'. Get a key from /admin/keys or your provider.",
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

        jobs = feed.filter_and_rank(
            _cached_all(), skills=skills, source=source, min_score=min_score
        )[:limit]

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
        body = self._read_body()
        try:
            data = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON body"})
        plan = (data.get("plan") or "free").strip().lower()
        label = (data.get("label") or "").strip()
        try:
            info = _store.create(plan=plan, label=label)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        return self._json(201, {
            "key": info.key,
            "plan": info.plan,
            "label": info.label,
            "limit_per_month": info.limit,
            "created": info.created,
            "hint": "store this key now; it is shown once",
        })

    def _handle_admin_keys_list(self):
        if not self._require_admin():
            return
        keys = _store.list_keys()
        return self._json(200, {
            "count": len(keys),
            "keys": [
                {
                    "key": k.key,
                    "plan": k.plan,
                    "label": k.label,
                    "calls_this_month": k.calls_this_month,
                    "limit": k.limit,
                    "created": k.created,
                } for k in keys
            ],
        })

    def _handle_admin_keys_revoke(self, q: dict):
        if not self._require_admin():
            return
        k = (q.get("k", [""])[0] or "").strip()
        if not k:
            return self._json(400, {"error": "missing ?k=***"})
        ok = _store.revoke(k)
        if ok:
            return self._json(200, {"revoked": k})
        return self._json(404, {"error": "key not found"})

    # ---------- routing ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        q = parse_qs(parsed.query)

        if path == "/health":
            return self._handle_health()
        if path == "/v1/jobs/sources":
            return self._handle_sources()
        if path == "/v1/jobs":
            return self._handle_jobs(q)
        if path == "/admin/keys":
            return self._handle_admin_keys_list()
        if path.startswith("/admin/keys?") or (path == "/admin/keys" and q.get("k")):
            return self._handle_admin_keys_revoke(q)

        return self._json(404, {"error": "not found",
                                "routes": ["/health", "/v1/jobs", "/v1/jobs/sources",
                                            "POST /admin/keys", "GET /admin/keys",
                                            "DELETE /admin/keys?k=***"]})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
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
    print(f"Remote-Jobs Data API listening on :{port}", flush=True)
    print(f"  admin token: {'set' if _ADMIN_TOKEN else 'NOT SET'}", flush=True)
    print(f"  keys file:   {_KEYS_PATH}", flush=True)
    print(f"  open mode:   {_OPEN_MODE}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
