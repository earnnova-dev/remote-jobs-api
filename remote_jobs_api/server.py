"""Remote-Jobs Data API — stdlib HTTP server.

Endpoints:
  GET /health                 -> {"status":"ok","sources":[...],"count_live":N}
  GET /v1/jobs                -> normalized job listings
  GET /v1/jobs/sources        -> {"sources":[...]}

Query params on /v1/jobs:
  skills   comma-separated keywords (e.g. "python,backend,api") -> fit_score 0-100
  source   remotive|remoteok|jobicy|wwr|hn   (filter to one board)
  limit    max results (default 50, max 500)
  min_score   minimum fit_score to return (0-100)
  format   json|csv (default json)

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

# In-memory cache: fetch is slow + upstreams rate-limit. Cache for N seconds.
_CACHE_TTL = int(os.environ.get("RJA_CACHE_TTL", "300"))  # 5 min
_cache: dict = {"ts": 0.0, "jobs": []}


def _cached_all(force: bool = False) -> list:
    now = time.time()
    if not force and now - _cache["ts"] < _CACHE_TTL and _cache["jobs"]:
        return _cache["jobs"]
    jobs = feed.collect(per_source_limit=120)
    _cache["ts"] = now
    _cache["jobs"] = jobs
    return jobs


class Handler(BaseHTTPRequestHandler):
    server_version = "RemoteJobsAPI/1.0"

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

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        q = parse_qs(parsed.query)

        if path == "/health":
            live = len(_cached_all())
            return self._json(200, {"status": "ok", "sources": SOURCES, "count_live": live})

        if path == "/v1/jobs/sources":
            return self._json(200, {"sources": SOURCES})

        if path == "/v1/jobs":
            skills = [s.strip() for s in (q.get("skills", [""])[0]).split(",") if s.strip()]
            source = (q.get("source", [""])[0] or "").strip() or None
            if source and source not in SOURCES:
                return self._json(400, {"error": f"unknown source {source!r}; choose from {SOURCES}"})
            try:
                limit = max(1, min(500, int(q.get("limit", ["50"])[0])))
            except ValueError:
                limit = 50
            min_score = None
            if q.get("min_score", [""])[0].strip():
                try:
                    min_score = int(q["min_score"][0])
                except ValueError:
                    return self._json(400, {"error": "min_score must be an int"})
            fmt = (q.get("format", ["json"])[0] or "json").lower()

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

        return self._json(404, {"error": "not found",
                                "routes": ["/health", "/v1/jobs", "/v1/jobs/sources"]})


def main():
    port = int(os.environ.get("PORT", "8321"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Remote-Jobs Data API listening on :{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
