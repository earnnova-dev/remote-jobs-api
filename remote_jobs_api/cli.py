"""remote-jobs-api CLI — query the normalized feed without running a server.

Usage:
  remote-jobs-api --skills python,api --limit 5
  remote-jobs-api --source wwr --format csv
  remote-jobs-api --serve --port 8321        # run the HTTP API
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys

from . import __version__, feed
from .feed import SOURCES


def _print_csv(jobs, file):
    buf = io.StringIO()
    cols = ["id", "title", "company", "location", "salary",
            "category", "source", "published", "fit_score", "url"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for j in jobs:
        w.writerow(j)
    file.write(buf.getvalue())


def _run_query(args) -> int:
    jobs = feed.filter_and_rank(
        feed.collect(),
        skills=args.skills or None,
        source=args.source,
        min_score=args.min_score,
    )[: max(1, min(500, args.limit))]

    if args.format == "csv":
        _print_csv(jobs, sys.stdout)
    else:
        print(json.dumps(
            {"count": len(jobs), "query": vars(args), "jobs": jobs},
            ensure_ascii=False, indent=2,
        ))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="remote-jobs-api",
        description="Normalized remote-job data from 5 boards: " + ", ".join(SOURCES),
    )
    p.add_argument("--version", action="version", version=f"remote-jobs-api {__version__}")
    p.add_argument("--skills", help="comma-separated keywords for fit scoring")
    p.add_argument("--source", choices=SOURCES, help="restrict to one board")
    p.add_argument("--limit", type=int, default=50, help="max results (1-500, default 50)")
    p.add_argument("--min-score", type=int, help="minimum fit_score (needs --skills)")
    p.add_argument("--format", choices=["json", "csv"], default="json")
    p.add_argument("--serve", action="store_true", help="run the HTTP API server")
    p.add_argument("--port", type=int, default=8321)
    args = p.parse_args(argv)

    if args.serve:
        import os
        os.environ["PORT"] = str(args.port)
        from .server import main as serve_main
        serve_main()
        return 0
    return _run_query(args)


if __name__ == "__main__":
    sys.exit(main())
